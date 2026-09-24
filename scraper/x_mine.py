"""Your own posts and replies: scraped from your profile, or imported from an X data archive."""
from __future__ import annotations

import json
import random
import re
import zipfile
from datetime import datetime, timezone
from io import BytesIO

import config
from scraper import browser
from scraper.browser import LoginExpired
from scraper.parse import clean, my_posts

KEYS = ("/UserRepliesTimeline", "/UserTweets", "/UserOriginalsTimeline")


async def _scrape(e, handle, scrolls, log):
    got = []
    async with browser.session(e) as page:
        browser.capture(page, KEYS, got)
        for path in ("with_replies", ""):
            await page.goto(f"https://x.com/{handle}/{path}".rstrip("/"), wait_until="domcontentloaded")
            await page.wait_for_timeout(6000)
            if browser.is_login_page(page.url):
                raise LoginExpired()
            idle = 0
            for _ in range(scrolls):
                before = len(got)
                await page.mouse.wheel(0, random.randint(2500, 3500))
                await page.wait_for_timeout(random.randint(1800, 3200))
                idle = idle + 1 if len(got) == before else 0
                if idle >= 3:  # reached the end of what X will show
                    break
    pairs, posts = my_posts([pl for _, pl in got], handle)
    log(f"your posts: {len(pairs)} replies, {len(posts)} posts")
    return pairs, posts


def scrape_mine(e, log=print, scrolls=None):
    handle = config.handle(e)
    if not handle:
        raise ValueError("MY_HANDLE is not set")
    browser.logged_in_cookies(e)
    return browser.run(_scrape(e, handle, scrolls or config.get_int(e, "MINE_SCROLLS"), log))


# ---------- X data archive (Settings > Your account > Download an archive of your data) ----------

def _archive_json(raw: bytes):
    text = raw.decode("utf-8-sig")
    text = re.sub(r"^\s*window\.YTD\.[\w.]+\s*=\s*", "", text)
    return json.loads(text)


def read_archive(data: bytes, filename: str = ""):
    """Accepts the archive .zip, or data/tweets.js from inside it. Returns (replies, posts)."""
    blobs = []
    if data[:2] == b"PK":
        with zipfile.ZipFile(BytesIO(data)) as z:
            for name in z.namelist():
                if re.search(r"(^|/)data/tweets(-part\d+)?\.js$", name):
                    blobs.append(z.read(name))
        if not blobs:
            raise ValueError("no data/tweets.js in this archive")
    else:
        blobs.append(data)
    replies, posts = [], []
    for blob in blobs:
        for row in _archive_json(blob):
            t = row.get("tweet", row)
            text = t.get("full_text") or t.get("text") or ""
            if text.startswith("RT @"):
                continue  # a retweet is someone else's words
            try:
                created = datetime.strptime(t["created_at"], "%a %b %d %H:%M:%S %z %Y").astimezone(timezone.utc)
            except (KeyError, ValueError):
                continue
            item = {"id": t.get("id_str") or str(t.get("id")), "text": clean(text), "created_at": created.isoformat(),
                    "likes": int(t.get("favorite_count") or 0), "replies": None, "views": None}
            if not item["text"]:
                continue
            if t.get("in_reply_to_status_id_str"):
                # the archive has no text for the post you replied to; it still teaches how you write
                replies.append({**item, "parent_id": t["in_reply_to_status_id_str"],
                                "parent_author": t.get("in_reply_to_screen_name") or "", "parent_text": ""})
            else:
                posts.append(item)
    return replies, posts
