"""Writing posts: quote posts on news, posts on a trend, and polishing your own text.

Nothing here posts anything. Results become drafts; you decide what to send.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import config
import store
from ai import llm, persona
from ai.review import review


def _write(e, template, user, temperature=0.9):
    system = persona.system(template, e, work=True)
    banned = persona.banned(e)
    out = {}
    for _ in range(2):
        out = llm.parse_json(llm.chat(e, system, user, temperature=temperature))
        text = str(out.get("text") or "").strip()
        if out.get("skip") or not text:
            return {"skip": True}
        hit = [b for b in banned if b in text]
        if not hit:
            return out
        user += (f"\n\n（上一版用了「{'、'.join(hit)}」，重写）" if persona.lang(e) == "zh"
                 else f"\n\n(The last version used: {', '.join(hit)}. Rewrite it.)")
    return {"skip": True}


def quote_for(e, source: dict, log=print, save=True):
    """Quote-post draft for one item: {"url","source","title","text"} (text = article body or post text).

    Returns the draft dict, or None when the model chose to skip it."""
    is_tweet = source.get("tweet") is not None
    title, body = source.get("title", ""), source.get("body", "")
    if not is_tweet and not body:
        from scraper import news
        t, body = news.article_text(source["url"])
        title, body = title or t, body or source.get("summary", "")
    if len(body or "") < (10 if is_tweet else 60):
        body = (body or "") + "\n" + (source.get("summary") or "")
    zh = persona.lang(e) == "zh"
    user = (f"来源：{source['source']}\n标题：{title}\n\n原文：\n{body}" if zh else
            f"Source: {source['source']}\nTitle: {title}\n\nText:\n{body}")
    out = _write(e, "quote", user)
    if out.get("skip"):
        return None
    tweet = source.get("tweet") or {}
    draft = {"kind": "quote" if is_tweet else "link", "angle": source["source"], "text": out["text"].strip(), "based_on": out.get("take") or "",
             "url": source["url"], "source": f"{source['source']}｜{title}"[:300], "facts": out.get("facts"),
             "target_id": tweet.get("id"), "target_author": tweet.get("author_handle")}
    if config.get_bool(e, "FIT_REVIEW"):
        review(e, [draft], log)
    if save:
        draft["id"] = store.add_drafts([draft])[0]
    return draft


def post_about(e, topic: str, context_text: str = "", log=print, save=True):
    """An original post on a trend or on a rough idea of yours."""
    zh = persona.lang(e) == "zh"
    user = (f"素材：{topic}" + (f"\n\n相关背景：\n{context_text}" if context_text else "")) if zh else \
        (f"Material: {topic}" + (f"\n\nContext:\n{context_text}" if context_text else ""))
    out = _write(e, "post", user)
    if out.get("skip"):
        return None
    draft = {"kind": "post", "angle": topic[:80], "text": out["text"].strip(), "based_on": out.get("take") or ""}
    if config.get_bool(e, "FIT_REVIEW"):
        review(e, [draft], log)
    if save:
        draft["id"] = store.add_drafts([draft])[0]
    return draft


def polish(e, text: str) -> dict:
    """Your text, made to sound more like you. Returns {"text", "fix"}."""
    out = llm.parse_json(llm.chat(e, persona.system("polish", e), text, temperature=0.4))
    return {"text": str(out.get("text") or text).strip(), "fix": out.get("fix") or ""}


# ---------- daily quote posts on the news ----------

def _news_candidates(hot_x):
    items = [{"url": n["url"], "source": n["source"], "title": n["title"], "summary": n["summary"] or ""}
             for n in store.fresh_news()]
    for t in hot_x:  # posts blowing up on the timeline are good to quote directly
        items.append({"url": t["url"], "source": f"X @{t['author_handle']}", "title": t["text"][:100],
                      "summary": t["text"][:500], "body": t["text"], "tweet": t})
    return items


def generate_news(e, hot_x=(), n=5, log=print):
    """Pick n news items and write a quote-post draft for each. Returns how many drafts were kept."""
    from scraper import news
    store.upsert_news(news.collect(log=log))
    cands = _news_candidates(hot_x)
    if not cands:
        log("no fresh news")
        return 0
    listing = "\n".join(f"[{i}] {c['source']}｜{c['title']}｜{c['summary'][:160]}" for i, c in enumerate(cands[:120]))
    system = persona.system("pick", e, work=True, n=n)
    picks = llm.parse_json(llm.chat(e, system, listing, temperature=0.2)).get("picks", [])
    picked, seen = [], set()
    for p in picks:
        i = p.get("i")
        if isinstance(i, str) and i.isdigit():
            i = int(i)
        if isinstance(i, int) and 0 <= i < min(len(cands), 120) and i not in seen:
            seen.add(i)
            picked.append(cands[i])
    picked = picked[:n]

    def one(c):
        try:
            return quote_for(e, c, log, save=False)
        except Exception as ex:
            log(f"quote draft failed ({c['source']}): {type(ex).__name__}: {str(ex)[:120]}")
            return None

    with ThreadPoolExecutor(3) as pool:
        drafts = [d for d in pool.map(one, picked) if d]
    store.mark_news([c["url"] for c in picked if "tweet" not in c])
    min_score = config.get_float(e, "QUOTE_MIN_SCORE")
    kept = [d for d in drafts if d.get("score") is None or d["score"] >= min_score]
    store.add_drafts(kept)
    log(f"news quote drafts: kept {len(kept)} of {len(drafts)} (picked {len(picked)})")
    return len(kept)
