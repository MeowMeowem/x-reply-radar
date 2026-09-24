"""X Reply Radar: `python app.py`, then open http://127.0.0.1:8796

A local web app. It never listens on anything but localhost unless you change that, and
it never sends anything to X unless you press a send button.
"""
from __future__ import annotations

import json
import logging
import os
import re
import threading
import webbrowser

import uvicorn
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import config
import i18n
import jobs
import publisher
import security
import store
from ai import llm, persona, posts, style
from publisher import x_api
from scraper import browser, news, x_mine, x_watch

ROOT = config.ROOT
env = config.env  # kept for scripts that import it from here
DEMO = os.environ.get("RADAR_DEMO") == "1"  # scripts/demo.py: made-up data, never talk to X or an AI


# ---------- logging ----------

class Redact(logging.Filter):
    """Replace any credential that shows up in a log line."""
    _cache = {"mtime": object(), "pieces": []}

    def pieces(self):
        mtime = config.env_mtime()
        if self._cache["mtime"] != mtime:
            e = config.env()
            vals = [e.get(k, "") for k in config.SECRET_KEYS] + [llm.api_key(e) or ""]
            self._cache.update(mtime=mtime, pieces=[p for v in vals for p in re.split(r"[;=\s]+", v) if len(p) >= 12])
        return self._cache["pieces"]

    def filter(self, record):
        msg = record.getMessage()
        for piece in self.pieces():
            msg = msg.replace(piece, "***")
        record.msg, record.args = msg, ()
        return True


def setup_logging():
    config.LOG_DIR.mkdir(parents=True, exist_ok=True)
    log = logging.getLogger("radar")
    if log.handlers:
        return log
    log.setLevel(logging.INFO)
    for h in (logging.FileHandler(config.LOG_DIR / "radar.log", encoding="utf-8"), logging.StreamHandler()):
        h.setFormatter(logging.Formatter("%(asctime)s %(message)s", "%m-%d %H:%M:%S"))
        h.addFilter(Redact())
        log.addHandler(h)
    return log


log = setup_logging()


# ---------- app ----------

app = FastAPI(title="X Reply Radar", docs_url=None, redoc_url=None, openapi_url=None)
app.add_middleware(security.LocalOnly)


@app.middleware("http")
async def no_cache(request, call_next):
    resp = await call_next(request)
    resp.headers["Cache-Control"] = "no-cache"
    return resp


app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")


def bg(fn, *args, **kw):
    threading.Thread(target=fn, args=args, kwargs=kw, daemon=True).start()


def _bad(msg, code=400):
    raise HTTPException(status_code=code, detail=msg)


def no_demo():
    if DEMO:
        _bad("demo_mode")


FEED_KEYS = ("id", "author_name", "author_handle", "author_avatar", "text", "url", "created_at", "media_type",
             "views", "replies", "likes", "retweets", "quotes", "topic", "reply_a", "reply_b", "ai_want",
             "hot_score", "stage", "stage_key", "age_min", "growth_pct", "growth_window", "measured", "vpm", "parts",
             "seen_count", "last_seen", "fit_a", "fit_b", "ai_at", "ai_skip")


def public(t):
    return {k: t.get(k) for k in FEED_KEYS}


KIND_LABELS = {"zh": {"quote": "引用", "post": "原创", "reply": "回复", "link": "分享链接"},
               "en": {"quote": "Quote", "post": "Post", "reply": "Reply", "link": "Link post"}}


LEGACY_KINDS = {"引用": "quote", "原创": "post", "短帖": "post", "中帖": "post", "长帖": "post"}


def public_draft(d):
    labels = KIND_LABELS[i18n.lang()]
    code = LEGACY_KINDS.get(d.get("kind"), d.get("kind") or "post")
    if code == "quote" and not re.search(r"/status/\d+", d.get("url") or ""):
        code = "link"  # an article can't be quoted on X; it's a post with the link
    return {**d, "kind_code": code, "kind": labels.get(code, code)}


def status():
    e = config.env()
    last = store.last_runs(1)
    s = dict(jobs.state)
    s.update(ai_ready=llm.ready(e), last_run=last[0] if last else None, channel=e.get("POST_CHANNEL"),
             fit_min=config.get_float(e, "FIT_MIN_SCORE"), ui_lang=e.get("UI_LANG"),
             x_ready=bool(browser.parse_cookie_config(e).get("auth_token")), handle=config.handle(e),
             queue=jobs.queue_status(e), demo=DEMO)
    s.pop("env_mtime_at_expiry", None)
    return s


