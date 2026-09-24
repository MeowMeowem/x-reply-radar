"""Search X for people asking for follow-backs: in their profile (People tab) and in recent posts (Latest tab)."""
from __future__ import annotations

import random
from urllib.parse import quote

from scraper import browser
from scraper.browser import LoginExpired
from scraper.parse import users_in

KEYS = ("/SearchTimeline",)


async def _search(e, words, scrolls, log):
    found = {}
    async with browser.session(e) as page:
        for word in words:
            for tab in ("user", "live"):
                got = []
                handler = browser.capture(page, KEYS, got)
                try:
                    await page.goto(f"https://x.com/search?q={quote(word)}&src=typed_query&f={tab}",
                                    wait_until="domcontentloaded", timeout=40000)
                    for _ in range(12):
                        if got or browser.is_login_page(page.url):
                            break
                        await page.wait_for_timeout(1000)
                    if browser.is_login_page(page.url):
                        raise LoginExpired()
                    for _ in range(scrolls):
                        await page.mouse.wheel(0, random.randint(2400, 3400))
                        await page.wait_for_timeout(random.randint(1600, 2800))
                except LoginExpired:
                    raise
                except Exception as ex:
                    log(f"follow search '{word}' ({tab}) failed: {type(ex).__name__}")
                finally:
                    page.remove_listener("response", handler)
                for _, pl in got:
                    for u in users_in(pl):
                        if u["user_id"] not in found or (tab == "user" and found[u["user_id"]]["source"] == "post"):
                            found[u["user_id"]] = {**u, "keyword": word}
                await page.wait_for_timeout(random.randint(1200, 2500))
    log(f"follow search: {len(found)} people for {len(words)} keywords")
    return list(found.values())


def search(e, words, log=print, scrolls=3):
    browser.logged_in_cookies(e)
    return browser.run(_search(e, words, scrolls, log))
