"""Official X API v2 (POST /2/tweets) with OAuth 1.0a user-context signing.

Needs a developer app with Read and Write permission and its four keys:
X_API_KEY, X_API_SECRET (consumer key/secret) and X_ACCESS_TOKEN, X_ACCESS_TOKEN_SECRET.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import time
from urllib.parse import quote

import httpx

from publisher import SendError

ENDPOINT = "https://api.x.com/2/tweets"
KEYS = ("X_API_KEY", "X_API_SECRET", "X_ACCESS_TOKEN", "X_ACCESS_TOKEN_SECRET")


def _enc(s) -> str:
    return quote(str(s), safe="~-._")


def oauth1_header(method, url, consumer_key, consumer_secret, token, token_secret,
                  params=None, nonce=None, timestamp=None) -> str:
    oauth = {
        "oauth_consumer_key": consumer_key,
        "oauth_nonce": nonce or secrets.token_hex(16),
        "oauth_signature_method": "HMAC-SHA1",
        "oauth_timestamp": str(timestamp or int(time.time())),
        "oauth_token": token,
        "oauth_version": "1.0",
    }
    pairs = sorted((_enc(k), _enc(v)) for k, v in {**(params or {}), **oauth}.items())
    base = "&".join([method.upper(), _enc(url), _enc("&".join(f"{k}={v}" for k, v in pairs))])
    key = f"{_enc(consumer_secret)}&{_enc(token_secret)}"
    oauth["oauth_signature"] = base64.b64encode(hmac.new(key.encode(), base.encode(), hashlib.sha1).digest()).decode()
    return "OAuth " + ", ".join(f'{_enc(k)}="{_enc(v)}"' for k, v in sorted(oauth.items()))


def configured(e) -> bool:
    return all((e.get(k) or "").strip() for k in KEYS)


def body_for(item) -> dict:
    body = {"text": item["text"]}
    if item["kind"] == "reply":
        body["reply"] = {"in_reply_to_tweet_id": item["target_id"]}
    elif item["kind"] == "quote":
        body["quote_tweet_id"] = item["target_id"]
    return body


def send(e, item) -> str:
    if not configured(e):
        raise SendError("X API keys are not set")
    if item["kind"] in ("reply", "quote") and not item.get("target_id"):
        raise SendError("missing target post")
    if str(e.get("SEND_DRY_RUN")) == "1":
        return ""
    auth = oauth1_header("POST", ENDPOINT, *(e[k].strip() for k in KEYS))
    try:
        r = httpx.post(ENDPOINT, json=body_for(item), headers={"Authorization": auth}, timeout=30)
    except httpx.HTTPError as ex:
        raise SendError(f"X API unreachable: {type(ex).__name__}", retryable=True)
    if r.status_code in (200, 201):
        return str((r.json().get("data") or {}).get("id") or "")
    detail = r.text[:300]
    try:
        j = r.json()
        detail = j.get("detail") or j.get("title") or (j.get("errors") or [{}])[0].get("message") or detail
    except ValueError:
        pass
    raise SendError(f"X API {r.status_code}: {detail}", retryable=r.status_code == 429 or r.status_code >= 500)


def whoami(e) -> str:
    """@username for the configured keys; proves they work without posting anything."""
    if not configured(e):
        raise SendError("X API keys are not set")
    url = "https://api.x.com/2/users/me"
    auth = oauth1_header("GET", url, *(e[k].strip() for k in KEYS))
    try:
        r = httpx.get(url, headers={"Authorization": auth}, timeout=20)
    except httpx.HTTPError as ex:
        raise SendError(f"X API unreachable: {type(ex).__name__}")
    if r.status_code != 200:
        raise SendError(f"X API {r.status_code}: {r.text[:200]}")
    return "@" + str((r.json().get("data") or {}).get("username") or "?")


_me = {}


def my_id(e) -> str:
    """Numeric id of the account the keys belong to (needed for the follow endpoint)."""
    key = e.get("X_ACCESS_TOKEN", "")
    if key not in _me:
        url = "https://api.x.com/2/users/me"
        auth = oauth1_header("GET", url, *(e[k].strip() for k in KEYS))
        r = httpx.get(url, headers={"Authorization": auth}, timeout=20)
        if r.status_code != 200:
            raise SendError(f"X API {r.status_code}: {r.text[:200]}")
        _me[key] = str(r.json()["data"]["id"])
    return _me[key]
