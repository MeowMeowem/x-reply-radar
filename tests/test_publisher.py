from urllib.parse import parse_qs, urlparse

import publisher
from publisher import x_api


def test_oauth1_signature_matches_x_docs():
    # the worked example from X's "Creating a signature" documentation
    header = x_api.oauth1_header(
        "POST", "https://api.twitter.com/1.1/statuses/update.json",
        "xvz1evFS4wEEPTGEFPHBog", "kAcSOqF21Fu85e7zjz7ZN2U4ZRhfV3WpwPAoE3Z7kBw",
        "370773112-GmHxMAgYyLbNEtIKZeRNFsMKPR9EyMZeS9weJAEb", "LswwdoUaIvS8ltyTt5jkRh4J50vUPVVHtR2YPi5kE",
        params={"status": "Hello Ladies + Gentlemen, a signed OAuth request!", "include_entities": "true"},
        nonce="kYjzVBB8Y0ZFabxSWbWovY3uYSQ2pTgmZeNu2VS4cg", timestamp=1318622958)
    assert 'oauth_signature="hCtSmYh%2BiHYCEqBWrE7C7hYmtUk%3D"' in header


def test_api_body():
    assert x_api.body_for({"kind": "reply", "text": "hi", "target_id": "9"}) == {
        "text": "hi", "reply": {"in_reply_to_tweet_id": "9"}}
    assert x_api.body_for({"kind": "quote", "text": "hi", "target_id": "9"}) == {"text": "hi", "quote_tweet_id": "9"}
    assert x_api.body_for({"kind": "post", "text": "hi"}) == {"text": "hi"}


def test_intent_url():
    q = parse_qs(urlparse(publisher.intent_url("reply", "a b", "123")).query)
    assert q == {"text": ["a b"], "in_reply_to": ["123"]}
    # X has no quote intent: a quote opens the post itself (Repost > Quote)
    assert publisher.intent_url("quote", "hi", "5", "https://x.com/a/status/5") == "https://x.com/a/status/5"


def test_x_length():
    assert publisher.x_length("hello") == 5
    assert publisher.x_length("你好") == 4
    assert publisher.x_length("see https://example.com/a/very/long/path") == 4 + 23
