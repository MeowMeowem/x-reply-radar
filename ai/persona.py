"""Your profile (who you are, what you've done, how you talk) and the prompt templates.

profile/ is yours and never committed:
  persona.md       who you are and how you talk, written by you (the most important file)
  work.md          facts the AI may mention: projects, tools, experience
  style_notes.md   notes learned from your real posts (regenerated; your edits are kept as a version)
  prompts/*.txt    optional overrides for any template in prompts/<lang>/

Templates use {{name}} placeholders so the JSON examples inside them need no escaping.
"""
from __future__ import annotations

import re
import shutil

import config
import store

EXAMPLE_DIR = config.ROOT / "profile.example"
PROMPT_DIR = config.ROOT / "prompts"
FILES = ("persona.md", "work.md", "style_notes.md")
MAX_EXAMPLES = 30


def lang(e) -> str:
    return e.get("CONTENT_LANG") if e.get("CONTENT_LANG") in ("zh", "en") else "zh"


def ensure(e) -> None:
    """First run: copy the example profile in the content language."""
    config.PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    for name in ("persona.md", "work.md"):
        target = config.PROFILE_DIR / name
        source = EXAMPLE_DIR / f"{name[:-3]}.{lang(e)}.md"
        if not source.exists():
            continue
        if not target.exists():
            shutil.copy(source, target)
            continue
        # still the untouched example in the other language: switch it with the content language
        other = EXAMPLE_DIR / f"{name[:-3]}.{'en' if lang(e) == 'zh' else 'zh'}.md"
        if other.exists() and target.read_bytes() == other.read_bytes():
            shutil.copy(source, target)


def path(name: str):
    if name not in FILES:
        raise ValueError(name)
    return config.PROFILE_DIR / name


def read(name: str) -> str:
    p = path(name)
    return p.read_text(encoding="utf-8") if p.exists() else ""


def write(name: str, text: str) -> None:
    p = path(name)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text.rstrip() + "\n", encoding="utf-8")


def strip_comments(text: str) -> str:
    return "\n".join(l for l in text.splitlines() if not l.lstrip().startswith("#")).strip()


PLACEHOLDER = re.compile(r"<<.*?>>")


def filled(text: str) -> str:
    """Comments and lines still holding a <<fill me in>> placeholder removed."""
    return "\n".join(l for l in strip_comments(text).splitlines() if not PLACEHOLDER.search(l)).strip()


def has_content(text: str) -> bool:
    """Real content, not just the example's headings."""
    return any(l.strip() and not l.strip().endswith((":", "：")) for l in filled(text).splitlines())


def is_filled(name: str) -> bool:
    return has_content(read(name))


def me(e) -> str:
    handle, name = config.handle(e), (e.get("DISPLAY_NAME") or "").strip()
    if lang(e) == "en":
        return f"{name} (@{handle} on X)" if name and handle else (f"@{handle} on X" if handle else "me")
    return f"{name}（X 账号 @{handle}）" if name and handle else (f"X 账号 @{handle}" if handle else "我")


def prompt(name: str, e) -> str:
    override = config.PROFILE_DIR / "prompts" / f"{name}.txt"
    if override.exists():
        return override.read_text(encoding="utf-8")
    p = PROMPT_DIR / lang(e) / f"{name}.txt"
    if not p.exists():
        p = PROMPT_DIR / "zh" / f"{name}.txt"
    return p.read_text(encoding="utf-8")


def render(template: str, **values) -> str:
    return re.sub(r"\{\{(\w+)\}\}", lambda m: str(values.get(m.group(1), m.group(0))), template)


def banned(e) -> list[str]:
    text = prompt("banned", e)
    return [l.strip() for l in text.splitlines() if l.strip() and not l.startswith("#")]


# ---------- context blocks ----------

def _block(title_zh, title_en, body, e):
    if not has_content(body):
        return ""
    body = filled(body)
    return f"【{title_zh}】\n{body}" if lang(e) == "zh" else f"[{title_en}]\n{body}"


def persona_block(e) -> str:
    return _block("我是谁、我怎么说话", "Who I am and how I talk", read("persona.md"), e)


def work_block(e) -> str:
    return _block("我做过的事", "Things I have done", read("work.md"), e)


def notes_block(e, notes=None) -> str:
    body = read("style_notes.md") if notes is None else notes
    return _block("从我真实帖子里学到的背景和习惯", "Learned from my real posts", body, e)


def pick_examples(exclude=()):
    pairs = [p for p in store.my_own_posts("reply")
             if p["id"] not in exclude and p.get("parent_text") and 2 <= len(p["text"]) <= 280]
    # newest first, with a nudge for replies that did well
    pairs.sort(key=lambda p: (p["created_at"] or "", (p["likes"] or 0) * 3 + (p["replies"] or 0)), reverse=True)
    return pairs[:MAX_EXAMPLES]


def examples_block(e, exclude=()) -> str:
    ex = pick_examples(exclude)
    zh = lang(e) == "zh"
    lines = []
    if ex:
        lines.append("下面是我真实回过的帖子（原帖 → 我的回复），语气、长度、用词以这些为准："
                     if zh else "Replies I really wrote (their post -> my reply). Match this tone, length and wording:")
        for p in ex:
            parent = (p["parent_text"] or "").replace("\n", " ")[:120]
            lines.append(f"- @{p['parent_author']}: {parent}\n  → {p['text']}")
    # Leave-one-out evaluation passes `exclude`; corrections could contain the held-out reply, so skip them.
    fixes = [] if exclude else [x for x in store.edits(limit=12) if x["ai_text"].strip() != x["final_text"].strip()]
    if fixes:
        lines.append("\n我改过的 AI 草稿（左边是 AI 写的，右边是我实际发的，照右边的感觉写）："
                     if zh else "\nAI drafts I corrected (AI wrote the left side, I posted the right side):")
        lines += [f"- {x['ai_text'][:140]}\n  → {x['final_text'][:200]}" for x in fixes]
    return "\n".join(lines)


def context(e, exclude=(), use_learned=True, work=False, notes=None) -> str:
    """The shared part of every writing prompt. `notes` overrides style_notes.md (used when comparing versions)."""
    blocks = [persona_block(e)]
    if work:
        blocks.append(work_block(e))
    if use_learned:
        blocks += [notes_block(e, notes), examples_block(e, exclude)]
    return "\n\n".join(b for b in blocks if b)


def system(name: str, e, exclude=(), use_learned=True, work=False, notes=None, **values) -> str:
    return render(prompt(name, e), me=me(e), context=context(e, exclude, use_learned, work, notes), **values)
