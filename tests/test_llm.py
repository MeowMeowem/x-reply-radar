import pytest

from ai import llm


@pytest.mark.parametrize("text", [
    '{"a": 1}',
    'Sure! Here you go:\n```json\n{"a": 1}\n```',
    'blah {"a": 1} trailing',
    'first {not json} then {"a": 1}',
])
def test_parse_json(text):
    assert llm.parse_json(text)["a"] == 1


def test_parse_json_braces_inside_strings():
    assert llm.parse_json('x {"t": "a } b { c", "n": 2} y') == {"t": "a } b { c", "n": 2}


def test_parse_json_fails_cleanly():
    with pytest.raises(llm.AIError):
        llm.parse_json("no json here")


def test_number():
    assert llm.number("8") == 8 and llm.number("8.5/10") == 8.5 and llm.number(None, 3) == 3


def test_api_key_from_other_file(tmp_path):
    other = tmp_path / "other.env"
    other.write_text("KEY=abc123\n")
    assert llm.api_key({"AI_API_KEY_FROM": f"{other}:KEY"}) == "abc123"
    assert llm.api_key({"AI_API_KEY": "direct", "AI_API_KEY_FROM": f"{other}:KEY"}) == "direct"


def test_ready():
    assert not llm.ready({"AI_BASE_URL": "http://x", "AI_API_KEY": "k"})
    assert llm.ready({"AI_BASE_URL": "http://x", "AI_API_KEY": "k", "AI_MODEL": "m"})
