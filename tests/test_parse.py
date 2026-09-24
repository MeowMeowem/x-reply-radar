from fixtures import entry, timeline, tweet

from scraper import parse


def test_tweet_fields():
    t = parse.tweet_from_result(tweet("1", "alice", "hello https://t.co/abc", entities={"media": [
        {"url": "https://t.co/abc", "type": "photo"}]}))
    assert t["id"] == "1" and t["author_handle"] == "alice"
    assert t["text"] == "hello" and t["media_type"] == "photo"
    assert t["views"] == 1000 and t["url"] == "https://x.com/alice/status/1"
    assert t["created_at"].startswith("2026-09-24T01:00:00")


def test_retweet_returns_original():
    original = tweet("2", "bob", "original")
    rt = tweet("3", "alice", "RT @bob: original", retweeted_status_result={"result": original})
    assert parse.tweet_from_result(rt)["id"] == "2"


def test_visibility_wrapper_and_bad_input():
    wrapped = {"__typename": "TweetWithVisibilityResults", "tweet": tweet("4", "c", "x")}
    assert parse.tweet_from_result(wrapped)["id"] == "4"
    assert parse.tweet_from_result({}) is None
    assert parse.tweet_from_result({"__typename": "TweetTombstone"}) is None


def test_timeline_skips_ads():
    pl = timeline(entry("tweet-1", tweet("1", "a", "one")), entry("promoted-tweet-2", tweet("2", "b", "ad")),
                  entry("tweet-3", tweet("3", "c", "three")))
    tweets, promoted = parse.parse_timeline(pl)
    assert [t["id"] for t in tweets] == ["1", "3"] and promoted == 1


def test_my_posts_pairs_reply_with_parent():
    parent = tweet("10", "someone", "what do you think?")
    mine = tweet("11", "me", "@someone looks good", reply_to="10")
    own = tweet("12", "me", "my own post")
    pl = timeline(entry("conversation-1", parent, mine), entry("tweet-12", own))
    pairs, posts = parse.my_posts([pl], "Me")
    assert len(pairs) == 1 and pairs[0]["text"] == "looks good"
    assert pairs[0]["parent_text"] == "what do you think?" and pairs[0]["parent_author"] == "someone"
    assert [p["id"] for p in posts] == ["12"]


def test_trends():
    pl = {"data": {"timeline": {"instructions": [{"entries": [{"entryId": "trend-1", "content": {"itemContent": {
        "__typename": "TimelineTrend", "name": "#AI", "trend_metadata": {
            "domain_context": "Technology · Trending", "meta_description": "12K posts"}}}},
        {"entryId": "trend-2", "content": {"itemContent": {"__typename": "TimelineTrend", "name": "#AI"}}}]}]}}}
    assert parse.trends([pl]) == [{"name": "#AI", "context": "Technology · Trending", "posts": "12K posts"}]


def test_clean():
    assert parse.clean("@a @b hi there https://t.co/xyz") == "hi there"
