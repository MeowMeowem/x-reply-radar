"""Background work: the radar cycle, scheduled learning, and the outbox sender.

One radar cycle runs at a time (they share a browser). The outbox sender is its own
thread so a slow scrape never delays something you asked to send.
"""
from __future__ import annotations

import logging
import random
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import config
import i18n
import store
from ai import llm, persona, posts, replies, review, style
from ranking import score
from ranking import follow as follow_rules
from scraper import browser, news, x_follow, x_home, x_mine, x_trends, x_watch

log = logging.getLogger("radar")

state = {"drafting": False, "running": False, "phase": "", "phase_key": "", "login_expired": False, "error": "",
         "last_ok": None, "next_auto": None, "env_mtime_at_expiry": None, "learning": False, "task": ""}
_state_lock = threading.Lock()
cycle_lock = threading.Lock()
learn_lock = threading.Lock()
wake_sender = threading.Event()


def set_state(**kw):
    with _state_lock:
        state.update(kw)


def phase(key, e=None, **kw):
    set_state(phase=i18n.t(f"phase.{key}", e, **kw) if key else "", phase_key=key or "")


def say(msg):
    log.info(msg)


# ---------- ranking ----------

def ranked(limit=10, source="home"):
    muted = store.mutes()
    done = store.replied_ids()  # never suggest a post you already replied to
    rows = [t for t in store.recent_tweets(hours=24, source=source)
            if not t["is_reply"] and t["relevance"] and not t["ai_skip"] and t["id"] not in done
            and ("author", t["author_handle"]) not in muted and ("topic", t["topic"]) not in muted]
    snaps = store.snapshots_for(t["id"] for t in rows)
    for t in rows:
        t.update(score.score(t, snaps[t["id"]]))
    rows.sort(key=lambda x: x["hot_score"], reverse=True)
    return rows[:limit]


# ---------- AI steps ----------

def fill_replies(e, n=10):
    """A/B replies for top posts that don't have them yet; skipped posts drop out and the next one moves up."""
    if not llm.ready(e):
        return
    for _ in range(3):
        todo = [t for t in ranked(n) if not t["ai_at"]]
        if not todo:
            return
        phase("replies", e, n=len(todo))
        avoid = store.recent_replies()
        done = []

        def one(t):
            try:
                r = replies.generate(e, t, avoid=avoid)
            except Exception as ex:
                say(f"AI failed {t['id']}: {type(ex).__name__}: {str(ex)[:160]}")
                return None
            return t, r

        with ThreadPoolExecutor(3) as pool:
            results = [x for x in pool.map(one, todo) if x]
        if not results:
            return
        keep = [(t, r) for t, r in results if not r["skip"]]
        items = [{"text": r[k]} for _, r in keep for k in ("a", "b")]
        if items and config.get_bool(e, "FIT_REVIEW"):
            review.review(e, items, say)
        for idx, (t, r) in enumerate(keep):
            a, b = items[2 * idx], items[2 * idx + 1]
            store.save_replies(t["id"], a["text"], b["text"], r["want"], False, a.get("score"), b.get("score"))
            done.append(t["id"])
        for t, r in results:
            if r["skip"]:
                store.save_replies(t["id"], r["a"], r["b"], r["want"], True)
        say(f"replies written for {len(done)} posts, {len(results) - len(done)} skipped")


def regenerate(e, tweet_id):
    """New A/B for one post (the 'try again' button)."""
    t = store.tweet(tweet_id)
    if not t:
        return None
    r = replies.generate(e, t, avoid=[x for x in (t.get("reply_a"), t.get("reply_b")) if x] + store.recent_replies(6))
    if r["skip"]:
        store.save_replies(tweet_id, r["a"], r["b"], r["want"], True)
        return store.tweet(tweet_id)
    items = [{"text": r["a"]}, {"text": r["b"]}]
    if config.get_bool(e, "FIT_REVIEW"):
        review.review(e, items, say)
    store.save_replies(tweet_id, items[0]["text"], items[1]["text"], r["want"], False,
                       items[0].get("score"), items[1].get("score"))
    return store.tweet(tweet_id)


