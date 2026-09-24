"""Your X home timeline ("For you"), plus a fresh look at current candidates for growth rates."""
from __future__ import annotations

import random
from urllib.parse import urlparse

from scraper import browser
from scraper.browser import LoginExpired, ScrapeError
from scraper.parse import find_tweet, parse_timeline

HOME = "https://x.com/home"
TIMELINE_KEYS = ("/HomeTimeline", "/HomeLatestTimeline")
DETAIL_KEY = "/TweetDetail"
UA = browser.UA


async def _refresh(page, targets, log):
    """Open each candidate's page and read its current numbers; a few per round, spaced out."""
    out = []
    for tid, url in targets:
        got = []
        handler = browser.capture(page, (DETAIL_KEY,), got)
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            for _ in range(15):
                if got:
                    break
                await page.wait_for_timeout(1000)
            t = next((x for x in (find_tweet(pl, tid) for _, pl in got) if x), None)
            if t:
                out.append(t)
        except Exception as ex:
            log(f"refresh failed {tid}: {type(ex).__name__}")
        finally:
            page.remove_listener("response", handler)
        await page.wait_for_timeout(random.randint(1500, 3500))
    return out


async def _scrape(e, target, max_scrolls, log, refresh=()):
    payloads, refreshed = [], []
    async with browser.session(e) as page:
        handler = browser.capture(page, TIMELINE_KEYS, payloads)
        await page.goto(HOME, wait_until="domcontentloaded", timeout=45000)

        def logged_out():  # logged out, X sends /home back to the landing page or /login
            return not urlparse(page.url).path.startswith("/home")

        for _ in range(30):
            if payloads or logged_out():
                break
            await page.wait_for_timeout(1000)
        if logged_out():
            raise LoginExpired()
        if not payloads:
            if await page.locator('[data-testid="loginButton"], a[href="/login"]').count():
                raise LoginExpired()
            raise ScrapeError("home timeline did not load within 30s")

        # if the home page remembers "Following", switch back to "For you"
        if all("HomeLatestTimeline" in u for u, _ in payloads):
            tab = page.locator('[role="tablist"] [role="tab"]').first
            if await tab.count():
                await tab.click()
                await page.wait_for_timeout(3000)

        def count():
            seen = set()
            for u, pl in payloads:
                if "HomeTimeline" in u and "Latest" not in u:
                    seen.update(t["id"] for t in parse_timeline(pl)[0])
            return len(seen)

        for _ in range(max_scrolls):
            if count() >= target:
                break
            await page.mouse.wheel(0, random.randint(2200, 3600))
            await page.wait_for_timeout(random.randint(1800, 3800))
        page.remove_listener("response", handler)
        if refresh:
            refreshed = await _refresh(page, refresh, log)

    for_you = [pl for u, pl in payloads if "HomeLatestTimeline" not in u]
    use = for_you or [pl for _, pl in payloads]
    tweets, promoted, seen = [], 0, set()
    for pl in use:
        ts, pr = parse_timeline(pl)
        promoted += pr
        for t in ts:
            if t["id"] not in seen:
                seen.add(t["id"])
                tweets.append(t)
    for t in refreshed:
        if t["id"] not in seen:
            seen.add(t["id"])
            tweets.append(t)
    log(f"home: {len(tweets) - len(refreshed)} posts ({'For you' if for_you else 'Following'}), "
        f"{promoted} ads skipped; rechecked {len(refreshed)}/{len(refresh)} candidates")
    return tweets, promoted


def scrape_home(e: dict, log=print, target: int = 40, max_scrolls: int = 6, refresh=()):
    """refresh: [(tweet_id, url)]. The home feed changes every time, so current candidates are
    revisited on their own pages to measure growth."""
    browser.logged_in_cookies(e)
    return browser.run(_scrape(e, target, max_scrolls, log, list(refresh)))
