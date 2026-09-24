import config
import jobs
import store


def test_rate_limits():
    config.save({"SEND_MIN_INTERVAL_SEC": "60", "SEND_MAX_PER_HOUR": "2", "SEND_MAX_PER_DAY": "5"})
    e = config.env()
    assert jobs.send_block_reason(e) is None
    first = store.enqueue("post", "one", "api")
    store.update_outbox(first, status="sent", sent_at=store.now())
    assert jobs.send_block_reason(e) == "interval"
    second = store.enqueue("post", "two", "api")
    store.update_outbox(second, status="sent", sent_at=store.now())
    assert jobs.send_block_reason(e) == "hourly_limit"


def test_interrupted_send_is_never_retried():
    item = store.enqueue("post", "x", "browser")
    store.update_outbox(item, status="sending")
    store.recover_sending()
    assert store.outbox_item(item)["status"] == "failed"


def test_archive_import():
    from scraper import x_mine
    js = b'window.YTD.tweets.part0 = [{"tweet": {"id_str": "1", "full_text": "@bob agreed", ' \
         b'"created_at": "Wed Sep 24 01:00:00 +0000 2026", "favorite_count": "3", ' \
         b'"in_reply_to_status_id_str": "9", "in_reply_to_screen_name": "bob"}},' \
         b'{"tweet": {"id_str": "2", "full_text": "my post", "created_at": "Wed Sep 24 02:00:00 +0000 2026"}},' \
         b'{"tweet": {"id_str": "3", "full_text": "RT @x: theirs", "created_at": "Wed Sep 24 03:00:00 +0000 2026"}}]'
    replies, posts = x_mine.read_archive(js)
    assert [r["text"] for r in replies] == ["agreed"] and replies[0]["parent_author"] == "bob"
    assert [p["text"] for p in posts] == ["my post"]