def refresh_mine(e, force=False):
    """Every few hours, read your own posts; relearn when enough are new."""
    if not config.handle(e):
        return 0
    last = float(store.kv_get("mine_at", 0))
    if not force and time.time() - last < config.get_int(e, "MINE_REFRESH_HOURS") * 3600:
        return 0
    phase("read_mine", e)
    first = not store.my_posts()
    pairs, mine = x_mine.scrape_mine(e, log=say, scrolls=30 if first or force else None)
    new = store.upsert_mine(pairs, mine)
    store.kv_set("mine_at", time.time())
    learned = int(store.kv_get("learned_count", 0))
    if llm.ready(e) and (not persona.strip_comments(persona.read("style_notes.md"))
                         or len(store.my_posts()) - learned >= 5):
        phase("learn", e)
        style.learn(e, log=say) if not persona.strip_comments(persona.read("style_notes.md")) else \
            style.consolidate(e, log=say, evaluate_versions=False)
    say(f"your posts: {new} new")
    return new


def make_drafts(e):
    set_state(drafting=True)
    try:
        # quote posts only: each one quotes a real source (an X post or an article) and adds your take
        hot = [t for t in ranked(40) if (t["views"] or 0) >= 3000][:25]
        posts.generate_news(e, hot, n=config.get_int(e, "NEWS_PER_DAY"), log=say)
        store.kv_set("drafts_date", datetime.now().strftime("%Y-%m-%d"))
    except Exception as ex:
        say(f"drafts failed: {type(ex).__name__}: {str(ex)[:200]}")
    finally:
        set_state(drafting=False)


def daily_drafts(e):
    """Once a day, after DRAFT_HOUR, write a batch of quote-post drafts."""
    today = datetime.now().strftime("%Y-%m-%d")
    if store.kv_get("drafts_date") == today or datetime.now().hour < config.get_int(e, "DRAFT_HOUR"):
        return
    if llm.ready(e):
        phase("drafts", e)
        make_drafts(e)


def _due(key, minutes):
    return time.time() - float(store.kv_get(key, 0)) >= minutes * 60


def refresh_trends(e, force=False):
    if not force and not _due("trends_at", config.get_int(e, "TRENDS_EVERY_MINUTES")):
        return
    phase("trends", e)
    try:
        items = x_trends.scrape_trends(e, log=say)
        if items:
            store.save_trends(items)
        store.kv_set("trends_at", time.time())
    except browser.LoginExpired:
        raise
    except Exception as ex:
        say(f"trends failed: {type(ex).__name__}: {str(ex)[:160]}")


def refresh_watch(e, force=False):
    if not x_watch.accounts(e) or (not force and not _due("watch_at", config.get_int(e, "WATCH_EVERY_MINUTES"))):
        return
    phase("watch", e)
    try:
        tweets = x_watch.scrape_watch(e, log=say)
        for t in tweets:
            score.classify(t)
            t["blocked"] = 0  # you chose to watch these accounts; don't filter them
            t["relevance"] = max(t["relevance"], 0.5)
        store.upsert(tweets, source="watch")
        store.kv_set("watch_at", time.time())
    except browser.LoginExpired:
        raise
    except Exception as ex:
        say(f"watch failed: {type(ex).__name__}: {str(ex)[:160]}")


def refresh_news(e, force=False):
    if not force and not _due("news_at", 60):
        return
    phase("news", e)
    try:
        store.upsert_news(news.collect(log=say))
        store.kv_set("news_at", time.time())
    except Exception as ex:
        say(f"news failed: {type(ex).__name__}: {str(ex)[:160]}")


def periodic_learning(e):
    days = config.get_int(e, "CONSOLIDATE_EVERY_DAYS")
    if days <= 0 or not llm.ready(e) or len(store.my_posts()) < 5:
        return
    last = store.kv_get("consolidate_run_at")
    if last and time.time() - float(last) < days * 86400:
        return
    store.kv_set("consolidate_run_at", time.time())
    run_learning("consolidate")


# ---------- one cycle ----------

