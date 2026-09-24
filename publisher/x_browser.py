"""Send through x.com in a headless browser logged in with your cookie.

It opens X's own compose page (the web intent) with the text filled in, presses Post and
reads the result from the CreateTweet response, exactly as if you pressed it yourself.
With SEND_DRY_RUN=1 it stops right before pressing Post (useful for testing).
"""
from __future__ import annotations

from publisher import SendError, intent_url
from scraper import browser
from scraper.browser import LoginExpired

BUTTONS = '[data-testid="tweetButton"], [data-testid="tweetButtonInline"]'


def _result(payload):
    data = (payload or {}).get("data") or {}
    res = (((data.get("create_tweet") or {}).get("tweet_results") or {}).get("result") or {})
    tid = res.get("rest_id") or (res.get("tweet") or {}).get("rest_id")
    errors = (payload or {}).get("errors") or []
    return tid, "; ".join(str(x.get("message") or x) for x in errors)


async def _send(e, item):
    got = []
    async with browser.session(e) as page:
        browser.capture(page, ("/CreateTweet", "/CreateNoteTweet"), got)
        url = intent_url(item["kind"], item["text"], item.get("target_id"), item.get("target_url"))
        await page.goto(url, wait_until="domcontentloaded", timeout=45000)
        button = page.locator(BUTTONS).first
        for _ in range(30):
            if browser.is_login_page(page.url):
                raise LoginExpired()
            if await button.count() and await button.is_visible():
                break
            await page.wait_for_timeout(1000)
        else:
            raise SendError("the compose page did not load", retryable=True)
        box = page.locator('[data-testid="tweetTextarea_0"]').first
        if await box.count():
            shown = (await box.inner_text()).strip()
            if item["text"].strip()[:12] not in shown.replace("\n", "") and item["text"].strip()[:12] not in shown:
                raise SendError("X did not fill in the text")
        for _ in range(10):
            if await button.is_enabled() and await button.get_attribute("aria-disabled") != "true":
                break
            await page.wait_for_timeout(500)
        else:
            raise SendError("X will not post this (too long, a duplicate, or not allowed)")
        if str(e.get("SEND_DRY_RUN")) == "1":
            return ""
        await button.click()
        for _ in range(40):
            if got:
                break
            await page.wait_for_timeout(500)
        if not got:
            raise SendError("no answer from X after pressing Post; check your profile before retrying")
        tid, error = _result(got[-1][1])
        if not tid:
            raise SendError(f"X refused the post: {error or 'unknown reason'}",
                            retryable="rate" in error.lower() or "limit" in error.lower())
        return tid


def send(e, item) -> str:
    browser.logged_in_cookies(e)
    return browser.run(_send(e, item))
