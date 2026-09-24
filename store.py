"""SQLite storage.

tweets     one row per post seen (home timeline, watched accounts, search), updated in place
snapshots  metrics each time a post is seen, used for growth rates
my_posts   your own posts and replies (scraped, imported from an X archive, or sent from here)
drafts     generated posts / quote posts waiting for you
outbox     everything you asked to send, with its result
edits      AI suggestion -> what you actually sent; the strongest style signal there is
style_versions / evals   learned style notes and how well each version scored
"""
import json
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

import config

DB_PATH = config.DATA_DIR / "radar.db"
_lock = threading.RLock()

SCHEMA = """
CREATE TABLE IF NOT EXISTS tweets (
  id TEXT PRIMARY KEY,
  author_name TEXT, author_handle TEXT, author_avatar TEXT, author_followers INTEGER,
  text TEXT, url TEXT, created_at TEXT, lang TEXT, media_type TEXT, is_reply INTEGER,
  views INTEGER, replies INTEGER, likes INTEGER, retweets INTEGER, quotes INTEGER,
  first_seen TEXT, last_seen TEXT, seen_count INTEGER DEFAULT 1,
  topic TEXT, relevance REAL, blocked INTEGER DEFAULT 0,
  reply_a TEXT, reply_b TEXT, ai_want REAL, ai_skip INTEGER, ai_at TEXT,
  dismissed INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS snapshots (
  tweet_id TEXT, ts TEXT, views INTEGER, replies INTEGER, likes INTEGER, retweets INTEGER, quotes INTEGER
);
CREATE INDEX IF NOT EXISTS idx_snap ON snapshots(tweet_id, ts);
CREATE TABLE IF NOT EXISTS mutes (kind TEXT, value TEXT, ts TEXT, PRIMARY KEY (kind, value));
CREATE TABLE IF NOT EXISTS my_posts (
  id TEXT PRIMARY KEY, kind TEXT, text TEXT, parent_id TEXT, parent_author TEXT, parent_text TEXT,
  created_at TEXT, views INTEGER, likes INTEGER, replies INTEGER, first_seen TEXT
);
CREATE TABLE IF NOT EXISTS drafts (
  id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT, kind TEXT, angle TEXT, text TEXT, based_on TEXT,
  status TEXT DEFAULT 'new', score REAL
);
CREATE TABLE IF NOT EXISTS news (
  url TEXT PRIMARY KEY, source TEXT, title TEXT, summary TEXT, published TEXT, first_seen TEXT, picked_at TEXT
);
CREATE TABLE IF NOT EXISTS kv (k TEXT PRIMARY KEY, v TEXT);
CREATE TABLE IF NOT EXISTS runs (ts TEXT, ok INTEGER, fetched INTEGER, new INTEGER, message TEXT);
CREATE TABLE IF NOT EXISTS outbox (
  id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT, kind TEXT, text TEXT, ai_text TEXT,
  target_id TEXT, target_url TEXT, target_author TEXT, target_text TEXT, draft_id INTEGER,
  channel TEXT, status TEXT DEFAULT 'pending', result_id TEXT, error TEXT, sent_at TEXT, attempts INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_outbox_status ON outbox(status, created_at);
CREATE TABLE IF NOT EXISTS edits (
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, kind TEXT, ai_text TEXT, final_text TEXT, context TEXT
);
CREATE TABLE IF NOT EXISTS style_versions (
  id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT, notes TEXT, reason TEXT,
  posts_count INTEGER, score REAL, active INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS evals (
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, version_id INTEGER, label TEXT, model TEXT,
  n INTEGER, score_a REAL, score_b REAL, score REAL, detail TEXT
);
CREATE TABLE IF NOT EXISTS trends (
  name TEXT, context TEXT, posts TEXT, rank INTEGER, fetched_at TEXT
);
"""