@app.get("/")
def index():
    html = (ROOT / "templates" / "index.html").read_text(encoding="utf-8")
    for f in ("style.css", "app.js", "i18n.js"):  # cache-bust by modification time
        p = ROOT / "static" / f
        if p.exists():
            html = html.replace(f"/static/{f}", f"/static/{f}?v={int(p.stat().st_mtime)}")
    return HTMLResponse(html)


# ---------- radar ----------

@app.get("/api/feed")
def feed():
    e = config.env()
    return {"items": [public(t) for t in jobs.ranked(config.get_int(e, "SHOW_TOP"))], "status": status()}


@app.get("/api/status")
def api_status():
    return status()


@app.post("/api/refresh")
def refresh():
    no_demo()
    if jobs.state["running"]:
        return {"started": False}
    bg(jobs.run_cycle, "manual")
    return {"started": True}


class Act(BaseModel):
    kind: str
    value: str


@app.post("/api/feedback")
def feedback(a: Act):
    if a.kind == "dismiss":
        store.dismiss(a.value)
    elif a.kind in ("author", "topic"):
        store.mute(a.kind, a.value)
    elif a.kind in ("unmute_author", "unmute_topic"):
        store.unmute(a.kind.split("_")[1], a.value)
    return {"ok": True}


@app.get("/api/mutes")
def api_mutes():
    return {"items": store.mute_list()}


class TweetRef(BaseModel):
    id: str


@app.post("/api/replies/regenerate")
def api_regenerate(a: TweetRef):
    no_demo()
    e = config.env()
    if not llm.ready(e):
        _bad("ai_not_ready")
    try:
        t = jobs.regenerate(e, a.id)
    except llm.AIError as ex:
        _bad(str(ex), 502)
    if not t:
        _bad("not_found", 404)
    return {"item": public({**t, **_scored(t)})}


def _scored(t):
    from ranking import score
    return score.score(t, store.snapshots(t["id"]))


# ---------- writing ----------

class QuoteReq(BaseModel):
    tweet_id: str | None = None
    news_url: str | None = None


@app.post("/api/quote/generate")
def api_quote(a: QuoteReq):
    no_demo()
    e = config.env()
    if not llm.ready(e):
        _bad("ai_not_ready")
    if a.tweet_id:
        t = store.tweet(a.tweet_id)
        if not t:
            _bad("not_found", 404)
        source = {"url": t["url"], "source": f"X @{t['author_handle']}", "title": t["text"][:100],
                  "summary": t["text"][:500], "body": t["text"], "tweet": t}
    elif a.news_url:
        n = store.news_item(a.news_url)
        if not n:
            _bad("not_found", 404)
        source = {"url": n["url"], "source": n["source"], "title": n["title"], "summary": n["summary"] or ""}
        store.mark_news([n["url"]])
    else:
        _bad("tweet_id or news_url required")
    try:
        d = posts.quote_for(e, source, log=log.info)
    except llm.AIError as ex:
        _bad(str(ex), 502)
    return {"draft": public_draft(store.draft(d["id"])) if d else None}


class PostReq(BaseModel):
    topic: str
    context: str = ""


@app.post("/api/post/generate")
def api_post(a: PostReq):
    no_demo()
    e = config.env()
    if not llm.ready(e):
        _bad("ai_not_ready")
    if not a.topic.strip():
        _bad("empty")
    try:
        d = posts.post_about(e, a.topic.strip()[:500], a.context[:3000], log=log.info)
    except llm.AIError as ex:
        _bad(str(ex), 502)
    return {"draft": public_draft(store.draft(d["id"])) if d else None}


class TextReq(BaseModel):
    text: str


@app.post("/api/polish")
def api_polish(a: TextReq):
    no_demo()
    e = config.env()
    if not llm.ready(e):
        _bad("ai_not_ready")
    if not a.text.strip():
        _bad("empty")
    try:
        return posts.polish(e, a.text.strip()[:4000])
    except llm.AIError as ex:
        _bad(str(ex), 502)


@app.get("/api/drafts")
def api_drafts():
    return {"items": [public_draft(d) for d in store.drafts(status="new", limit=40)], "status": status()}


@app.post("/api/drafts/generate")
def api_make_drafts():
    no_demo()
    if jobs.state["drafting"]:
        return {"started": False}
    bg(jobs.make_drafts, config.env())
    return {"started": True}


class DraftAct(BaseModel):
    id: int
    status: str
    text: str | None = None


@app.post("/api/drafts/mark")
def api_mark_draft(a: DraftAct):
    if a.status in ("posted", "dropped", "new"):
        store.set_draft(a.id, a.status, a.text)
    return {"ok": True}


