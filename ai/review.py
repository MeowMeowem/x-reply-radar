"""Score how much a batch of texts sounds like you, and rewrite the ones that don't.

Every item gets `score` (1-10, 10 = indistinguishable from your real posts). Items under
FIT_MIN_SCORE are rewritten in your voice, and rewritten items are scored again in the
next round, so the stored score always belongs to the stored text.
"""
from __future__ import annotations

import config
from ai import llm, persona


def review(e, items: list[dict], log=print, rounds: int = 2, min_score: float | None = None, rewrite=True):
    if not items:
        return items
    min_score = config.get_float(e, "FIT_MIN_SCORE") if min_score is None else min_score
    todo = list(range(len(items)))
    for _ in range(rounds):
        todo = _once(e, items, todo, log, min_score, rewrite)
        if not todo:
            break
    return items


def _once(e, items, idx, log, min_score, rewrite):
    listing = "\n\n".join(f"[{i}] {items[i]['text']}" for i in idx)
    system = persona.system("review", e, min_score=f"{min_score:g}")
    if not rewrite:
        system += ("\n\n这一轮只打分，text 原样返回。" if persona.lang(e) == "zh"
                   else "\n\nThis round is scoring only: return every text unchanged.")
    try:
        out = llm.parse_json(llm.chat(e, system, listing, temperature=0.3))
    except Exception as ex:  # a failed review keeps the drafts, just without a score
        log(f"review failed, keeping drafts as they are: {type(ex).__name__}: {str(ex)[:120]}")
        return []
    again = []
    rows = out.get("items") or out.get("posts") or []
    for r in rows:
        i = r.get("i")
        if isinstance(i, str) and i.isdigit():
            i = int(i)
        if i not in idx:
            continue
        items[i]["score"] = llm.number(r.get("score"), None)
        text = (r.get("text") or "").strip()
        if rewrite and r.get("fix") and text and text != items[i]["text"]:
            items[i].setdefault("original", items[i]["text"])
            items[i]["text"] = text
            items[i]["fix"] = r.get("fix")
            items[i]["score"] = None  # belongs to the old text; scored again next round
            again.append(i)
    return again
