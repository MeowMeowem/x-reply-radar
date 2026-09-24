"""Following someone: X's follow page (you press Follow), a headless browser, or the official API."""
from __future__ import annotations

from urllib.parse import urlencode

import httpx

from publisher import SendError
from publisher import x_api
from scraper import browser
from scraper.browser import LoginExpired

LIMIT_WORDS = ("limit", "unable to follow", "161", "too many")


def intent_url(handle: str) -> str:
    return "https://x.com/intent/follow?" + urlencode({"screen_name": handle})


async def _follow(e, c):
    got = []
    async with browser.session(e) as page:
        browser.capture(page, ("/friendships/create",), got)
        await page.goto(f"https://x.com/{c['handle']}", wait_until="domcontentloaded", timeout=40000)
        follow = page.locator(f'[data-testid="{c["user_id"]}-follow"]').first
        unfollow = page.locator(f'[data-testid="{c["user_id"]}-unfollow"]').first
        for _ in range(25):
            if browser.is_login_page(page.url):
                raise LoginExpired()
            if await unfollow.count():
                return "already"
            if await follow.count():
                break
            await page.wait_for_timeout(1000)
        else:
            raise SendError("no follow button on this profile (suspended, blocked or renamed)")
        if str(e.get("SEND_DRY_RUN")) == "1":
            return "dry_run"
        await follow.click()
        for _ in range(20):
            if await unfollow.count():
                return "followed"
            await page.wait_for_timeout(500)
        detail = ""
        if got:
            errors = (got[-1][1] or {}).get("errors") or []
            detail = "; ".join(str(x.get("message") or x) for x in errors)
        raise SendError(f"X did not confirm the follow{': ' + detail if detail else ''}",
                        retryable=any(w in detail.lower() for w in LIMIT_WORDS))


def follow_browser(e, c) -> str:
    browser.logged_in_cookies(e)
    return browser.run(_follow(e, c))


def follow_api(e, c) -> str:
    if not x_api.configured(e):
        raise SendError("X API keys are not set")
    if str(e.get("SEND_DRY_RUN")) == "1":
        return "dry_run"
    me = x_api.my_id(e)
    url = f"https://api.x.com/2/users/{me}/following"
    auth = x_api.oauth1_header("POST", url, *(e[k].strip() for k in x_api.KEYS))
    try:
        r = httpx.post(url, json={"target_user_id": c["user_id"]}, headers={"Authorization": auth}, timeout=30)
    except httpx.HTTPError as ex:
        raise SendError(f"X API unreachable: {type(ex).__name__}", retryable=True)
    if r.status_code in (200, 201):
        return "followed"
    raise SendError(f"X API {r.status_code}: {r.text[:200]}", retryable=r.status_code == 429)


def follow(e, c) -> str:
    channel = c.get("channel") or e.get("POST_CHANNEL") or "intent"
    if channel == "api":
        return follow_api(e, c)
    if channel == "browser":
        return follow_browser(e, c)
    raise SendError("the intent channel follows from your own browser")
