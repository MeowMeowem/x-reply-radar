"""Minimal X GraphQL shapes, written by hand from real responses."""


def user(handle, name=None, followers=100):
    return {"__typename": "User", "core": {"screen_name": handle, "name": name or handle},
            "legacy": {"followers_count": followers}, "avatar": {"image_url": f"https://pbs/{handle}.jpg"}}


def tweet(tid, handle, text, reply_to=None, views="1000", created="Wed Sep 24 01:00:00 +0000 2026", **legacy):
    return {"__typename": "Tweet", "rest_id": tid, "views": {"count": views},
            "core": {"user_results": {"result": user(handle)}},
            "legacy": {"id_str": tid, "full_text": text, "created_at": created, "lang": "en",
                       "reply_count": 3, "favorite_count": 10, "retweet_count": 2, "quote_count": 1,
                       "in_reply_to_status_id_str": reply_to, **legacy}}


def entry(eid, *results):
    if len(results) == 1:
        return {"entryId": eid, "content": {"itemContent": {"tweet_results": {"result": results[0]}}}}
    return {"entryId": eid, "content": {"items": [{"item": {"itemContent": {"tweet_results": {"result": r}}}}
                                                  for r in results]}}


def timeline(*entries_):
    return {"data": {"home": {"home_timeline_urt": {"instructions": [{"type": "TimelineAddEntries",
                                                                        "entries": list(entries_)}]}}}}
