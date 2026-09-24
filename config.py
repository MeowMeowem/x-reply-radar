"""Settings: one table of every option, read from .env (and the process environment).

The settings page, .env.example and every module read options through here, so an
option only has to be declared once. Secrets are never returned to the browser in
full; see `public_settings()`.
"""
from __future__ import annotations

import os
import re
import threading
from dataclasses import dataclass
from pathlib import Path

from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parent
ENV_FILE = Path(os.environ.get("RADAR_ENV_FILE") or ROOT / ".env")
DATA_DIR = Path(os.environ.get("RADAR_DATA_DIR") or ROOT / "data")
PROFILE_DIR = Path(os.environ.get("RADAR_PROFILE_DIR") or ROOT / "profile")
LOG_DIR = Path(os.environ.get("RADAR_LOG_DIR") or ROOT / "logs")


@dataclass(frozen=True)
class Opt:
    key: str
    default: str
    group: str
    kind: str = "text"  # text | secret | int | float | bool | choice
    choices: tuple = ()
    ui: bool = True  # shown on the settings page


OPTIONS: tuple[Opt, ...] = (
    # X login (cookie from a logged-in browser session)
    Opt("X_AUTH_TOKEN", "", "x", "secret"),
    Opt("X_CT0", "", "x", "secret"),
    Opt("X_COOKIE", "", "x", "secret", ui=False),
    Opt("MY_HANDLE", "", "x"),
    Opt("DISPLAY_NAME", "", "x"),
    # AI (any OpenAI-compatible endpoint)
    Opt("AI_BASE_URL", "https://api.openai.com/v1", "ai"),
    Opt("AI_API_KEY", "", "ai", "secret"),
    Opt("AI_API_KEY_FROM", "", "ai", ui=False),
    Opt("AI_MODEL", "", "ai"),
    Opt("AI_TIMEOUT", "90", "ai", "int", ui=False),
    # Language
    Opt("UI_LANG", "auto", "general", "choice", ("auto", "zh", "en")),
    Opt("CONTENT_LANG", "zh", "general", "choice", ("zh", "en")),
    # Posting
    Opt("POST_CHANNEL", "intent", "post", "choice", ("intent", "browser", "api")),
    Opt("SEND_MIN_INTERVAL_SEC", "90", "post", "int"),
    Opt("SEND_MAX_PER_HOUR", "10", "post", "int"),
    Opt("SEND_MAX_PER_DAY", "40", "post", "int"),
    Opt("SEND_DRY_RUN", "0", "post", "bool", ui=False),
    Opt("X_API_KEY", "", "post", "secret"),
    Opt("X_API_SECRET", "", "post", "secret"),
    Opt("X_ACCESS_TOKEN", "", "post", "secret"),
    Opt("X_ACCESS_TOKEN_SECRET", "", "post", "secret"),
    # Follow-back finder
    Opt("FOLLOW_KEYWORDS", "互关, 互粉, 互fo, 回关, 必回关, follow back, #followback, f4f", "follow"),
    Opt("FOLLOW_MAX_RATIO", "1.2", "follow", "float"),
    Opt("FOLLOW_MIN_FOLLOWING", "20", "follow", "int"),
    Opt("FOLLOW_MIN_POSTS", "5", "follow", "int"),
    Opt("FOLLOW_SEARCH_SCROLLS", "3", "follow", "int"),
    Opt("FOLLOW_MIN_INTERVAL_SEC", "90", "follow", "int"),
    Opt("FOLLOW_MAX_PER_HOUR", "10", "follow", "int"),
    Opt("FOLLOW_MAX_PER_DAY", "30", "follow", "int"),
    # Radar
    Opt("AUTO_REFRESH", "1", "radar", "bool"),
    Opt("REFRESH_MIN_MINUTES", "6", "radar", "int"),
    Opt("REFRESH_MAX_MINUTES", "10", "radar", "int"),
    Opt("SCRAPE_TARGET", "40", "radar", "int"),
    Opt("SHOW_TOP", "10", "radar", "int"),
    Opt("RECHECK_TOP", "8", "radar", "int"),
    Opt("KEEP_DAYS", "10", "radar", "int"),
    Opt("SCRAPE_ON_START", "1", "radar", "bool", ui=False),
    Opt("TRENDS_EVERY_MINUTES", "30", "radar", "int"),
    Opt("WATCH_ACCOUNTS", "", "radar"),
    Opt("WATCH_EVERY_MINUTES", "60", "radar", "int"),
    # Learning
    Opt("MINE_REFRESH_HOURS", "6", "learn", "int"),
    Opt("MINE_SCROLLS", "8", "learn", "int"),
    Opt("FIT_REVIEW", "1", "learn", "bool"),
    Opt("FIT_MIN_SCORE", "7", "learn", "float"),
    Opt("CONSOLIDATE_EVERY_DAYS", "7", "learn", "int"),
    Opt("EVAL_SAMPLES", "8", "learn", "int"),
    # Drafts
    Opt("DRAFT_HOUR", "9", "drafts", "int"),
    Opt("NEWS_PER_DAY", "8", "drafts", "int"),
    Opt("QUOTE_MIN_SCORE", "7", "drafts", "float"),
    # Server
    Opt("PORT", "8796", "server", "int", ui=False),
    Opt("OPEN_BROWSER", "1", "server", "bool", ui=False),
    Opt("BROWSER_CHANNEL", "chrome", "server", "choice", ("chrome", "chromium", "msedge"), ui=False),
    Opt("ALLOWED_HOSTS", "", "server", ui=False),
)
BY_KEY = {o.key: o for o in OPTIONS}
SECRET_KEYS = tuple(o.key for o in OPTIONS if o.kind == "secret")

