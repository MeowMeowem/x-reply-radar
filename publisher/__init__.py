"""Sending posts, replies and quote posts to X.

Three channels (POST_CHANNEL):
  intent   opens X's own compose page with the text filled in; you press Post. Nothing is automated.
  browser  a headless browser logged in with your cookie opens that same page and presses Post.
  api      the official X API v2 with your developer keys (OAuth 1.0a user context).

Every send goes through the outbox (see jobs.py), which spaces sends out and enforces
hourly and daily limits.
"""
from __future__ import annotations

from urllib.parse import urlencode

KINDS = ("post", "reply", "quote")


class SendError(Exception):
    def __init__(self, message, retryable=False):
        super().__init__(message)
        self.retryable = retryable


def intent_url(kind: str, text: str, target_id: str | None = None, target_url: str | None = None) -> str:
    params = {"text": text}
    if kind == "reply" and target_id:
        params["in_reply_to"] = target_id
    if kind == "quote" and target_url:
        params["url"] = target_url
    return "https://x.com/intent/post?" + urlencode(params)


def x_length(text: str) -> int:
    """X's weighted length: most CJK and emoji count as 2, URLs as 23."""
    import re
    n = 0
    text = re.sub(r"https?://\S+", "x" * 23, text or "")
    for ch in text:
        cp = ord(ch)
        light = (cp <= 0x10FF or 0x2000 <= cp <= 0x200D or 0x2010 <= cp <= 0x201F or 0x2032 <= cp <= 0x2037)
        n += 1 if light else 2
    return n


def send(e: dict, item: dict) -> str:
    """Send one outbox item through the configured channel. Returns the new post id ('' if unknown)."""
    channel = item.get("channel") or e.get("POST_CHANNEL") or "intent"
    if channel == "api":
        from publisher import x_api
        return x_api.send(e, item)
    if channel == "browser":
        from publisher import x_browser
        return x_browser.send(e, item)
    raise SendError(f"channel {channel} is sent from your browser, not the server")
