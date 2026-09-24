import pytest

import config


def test_save_keeps_comments_and_quotes(tmp_path):
    config.ENV_FILE.write_text("# my notes\nMY_HANDLE=old\nUNRELATED=1\n")
    config.save({"MY_HANDLE": "@new", "DISPLAY_NAME": "Emma W"})
    text = config.ENV_FILE.read_text()
    assert "# my notes" in text and "UNRELATED=1" in text
    assert "MY_HANDLE=new" in text and 'DISPLAY_NAME="Emma W"' in text
    assert config.env()["DISPLAY_NAME"] == "Emma W"


def test_empty_secret_keeps_old_value():
    config.save({"AI_API_KEY": "sk-secret-value-123"})
    config.save({"AI_API_KEY": ""})
    assert config.env()["AI_API_KEY"] == "sk-secret-value-123"


def test_secrets_never_leave_in_full():
    config.save({"AI_API_KEY": "sk-secret-value-123"})
    s = config.public_settings()["AI_API_KEY"]
    assert s["value"] == "" and s["set"] and "sk-secret" not in s["hint"]


@pytest.mark.parametrize("key,value", [("SEND_MAX_PER_HOUR", "ten"), ("POST_CHANNEL", "smoke"),
                                       ("AI_BASE_URL", "ftp://x"), ("MY_HANDLE", "a\nb"), ("NOT_A_KEY", "1")])
def test_validation(key, value):
    with pytest.raises(ValueError):
        config.save({key: value})


def test_example_env_lists_every_ui_option():
    text = config.example_env()
    for o in config.OPTIONS:
        assert o.key in text
