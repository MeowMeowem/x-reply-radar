"""Latest posts from accounts you watch (e.g. official accounts of the companies you follow)."""
from __future__ import annotations

import random
import re

from scraper import browser
from scraper.browser import LoginExpired
from scraper.parse import tweets_in

KEYS = ("/UserTweets", "/UserOriginalsTimeline")  # X renamed the profile timeline in 2026


def accounts(e) -> list[str]:
    return [a for a in (x.strip().lstrip("@") for x in re.split(r"[,\s]+", e.get("WATCH_ACCOUNTS") or "")) if a][:20]


async def _scrape(e, handles, per_account, log):
    out = []
    async with browser.session(e) as page:
        for handle in handles:
            got = []
            handler = browser.capture(page, KEYS, got)
            try:
                await page.goto(f"https://x.com/{handle}", wait_until="domcontentloaded", timeout=30000)
                for _ in range(12):
                    if got or browser.is_login_page(page.url):
                        break
                    await page.wait_for_timeout(1000)
                if browser.is_login_page(page.url):
                    raise LoginExpired()
                posts = [t for pl in (p for _, p in got) for t in tweets_in(pl)[0]
                         if t["author_handle"].lower() == handle.lower() and not t["is_reply"]]
                posts.sort(key=lambda t: t["created_at"], reverse=True)
                out += posts[:per_account]
            except LoginExpired:
                raise
            except Exception as ex:
                log(f"watch @{handle} failed: {type(ex).__name__}")
            finally:
                page.remove_listener("response", handler)
            await page.wait_for_timeout(random.randint(1500, 3000))
    log(f"watched accounts: {len(out)} posts from {len(handles)} accounts")
    return out


def scrape_watch(e, log=print, per_account=5):
    handles = accounts(e)
    if not handles:
        return []
    browser.logged_in_cookies(e)
    return browser.run(_scrape(e, handles, per_account, log))
