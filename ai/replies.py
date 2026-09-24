"""Reply suggestions (A and B) for a post, in your voice."""
from __future__ import annotations

from ai import llm, persona


def _user_message(e, tweet, avoid):
    zh = persona.lang(e) == "zh"
    media = {"photo": ("（带图）", " (with image)"), "video": ("（带视频）", " (with video)")}
    tag = media.get(tweet.get("media_type") or "", ("", ""))[0 if zh else 1]
    msg = (f"作者：{tweet['author_name']} @{tweet['author_handle']}\n原帖{tag}：\n{tweet['text']}" if zh else
           f"Author: {tweet['author_name']} @{tweet['author_handle']}\nPost{tag}:\n{tweet['text']}")
    if avoid:  # each post is written separately; show recent lines so a screen isn't the same catchphrase
        msg += ("\n\n最近几条已经这么回过了，别再用相同的开头、口头禅和同一个背景点：\n" if zh else
                "\n\nRecent replies already used these; avoid the same openings, catchphrases and background points:\n")
        msg += "\n".join(f"- {x}" for x in avoid)
    return msg


def generate(e, tweet, system=None, avoid=()):
    """{skip, want, a, b}. A banned phrase triggers one rewrite; if it's still there, the post is skipped."""
    system = system if system is not None else persona.system("reply", e)
    user = _user_message(e, tweet, avoid)
    banned = persona.banned(e)
    a = b = ""
    for _ in range(2):
        out = llm.parse_json(llm.chat(e, system, user))
        skip = bool(out.get("skip"))
        a, b = str(out.get("a") or "").strip(), str(out.get("b") or "").strip()
        want = max(0.0, min(10.0, llm.number(out.get("want"))))
        if skip or not (a and b):
            return {"skip": True, "want": want, "a": a, "b": b}
        hit = [p for p in banned if p in a or p in b]
        if not hit:
            return {"skip": False, "want": want, "a": a, "b": b}
        user += (f"\n\n（上一版用了「{'、'.join(hit)}」这种 AI 腔，重写，更像随手回的）" if persona.lang(e) == "zh"
                 else f"\n\n(The last version used AI-sounding phrases: {', '.join(hit)}. Rewrite it more offhand.)")
    return {"skip": True, "want": 0, "a": a, "b": b}