# ---------- sending ----------

class SendReq(BaseModel):
    kind: str
    text: str
    target_id: str | None = None
    draft_id: int | None = None
    ai_text: str | None = None


def _enqueue(e, a: SendReq):
    no_demo()
    if a.kind not in publisher.KINDS + ("link",):
        _bad("bad_kind")
    text = jobs.clean_text(a.text)
    if not text:
        _bad("empty")
    if a.kind == "link":  # a post that shares an article: the link goes at the end
        d = store.draft(a.draft_id) if a.draft_id else None
        url = (d or {}).get("url") or ""
        if url and url not in text:
            text = f"{text}\n{url}"
        a = SendReq(kind="post", text=text, draft_id=a.draft_id, ai_text=a.ai_text)
    target = None
    if a.kind in ("reply", "quote"):
        target = store.tweet(a.target_id or "")
        if not target:
            d = store.draft(a.draft_id) if a.draft_id else None
            if d and d.get("url") and a.kind == "quote":
                m = re.search(r"/status/(\d+)", d["url"])
                target = {"id": m.group(1) if m else None, "url": d["url"], "author_handle": d.get("target_author"),
                          "text": d.get("source") or ""}
        if not target:
            _bad("target_not_found", 404)
    if a.kind == "quote" and not (target.get("id") or "").isdigit():
        # quoting an article: it's a normal post with the link at the end
        text = f"{text}\n{target['url']}"
        a = SendReq(kind="post", text=text, draft_id=a.draft_id, ai_text=a.ai_text)
        target = None
    channel = e.get("POST_CHANNEL") or "intent"
    if channel == "api" and not x_api.configured(e):
        _bad("api_not_configured")
    if channel == "browser" and not browser.parse_cookie_config(e).get("auth_token"):
        _bad("x_not_configured")
    status_ = "opened" if channel == "intent" else "pending"
    item_id = store.enqueue(a.kind, text, channel, ai_text=a.ai_text, target=target, draft_id=a.draft_id,
                            status=status_)
    if a.draft_id:
        store.set_draft(a.draft_id, "queued", text=text)
    out = {"id": item_id, "channel": channel, "status": status_}
    if channel == "intent":
        out["intent_url"] = publisher.intent_url(a.kind, text, target and target.get("id"), target and target.get("url"))
    else:
        jobs.wake_sender.set()
    return out


@app.post("/api/send")
def api_send(a: SendReq):
    return _enqueue(config.env(), a)


class BatchReq(BaseModel):
    items: list[SendReq]


@app.post("/api/send/batch")
def api_send_batch(a: BatchReq):
    e = config.env()
    if (e.get("POST_CHANNEL") or "intent") == "intent" and len(a.items) > 1:
        _bad("batch_needs_auto_channel")
    return {"items": [_enqueue(e, it) for it in a.items[:20]]}


@app.get("/api/outbox")
def api_outbox():
    return {"items": store.outbox(limit=80), "queue": jobs.queue_status()}


class OutboxAct(BaseModel):
    id: int
    action: str  # confirm | cancel | retry | not_sent


@app.post("/api/outbox/act")
def api_outbox_act(a: OutboxAct):
    item = store.outbox_item(a.id)
    if not item:
        _bad("not_found", 404)
    if a.action == "confirm" and item["status"] == "opened":
        jobs.record_sent(item)
    elif a.action == "not_sent" and item["status"] == "opened":
        store.update_outbox(a.id, status="cancelled")
        if item.get("draft_id"):
            store.set_draft(item["draft_id"], "new")
    elif a.action == "cancel" and item["status"] == "pending":
        store.update_outbox(a.id, status="cancelled")
        if item.get("draft_id"):
            store.set_draft(item["draft_id"], "new")
    elif a.action == "retry" and item["status"] == "failed":
        store.update_outbox(a.id, status="pending", error=None)
        jobs.wake_sender.set()
    else:
        _bad("not_allowed")
    return {"ok": True, "item": store.outbox_item(a.id)}


# ---------- trends & news ----------

@app.get("/api/trends")
def api_trends():
    return {"items": store.trends(), "fetched_at": store.kv_get("trends_at")}


def _locked_refresh(fn, key):
    def run():
        if not jobs.cycle_lock.acquire(timeout=600):
            return
        jobs.set_state(task=key)
        try:
            fn(config.env(), force=True)
        except browser.LoginExpired:
            jobs.set_state(login_expired=True, env_mtime_at_expiry=config.env_mtime())
        except Exception as ex:
            log.info(f"{key} failed: {type(ex).__name__}: {ex}")
        finally:
            jobs.set_state(task="")
            jobs.phase("")
            jobs.cycle_lock.release()
    bg(run)


