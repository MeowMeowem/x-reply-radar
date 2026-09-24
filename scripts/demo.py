"""Demo mode: made-up accounts and posts, no X login or AI key needed.

    python scripts/demo.py              # English, http://127.0.0.1:8799
    python scripts/demo.py --lang zh    # Chinese

Everything lives in data/demo-<lang>/ and is recreated on every start. Buttons that
need X or an AI (refresh, new replies, sending) will fail politely, because there is
nothing real behind them. Every account, company and link here is fictional.
"""
import argparse
import os
import random
import shutil
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

NOW = datetime.now(timezone.utc)


def ago(**kw):
    return (NOW - timedelta(**kw)).isoformat(timespec="seconds")


# ---------- content ----------

EN = {
    "persona": """Name: Mia
Who I am: indie developer, I ship small AI tools and write about what breaks.
Why I reply: to be useful for ten seconds and maybe make someone curious about my profile.

How I talk:
- short, lowercase-ish, one line most of the time
- "ok this is good", "wait what", "lol", "been there"
- concrete numbers when I have them, never when I don't
- an emoji maybe once a day

Things I never say:
- "great thread", "game-changer", life lessons, summaries of the post""",
    "work": """Tinyform (a form builder that writes its own validation)
- 1,200 users, mostly solo founders; launched on a Tuesday by accident

Tools I use
- a coding agent every day, a local model for drafts, Figma for everything visual""",
    "notes": """[My real background]
- runs Tinyform, a small form builder, 1,200 users
- codes with an agent daily, keeps a local model for drafts
- launches things quietly and fixes them in public

[How I talk]
- one short line, rarely two
- starts with the reaction, not the context ("ok wait", "honestly no")
- uses real numbers from her own projects
- lowercase, few commas, no em dashes
- never: "great thread", summaries, advice nobody asked for""",
    "tweets": [
        ("Ada Park", "ada_ships", "Shipped a feature in 40 minutes with an AI agent today. Spent the next 3 hours reading what it wrote so I could trust it. Still faster? Honestly not sure.",
         48200, 64, 910, 24, "wait the 3 hours of reading is the real product review lol", "been there. the reading is where you find the one line that deletes prod", 8.6, 9.1, 18, 12000),
        ("Jun Tanaka", "jun_codes", "Hot take: most AI products don't need a chat box. They need one good button.", 129000, 211, 3400, 190,
         "tinyform had a chat box for two weeks. usage went up when we deleted it", "one good button > one clever prompt", 9.0, 8.4, 42, 88000),
        ("Lina Wu", "lina_ai_notes", "Ran the same prompt on 5 models for a week of customer emails. The cheapest one won on tone. Writing it up tomorrow.",
         22400, 31, 480, 12, "please include the tone rubric, that's the part everyone guesses", "cheapest winning on tone is my favorite genre of result", 7.4, 8.8, 9, 5400),
        ("Sam Ortiz", "samwrites", "Indie devs: what's the smallest thing you built that people actually paid for?", 61800, 402, 720, 30,
         "a validation rule generator. $9. still my favorite invoice", "a regex explainer lol", 8.1, 7.2, 55, 23000),
        ("Kai Mercer", "kai_prompts", "Prompt engineering is dead, long live context engineering. Your model is only as good as what you put in front of it.", 9100, 12, 150, 8,
         "the model is only as good as the docs i forgot to update", "context is just prompt engineering that went to therapy", 6.4, 8.9, 25, 3100),
        ("Mo Hassan", "mo_indie", "Month 3 of building in public: $1,140 MRR, 2 churned customers, 1 very kind email that made my week.", 17300, 58, 640, 20,
         "the kind email is the real mrr", "congrats on 1140, the churn emails are the useful ones", 8.8, 7.9, 70, 7600),
    ],
    "trends": [("#buildinpublic", "Technology · Trending", "18.2K posts"), ("Vibe coding", "Technology · Trending", "42K posts"),
               ("Open weights", "AI · Trending", "9,870 posts"), ("#IndieHackers", "Business · Trending", "6,112 posts"),
               ("Local LLMs", "Technology · Trending", "3,405 posts"), ("Agent frameworks", "Only on X · Trending", ""),
               ("Launch day", "Trending", "12.9K posts"), ("Dark mode", "Design · Trending", "2,210 posts")],
    "news": [("Nimbus AI", "Nimbus 4 is out: faster, cheaper, and it finally reads PDFs properly", "A new flagship model with a lower price and a longer context window.", 3),
             ("Orbit Labs", "Orbit Studio adds one-click deploys for AI agents", "Agents built in Orbit Studio can now be deployed to a hosted endpoint.", 9),
             ("Daily Papers", "Small models, big context: a study of long-document retrieval", "The authors find that retrieval quality matters more than model size.", 14),
             ("Dev Digest", "The state of indie SaaS pricing in 2026", "Survey of 1,800 indie products and what they charge.", 20)],
    "watch": [("Nimbus AI", "nimbusai_demo", "Nimbus 4 is rolling out to everyone today. Same price for the first month, and PDFs just work now.", 310000, 1200, 9800, 3),
              ("Orbit Labs", "orbitlabs_demo", "You can now deploy an agent from Orbit Studio with one click. Here's a 60-second demo.", 88000, 240, 2100, 9)],
    "drafts": [("quote", "Nimbus AI", "pdfs just work now is the most underrated line in any launch post this year", "The PDF fix matters more than the benchmark", 8.7),
               ("quote", "Dev Digest", "1,800 products and the median is still $9. we are all underpricing, me included", "Indie pricing is too low", 8.1),
               ("post", "Vibe coding", "vibe coded a pricing page tonight. it works. i do not know why. shipping it anyway", "Fun, honest", 7.9)],
    "mine": [("the reading is the review", "Shipped with an agent, then spent hours reviewing"), ("tinyform does this and people still email me the regex", "Form validation is solved?"),
             ("ok this is good", "Launch post for a small tool"), ("1,200 users and i still answer every email myself", "How do you do support?"),
             ("honestly no, the local model is fine for drafts", "Do you pay for the big models?"), ("lowercase is a lifestyle", "Why no caps?")],
    "edits": [("This is a really interesting point about agents and code review.", "the reading is the review lol"),
              ("Congratulations on reaching this milestone! Keep going!", "congrats, 1140 is real money"),
              ("I think deleting the chat box is a great product decision.", "we deleted ours too. usage went up")],
}