# Columns added after the first release; init() adds whichever are missing.
MIGRATIONS = {
    "drafts": ("score REAL", "url TEXT", "source TEXT", "facts TEXT", "target_id TEXT", "target_author TEXT"),
    "tweets": ("fit_a REAL", "fit_b REAL", "source TEXT", "quote_draft TEXT"),
    "my_posts": ("origin TEXT",),
}

METRICS = ("views", "replies", "likes", "retweets", "quotes")


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _ago(**kw):
    return (datetime.now(timezone.utc) - timedelta(**kw)).isoformat()


@contextmanager
def conn():
    """One short-lived connection per call; committed on success, always closed."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(DB_PATH, timeout=15)
    c.row_factory = sqlite3.Row
    try:
        with c:
            yield c
    finally:
        c.close()


def init():
    with _lock, conn() as c:
        c.execute("PRAGMA journal_mode=WAL")
        c.executescript(SCHEMA)
        for table, cols in MIGRATIONS.items():
            have = {r[1] for r in c.execute(f"PRAGMA table_info({table})")}
            for col in cols:
                if col.split()[0] not in have:
                    c.execute(f"ALTER TABLE {table} ADD COLUMN {col}")
        c.execute("CREATE INDEX IF NOT EXISTS idx_tweets_created ON tweets(created_at)")


# ---------- radar posts ----------

def upsert(tweets, ts=None, source="home"):
    """New posts are inserted, known ones only get fresh numbers. Returns how many were new."""
    ts = ts or now()
    new = 0
    with _lock, conn() as c:
        for t in tweets:
            row = c.execute("SELECT id FROM tweets WHERE id=?", (t["id"],)).fetchone()
            if row:
                c.execute(
                    "UPDATE tweets SET views=COALESCE(?,views), replies=?, likes=?, retweets=?, quotes=?,"
                    " author_followers=COALESCE(?,author_followers), last_seen=?, seen_count=seen_count+1,"
                    " topic=?, relevance=?, blocked=? WHERE id=?",
                    (t["views"], t["replies"], t["likes"], t["retweets"], t["quotes"],
                     t["author_followers"], ts, t.get("topic", ""), t.get("relevance", 0), t.get("blocked", 0),
                     t["id"]))
            else:
                new += 1
                c.execute(
                    "INSERT INTO tweets (id, author_name, author_handle, author_avatar, author_followers, text, url,"
                    " created_at, lang, media_type, is_reply, views, replies, likes, retweets, quotes,"
                    " first_seen, last_seen, topic, relevance, blocked, source)"
                    " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (t["id"], t["author_name"], t["author_handle"], t["author_avatar"], t["author_followers"],
                     t["text"], t["url"], t["created_at"], t["lang"], t["media_type"], int(t["is_reply"]),
                     t["views"], t["replies"], t["likes"], t["retweets"], t["quotes"],
                     ts, ts, t.get("topic", ""), t.get("relevance", 0), t.get("blocked", 0), source))
            c.execute("INSERT INTO snapshots VALUES (?,?,?,?,?,?,?)",
                      (t["id"], ts, t["views"], t["replies"], t["likes"], t["retweets"], t["quotes"]))
    return new


def snapshots(tweet_id):
    with conn() as c:
        return [dict(r) for r in c.execute("SELECT * FROM snapshots WHERE tweet_id=? ORDER BY ts", (tweet_id,))]


def snapshots_for(ids):
    """Snapshots for many posts in one query: {tweet_id: [snap, ...]}."""
    ids = list(ids)
    out = {i: [] for i in ids}
    if not ids:
        return out
    with conn() as c:
        for chunk in range(0, len(ids), 500):
            part = ids[chunk:chunk + 500]
            q = f"SELECT * FROM snapshots WHERE tweet_id IN ({','.join('?' * len(part))}) ORDER BY ts"
            for r in c.execute(q, part):
                out[r["tweet_id"]].append(dict(r))
    return out


def recent_tweets(hours=24, source="home"):
    """Undismissed, unblocked posts from the last `hours`. source=None means any source."""
    q = "SELECT * FROM tweets WHERE created_at > ? AND dismissed=0 AND blocked=0"
    args = [_ago(hours=hours)]
    if source == "home":
        q += " AND COALESCE(source,'home')='home'"
    elif source:
        q += " AND source=?"
        args.append(source)
    with conn() as c:
        return [dict(r) for r in c.execute(q, args)]


def tweet(tweet_id):
    with conn() as c:
        r = c.execute("SELECT * FROM tweets WHERE id=?", (tweet_id,)).fetchone()
        return dict(r) if r else None


def save_replies(tweet_id, a, b, want, skip, fit_a=None, fit_b=None):
    with _lock, conn() as c:
        c.execute("UPDATE tweets SET reply_a=?, reply_b=?, ai_want=?, ai_skip=?, ai_at=?, fit_a=?, fit_b=?"
                  " WHERE id=?", (a, b, want, int(skip), now(), fit_a, fit_b, tweet_id))


def reset_replies(tweet_id):
    with _lock, conn() as c:
        c.execute("UPDATE tweets SET reply_a=NULL, reply_b=NULL, ai_at=NULL, ai_skip=0, fit_a=NULL, fit_b=NULL"
                  " WHERE id=?", (tweet_id,))


def recent_replies(n=12):
    with conn() as c:
        rows = c.execute("SELECT reply_a, reply_b FROM tweets WHERE ai_skip=0 AND reply_a IS NOT NULL"
                         " ORDER BY ai_at DESC LIMIT ?", (n // 2,)).fetchall()
    return [x for r in rows for x in r if x]


def dismiss(tweet_id):
    with _lock, conn() as c:
        c.execute("UPDATE tweets SET dismissed=1 WHERE id=?", (tweet_id,))


def mute(kind, value):
    with _lock, conn() as c:
        c.execute("INSERT OR REPLACE INTO mutes VALUES (?,?,?)", (kind, value, now()))


def unmute(kind, value):
    with _lock, conn() as c:
        c.execute("DELETE FROM mutes WHERE kind=? AND value=?", (kind, value))


def mutes():
    with conn() as c:
        return {(r["kind"], r["value"]) for r in c.execute("SELECT kind, value FROM mutes")}


def mute_list():
    with conn() as c:
        return [dict(r) for r in c.execute("SELECT * FROM mutes ORDER BY ts DESC")]


def log_run(ok, fetched, new, message):
    with _lock, conn() as c:
        c.execute("INSERT INTO runs VALUES (?,?,?,?,?)", (now(), int(ok), fetched, new, message))


def last_runs(n=1):
    with conn() as c:
        return [dict(r) for r in c.execute("SELECT * FROM runs ORDER BY ts DESC LIMIT ?", (n,))]


def last_ok_ts():
    with conn() as c:
        r = c.execute("SELECT ts FROM runs WHERE ok=1 ORDER BY ts DESC LIMIT 1").fetchone()
        return r["ts"] if r else None


# ---------- your own posts ----------

def upsert_mine(pairs, posts, origin="scrape"):
    """Your replies / posts: never cleaned up. Returns how many were new."""
    new = 0
    with _lock, conn() as c:
        for kind, rows in (("reply", pairs), ("post", posts)):
            for t in rows:
                if not c.execute("SELECT 1 FROM my_posts WHERE id=?", (t["id"],)).fetchone():
                    new += 1
                c.execute(
                    "INSERT INTO my_posts (id, kind, text, parent_id, parent_author, parent_text, created_at,"
                    " views, likes, replies, first_seen, origin) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)"
                    " ON CONFLICT(id) DO UPDATE SET views=COALESCE(excluded.views, views),"
                    " likes=COALESCE(excluded.likes, likes), replies=COALESCE(excluded.replies, replies),"
                    " parent_text=CASE WHEN COALESCE(parent_text,'')='' THEN excluded.parent_text ELSE parent_text END,"
                    " parent_author=COALESCE(parent_author, excluded.parent_author)",
                    (t["id"], kind, t["text"], t.get("parent_id"), t.get("parent_author"), t.get("parent_text") or "",
                     t["created_at"], t.get("views"), t.get("likes"), t.get("replies"), now(), origin))
    return new


def my_posts(kind=None):
    with conn() as c:
        q = "SELECT * FROM my_posts" + (" WHERE kind=?" if kind else "") + " ORDER BY created_at DESC"
        return [dict(r) for r in c.execute(q, (kind,) if kind else ())]


def my_posts_stats():
    with conn() as c:
        rows = c.execute("SELECT kind, COALESCE(origin,'scrape') AS origin, COUNT(*) AS n FROM my_posts"
                         " GROUP BY kind, origin").fetchall()
        newest = c.execute("SELECT MAX(created_at) FROM my_posts").fetchone()[0]
    return {"by": [dict(r) for r in rows], "total": sum(r["n"] for r in rows), "newest": newest}


def _norm(text):
    import re
    return re.sub(r"\s+", " ", re.sub(r"^(@\w+\s*)+", "", text or "")).strip()


def ai_written_texts():
    """Texts you sent from here that started as an AI draft. They are not your own writing, so they stay
    out of examples, evaluation and learning (your edits to them are learned through `edits`)."""
    with conn() as c:
        return {_norm(r[0]) for r in c.execute(
            "SELECT text FROM outbox WHERE status='sent' AND ai_text IS NOT NULL AND ai_text != ''")}


def my_own_posts(kind=None):
    """Your posts minus anything AI-drafted."""
    ai = ai_written_texts()
    return [p for p in my_posts(kind) if _norm(p["text"]) not in ai]


def replied_ids():
    with conn() as c:
        ids = {r[0] for r in c.execute("SELECT parent_id FROM my_posts WHERE kind='reply' AND parent_id IS NOT NULL")}
        ids |= {r[0] for r in c.execute("SELECT target_id FROM outbox WHERE kind='reply'"
                                        " AND status IN ('pending','sending','sent','opened')")}
    return ids


# ---------- drafts ----------

def add_drafts(posts):
    ts = now()
    with _lock, conn() as c:
        ids = []
        for p in posts:
            cur = c.execute(
                "INSERT INTO drafts (created_at, kind, angle, text, based_on, score, url, source, facts,"
                " target_id, target_author) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (ts, p.get("kind"), p.get("angle"), p["text"].strip(), p.get("based_on"), p.get("score"),
                 p.get("url"), p.get("source"), p.get("facts"), p.get("target_id"), p.get("target_author")))
            ids.append(cur.lastrowid)
    return ids


def drafts(status=None, limit=50):
    with conn() as c:
        q = "SELECT * FROM drafts" + (" WHERE status=?" if status else "") + " ORDER BY created_at DESC, id ASC LIMIT ?"
        return [dict(r) for r in c.execute(q, ((status, limit) if status else (limit,)))]


def draft(draft_id):
    with conn() as c:
        r = c.execute("SELECT * FROM drafts WHERE id=?", (draft_id,)).fetchone()
        return dict(r) if r else None


def set_draft(draft_id, status, text=None):
    with _lock, conn() as c:
        if text is None:
            c.execute("UPDATE drafts SET status=? WHERE id=?", (status, draft_id))
        else:
            c.execute("UPDATE drafts SET status=?, text=? WHERE id=?", (status, text, draft_id))


# ---------- news & trends ----------

def upsert_news(items):
    ts = now()
    with _lock, conn() as c:
        for it in items:
            c.execute("INSERT INTO news (url, source, title, summary, published, first_seen) VALUES (?,?,?,?,?,?)"
                      " ON CONFLICT(url) DO NOTHING",
                      (it["url"], it["source"], it["title"], it["summary"], it.get("published"), ts))


def fresh_news(hours=36):
    """News not picked for a draft yet, newest first; undated items count from when we first saw them."""
    with conn() as c:
        return [dict(r) for r in c.execute(
            "SELECT * FROM news WHERE picked_at IS NULL AND COALESCE(published, first_seen) > ?"
            " ORDER BY COALESCE(published, first_seen) DESC", (_ago(hours=hours),))]


def latest_news(hours=72, limit=60):
    with conn() as c:
        return [dict(r) for r in c.execute(
            "SELECT * FROM news WHERE COALESCE(published, first_seen) > ?"
            " ORDER BY COALESCE(published, first_seen) DESC LIMIT ?", (_ago(hours=hours), limit))]


def news_item(url):
    with conn() as c:
        r = c.execute("SELECT * FROM news WHERE url=?", (url,)).fetchone()
        return dict(r) if r else None


def mark_news(urls):
    with _lock, conn() as c:
        c.executemany("UPDATE news SET picked_at=? WHERE url=?", [(now(), u) for u in urls])


def save_trends(items):
    ts = now()
    with _lock, conn() as c:
        c.execute("DELETE FROM trends")
        c.executemany("INSERT INTO trends VALUES (?,?,?,?,?)",
                      [(t["name"], t.get("context", ""), t.get("posts", ""), i, ts) for i, t in enumerate(items)])


def trends():
    with conn() as c:
        return [dict(r) for r in c.execute("SELECT * FROM trends ORDER BY rank")]


# ---------- outbox ----------

def enqueue(kind, text, channel, ai_text=None, target=None, draft_id=None, status="pending"):
    target = target or {}
    with _lock, conn() as c:
        cur = c.execute(
            "INSERT INTO outbox (created_at, kind, text, ai_text, target_id, target_url, target_author, target_text,"
            " draft_id, channel, status) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (now(), kind, text, ai_text, target.get("id"), target.get("url"), target.get("author_handle"),
             (target.get("text") or "")[:1000], draft_id, channel, status))
        return cur.lastrowid


def outbox(limit=100, status=None):
    with conn() as c:
        q = "SELECT * FROM outbox" + (" WHERE status=?" if status else "") + " ORDER BY id DESC LIMIT ?"
        return [dict(r) for r in c.execute(q, ((status, limit) if status else (limit,)))]


def outbox_item(item_id):
    with conn() as c:
        r = c.execute("SELECT * FROM outbox WHERE id=?", (item_id,)).fetchone()
        return dict(r) if r else None


def next_pending():
    with conn() as c:
        r = c.execute("SELECT * FROM outbox WHERE status='pending' ORDER BY id LIMIT 1").fetchone()
        return dict(r) if r else None


def update_outbox(item_id, **fields):
    if not fields:
        return
    cols = ", ".join(f"{k}=?" for k in fields)
    with _lock, conn() as c:
        c.execute(f"UPDATE outbox SET {cols} WHERE id=?", (*fields.values(), item_id))


def sent_since(**kw):
    with conn() as c:
        return c.execute("SELECT COUNT(*) FROM outbox WHERE status='sent' AND sent_at > ?",
                         (_ago(**kw),)).fetchone()[0]


def last_sent_at():
    with conn() as c:
        return c.execute("SELECT MAX(sent_at) FROM outbox WHERE status='sent'").fetchone()[0]


def recover_sending():
    """After a crash, anything stuck in 'sending' is unknown: mark it so it is never sent twice."""
    with _lock, conn() as c:
        c.execute("UPDATE outbox SET status='failed', error='interrupted' WHERE status='sending'")


# ---------- learning ----------

def add_edit(kind, ai_text, final_text, context=""):
    if not ai_text or not final_text:
        return
    with _lock, conn() as c:
        c.execute("INSERT INTO edits (ts, kind, ai_text, final_text, context) VALUES (?,?,?,?,?)",
                  (now(), kind, ai_text, final_text, context[:500]))


def edits(since=None, limit=60):
    with conn() as c:
        q = "SELECT * FROM edits" + (" WHERE ts > ?" if since else "") + " ORDER BY id DESC LIMIT ?"
        return [dict(r) for r in c.execute(q, ((since, limit) if since else (limit,)))]


def dropped_drafts(since=None, limit=30):
    with conn() as c:
        q = "SELECT text FROM drafts WHERE status='dropped'" + (" AND created_at > ?" if since else "") + \
            " ORDER BY id DESC LIMIT ?"
        return [r[0] for r in c.execute(q, ((since, limit) if since else (limit,)))]


def add_style_version(notes, reason, posts_count, score=None, active=True):
    with _lock, conn() as c:
        if active:
            c.execute("UPDATE style_versions SET active=0")
        cur = c.execute("INSERT INTO style_versions (created_at, notes, reason, posts_count, score, active)"
                        " VALUES (?,?,?,?,?,?)", (now(), notes, reason, posts_count, score, int(active)))
        return cur.lastrowid


def style_versions(limit=30):
    with conn() as c:
        return [dict(r) for r in c.execute("SELECT * FROM style_versions ORDER BY id DESC LIMIT ?", (limit,))]


def style_version(version_id):
    with conn() as c:
        r = c.execute("SELECT * FROM style_versions WHERE id=?", (version_id,)).fetchone()
        return dict(r) if r else None


def activate_style_version(version_id):
    with _lock, conn() as c:
        c.execute("UPDATE style_versions SET active=0")
        c.execute("UPDATE style_versions SET active=1 WHERE id=?", (version_id,))


def set_style_score(version_id, score):
    with _lock, conn() as c:
        c.execute("UPDATE style_versions SET score=? WHERE id=?", (score, version_id))


def active_style_version():
    with conn() as c:
        r = c.execute("SELECT * FROM style_versions WHERE active=1 ORDER BY id DESC LIMIT 1").fetchone()
        return dict(r) if r else None


def add_eval(version_id, label, model, n, score_a, score_b, detail):
    score = round((score_a + score_b) / 2, 2) if n else None
    with _lock, conn() as c:
        c.execute("INSERT INTO evals (ts, version_id, label, model, n, score_a, score_b, score, detail)"
                  " VALUES (?,?,?,?,?,?,?,?,?)",
                  (now(), version_id, label, model, n, score_a, score_b, score, json.dumps(detail, ensure_ascii=False)))
    return score


def evals(limit=40):
    with conn() as c:
        return [dict(r) for r in c.execute(
            "SELECT id, ts, version_id, label, model, n, score_a, score_b, score FROM evals ORDER BY id DESC LIMIT ?",
            (limit,))]


def fit_stats(days=7):
    """Average fit score of the A/B suggestions generated in the last `days`."""
    with conn() as c:
        r = c.execute("SELECT AVG(fit_a), AVG(fit_b), COUNT(fit_a) FROM tweets WHERE ai_at > ? AND fit_a IS NOT NULL",
                      (_ago(days=days),)).fetchone()
    return {"a": round(r[0], 2) if r[0] else None, "b": round(r[1], 2) if r[1] else None, "n": r[2]}


# ---------- misc ----------

def kv_get(k, default=None):
    with conn() as c:
        r = c.execute("SELECT v FROM kv WHERE k=?", (k,)).fetchone()
        return r[0] if r else default


def kv_set(k, v):
    with _lock, conn() as c:
        c.execute("INSERT OR REPLACE INTO kv VALUES (?,?)", (k, str(v)))


def cleanup(days=10):
    cut = _ago(days=days)
    with _lock, conn() as c:
        c.execute("DELETE FROM snapshots WHERE ts < ?", (cut,))
        c.execute("DELETE FROM tweets WHERE last_seen < ?", (cut,))
        c.execute("DELETE FROM runs WHERE ts < ?", (cut,))