@app.post("/api/trends/refresh")
def api_trends_refresh():
    no_demo()
    _locked_refresh(jobs.refresh_trends, "trends")
    return {"started": True}


@app.get("/api/news")
def api_news():
    e = config.env()
    watch = sorted(store.recent_tweets(hours=72, source="watch"), key=lambda t: t["created_at"], reverse=True)
    return {"news": store.latest_news(), "watch": [public(t) for t in watch[:60]],
            "accounts": x_watch.accounts(e), "sources": json.loads(news.sources_file().read_text(encoding="utf-8"))}


@app.post("/api/news/refresh")
def api_news_refresh():
    no_demo()

    def run():
        jobs.refresh_news(config.env(), force=True)
        jobs.phase("")
    bg(run)
    _locked_refresh(jobs.refresh_watch, "watch")
    return {"started": True}


# ---------- learning ----------

@app.get("/api/learn")
def api_learn():
    e = config.env()
    style.sync_manual_edit()
    versions = [{k: v for k, v in x.items() if k != "notes"} | {"preview": x["notes"][:300]}
                for x in store.style_versions()]
    return {
        "files": {n: persona.read(n) for n in persona.FILES},
        "filled": {n: persona.is_filled(n) for n in persona.FILES},
        "mine": store.my_posts_stats(),
        "examples": len(persona.pick_examples()),
        "edits": len(store.edits(limit=1000)),
        "versions": versions,
        "evals": store.evals(),
        "fit": store.fit_stats(),
        "eval_sample": len(style.eval_sample(e)),
        "consolidated_at": store.kv_get("consolidated_at"),
        "next_consolidate_days": config.get_int(e, "CONSOLIDATE_EVERY_DAYS"),
        "state": {"learning": jobs.state["learning"], "task": jobs.state["task"]},
    }


class LearnReq(BaseModel):
    task: str
    force: bool = False


@app.post("/api/learn/run")
def api_learn_run(a: LearnReq):
    no_demo()
    e = config.env()
    if a.task not in ("scrape_mine", "learn", "consolidate", "eval"):
        _bad("bad_task")
    if a.task != "scrape_mine" and not llm.ready(e):
        _bad("ai_not_ready")
    if a.task == "scrape_mine" and not config.handle(e):
        _bad("handle_missing")
    if jobs.state["learning"]:
        return {"started": False}
    bg(jobs.run_learning, a.task, force=a.force)
    return {"started": True}


class VersionReq(BaseModel):
    id: int


@app.post("/api/learn/activate")
def api_learn_activate(a: VersionReq):
    if not style.activate(config.env(), a.id):
        _bad("not_found", 404)
    return {"ok": True}


@app.get("/api/learn/eval/{eval_id}")
def api_eval_detail(eval_id: int):
    with store.conn() as c:
        r = c.execute("SELECT * FROM evals WHERE id=?", (eval_id,)).fetchone()
    if not r:
        _bad("not_found", 404)
    d = dict(r)
    d["detail"] = json.loads(d["detail"] or "[]")
    return d


class ProfileReq(BaseModel):
    name: str
    text: str


@app.post("/api/profile")
def api_profile(a: ProfileReq):
    if a.name not in persona.FILES:
        _bad("bad_file")
    persona.write(a.name, a.text[:20000])
    if a.name == "style_notes.md":
        style.sync_manual_edit()
    return {"ok": True, "filled": persona.is_filled(a.name)}


@app.post("/api/import/archive")
async def api_import_archive(file: UploadFile = File(...)):
    no_demo()
    data = await file.read()
    if len(data) > 300 * 1024 * 1024:
        _bad("too_large", 413)
    try:
        replies_, posts_ = x_mine.read_archive(data, file.filename or "")
    except (ValueError, KeyError, json.JSONDecodeError) as ex:
        _bad(f"archive: {ex}")
    new = store.upsert_mine(replies_, posts_, origin="archive")
    log.info(f"archive import: {len(replies_)} replies, {len(posts_)} posts, {new} new")
    return {"replies": len(replies_), "posts": len(posts_), "new": new}


# ---------- settings ----------

@app.get("/api/settings")
def api_settings():
    e = config.env()
    return {"values": config.public_settings(e), "setup": setup_state(e)}


