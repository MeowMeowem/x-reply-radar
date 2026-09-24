"""OpenAI-compatible chat calls with retries and tolerant JSON parsing.

Only post text and author names are ever sent to the model; X credentials never pass
through here.
"""
from __future__ import annotations

import json
import random
import re
import time
from pathlib import Path

import httpx
from dotenv import dotenv_values

import config


class AIError(Exception):
    pass


def api_key(e: dict) -> str | None:
    """AI_API_KEY, or AI_API_KEY_FROM=<env file>:<VAR> to reuse a key kept in another env file."""
    if e.get("AI_API_KEY"):
        return e["AI_API_KEY"]
    ref = e.get("AI_API_KEY_FROM") or ""
    if ":" in ref:
        path, var = ref.rsplit(":", 1)
        path = Path(path).expanduser()
        if path.is_file():
            return dotenv_values(path).get(var)
    return None


def ready(e: dict) -> bool:
    return bool((e.get("AI_BASE_URL") or "").strip() and api_key(e) and (e.get("AI_MODEL") or "").strip())


def _endpoint(base: str) -> str:
    base = base.rstrip("/")
    return base if base.endswith("/chat/completions") else f"{base}/chat/completions"


def chat(e: dict, system: str, user: str, temperature: float = 0.9, retries: int = 3) -> str:
    base, key, model = (e.get("AI_BASE_URL") or "").strip(), api_key(e), (e.get("AI_MODEL") or "").strip()
    if not (base and key and model):
        raise AIError("AI is not configured (AI_BASE_URL / AI_API_KEY / AI_MODEL)")
    body = {"model": model, "temperature": temperature,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}
    last = None
    for attempt in range(retries):
        try:
            r = httpx.post(_endpoint(base), timeout=config.get_int(e, "AI_TIMEOUT"),
                           headers={"Authorization": f"Bearer {key}"}, json=body)
        except httpx.HTTPError as ex:
            last = AIError(f"AI request failed: {type(ex).__name__}")
        else:
            if r.status_code == 200:
                try:
                    return r.json()["choices"][0]["message"]["content"] or ""
                except (ValueError, KeyError, IndexError, TypeError):
                    raise AIError(f"AI returned an unexpected body: {r.text[:200]}")
            last = AIError(f"AI API {r.status_code}: {r.text[:200]}")
            if r.status_code not in (408, 409, 425, 429) and r.status_code < 500:
                raise last
        if attempt < retries - 1:
            time.sleep(min(20, 2 ** attempt * 2) + random.random())
    raise last


def parse_json(text: str) -> dict:
    """First JSON object in a reply, tolerating ```json fences and chatter around it."""
    text = (text or "").strip()
    fenced = re.findall(r"```(?:json)?\s*(.*?)```", text, re.S)
    for candidate in fenced + [text]:
        candidate = candidate.strip()
        try:
            out = json.loads(candidate)
            if isinstance(out, dict):
                return out
        except json.JSONDecodeError:
            pass
        start = candidate.find("{")
        while start != -1:
            depth, in_str, esc = 0, False, False
            for i in range(start, len(candidate)):
                ch = candidate[i]
                if in_str:
                    if esc:
                        esc = False
                    elif ch == "\\":
                        esc = True
                    elif ch == '"':
                        in_str = False
                    continue
                if ch == '"':
                    in_str = True
                elif ch == "{":
                    depth += 1
                elif ch == "}":
                    depth -= 1
                    if depth == 0:
                        try:
                            out = json.loads(candidate[start:i + 1])
                            if isinstance(out, dict):
                                return out
                        except json.JSONDecodeError:
                            pass
                        break
            start = candidate.find("{", start + 1)
    raise AIError("the model did not return JSON")


def number(value, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        m = re.search(r"-?\d+(\.\d+)?", str(value or ""))
        return float(m.group(0)) if m else default
