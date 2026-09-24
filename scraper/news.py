"""Official news: recent articles from the feeds in sources.json, full text fetched on demand.

profile/sources.json, if present, replaces config/sources.json. Only public pages are read.
"""
import json
import re
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import feedparser
import httpx
import trafilatura

import config

DEFAULT_SOURCES = config.ROOT / "config" / "sources.json"


def sources_file():
    custom = config.PROFILE_DIR / "sources.json"
    return custom if custom.exists() else DEFAULT_SOURCES
UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) x-reply-radar/1.0"}


def _get(url):
    r = httpx.get(url, timeout=20, follow_redirects=True, headers=UA)
    r.raise_for_status()
    return r


def _strip(html):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html or "")).strip()


def _rss(src):
    feed = feedparser.parse(_get(src["url"]).content)
    out = []
    for e in feed.entries[: src.get("limit", 20)]:
        t = e.get("published_parsed") or e.get("updated_parsed")
        out.append({"url": e.get("link"), "title": e.get("title", "").strip(),
                    "summary": _strip(e.get("summary", ""))[:500],
                    "published": datetime.fromtimestamp(time.mktime(t), timezone.utc).isoformat() if t else None})
    return out


def _hf_papers(src):
    out = []
    for p in _get(src["url"]).json()[: src.get("limit", 10)]:
        paper = p.get("paper", {})
        out.append({"url": f"https://huggingface.co/papers/{paper.get('id')}", "title": paper.get("title", ""),
                    "summary": (paper.get("summary") or "")[:500], "published": p.get("publishedAt"),
                    "score": paper.get("upvotes")})
    return out


def _links(src):
    html = _get(src["url"]).text
    seen, out = set(), []
    for path in re.findall(src["pattern"], html):
        if path not in seen:
            seen.add(path)
            out.append({"url": src.get("base", "") + path, "title": path.rsplit("/", 1)[-1].replace("-", " "),
                        "summary": "", "published": None})
    return out[: src.get("limit", 8)]


def collect(log=print, hours=48):
    """Items from the last `hours` hours (undated ones too; the database dates them by first sighting)."""
    cfg = json.loads(sources_file().read_text(encoding="utf-8"))["sources"]
    since = datetime.now(timezone.utc) - timedelta(hours=hours)

    def one(src):
        try:
            items = {"rss": _rss, "hf_papers": _hf_papers, "links": _links}[src["type"]](src)
        except Exception as ex:
            log(f"news source failed {src['name']}: {type(ex).__name__}")
            return []
        words = [w.lower() for w in src.get("filter", [])]
        keep = []
        for it in items:
            if not it.get("url") or not it.get("title"):
                continue
            if words and not any(w in (it["title"] + it["summary"]).lower() for w in words):
                continue
            if it["published"] and datetime.fromisoformat(it["published"].replace("Z", "+00:00")) < since:
                continue
            keep.append({**it, "source": src["name"]})
        return keep

    with ThreadPoolExecutor(6) as pool:
        items = [it for chunk in pool.map(one, cfg) for it in chunk]
    log(f"news: {len(items)} items from {len(cfg)} sources")
    return items


def article_text(url, limit=6000):
    """Article text, so the model works from the source instead of guessing from a title."""
    try:
        data = trafilatura.extract(_get(url).text, output_format="json", with_metadata=True)
        d = json.loads(data) if data else {}
        return (d.get("title") or ""), (d.get("text") or "")[:limit]
    except Exception:
        return "", ""
