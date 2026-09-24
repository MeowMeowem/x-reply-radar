"""Server-side strings: progress phases, stage labels and score parts.

Everything the browser shows is translated in static/i18n.js; the server only sends
localized text where another client (for example an integration reading /api/status)
displays it as-is. The language follows CONTENT_LANG, falling back to Chinese.
"""
import config

STRINGS = {
    "zh": {
        "phase.scrape_home": "抓取 X 首页",
        "phase.read_mine": "读取我的帖子",
        "phase.learn": "学习我的风格",
        "phase.drafts": "写发帖草稿",
        "phase.replies": "生成回复 {n} 条",
        "phase.trends": "抓取趋势",
        "phase.watch": "抓取关注的官方账号",
        "phase.news": "读取官方动态",
        "phase.consolidate": "整理风格笔记",
        "phase.eval": "契合度评测",
        "phase.follow_search": "搜索互关的人",
        "stage.rising": "刚起量",
        "stage.viral": "正在爆",
        "stage.late": "已经太晚",
        "error.scrape": "本轮抓取失败，保留上一次结果",
        "part.fresh": "新鲜", "part.views": "浏览增速", "part.engage": "互动增速", "part.relevance": "相关",
        "part.author": "作者", "part.accel": "加速", "part.saturation": "评论饱和", "part.stage": "阶段",
        "part.want": "想回",
    },
    "en": {
        "phase.scrape_home": "Reading your X home timeline",
        "phase.read_mine": "Reading your own posts",
        "phase.learn": "Learning your style",
        "phase.drafts": "Writing post drafts",
        "phase.replies": "Writing {n} replies",
        "phase.trends": "Reading trends",
        "phase.watch": "Reading watched accounts",
        "phase.news": "Reading official news",
        "phase.consolidate": "Consolidating style notes",
        "phase.eval": "Running the fit evaluation",
        "phase.follow_search": "Searching for follow-backs",
        "stage.rising": "Rising",
        "stage.viral": "Going viral",
        "stage.late": "Too late",
        "error.scrape": "This round failed; showing the previous results",
        "part.fresh": "Fresh", "part.views": "View velocity", "part.engage": "Engagement velocity",
        "part.relevance": "Relevance", "part.author": "Author reach", "part.accel": "Accelerating",
        "part.saturation": "Reply saturation", "part.stage": "Stage", "part.want": "Want to reply",
    },
}


def lang(e=None) -> str:
    e = e or config.env()
    return e.get("CONTENT_LANG") if e.get("CONTENT_LANG") in STRINGS else "zh"


def t(key: str, e=None, **kw) -> str:
    table = STRINGS[lang(e)]
    return table.get(key, STRINGS["zh"].get(key, key)).format(**kw)
