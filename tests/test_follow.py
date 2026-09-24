import time

import pytest
from fastapi.testclient import TestClient

import app
import config
import jobs
import store
from ranking import follow as rules
from scraper import parse


def user_2026(uid, handle, followers, following, posts=100, bio="互关 回关", following_now=False, followed_by=False,
              protected=False):
    return {"__typename": "User", "rest_id": uid, "core": {"screen_name": handle, "name": handle.title()},
            "relationship_counts": {"followers": followers, "following": following},
            "relationship_perspectives": {"following": following_now, "followed_by": followed_by},
            "privacy": {"protected": protected}, "profile_bio": {"description": bio}, "tweet_counts": {"tweets": posts},
            "avatar": {"image_url": "https://pbs/a.jpg"}}


def people_payload(*users):
    return {"data": {"search_by_raw_query": {"search_timeline": {"timeline": {"instructions": [{"entries": [
        {"entryId": f"user-{u['rest_id']}", "content": {"itemContent": {"__typename": "TimelineUser",
                                                                          "user_results": {"result": u}}}}
        for u in users]}]}}}}}


def as_user(**kw):
    return parse.user_from_result(user_2026(**kw))


def test_parses_2026_and_legacy_shapes():
    new = parse.user_from_result(user_2026("1", "amy", 500, 800, followed_by=True))
    assert (new["followers"], new["following"], new["followed_by"], new["bio"]) == (500, 800, True, "互关 回关")
    old = parse.user_from_result({"__typename": "User", "rest_id": "2", "legacy": {
        "screen_name": "bob", "name": "Bob", "followers_count": 10, "friends_count": 40, "statuses_count": 7,
        "description": "follow back", "following": True, "protected": False}})
    assert (old["handle"], old["followers"], old["following"], old["posts"], old["following_now"]) == \
        ("bob", 10, 40, 7, True)


def test_users_in_people_search():
    users = parse.users_in(people_payload(user_2026("1", "amy", 500, 800), user_2026("2", "bo", 9000, 300)))
    assert [(u["handle"], u["source"]) for u in users] == [("amy", "bio"), ("bo", "bio")]


@pytest.mark.parametrize("kw,reason", [
    (dict(followers=9000, following=300), "ratio"),          # follows few, followed by many: not sincere
    (dict(followers=100, following=10), "ratio"),
    (dict(followers=5, following=10), "few_following"),
    (dict(followers=100, following=200, posts=1), "few_posts"),
    (dict(followers=100, following=200, protected=True), "protected"),
    (dict(followers=100, following=200, following_now=True), "already_following"),
    (dict(followers=500, following=450), ""),                  # within 1.2x: fine
    (dict(followers=100, following=800), ""),
])
def test_rules(kw, reason):
    ok, got, _ = rules.evaluate(as_user(uid="1", handle="x", **kw), config.env())
    assert got == reason and ok == (reason == "")


def test_people_who_follow_you_come_first():
    e = config.env()
    ok, _ = rules.split([as_user(uid="1", handle="a", followers=100, following=900),
                         as_user(uid="2", handle="b", followers=100, following=120, followed_by=True)], e)
    assert [u["handle"] for u in ok] == ["b", "a"]


def test_follow_back_is_noticed_on_the_next_search():
    store.upsert_candidates([as_user(uid="1", handle="a", followers=100, following=300)])
    store.set_candidates(["1"], status="followed", followed_at=store.now())
    store.upsert_candidates([as_user(uid="1", handle="a", followers=101, following=300, following_now=True,
                                     followed_by=True)])
    c = store.candidate("1")
    assert c["followed_back_at"] and c["followers"] == 101
    assert store.follow_stats()["followed_back"] == 1


def test_queue_only_accepts_eligible_people():
    client = TestClient(app.app, base_url="http://127.0.0.1:8796")
    store.upsert_candidates([as_user(uid="1", handle="good", followers=100, following=300),
                             as_user(uid="2", handle="fake", followers=9000, following=100)])
    assert client.post("/api/follow/queue", json={"ids": ["1", "2"]}).json()["detail"] == "batch_needs_auto_channel"
    config.save({"POST_CHANNEL": "api", "X_API_KEY": "k", "X_API_SECRET": "s", "X_ACCESS_TOKEN": "t",
                 "X_ACCESS_TOKEN_SECRET": "ts"})
    r = client.post("/api/follow/queue", json={"ids": ["1", "2"]}).json()
    assert (r["queued"], r["skipped"]) == (1, 1)
    assert store.candidate("1")["status"] == "queued" and store.candidate("2")["status"] == "new"


def test_follow_limits_and_pause():
    config.save({"FOLLOW_MAX_PER_HOUR": "2", "FOLLOW_MIN_INTERVAL_SEC": "60"})
    e = config.env()
    assert jobs.follow_block_reason(e) is None
    store.upsert_candidates([as_user(uid=str(i), handle=f"u{i}", followers=10, following=100) for i in range(3)])
    store.set_candidates(["0", "1"], status="followed", followed_at=store.now())
    assert jobs.follow_block_reason(e) == "hourly_limit"
    store.kv_set("follow_paused_until", time.time() + 60)
    assert jobs.follow_block_reason(e) == "paused"
