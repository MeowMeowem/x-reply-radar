"""Learning your style, and measuring how well it works.

learn()        first notes, written from your real posts and replies
consolidate()  periodic update: keeps what still holds, adds what's new, and learns from how you
               edited AI drafts and which drafts you rejected; the new version is only kept if it
               scores at least as well as the current one
evaluate()     fit score: for a fixed sample of your real replies, write a reply without seeing
               yours (leave-one-out), then have a judge compare it with what you really wrote

Every version of the notes is kept in the database; profile/style_notes.md is the active one.
Editing that file by hand is fine: the edit is saved as a "manual" version.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import config
import store
from ai import llm, persona, replies

NOTES = "style_notes.md"


def _header(e):
    if persona.lang(e) == "zh":
        return ("# 自动学习生成，可以手改：改动会存成一个新版本，下次整理会在它的基础上继续。\n"
                "# 想永久固定的规则写到 persona.md。\n\n")
    return ("# Learned automatically. You can edit it: your edit is saved as a new version and the next\n"
            "# consolidation builds on it. Rules you want to keep forever belong in persona.md.\n\n")


def _write_notes(e, notes):
    persona.write(NOTES, _header(e) + notes.strip())


def sync_manual_edit():
    """If you edited style_notes.md since the active version, record it as a version."""
    text = persona.strip_comments(persona.read(NOTES))
    if not text:
        return None
    active = store.active_style_version()
    if active and persona.strip_comments(active["notes"]) == text:
        return None
    return store.add_style_version(text, "manual" if active else "initial", len(store.my_posts()))


def _corpus(e, posts):
    zh = persona.lang(e) == "zh"
    out = []
    for p in posts[:150]:
        if p["kind"] == "reply":
            head = f"[回复 @{p['parent_author']}：{(p['parent_text'] or '')[:80]}]" if zh else \
                f"[reply to @{p['parent_author']}: {(p['parent_text'] or '')[:80]}]"
        else:
            head = "[原创]" if zh else "[post]"
        out.append(f"{head}\n{p['text']}")
    return "\n\n".join(out)


def learn(e, log=print):
    """Write first notes from everything you've posted."""
    mine = store.my_own_posts()
    if not mine:
        return False
    system = persona.render(persona.prompt("learn", e), me=persona.me(e))
    notes = llm.chat(e, system, _corpus(e, mine), temperature=0.3).strip()
    version = store.add_style_version(notes, "learn", len(mine))
    _write_notes(e, notes)
    store.kv_set("learned_count", len(mine))
    store.kv_set("consolidated_at", store.now())
    log(f"style learned from {len(mine)} posts (version {version})")
    return True


def _feedback_since(e, since):
    zh = persona.lang(e) == "zh"
    parts = []
    new_posts = [p for p in store.my_own_posts() if (p["first_seen"] or "") > since]
    if new_posts:
        parts.append(("【上次整理之后新发的内容】\n" if zh else "[Posted since the last update]\n") + _corpus(e, new_posts))
    fixes = [x for x in store.edits(since=since) if x["ai_text"].strip() != x["final_text"].strip()]
    if fixes:
        parts.append(("【AI 写的 → 本人实际发的】\n" if zh else "[AI wrote -> they posted]\n") + "\n".join(
            f"- {x['ai_text'][:200]}\n  → {x['final_text'][:240]}" for x in fixes))
    dropped = store.dropped_drafts(since=since)
    if dropped:
        parts.append(("【本人不要的草稿】\n" if zh else "[Drafts they rejected]\n") + "\n".join(f"- {t[:160]}" for t in dropped))
    return parts, len(new_posts) + len(fixes) + len(dropped)