def run_cycle(source="manual"):
    if not cycle_lock.acquire(blocking=False):
        return False
    set_state(running=True, error="")
    phase("scrape_home")
    try:
        e = config.env()
        persona.ensure(e)
        # the home feed is different every time; current candidates are revisited to measure growth
        watch = [(t["id"], t["url"]) for t in ranked(config.get_int(e, "RECHECK_TOP")) if t["age_min"] < 12 * 60]
        try:
            tweets, _ = x_home.scrape_home(e, log=say, target=config.get_int(e, "SCRAPE_TARGET"), refresh=watch)
        except browser.LoginExpired:
            set_state(login_expired=True, env_mtime_at_expiry=config.env_mtime())
            store.log_run(False, 0, 0, "login_expired")
            say("X login expired; automatic refresh paused until the cookie changes")
            return True
        except Exception as ex:
            set_state(error=i18n.t("error.scrape", e))
            store.log_run(False, 0, 0, str(ex)[:300])
            say(f"scrape failed ({source}): {type(ex).__name__}: {str(ex)[:300]}")
            return True

        set_state(login_expired=False)
        for t in tweets:
            score.classify(t)
        new = store.upsert(tweets)
        store.cleanup(days=config.get_int(e, "KEEP_DAYS"))
        store.log_run(True, len(tweets), new, source)
        say(f"stored {len(tweets)}, new {new}, candidates {sum(1 for t in tweets if t['relevance'] and not t['blocked'])}")
        set_state(last_ok=store.now())

        for step in (refresh_trends, refresh_watch, refresh_news):
            try:
                step(e)
            except browser.LoginExpired:
                break
        try:
            refresh_mine(e)
        except Exception as ex:
            say(f"reading your posts failed: {type(ex).__name__}: {str(ex)[:200]}")
        daily_drafts(e)
        try:
            fill_replies(e)
        except Exception as ex:
            say(f"writing replies failed: {type(ex).__name__}: {str(ex)[:200]}")
        periodic_learning(e)
        return True
    finally:
        set_state(running=False)
        phase("")
        cycle_lock.release()


def run_learning(task, **kw):
    """Learning tasks triggered from the Learn page or the schedule; one at a time."""
    if not learn_lock.acquire(blocking=False):
        return False
    set_state(learning=True, task=task)
    try:
        e = config.env()
        if task == "scrape_mine":
            with cycle_lock:  # shares the browser with the radar cycle
                refresh_mine(e, force=True)
        elif task == "learn":
            style.learn(e, log=say)
        elif task == "consolidate":
            phase("consolidate", e)
            style.consolidate(e, log=say, force=kw.get("force", False))
        elif task == "eval":
            phase("eval", e)
            active = store.active_style_version()
            s = style.evaluate(e, label="current", version_id=active["id"] if active else None, log=say)
            if active and s is not None:
                store.set_style_score(active["id"], s)
            style.evaluate(e, label="baseline", use_learned=False, log=say)
        return True
    except Exception as ex:
        say(f"{task} failed: {type(ex).__name__}: {str(ex)[:200]}")
        set_state(error=f"{task}: {str(ex)[:120]}")
        return False
    finally:
        set_state(learning=False, task="")
        if not state["running"]:
            phase("")
        learn_lock.release()


def scheduler():
    while True:
        e = config.env()
        if not config.get_bool(e, "AUTO_REFRESH"):
            set_state(next_auto=None)
            time.sleep(30)
            continue
        lo, hi = config.get_int(e, "REFRESH_MIN_MINUTES"), config.get_int(e, "REFRESH_MAX_MINUTES")
        wait = random.uniform(max(1, lo) * 60, max(lo, hi, 1) * 60)
        set_state(next_auto=datetime.fromtimestamp(time.time() + wait, timezone.utc).isoformat(timespec="seconds"))
        time.sleep(wait)
        if state["login_expired"] and config.env_mtime() == state["env_mtime_at_expiry"]:
            continue  # the cookie hasn't changed; don't keep knocking
        run_cycle("auto")


# ---------- outbox ----------

def _parse_ts(ts):
    return datetime.fromisoformat(ts).timestamp() if ts else 0


