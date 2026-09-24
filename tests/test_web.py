import json

import pytest
from fastapi.testclient import TestClient

import app
import store


@pytest.fixture
def client():
    return TestClient(app.app, base_url="http://127.0.0.1:8796")


def test_pages_load(client):
    assert client.get("/").status_code == 200
    for path in ("/api/feed", "/api/status", "/api/drafts", "/api/outbox", "/api/trends", "/api/learn",
                 "/api/settings", "/api/mutes"):
        assert client.get(path).status_code == 200, path


def test_foreign_host_blocked():
    assert TestClient(app.app, base_url="http://evil.example").get("/api/feed").status_code == 403


def test_cross_site_post_blocked(client):
    assert client.post("/api/refresh", headers={"origin": "https://evil.example"}).status_code == 403
    assert client.post("/api/feedback", json={"kind": "dismiss", "value": "1"},
                       headers={"sec-fetch-site": "cross-site"}).status_code == 403
    # same origin and non-browser clients (no Origin) are fine
    assert client.post("/api/feedback", json={"kind": "dismiss", "value": "1"},
                       headers={"origin": "http://127.0.0.1:8796"}).status_code == 200
    assert client.post("/api/feedback", json={"kind": "dismiss", "value": "1"}).status_code == 200


@pytest.mark.parametrize("raw", [
    "auth_token=aaaaaaaa; ct0=bbbbbbbb; lang=en",
    json.dumps([{"name": "auth_token", "value": "aaaaaaaa"}, {"name": "ct0", "value": "bbbbbbbb"}]),
    ".x.com\tTRUE\t/\tTRUE\t0\tauth_token\taaaaaaaa\n.x.com\tTRUE\t/\tTRUE\t0\tct0\tbbbbbbbb",
])
def test_cookie_formats(raw):
    assert app.parse_cookie_input(raw) == {"auth_token": "aaaaaaaa", "ct0": "bbbbbbbb"}


def test_cookie_endpoint_rejects_incomplete(client):
    assert client.post("/api/settings/cookie", json={"text": "auth_token=only"}).status_code == 400


def test_intent_send_and_confirm_records_learning(client):
    store.upsert([{"id": "77", "author_name": "A", "author_handle": "a", "author_avatar": None,
                   "author_followers": 1, "text": "their post", "url": "https://x.com/a/status/77",
                   "created_at": store.now(), "lang": "en", "media_type": "", "is_reply": False, "views": 1,
                   "replies": 0, "likes": 0, "retweets": 0, "quotes": 0}])
    r = client.post("/api/send", json={"kind": "reply", "text": "my edit", "target_id": "77", "ai_text": "ai draft"})
    assert r.status_code == 200 and "in_reply_to=77" in r.json()["intent_url"]
    item_id = r.json()["id"]
    assert client.post("/api/outbox/act", json={"id": item_id, "action": "confirm"}).json()["item"]["status"] == "sent"
    assert store.edits()[0]["final_text"] == "my edit"
    mine = store.my_posts("reply")
    assert mine[0]["parent_text"] == "their post" and mine[0]["origin"] == "sent"
    assert "77" in store.replied_ids()


def test_batch_needs_automatic_channel(client):
    items = [{"kind": "post", "text": "a"}, {"kind": "post", "text": "b"}]
    assert client.post("/api/send/batch", json={"items": items}).status_code == 400


def test_ai_drafted_replies_are_not_learned_from(client):
    test_intent_send_and_confirm_records_learning(client)
    assert store.my_posts("reply") and not store.my_own_posts("reply")
