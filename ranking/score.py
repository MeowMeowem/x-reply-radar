"""Topic matching and hot_score.

hot_score（约 0~100）=
  fresh(25) + view velocity(25) + engagement velocity(20) + topic relevance(15) + author reach(5)
  + accelerating(10) - reply saturation + stage + the AI's "want to reply" adjustment
"""
import json
import math
import re
from datetime import datetime, timezone

import config
import i18n

DEFAULT_TOPICS = config.ROOT / "config" / "topics.json"


def topics_file():
    """profile/topics.json, if present, replaces the default topics and block list."""
    custom = config.PROFILE_DIR / "topics.json"
    return custom if custom.exists() else DEFAULT_TOPICS
CASHTAG = re.compile(r"\$[A-Za-z]{2,10}\b")


def _matcher(words):
    pats = []
    for w in words:
        w = w.lower()
        prefix = w.endswith("*")  # gpt* 能匹配 gptplus
        w = w.rstrip("*")
        if re.fullmatch(r"[a-z0-9 .\-]+", w):
            # 英文词按词边界匹配，但允许后面紧跟版本号（opus5.5）
            pats.append(re.compile(r"(?<![a-z0-9])" + re.escape(w) + ("" if prefix else r"(?![a-z])")))
        else:
            pats.append(w)
    return pats


def _hits(text, pats):
    n = 0
    for p in pats:
        if (p.search(text) if isinstance(p, re.Pattern) else p in text):
            n += 1
    return n


_cache = {}


def _load():
    f = topics_file()
    mtime = (str(f), f.stat().st_mtime)
    if _cache.get("mtime") != mtime:
        cfg = json.loads(f.read_text(encoding="utf-8"))
        _cache.update(mtime=mtime,
                      topics={k: _matcher(v) for k, v in cfg["topics"].items()},
                      block=_matcher(cfg.get("block", [])))
    return _cache


def classify(t):
    """给帖子加 topic / relevance / blocked。"""
    cfg = _load()
    text = f"{t['text']} {t['author_name']}".lower()
    blocked = bool(_hits(text, cfg["block"]) or CASHTAG.search(t["text"]))
    scores = {k: _hits(text, v) for k, v in cfg["topics"].items()}
    topic, hits = max(scores.items(), key=lambda kv: kv[1]) if scores else ("", 0)
    total = sum(scores.values())
    t["topic"] = topic if hits else ""
    t["relevance"] = min(1.0, 0.5 + 0.2 * (total - 1)) if total else 0.0
    t["blocked"] = int(blocked)
    return t


def _parse(ts):
    return datetime.fromisoformat(ts)


def _eng(s):
    return (s["likes"] or 0) + 2 * (s["retweets"] or 0) + 3 * (s["replies"] or 0) + 2 * (s["quotes"] or 0)


def growth(snaps, now):
    """用快照算最近 5/10/30 分钟的增速；只有一次快照时返回 None，不瞎猜。"""
    if len(snaps) < 2:
        return None
    cur = snaps[-1]
    out = {}
    for w in (5, 10, 30):
        base = None
        for s in reversed(snaps[:-1]):
            if (_parse(cur["ts"]) - _parse(s["ts"])).total_seconds() >= w * 60 * 0.6:
                base = s
                break
        if not base:
            continue
        mins = (_parse(cur["ts"]) - _parse(base["ts"])).total_seconds() / 60
        v0, v1 = base["views"] or 0, cur["views"] or 0
        out[w] = {
            "mins": round(mins, 1),
            "vpm": (v1 - v0) / mins,
            "epm": (_eng(cur) - _eng(base)) / mins,
            "rpm": ((cur["replies"] or 0) - (base["replies"] or 0)) / mins,
            "pct": (v1 - v0) / v0 * 100 if v0 else None,
        }
    if not out:  # 快照间隔太短，拿最早那次
        base = snaps[0]
        mins = (_parse(cur["ts"]) - _parse(base["ts"])).total_seconds() / 60
        if mins < 1:
            return None
        v0, v1 = base["views"] or 0, cur["views"] or 0
        out[0] = {"mins": round(mins, 1), "vpm": (v1 - v0) / mins, "epm": (_eng(cur) - _eng(base)) / mins,
                  "rpm": ((cur["replies"] or 0) - (base["replies"] or 0)) / mins,
                  "pct": (v1 - v0) / v0 * 100 if v0 else None}
    return out


def _log_ratio(x, top):
    return min(1.0, math.log10(1 + max(0, x)) / math.log10(1 + top))


def score(t, snaps, now=None):
    now = now or datetime.now(timezone.utc)
    age = max(1.0, (now - _parse(t["created_at"])).total_seconds() / 60)
    views, replies = t["views"] or 0, t["replies"] or 0

    life_vpm = views / age
    life_epm = _eng(t) / age
    g = growth(snaps, now)
    win = None
    if g:
        win = g.get(10) or g.get(30) or g.get(5) or g.get(0)
    vpm = win["vpm"] if win else life_vpm
    epm = win["epm"] if win else life_epm

    parts = {}
    parts["fresh"] = 25.0 if age <= 30 else 25 * math.exp(-(age - 30) / 150)
    parts["views"] = 25 * _log_ratio(vpm, 1000)
    parts["engage"] = 20 * _log_ratio(epm, 50)
    parts["relevance"] = 15 * (t["relevance"] or 0)
    parts["author"] = 5 * _log_ratio(t["author_followers"] or 0, 1_000_000)
    accel = win["vpm"] / life_vpm if win and life_vpm > 0 else None
    parts["accel"] = 10 * min(1.0, max(0.0, accel - 1)) if accel else 0.0
    parts["saturation"] = -min(25, 12 * math.log10(replies / 150)) if replies > 150 else 0.0

    if age > 8 * 60 or replies > 1000 or (age > 3 * 60 and not (accel and accel > 1.2)):
        stage = "late"
        parts["stage"] = -15
    elif vpm >= 200 or (views >= 50_000 and age < 180):
        stage = "viral"
        parts["stage"] = 0
    else:
        stage = "rising"
        parts["stage"] = 5

    if t.get("ai_want") is not None:
        parts["want"] = (t["ai_want"] - 5) * 2

    total = sum(parts.values())
    return {
        "hot_score": round(max(0, min(100, total))),
        "stage": i18n.t(f"stage.{stage}"),
        "stage_key": stage,
        "age_min": round(age),
        "vpm": round(vpm, 1),
        "growth_pct": round(win["pct"], 1) if win and win["pct"] is not None else None,
        "growth_window": win["mins"] if win else None,
        "measured": bool(win),
        "parts": {k: round(v, 1) for k, v in parts.items()},
    }