def send_block_reason(e):
    """Why the next send has to wait, or None."""
    if store.sent_since(hours=1) >= config.get_int(e, "SEND_MAX_PER_HOUR"):
        return "hourly_limit"
    if store.sent_since(days=1) >= config.get_int(e, "SEND_MAX_PER_DAY"):
        return "daily_limit"
    gap = config.get_int(e, "SEND_MIN_INTERVAL_SEC")
    if time.time() - _parse_ts(store.last_sent_at()) < gap:
        return "interval"
    return None


def record_sent(item, result_id=""):
    """A send went out: remember it as your post and learn from any edit you made."""
    e = config.env()
    store.update_outbox(item["id"], status="sent", result_id=result_id, sent_at=store.now(), error=None)
    if item.get("ai_text"):
        store.add_edit(item["kind"], item["ai_text"], item["text"], item.get("target_text") or "")
    if item.get("draft_id"):
        store.set_draft(item["draft_id"], "posted", text=item["text"])
    pid = result_id or f"local-{item['id']}"
    row = {"id": pid, "text": item["text"], "created_at": store.now(), "views": None, "likes": None, "replies": None}
    if item["kind"] == "reply":
        store.upsert_mine([{**row, "parent_id": item.get("target_id"), "parent_author": item.get("target_author"),
                            "parent_text": item.get("target_text") or ""}], [], origin="sent")
    else:
        store.upsert_mine([], [row], origin="sent")
    if item["kind"] == "reply" and item.get("target_id"):
        store.dismiss(item["target_id"])
    say(f"sent {item['kind']} #{item['id']} via {item['channel']}" + (f" -> {result_id}" if result_id else ""))
    return e


# ---------- follow-back finder ----------

def run_follow_search(words=None):
    """Search for people asking for follow-backs and store them with fresh numbers."""
    e = config.env()
    words = words or follow_rules.keywords(e)
    if not words:
        return False
    set_state(task="follow_search")  # shown right away, also while waiting for the browser
    if not cycle_lock.acquire(timeout=600):
        set_state(task="")
        return False
    phase("follow_search", e)
    try:
        users = x_follow.search(e, words, log=say, scrolls=config.get_int(e, "FOLLOW_SEARCH_SCROLLS"))
        new = store.upsert_candidates(users)
        store.kv_set("follow_search_at", store.now())
        say(f"follow search: {len(users)} found, {new} new")
        return True
    except browser.LoginExpired:
        set_state(login_expired=True, env_mtime_at_expiry=config.env_mtime())
        return False
    except Exception as ex:
        say(f"follow search failed: {type(ex).__name__}: {str(ex)[:200]}")
        set_state(error=f"follow search: {str(ex)[:120]}")
        return False
    finally:
        set_state(task="")
        phase("")
        cycle_lock.release()


def follow_block_reason(e):
    paused = float(store.kv_get("follow_paused_until", 0))
    if time.time() < paused:
        return "paused"
    if store.followed_since(hours=1) >= config.get_int(e, "FOLLOW_MAX_PER_HOUR"):
        return "hourly_limit"
    if store.followed_since(days=1) >= config.get_int(e, "FOLLOW_MAX_PER_DAY"):
        return "daily_limit"
    if time.time() < float(store.kv_get("follow_next_at", 0)):
        return "interval"
    return None


def follow_queue_status(e=None):
    e = e or config.env()
    reason = follow_block_reason(e)
    wait = 0
    if reason == "interval":
        wait = int(float(store.kv_get("follow_next_at", 0)) - time.time())
    elif reason == "paused":
        wait = int(float(store.kv_get("follow_paused_until", 0)) - time.time())
    return {"queued": len(store.candidates(["queued"])), "blocked": reason, "wait_sec": max(0, wait),
            "hour": store.followed_since(hours=1), "day": store.followed_since(days=1),
            "max_hour": config.get_int(e, "FOLLOW_MAX_PER_HOUR"), "max_day": config.get_int(e, "FOLLOW_MAX_PER_DAY")}


