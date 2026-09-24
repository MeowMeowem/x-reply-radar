"""Who is worth following back.

Someone who asks for follow-backs but follows far fewer people than follow them is not
really following back. Excluded, with the reason shown:
  already_following, self, protected,
  ratio          followers > following x FOLLOW_MAX_RATIO
  few_following  following < FOLLOW_MIN_FOLLOWING
  few_posts      posts < FOLLOW_MIN_POSTS (empty or throwaway accounts)
"""
import re

import config


def keywords(e) -> list[str]:
    return [k.strip() for k in re.split(r"[,，\n]+", e.get("FOLLOW_KEYWORDS") or "") if k.strip()][:12]


def ratio(u) -> float:
    return round(u["followers"] / max(1, u["following"]), 2)


def evaluate(u, e):
    """(eligible, reason, detail) for one user."""
    me = config.handle(e).lower()
    if u["following_now"]:
        return False, "already_following", ""
    if me and u["handle"].lower() == me:
        return False, "self", ""
    if u["protected"]:
        return False, "protected", ""
    max_ratio = config.get_float(e, "FOLLOW_MAX_RATIO")
    if u["followers"] > u["following"] * max_ratio:
        return False, "ratio", f"{ratio(u):g}"
    if u["following"] < config.get_int(e, "FOLLOW_MIN_FOLLOWING"):
        return False, "few_following", str(u["following"])
    if u["posts"] < config.get_int(e, "FOLLOW_MIN_POSTS"):
        return False, "few_posts", str(u["posts"])
    return True, "", ""


def split(users, e):
    """(eligible, excluded) with `reason` / `detail` / `ratio` / `diff` added; people who already follow you first."""
    ok, out = [], []
    for u in users:
        good, reason, detail = evaluate(u, e)
        u = {**u, "reason": reason, "detail": detail, "ratio": ratio(u), "diff": u["following"] - u["followers"]}
        (ok if good else out).append(u)
    ok.sort(key=lambda u: (not u["followed_by"], -u["diff"]))
    return ok, out