ZH = {
    "persona": """昵称：小满
我是谁：独立开发者，做一些小的 AI 工具，喜欢把踩过的坑写出来。
我回帖的目的：顺手接一句，让人觉得这人挺实在，想点进主页看看。

我说话的样子：
- 很短，大多一句话，两个空格断句
- 「确实」「笑死」「我也是」「等一下」
- 有真实数字才说数字，没有就不编
- 偶尔一个 emoji

我基本不会这样说：
- 不写总结、不讲道理、不说「感谢分享」""",
    "work": """小表单（一个会自己写校验规则的表单工具）
- 1200 个用户，大多是一个人做产品的开发者

在用的工具
- 天天用编程智能体写代码，本机模型写草稿""",
    "notes": """【我的真实背景】
- 在做「小表单」，1200 个用户
- 天天用编程智能体，本机模型写草稿

【我说话的习惯】
- 一句话为主，两个空格断句
- 先说反应再说事：「等一下」「确实」
- 用自己项目里的真实数字
- 基本不会：写总结、讲道理、「感谢分享」""",
    "tweets": [
        ("阿杰做产品", "ajie_builds", "今天用 AI 智能体 40 分钟写完一个功能，然后花了 3 个小时读它写的代码才敢上线。到底算不算快，我真的不确定。",
         48200, 64, 910, 24, "读代码那 3 小时才是真正的验收  笑死", "我也是  读着读着发现一行能把库删了", 8.6, 9.1, 18, 12000),
        ("老张写代码", "laozhang_dev", "暴论：大部分 AI 产品根本不需要聊天框，需要的是一个好用的按钮。", 129000, 211, 3400, 190,
         "小表单做过两周聊天框  删掉以后使用量反而涨了", "一个好按钮 > 一段聪明的提示词", 9.0, 8.4, 42, 88000),
        ("小鱼的 AI 笔记", "xiaoyu_ai_notes", "拿同一个提示词让 5 个模型回了一周客服邮件，语气最好的居然是最便宜的那个。明天写复盘。",
         22400, 31, 480, 12, "求把语气的评分标准也放出来  大家都是凭感觉", "最便宜的赢  这种结果我最爱看", 7.4, 8.8, 9, 5400),
        ("一个人的公司", "solo_company_cn", "独立开发的朋友们：你做过最小、但真有人付钱的东西是什么？", 61800, 402, 720, 30,
         "一个校验规则生成器  9 块钱  到现在还是我最喜欢的一张发票", "一个正则解释器  哈哈", 8.1, 7.2, 55, 23000),
        ("提示词研究所", "prompt_lab_cn", "提示词工程已死，上下文工程当立。模型好不好，取决于你喂给它什么。", 9100, 12, 150, 8,
         "模型好不好  取决于我忘了更新的那份文档", "上下文工程就是提示词工程去做了心理咨询", 6.4, 8.9, 25, 3100),
    ],
    "trends": [("#独立开发", "科技 · 趋势", "1.8万 帖子"), ("AI 编程", "科技 · 趋势", "4.2万 帖子"), ("开源模型", "AI · 趋势", "9870 帖子"),
               ("副业", "商业 · 趋势", "6112 帖子"), ("本地大模型", "科技 · 趋势", "3405 帖子"), ("智能体框架", "仅在 X · 趋势", ""),
               ("产品上线", "趋势", "1.2万 帖子"), ("深色模式", "设计 · 趋势", "2210 帖子")],
    "news": [("Nimbus AI", "Nimbus 4 发布：更快、更便宜，终于能正经读 PDF 了", "新旗舰模型降价，并支持更长的上下文。", 3),
             ("Orbit Labs", "Orbit Studio 支持一键部署 AI 智能体", "在 Orbit Studio 里做的智能体现在可以一键部署。", 9),
             ("论文日报", "小模型、长上下文：长文档检索的一项研究", "作者发现检索质量比模型大小更重要。", 14),
             ("开发者周刊", "2026 年独立 SaaS 定价调查", "调查了 1800 个独立产品的定价。", 20)],
    "watch": [("Nimbus AI", "nimbusai_demo", "Nimbus 4 今天全量上线。首月价格不变，PDF 现在能直接读了。", 310000, 1200, 9800, 3),
              ("Orbit Labs", "orbitlabs_demo", "现在可以在 Orbit Studio 里一键部署智能体了，附 60 秒演示。", 88000, 240, 2100, 9)],
    "drafts": [("quote", "Nimbus AI", "「PDF 现在能直接读了」是今年最被低估的一句发布文案", "PDF 修好了比跑分重要", 8.7),
               ("quote", "开发者周刊", "1800 个产品  中位数还是 9 块钱  我们都定价太低了  包括我", "独立产品普遍定价太低", 8.1),
               ("post", "AI 编程", "今晚用 AI 写了个定价页  能跑  不知道为什么能跑  先上线再说", "好玩、真实", 7.9)],
    "mine": [("读代码才是验收", "用智能体写完功能又花几小时看代码"), ("小表单就是干这个的  还是有人给我发正则", "表单校验不是早就解决了吗"),
             ("确实", "一个小工具的上线帖"), ("1200 个用户  邮件还是我自己回", "你们客服怎么做"),
             ("不用  本机模型写草稿够了", "你会给大模型付费吗"), ("小写是一种生活方式", "为什么从来不用大写")],
    "edits": [("这个关于智能体和代码审查的观点真的很有意思。", "读代码才是验收  笑死"),
              ("恭喜达成这个里程碑！继续加油！", "恭喜  1140 是真钱"),
              ("我觉得删掉聊天框是一个很好的产品决策。", "我们也删了  使用量反而涨了")],
}