def _follow_one(e):
    from publisher import SendError
    from publisher import follow as follower
    c = store.next_follow()
    if not c or follow_block_reason(e):
        return False
    store.set_candidates([c["user_id"]], status="sending", attempts=(c["attempts"] or 0) + 1)
    try:
        with cycle_lock if c["channel"] == "browser" else _nullcontext():
            result = follower.follow(e, c)
        if result == "dry_run":
            store.set_candidates([c["user_id"]], status="new", error="dry run: follow button found, not pressed")
        else:
            store.set_candidates([c["user_id"]], status="followed", followed_at=store.now(), error=None,
                                 following_now=1)
            say(f"followed @{c['handle']} ({result})")
    except browser.LoginExpired:
        store.set_candidates([c["user_id"]], status="queued")
        set_state(login_expired=True, env_mtime_at_expiry=config.env_mtime())
        return False
    except SendError as ex:
        store.set_candidates([c["user_id"]], status="failed", error=str(ex)[:300])
        if ex.retryable:  # X says we're following too fast: stop everything for a few hours
            store.kv_set("follow_paused_until", time.time() + 3 * 3600)
            say(f"follow paused for 3 hours: {ex}")
        else:
            say(f"follow @{c['handle']} failed: {ex}")
    except Exception as ex:
        store.set_candidates([c["user_id"]], status="failed", error=f"{type(ex).__name__}: {str(ex)[:250]}")
    gap = config.get_int(e, "FOLLOW_MIN_INTERVAL_SEC")
    store.kv_set("follow_next_at", time.time() + gap + random.uniform(0, gap * 0.7))  # never on a fixed beat
    return True


def sender():
    from publisher import SendError, send
    store.recover_sending()
    store.set_candidates([c["user_id"] for c in store.candidates(["sending"])], status="failed",
                         error="interrupted")
    while True:
        wake_sender.wait(timeout=15)
        wake_sender.clear()
        try:
            e = config.env()
            if _follow_one(e):
                wake_sender.set()
            item = store.next_pending()
            if not item:
                continue
            if send_block_reason(e):
                continue
            store.update_outbox(item["id"], status="sending", attempts=(item["attempts"] or 0) + 1)
            try:
                with cycle_lock if item["channel"] == "browser" else _nullcontext():
                    result_id = send(e, item)
                if config.get_bool(e, "SEND_DRY_RUN"):  # stopped right before pressing Post
                    store.update_outbox(item["id"], status="cancelled", error="dry run: X accepted the text, not posted")
                    say(f"dry run #{item['id']} ok")
                else:
                    record_sent(item, result_id)
            except browser.LoginExpired:
                store.update_outbox(item["id"], status="failed", error="X login expired")
                set_state(login_expired=True, env_mtime_at_expiry=config.env_mtime())
            except SendError as ex:
                retry = ex.retryable and (item["attempts"] or 0) < 2
                store.update_outbox(item["id"], status="pending" if retry else "failed", error=str(ex)[:300])
                say(f"send #{item['id']} failed: {ex}")
            except Exception as ex:
                store.update_outbox(item["id"], status="failed", error=f"{type(ex).__name__}: {str(ex)[:250]}")
                say(f"send #{item['id']} crashed: {type(ex).__name__}: {ex}")
            wake_sender.set()  # more may be waiting; limits decide when
            time.sleep(1)
        except Exception as ex:  # never let the sender thread die
            say(f"sender loop error: {type(ex).__name__}: {ex}")
            time.sleep(5)


class _nullcontext:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def queue_status(e=None):
    e = e or config.env()
    reason = send_block_reason(e)
    wait = 0
    if reason == "interval":
        wait = max(0, int(config.get_int(e, "SEND_MIN_INTERVAL_SEC") - (time.time() - _parse_ts(store.last_sent_at()))))
    return {"pending": len(store.outbox(status="pending")), "blocked": reason, "wait_sec": wait,
            "sent_hour": store.sent_since(hours=1), "sent_day": store.sent_since(days=1),
            "max_hour": config.get_int(e, "SEND_MAX_PER_HOUR"), "max_day": config.get_int(e, "SEND_MAX_PER_DAY")}


def clean_text(text):
    return re.sub(r"[ \t]+\n", "\n", (text or "").strip())