def setup_state(e):
    return {"x": bool(browser.parse_cookie_config(e).get("auth_token") and browser.parse_cookie_config(e).get("ct0")),
            "ai": llm.ready(e), "handle": bool(config.handle(e)), "persona": persona.is_filled("persona.md"),
            "mine": store.my_posts_stats()["total"], "login_expired": jobs.state["login_expired"]}


class SettingsReq(BaseModel):
    values: dict


@app.post("/api/settings")
def api_settings_save(a: SettingsReq):
    try:
        config.save(a.values)
    except ValueError as ex:
        _bad(str(ex))
    e = config.env()
    persona.ensure(e)
    if "X_AUTH_TOKEN" in a.values or "X_CT0" in a.values:
        jobs.set_state(login_expired=False)
    return {"ok": True, "values": config.public_settings(e), "setup": setup_state(e)}


def parse_cookie_input(raw: str) -> dict:
    """auth_token and ct0 from a Cookie header, a cookie-editor JSON export, or a Netscape cookies.txt."""
    raw = (raw or "").strip()
    found = {}
    if raw.startswith("[") or raw.startswith("{"):
        try:
            data = json.loads(raw)
            rows = data if isinstance(data, list) else data.get("cookies", [])
            for c in rows:
                if isinstance(c, dict) and c.get("name") in ("auth_token", "ct0"):
                    found[c["name"]] = str(c.get("value", ""))
        except json.JSONDecodeError:
            pass
    if not found:
        for line in raw.splitlines():
            cols = line.split("\t")
            if len(cols) >= 7 and cols[5] in ("auth_token", "ct0"):
                found[cols[5]] = cols[6].strip()
    if not found:
        for m in re.finditer(r"(?:^|[;\s])(auth_token|ct0)\s*[=:]\s*\"?([A-Za-z0-9%_\-]+)", raw):
            found[m.group(1)] = m.group(2)
    return found


@app.post("/api/settings/cookie")
def api_settings_cookie(a: TextReq):
    found = parse_cookie_input(a.text)
    if not found.get("auth_token") or not found.get("ct0"):
        _bad("cookie_incomplete")
    config.save({"X_AUTH_TOKEN": found["auth_token"], "X_CT0": found["ct0"]})
    jobs.set_state(login_expired=False)
    return {"ok": True}


@app.post("/api/settings/logout-x")
def api_logout_x():
    config.clear(["X_AUTH_TOKEN", "X_CT0", "X_COOKIE"])
    return {"ok": True}


class TestReq(BaseModel):
    what: str


@app.post("/api/settings/test")
def api_settings_test(a: TestReq):
    no_demo()
    e = config.env()
    if a.what == "ai":
        try:
            out = llm.chat(e, "Reply with exactly: OK", "ping", temperature=0, retries=1)
            return {"ok": True, "detail": out.strip()[:80]}
        except llm.AIError as ex:
            return {"ok": False, "detail": str(ex)[:300]}
    if a.what == "x":
        if not jobs.cycle_lock.acquire(timeout=120):
            return {"ok": False, "detail": "busy"}
        try:
            handle = browser.check_login(e)
        except browser.LoginExpired:
            return {"ok": False, "detail": "login_expired"}
        except Exception as ex:
            return {"ok": False, "detail": f"{type(ex).__name__}: {str(ex)[:200]}"}
        finally:
            jobs.cycle_lock.release()
        if handle and not config.handle(e):
            config.save({"MY_HANDLE": handle})
        jobs.set_state(login_expired=False)
        return {"ok": True, "detail": f"@{handle}" if handle else ""}
    if a.what == "api":
        try:
            return {"ok": True, "detail": x_api.whoami(e)}
        except publisher.SendError as ex:
            return {"ok": False, "detail": str(ex)}
    _bad("bad_test")


# ---------- startup ----------

def main():
    store.init()
    e = config.env()
    persona.ensure(e)
    style.sync_manual_edit()
    port = config.get_int(e, "PORT")
    jobs.set_state(last_ok=store.last_ok_ts())
    threading.Thread(target=jobs.scheduler, daemon=True, name="scheduler").start()
    threading.Thread(target=jobs.sender, daemon=True, name="sender").start()
    if config.get_bool(e, "SCRAPE_ON_START") and browser.parse_cookie_config(e).get("auth_token"):
        bg(jobs.run_cycle, "start")
    if config.get_bool(e, "OPEN_BROWSER"):  # launchd / services pass OPEN_BROWSER=0
        threading.Timer(1.2, lambda: webbrowser.open(f"http://127.0.0.1:{port}")).start()
    host = os.environ.get("HOST", "127.0.0.1")
    uvicorn.run(app, host=host, port=port, log_level="warning")


if __name__ == "__main__":
    main()
