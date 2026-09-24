"""Trending topics from Explore, as X shows them for your account and location."""
from __future__ import annotations

from scraper import browser
from scraper.browser import LoginExpired
from scraper.parse import trends

KEYS = ("/ExplorePage", "/GenericTimelineById", "/guide.json", "/ExploreSidebar", "/TrendHistory")


async def _scrape(e, log):
    got = []
    async with browser.session(e) as page:
        browser.capture(page, KEYS, got)
        await page.goto("https://x.com/explore/tabs/trending", wait_until="domcontentloaded", timeout=45000)
        for _ in range(20):
            if trends([pl for _, pl in got]) or browser.is_login_page(page.url):
                break
            await page.wait_for_timeout(1000)
        if browser.is_login_page(page.url):
            raise LoginExpired()
        await page.mouse.wheel(0, 2500)
        await page.wait_for_timeout(2500)
    items = trends([pl for _, pl in got])
    log(f"trends: {len(items)}")
    return items


def scrape_trends(e, log=print):
    browser.logged_in_cookies(e)
    return browser.run(_scrape(e, log))