def consolidate(e, log=print, evaluate_versions=True, force=False):
    """Merge new evidence into the notes. Returns a summary dict."""
    sync_manual_edit()
    current = persona.strip_comments(persona.read(NOTES))
    if not current:
        ok = learn(e, log)
        return {"action": "learned" if ok else "no_posts"}
    active = store.active_style_version()
    since = store.kv_get("consolidated_at") or (active["created_at"] if active else "")
    parts, signals = _feedback_since(e, since)
    if not signals and not force:
        store.kv_set("consolidated_at", store.now())
        return {"action": "nothing_new"}
    zh = persona.lang(e) == "zh"
    payload = "\n\n".join([("【当前笔记】\n" if zh else "[Current notes]\n") + current] + parts)
    system = persona.render(persona.prompt("consolidate", e), me=persona.me(e))
    candidate = llm.chat(e, system, payload, temperature=0.3).strip()
    if not candidate:
        return {"action": "empty"}

    result = {"action": "updated", "signals": signals}
    keep = True
    if evaluate_versions and len(eval_sample(e)) >= 4:
        base = evaluate(e, notes=current, label="current", version_id=active["id"] if active else None, log=log)
        new = evaluate(e, notes=candidate, label="candidate", log=log)
        result.update(current_score=base, candidate_score=new)
        keep = new is None or base is None or new >= base - 0.2
        if active and base is not None:
            store.set_style_score(active["id"], base)
    version = store.add_style_version(candidate, "consolidate", len(store.my_posts()),
                                      score=result.get("candidate_score"), active=keep)
    if keep:
        _write_notes(e, candidate)
    else:
        result["action"] = "kept_current"
    store.kv_set("consolidated_at", store.now())
    result["version"] = version
    log(f"style consolidation: {result}")
    return result


def activate(e, version_id):
    v = store.style_version(version_id)
    if not v:
        return False
    store.activate_style_version(version_id)
    _write_notes(e, v["notes"])
    return True


# ---------- fit evaluation ----------

def eval_sample(e):
    """A fixed, recent set of your real replies, so different versions are compared on the same posts."""
    me = config.handle(e).lower()
    pairs = [p for p in store.my_own_posts("reply")
             if p.get("parent_text") and (p["parent_author"] or "").lower() != me]
    return pairs[:config.get_int(e, "EVAL_SAMPLES")]


def evaluate(e, notes=None, label="current", version_id=None, use_learned=True, log=print):
    """Average fit score (1-10) over the eval sample, or None when there is nothing to compare with."""
    tests = eval_sample(e)
    if not tests:
        return None
    all_pairs = store.my_own_posts("reply")
    judge = persona.prompt("judge", e)

    def one(p):
        refs = "\n".join(f"- {q['text']}" for q in all_pairs[:40] if q["id"] != p["id"])
        system = persona.system("reply", e, exclude={p["id"]}, use_learned=use_learned, notes=notes)
        try:
            out = replies.generate(e, {"author_name": p["parent_author"], "author_handle": p["parent_author"],
                                       "text": p["parent_text"], "media_type": ""}, system=system)
            if out["skip"]:
                return p, out, None
            j = llm.parse_json(llm.chat(e, judge, (
                f"原帖 / Post: {p['parent_text']}\n\n真实回复 / Real reply: {p['text']}\n\n"
                f"平时的其他回复 / Other replies:\n{refs}\n\n候选 A: {out['a']}\n候选 B: {out['b']}"), temperature=0))
            return p, out, {"a": llm.number(j.get("a")), "b": llm.number(j.get("b")), "why": j.get("why", "")}
        except Exception as ex:
            log(f"eval item failed: {type(ex).__name__}: {str(ex)[:120]}")
            return p, None, None

    with ThreadPoolExecutor(4) as pool:
        results = list(pool.map(one, tests))
    scored = [(p, out, j) for p, out, j in results if j]
    if not scored:
        return None
    sa = sum(j["a"] for _, _, j in scored) / len(scored)
    sb = sum(j["b"] for _, _, j in scored) / len(scored)
    detail = [{"post": p["parent_text"][:200], "real": p["text"], "a": out["a"], "b": out["b"],
               "score_a": j["a"], "score_b": j["b"], "why": j["why"]} for p, out, j in scored]
    score = store.add_eval(version_id, label, e.get("AI_MODEL"), len(scored), round(sa, 2), round(sb, 2), detail)
    log(f"fit eval [{label}]: A {sa:.1f}, B {sb:.1f} over {len(scored)} posts ({len(tests) - len(scored)} skipped)")
    return score