_write_lock = threading.Lock()


def env() -> dict:
    """Current settings: defaults < .env < process environment (for containers/launchd)."""
    values = {o.key: o.default for o in OPTIONS}
    if ENV_FILE.exists():
        values.update({k: v for k, v in dotenv_values(ENV_FILE).items() if v is not None})
    values.update({k: v for k, v in os.environ.items() if k in BY_KEY})
    return values


def get_int(e: dict, key: str) -> int:
    try:
        return int(float(e.get(key) or BY_KEY[key].default))
    except (TypeError, ValueError):
        return int(BY_KEY[key].default)


def get_float(e: dict, key: str) -> float:
    try:
        return float(e.get(key) or BY_KEY[key].default)
    except (TypeError, ValueError):
        return float(BY_KEY[key].default)


def get_bool(e: dict, key: str) -> bool:
    return str(e.get(key, BY_KEY[key].default)).strip().lower() in ("1", "true", "yes", "on")


def handle(e: dict) -> str:
    return (e.get("MY_HANDLE") or "").strip().lstrip("@")


def mask(value: str) -> str:
    return "" if not value else ("•" * 6 + value[-4:] if len(value) > 8 else "•" * 6)


def public_settings(e: dict | None = None) -> dict:
    """Settings for the browser: secrets only say whether they are set."""
    e = e or env()
    out = {}
    for o in OPTIONS:
        if not o.ui:
            continue
        v = e.get(o.key, "")
        out[o.key] = {"group": o.group, "kind": o.kind, "choices": list(o.choices),
                      "value": "" if o.kind == "secret" else v,
                      "set": bool(v), "hint": mask(v) if o.kind == "secret" else ""}
    if not e.get("AI_API_KEY") and e.get("AI_API_KEY_FROM"):  # key read from another env file
        out["AI_API_KEY"].update(set=True, hint="AI_API_KEY_FROM")
    return out


def _quote(v: str) -> str:
    if v == "" or re.fullmatch(r"[A-Za-z0-9_./:@,+\-]*", v):
        return v
    return '"' + v.replace("\\", "\\\\").replace('"', '\\"') + '"'


def validate(key: str, value) -> str:
    o = BY_KEY.get(key)
    if not o or not o.ui:
        raise ValueError(f"unknown setting {key}")
    value = "" if value is None else str(value).strip()
    if "\n" in value or "\r" in value:
        raise ValueError(f"{key}: single line only")
    if o.kind == "int" and value and not re.fullmatch(r"-?\d+", value):
        raise ValueError(f"{key}: integer expected")
    if o.kind == "float" and value and not re.fullmatch(r"-?\d+(\.\d+)?", value):
        raise ValueError(f"{key}: number expected")
    if o.kind == "bool":
        value = "1" if value.lower() in ("1", "true", "yes", "on") else "0"
    if o.kind == "choice" and value not in o.choices:
        raise ValueError(f"{key}: one of {', '.join(o.choices)}")
    if key == "AI_BASE_URL" and value and not re.match(r"^https?://", value):
        raise ValueError("AI_BASE_URL must start with http:// or https://")
    if key == "MY_HANDLE":
        value = value.lstrip("@")
    return value


def save(updates: dict) -> None:
    """Write settings into .env, keeping comments and unrelated lines. Empty secret = unchanged."""
    clean = {}
    for k, v in updates.items():
        v = validate(k, v)
        if BY_KEY[k].kind == "secret" and v == "":
            continue
        clean[k] = v
    if not clean:
        return
    with _write_lock:
        lines = ENV_FILE.read_text(encoding="utf-8").splitlines() if ENV_FILE.exists() else []
        seen = set()
        for i, line in enumerate(lines):
            m = re.match(r"^\s*([A-Z0-9_]+)\s*=", line)
            if m and m.group(1) in clean:
                lines[i] = f"{m.group(1)}={_quote(clean[m.group(1)])}"
                seen.add(m.group(1))
        lines += [f"{k}={_quote(v)}" for k, v in clean.items() if k not in seen]
        ENV_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = ENV_FILE.with_suffix(".tmp")
        tmp.write_text("\n".join(lines) + "\n", encoding="utf-8")
        os.chmod(tmp, 0o600)
        tmp.replace(ENV_FILE)


def clear(keys: list[str]) -> None:
    """Remove secrets (e.g. log out of X)."""
    with _write_lock:
        if not ENV_FILE.exists():
            return
        lines = [l for l in ENV_FILE.read_text(encoding="utf-8").splitlines()
                 if not (m := re.match(r"^\s*([A-Z0-9_]+)\s*=", l)) or m.group(1) not in keys]
        ENV_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")


def env_mtime() -> float | None:
    return ENV_FILE.stat().st_mtime if ENV_FILE.exists() else None


def example_env() -> str:
    """Body of .env.example, generated from OPTIONS so it never drifts."""
    titles = {"x": "X account (cookie from your logged-in browser)", "ai": "AI: any OpenAI-compatible API",
              "general": "Language", "post": "Posting (intent = opens X with the text filled in, you press Post)",
              "radar": "Radar", "learn": "Style learning", "drafts": "Daily drafts", "server": "Server",
              "follow": "Follow-back finder (search, filter, follow)"}
    out, group = ["# Copy to .env, or fill everything in from the Settings page."], None
    for o in OPTIONS:
        if o.group != group:
            group = o.group
            out += ["", f"# --- {titles[group]} ---"]
        choice = f"  # {' | '.join(o.choices)}" if o.choices else ""
        prefix = "" if o.ui or o.key in ("PORT",) else "# "
        out.append(f"{prefix}{o.key}={o.default}{choice}")
    return "\n".join(out) + "\n"
