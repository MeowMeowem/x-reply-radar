"""Shared headless browser session for x.com, logged in with your cookie.

The cookie is read from settings here and handed straight to the browser; it is never
logged or returned. Pages are read by capturing the GraphQL responses the X web app
itself requests, which is far steadier than parsing the DOM.
"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

from playwright.async_api import async_playwright

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36")


class LoginExpired(Exception):
    pass


class ScrapeError(Exception):
    pass


def parse_cookie_config(e: dict) -> dict:
    """X_AUTH_TOKEN + X_CT0, or a whole Cookie header in X_COOKIE."""
    cookies = {}
    for part in (e.get("X_COOKIE") or "").strip().split(";"):
        if "=" in part:
            k, v = part.split("=", 1)
            cookies[k.strip()] = v.strip()
    if e.get("X_AUTH_TOKEN"):
        cookies["auth_token"] = e["X_AUTH_TOKEN"].strip()
    if e.get("X_CT0"):
        cookies["ct0"] = e["X_CT0"].strip()
    return cookies


def logged_in_cookies(e: dict) -> dict:
    cookies = parse_cookie_config(e)
    if not cookies.get("auth_token") or not cookies.get("ct0"):
        raise LoginExpired()
    return cookies


def locale(e: dict) -> str:
    return "en-US" if e.get("CONTENT_LANG") == "en" else "zh-CN"


async def _launch(p, e):
    channel = (e.get("BROWSER_CHANNEL") or "chrome").strip()
    if channel and channel != "chromium":
        try:
            return await p.chromium.launch(channel=channel, headless=True)
        except Exception:
            pass  # that browser isn't installed: fall back to Playwright's bundled Chromium
    return await p.chromium.launch(headless=True)


@asynccontextmanager
async def session(e: dict):
    """Yields a logged-in page. Raises LoginExpired when no cookie is configured."""
    cookies = logged_in_cookies(e)
    async with async_playwright() as p:
        browser = await _launch(p, e)
        try:
            ctx = await browser.new_context(user_agent=UA, locale=locale(e), viewport={"width": 1280, "height": 1600})
            await ctx.add_cookies([
                {"name": k, "value": v, "domain": ".x.com", "path": "/", "secure": True,
                 "httpOnly": k == "auth_token", "sameSite": "None" if k == "ct0" else "Lax"}
                for k, v in cookies.items()])
            yield await ctx.new_page()
        finally:
            await browser.close()


def is_login_page(url: str) -> bool:
    return any(x in url for x in ("/i/flow/login", "/login", "/i/flow/signup")) or url.rstrip("/") in (
        "https://x.com", "https://twitter.com")


def capture(page, keys, sink: list):
    """Collect JSON bodies of responses whose URL contains any of `keys`. Returns the handler to remove later."""
    async def on_response(resp):
        if resp.status == 200 and any(k in resp.url for k in keys):
            try:
                sink.append((resp.url, await resp.json()))
            except Exception:
                pass
    page.on("response", on_response)
    return on_response


def run(coro):
    return asyncio.run(coro)


async def _check(e):
    async with session(e) as page:
        await page.goto("https://x.com/home", wait_until="domcontentloaded", timeout=45000)
        link = page.locator('a[data-testid="AppTabBar_Profile_Link"]').first
        for _ in range(25):
            if is_login_page(page.url):
                raise LoginExpired()
            if await link.count():
                href = await link.get_attribute("href") or ""
                return href.strip("/").split("/")[0] or None
            await page.wait_for_timeout(1000)
        if not page.url.startswith("https://x.com/home"):
            raise LoginExpired()
        return None


def check_login(e: dict):
    """Your @handle if the cookie works (None if logged in but the handle couldn't be read)."""
    logged_in_cookies(e)
    return run(_check(e))
