"""Turning X GraphQL payloads into plain dicts. Pure functions, easy to test with fixtures."""
from __future__ import annotations

import re
from datetime import datetime, timezone

MENTION = re.compile(r"^(@\w+\s*)+")
TCO = re.compile(r"https://t\.co/\w+")


def clean(text: str) -> str:
    """Drop the @mentions X prepends to replies and trailing t.co links."""
    return TCO.sub("", MENTION.sub("", text or "")).strip()


def tweet_from_result(result: dict):
    if not result:
        return None
    if result.get("__typename") == "TweetWithVisibilityResults":
        result = result.get("tweet") or {}
    if result.get("__typename") not in ("Tweet", None) or "legacy" not in result:
        return None
    legacy = result["legacy"]
    rt = (legacy.get("retweeted_status_result") or {}).get("result")
    if rt:  # a retweet: use the original post
        return tweet_from_result(rt)

    user = ((result.get("core") or {}).get("user_results") or {}).get("result") or {}
    ucore, ulegacy = user.get("core") or {}, user.get("legacy") or {}
    handle = ucore.get("screen_name") or ulegacy.get("screen_name")
    name = ucore.get("name") or ulegacy.get("name")
    avatar = (user.get("avatar") or {}).get("image_url") or ulegacy.get("profile_image_url_https")
    if not handle:
        return None

    text = (((result.get("note_tweet") or {}).get("note_tweet_results") or {})
            .get("result") or {}).get("text") or legacy.get("full_text", "")
    media = (legacy.get("extended_entities") or {}).get("media") or (legacy.get("entities") or {}).get("media") or []
    for m in media:  # drop the media short link at the end of the text
        if m.get("url"):
            text = text.replace(m["url"], "")
    kinds = {m.get("type") for m in media}
    media_type = "video" if kinds & {"video", "animated_gif"} else ("photo" if "photo" in kinds else "")

    try:
        created = datetime.strptime(legacy["created_at"], "%a %b %d %H:%M:%S %z %Y").astimezone(timezone.utc)
    except (KeyError, ValueError):
        return None
    views = (result.get("views") or {}).get("count")
    tid = result.get("rest_id") or legacy.get("id_str")
    quoted = ((result.get("quoted_status_result") or {}).get("result"))
    return {
        "id": tid,
        "author_name": name,
        "author_handle": handle,
        "author_avatar": avatar,
        "author_followers": (user.get("relationship_counts") or {}).get("followers", ulegacy.get("followers_count")),
        "text": text.strip(),
        "url": f"https://x.com/{handle}/status/{tid}",
        "created_at": created.isoformat(),
        "lang": legacy.get("lang"),
        "media_type": media_type,
        "views": int(views) if views is not None and str(views).isdigit() else None,
        "replies": legacy.get("reply_count"),
        "likes": legacy.get("favorite_count"),
        "retweets": legacy.get("retweet_count"),
        "quotes": legacy.get("quote_count"),
        "is_reply": bool(legacy.get("in_reply_to_status_id_str")),
        "reply_to": legacy.get("in_reply_to_status_id_str"),
        "is_quote": bool(quoted),
    }


def entries(payload):
    """Every timeline entry anywhere in a payload (home, profile, search, explore)."""
    stack = [payload]
    while stack:
        o = stack.pop()
        if isinstance(o, dict):
            if "instructions" in o and isinstance(o["instructions"], list):
                for ins in o["instructions"]:
                    yield from ins.get("entries", []) or ([ins["entry"]] if ins.get("entry") else [])
                    for it in ins.get("moduleItems", []) or []:
                        yield {"entryId": it.get("entryId", ""), "content": {"itemContent": (it.get("item") or {}).get("itemContent")}}
            else:
                stack.extend(o.values())
        elif isinstance(o, list):
            stack.extend(o)


def item_contents(entry):
    content = entry.get("content") or {}
    out = []
    if content.get("itemContent"):
        out.append(content["itemContent"])
    for it in content.get("items", []) or []:
        ic = (it.get("item") or {}).get("itemContent")
        if ic:
            out.append(ic)
    return out


def tweets_in(payload, skip_promoted=True):
    """(tweets in timeline order, number of promoted entries skipped)."""
    tweets, promoted = [], 0
    for entry in entries(payload):
        eid = entry.get("entryId", "")
        for ic in item_contents(entry):
            if skip_promoted and (eid.startswith("promoted") or ic.get("promotedMetadata")):
                promoted += 1
                continue
            t = tweet_from_result(((ic.get("tweet_results") or {}).get("result")))
            if t:
                tweets.append(t)
    return tweets, promoted


def parse_timeline(payload):
    """Home timeline: (tweets, promoted_count)."""
    return tweets_in(payload)


def find_tweet(payload, tweet_id):
    stack = [payload]
    while stack:
        o = stack.pop()
        if isinstance(o, dict):
            r = (o.get("tweet_results") or {}).get("result") if "tweet_results" in o else None
            if r:
                t = tweet_from_result(r)
                if t and t["id"] == tweet_id:
                    return t
            stack.extend(o.values())
        elif isinstance(o, list):
            stack.extend(o)
    return None


def my_posts(payloads, handle):
    """Your replies (paired with the post you replied to) and original posts, from profile timelines."""
    pairs, posts = {}, {}
    me = handle.lower()
    for pl in payloads:
        for entry in entries(pl):
            ts = [t for t in (tweet_from_result(((ic or {}).get("tweet_results") or {}).get("result"))
                              for ic in item_contents(entry)) if t]
            for i, t in enumerate(ts):
                if t["author_handle"].lower() != me:
                    continue
                text = clean(t["text"])
                if not text:
                    continue
                parent = ts[i - 1] if i > 0 and ts[i - 1]["id"] == t["reply_to"] else None
                if parent:
                    pairs[t["id"]] = {**t, "text": text, "parent_id": parent["id"],
                                      "parent_author": parent["author_handle"], "parent_text": clean(parent["text"])}
                elif not t["is_reply"]:
                    posts[t["id"]] = {**t, "text": text}
    return list(pairs.values()), list(posts.values())


def _fmt_count(meta):
    return str(meta or "").strip()


def trends(payloads):
    """Trending topics from Explore payloads: [{name, context, posts}] in display order, de-duplicated."""
    out, seen = [], set()
    for pl in payloads:
        stack = [pl]
        while stack:
            o = stack.pop(0)
            if isinstance(o, dict):
                if o.get("__typename") == "TimelineTrend" or o.get("itemType") == "TimelineTrend":
                    name = o.get("name")
                    if name and name not in seen:
                        seen.add(name)
                        meta = o.get("trend_metadata") or {}
                        out.append({"name": name,
                                    "context": _fmt_count(meta.get("domain_context")),
                                    "posts": _fmt_count(meta.get("meta_description"))})
                    continue
                stack.extend(o.values())
            elif isinstance(o, list):
                stack.extend(o)
    return out