# ---------- seeding ----------

def tweet_row(tid, name, handle, text, views, replies, likes, rts, age_min, followers=5000, source="home"):
    return {"id": tid, "author_name": name, "author_handle": handle, "author_avatar": None, "author_followers": followers,
            "text": text, "url": f"https://x.com/{handle}/status/{tid}", "created_at": ago(minutes=age_min), "lang": "en",
            "media_type": "", "is_reply": False, "views": views, "replies": replies, "likes": likes, "retweets": rts,
            "quotes": rts // 3}


def seed(lang):
    import store
    from ai import persona
    from ranking import score

    c = EN if lang == "en" else ZH
    store.init()
    persona.write("persona.md", c["persona"])
    persona.write("work.md", c["work"])
    persona.write("style_notes.md", c["notes"])

    # hot posts with two snapshots each, so growth rates show up
    for i, (name, handle, text, views, rep, likes, rts, a, b, fa, fb, age, followers) in enumerate(c["tweets"]):
        tid = str(1970000000000000000 + i)
        grow = (0.62, 0.74, 0.81, 0.88, 0.7, 0.93)[i % 6]  # a different growth rate for each post
        t = tweet_row(tid, name, handle, text, int(views * grow), max(1, rep - 8), int(likes * grow), rts, age, followers)
        t["topic"], t["relevance"], t["blocked"] = "AI", 1.0, 0
        score.classify(t)
        t["relevance"] = max(t["relevance"], 0.7)
        store.upsert([t], ts=ago(minutes=12))
        store.upsert([{**t, "views": views, "replies": rep, "likes": likes}], ts=ago(minutes=1))
        store.save_replies(tid, a, b, 8, False, fa, fb)

    for i, (name, handle, text, views, rep, likes, age_h) in enumerate(c["watch"]):
        t = tweet_row(str(1971000000000000000 + i), name, handle, text, views, rep, likes, likes // 10, age_h * 60, 900000)
        t.update(topic="AI", relevance=1.0, blocked=0)
        store.upsert([t], source="watch")

    store.save_trends([{"name": n, "context": ctx, "posts": p} for n, ctx, p in c["trends"]])
    store.kv_set("trends_at", (NOW - timedelta(minutes=6)).timestamp())
    store.upsert_news([{"url": f"https://example.com/news/{i}", "source": src, "title": title, "summary": summary,
                        "published": ago(hours=h)} for i, (src, title, summary, h) in enumerate(c["news"])])

    # one quote of a (made-up) post on X, one post sharing an article, one original post
    watch_url = f"https://x.com/{c['watch'][0][1]}/status/1971000000000000000"
    drafts = []
    for n, (kind, angle, text, basis, sc) in enumerate(c["drafts"]):
        d = {"kind": kind, "angle": angle, "text": text, "based_on": basis, "score": sc}
        if kind == "quote" and n == 0:
            d.update(url=watch_url, source=f"X @{c['watch'][0][1]}", target_id="1971000000000000000",
                     target_author=c["watch"][0][1])
        elif kind == "quote":
            title = next((x[1] for x in c["news"] if x[0] == angle), "")
            d.update(kind="link", url="https://example.com/news/3", source=f"{angle}｜{title}")
        drafts.append(d)
    store.add_drafts(drafts)

    # your own posts: replies with the post they answered, plus a few originals
    rnd = random.Random(7)
    pairs, posts = [], []
    for n in range(36):
        text, parent = c["mine"][n % len(c["mine"])]
        pairs.append({"id": str(1960000000000000000 + n), "text": text, "created_at": ago(days=n // 2, hours=rnd.randint(0, 20)),
                      "likes": rnd.randint(0, 30), "replies": rnd.randint(0, 5), "views": rnd.randint(300, 4000),
                      "parent_id": str(1950000000000000000 + n), "parent_author": "someone_demo", "parent_text": parent})
    for n in range(9):
        posts.append({"id": str(1961000000000000000 + n), "text": c["mine"][n % len(c["mine"])][0],
                      "created_at": ago(days=n * 3), "likes": rnd.randint(5, 80), "replies": 2, "views": 5000})
    store.upsert_mine(pairs, posts)
    store.upsert_mine([{**p, "id": "19590000000000000" + str(n).zfill(2), "created_at": ago(days=60 + n)} for n, p in enumerate(pairs[:12])],
                      [], origin="archive")
    store.kv_set("consolidate_run_at", NOW.timestamp())  # the demo never runs a real consolidation
    for ai_text, final in c["edits"]:
        store.add_edit("reply", ai_text, final)

    # four weeks of learning: versions and fit evaluations that improve over time
    history = [(28, "learn", None), (21, "consolidate", 6.9), (14, "consolidate", 6.6), (7, "consolidate", 7.6),
               (2, "manual", None)]
    dated = [(store.add_style_version(c["notes"], reason, 40, score=sc), days) for days, reason, sc in history]
    with store.conn() as db:
        for vid, days in dated:
            db.execute("UPDATE style_versions SET created_at=? WHERE id=?", (ago(days=days), vid))
    runs = [(27, 6.1, 6.3, 6.2), (20, 6.2, 6.9, 7.1), (13, 6.0, 7.2, 6.8), (6, 6.3, 7.7, 7.9), (1, 6.2, 8.1, None)]
    for days, base, cur, cand in runs:
        for label, s in (("baseline", base), ("current", cur), ("candidate", cand)):
            if s is None:
                continue
            store.add_eval(None, label, "demo-model", 8, round(s - 0.4, 2), round(s + 0.4, 2), [
                {"post": c["mine"][1][1], "real": c["mine"][1][0], "a": c["edits"][0][1], "b": c["mine"][0][0],
                 "score_a": round(s - 0.4, 1), "score_b": round(s + 0.4, 1), "why": "demo"}])
            with store.conn() as db:
                db.execute("UPDATE evals SET ts=? WHERE id=(SELECT MAX(id) FROM evals)", (ago(days=days, minutes=-2),))

    # people asking for follow-backs: some worth following, some that only collect followers
    people = [("maker_lin", "Lin builds", 820, 1340, True, "bio"), ("pixel_june", "June", 460, 910, False, "post"),
              ("devnotes_kai", "Kai Notes", 2100, 2380, False, "bio"), ("tiny_saas_bo", "Bo", 150, 600, True, "bio"),
              ("aiweekly_sam", "AI Weekly", 38000, 900, False, "bio"), ("growth_guru", "Growth Guru", 12500, 40, False, "post"),
              ("newbie_01", "New here", 3, 8, False, "bio")]
    bio = "互关 · 必回关 · 做独立产品" if lang == "zh" else "follow back 100% · building in public"
    store.upsert_candidates([{"user_id": str(1980000000000000000 + i), "handle": h, "name": n, "avatar": None, "bio": bio,
                              "followers": fr, "following": fg, "posts": 5 if h == "newbie_01" else 300, "protected": False,
                              "verified": False, "following_now": False, "followed_by": fb, "source": src,
                              "matched": bio, "keyword": "互关" if lang == "zh" else "follow back"}
                             for i, (h, n, fr, fg, fb, src) in enumerate(people)])
    store.set_candidates(["1980000000000000000"], status="followed", followed_at=ago(days=2))

    # a few sends in different states
    t0 = store.tweet("1970000000000000001")
    for status, text, kind, extra in [("sent", c["tweets"][1][7], "reply", {"result_id": "1970000000000009999"}),
                                      ("opened", c["tweets"][0][7], "reply", {}),
                                      ("failed", c["drafts"][2][2], "post", {"error": "X refused the post: duplicate"}),
                                      ("sent", c["drafts"][0][2], "quote", {"result_id": "1970000000000009998"})]:
        item = store.enqueue(kind, text, "intent", ai_text=text, target=t0 if kind != "post" else None, status=status)
        store.update_outbox(item, sent_at=store.now() if status == "sent" else None, **extra)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--lang", choices=("en", "zh"), default="en")
    ap.add_argument("--port", type=int, default=8799)
    args = ap.parse_args()

    demo = ROOT / "data" / f"demo-{args.lang}"
    shutil.rmtree(demo, ignore_errors=True)
    demo.mkdir(parents=True)
    (demo / ".env").write_text("\n".join([
        "X_AUTH_TOKEN=demo-not-a-real-token", "X_CT0=demo-not-a-real-ct0", "MY_HANDLE=" + ("mia_builds" if args.lang == "en" else "xiaoman_builds"),
        "DISPLAY_NAME=" + ("Mia" if args.lang == "en" else "小满"), "AI_BASE_URL=https://api.openai.com/v1",
        "AI_API_KEY=demo-not-a-real-key", "AI_MODEL=gpt-5.6-mini", f"CONTENT_LANG={args.lang}", f"UI_LANG={args.lang}", "WATCH_ACCOUNTS=nimbusai_demo, orbitlabs_demo",
    ]) + "\n")
    os.environ.update(RADAR_DATA_DIR=str(demo / "data"), RADAR_PROFILE_DIR=str(demo / "profile"),
                      RADAR_LOG_DIR=str(demo / "logs"), RADAR_ENV_FILE=str(demo / ".env"), PORT=str(args.port),
                      AUTO_REFRESH="0", SCRAPE_ON_START="0", RADAR_DEMO="1")
    os.environ.setdefault("OPEN_BROWSER", "1")
    seed(args.lang)
    print(f"Demo ({args.lang}) on http://127.0.0.1:{args.port} — all data is made up.")
    import app
    app.main()


if __name__ == "__main__":
    main()
