#!/usr/bin/env python3
"""Builds gaming-style GitHub + LeetCode stat cards as self-contained SVGs.

Run by .github/workflows/stats.yml. Uses only the Python standard library.
  python scripts/update_cards.py          -> fetch live data and write cards
  python scripts/update_cards.py --seed   -> write empty 'awaiting sync' cards
"""
import html
import json
import math
import os
import sys
import urllib.request
from pathlib import Path

GH_USER = os.environ.get("PROFILE_USER", "arghasoni")
LC_USER = os.environ.get("LEETCODE_USER", "arghasoni")
TOKEN = os.environ.get("GH_TOKEN", "")
OUT = Path(os.environ.get("CARD_OUT", Path(__file__).resolve().parent.parent / "assets"))
esc = html.escape
MONO = "'Courier New',monospace"


# ------------------------------------------------------------------ fetching
def post_json(url, payload, headers):
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", **headers},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.load(resp)


def fetch_github():
    query = """
    query($login: String!) {
      user(login: $login) {
        followers { totalCount }
        pullRequests { totalCount }
        issues { totalCount }
        repositories(ownerAffiliations: OWNER, isFork: false, first: 100, privacy: PUBLIC) {
          totalCount
          nodes {
            stargazerCount
            languages(first: 6, orderBy: {field: SIZE, direction: DESC}) {
              edges { size node { name color } }
            }
          }
        }
        contributionsCollection {
          totalCommitContributions
          contributionCalendar { totalContributions }
        }
      }
    }"""
    data = post_json(
        "https://api.github.com/graphql",
        {"query": query, "variables": {"login": GH_USER}},
        {"Authorization": f"bearer {TOKEN}", "User-Agent": "profile-cards"},
    )
    if "errors" in data:
        raise RuntimeError(data["errors"])
    u = data["data"]["user"]
    langs = {}
    for repo in u["repositories"]["nodes"]:
        for edge in repo["languages"]["edges"]:
            name = edge["node"]["name"]
            cur = langs.setdefault(name, {"size": 0, "color": edge["node"]["color"] or "#8b95a8"})
            cur["size"] += edge["size"]
    top = sorted(langs.items(), key=lambda kv: kv[1]["size"], reverse=True)[:5]
    total = sum(v["size"] for _, v in top) or 1
    return {
        "stars": sum(r["stargazerCount"] for r in u["repositories"]["nodes"]),
        "commits": u["contributionsCollection"]["totalCommitContributions"],
        "prs": u["pullRequests"]["totalCount"],
        "issues": u["issues"]["totalCount"],
        "repos": u["repositories"]["totalCount"],
        "followers": u["followers"]["totalCount"],
        "contribs": u["contributionsCollection"]["contributionCalendar"]["totalContributions"],
        "langs": [(n, v["color"], v["size"] / total) for n, v in top],
    }


def fetch_leetcode():
    query = """
    query userStats($username: String!) {
      allQuestionsCount { difficulty count }
      matchedUser(username: $username) {
        profile { ranking }
        submitStats { acSubmissionNum { difficulty count } }
      }
      userContestRanking(username: $username) { rating attendedContestsCount }
    }"""
    data = post_json(
        "https://leetcode.com/graphql",
        {"query": query, "variables": {"username": LC_USER}},
        {
            "Referer": f"https://leetcode.com/u/{LC_USER}/",
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/124 Safari/537.36",
        },
    )
    d = data["data"]
    if not d.get("matchedUser"):
        raise RuntimeError("LeetCode user not found")
    solved = {x["difficulty"]: x["count"] for x in d["matchedUser"]["submitStats"]["acSubmissionNum"]}
    total = {x["difficulty"]: x["count"] for x in d["allQuestionsCount"]}
    contest = d.get("userContestRanking") or {}
    return {
        "solved": solved,
        "total": total,
        "rank": d["matchedUser"]["profile"].get("ranking"),
        "rating": round(contest["rating"]) if contest.get("rating") else None,
        "contests": contest.get("attendedContestsCount"),
    }


# ----------------------------------------------------------------- rendering
def fmt(n):
    return "--" if n is None else f"{n:,}"


def frame(w, h, title, accent, right_text, body, label):
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}" role="img" aria-label="{esc(label)}">
<defs>
  <linearGradient id="neon" x1="0" x2="1"><stop offset="0" stop-color="#00f0ff"/><stop offset=".5" stop-color="#b44cff"/><stop offset="1" stop-color="#ff2e88"/></linearGradient>
  <pattern id="scan" width="4" height="4" patternUnits="userSpaceOnUse"><rect width="4" height="1" fill="#000" fill-opacity=".22"/></pattern>
  <clipPath id="frame"><rect width="{w}" height="{h}" rx="14"/></clipPath>
</defs>
<g clip-path="url(#frame)">
<rect width="{w}" height="{h}" fill="#0b0f1a"/>
<rect width="{w}" height="{h}" fill="url(#scan)"/>
<rect x="0" y="-4" width="{w}" height="3" fill="url(#neon)" opacity=".4"><animate attributeName="y" values="-4;{h}" dur="5s" repeatCount="indefinite"/></rect>
<rect x="0" y="{h-5}" width="{w}" height="5" fill="url(#neon)"><animate attributeName="opacity" values=".5;1;.5" dur="2.5s" repeatCount="indefinite"/></rect>
</g>
<rect x=".5" y=".5" width="{w-1}" height="{h-1}" rx="14" fill="none" stroke="{accent}" stroke-opacity=".55"/>
<text x="24" y="36" font-family="{MONO}" font-size="18" font-weight="700" fill="{accent}" letter-spacing="3">▌{esc(title)}</text>
<text x="{w-24}" y="36" text-anchor="end" font-family="{MONO}" font-size="12" fill="#8b95a8" letter-spacing="1">{esc(right_text)}</text>
{body}
</svg>'''


def render_github(d):
    seed = d is None
    keys = [("STARS EARNED", "stars"), ("COMMITS (1Y)", "commits"), ("PULL REQUESTS", "prs"),
            ("ISSUES", "issues"), ("PUBLIC REPOS", "repos"), ("FOLLOWERS", "followers")]
    body = []
    for i, (label, key) in enumerate(keys):
        x = 24 + (i % 3) * 150
        y = 70 + (i // 3) * 54
        val = fmt(None if seed else d[key])
        body.append(f'<text x="{x}" y="{y}" font-family="{MONO}" font-size="11" fill="#8b95a8" letter-spacing="2">{label}</text>'
                    f'<text x="{x}" y="{y+26}" font-family="{MONO}" font-size="24" font-weight="700" fill="#ffffff">{val}</text>')
    # languages
    body.append(f'<text x="24" y="182" font-family="{MONO}" font-size="11" fill="#8b95a8" letter-spacing="2">TOP LANGUAGES</text>')
    body.append('<clipPath id="lc"><rect x="24" y="190" width="432" height="10" rx="3"><animate attributeName="width" values="0;432;432;0" keyTimes="0;.15;.9;1" dur="9s" repeatCount="indefinite"/></rect></clipPath>')
    body.append('<rect x="24" y="190" width="432" height="10" rx="3" fill="#161b22" stroke="#00f0ff" stroke-opacity=".3"/>')
    if not seed:
        x = 24.0
        lx = 24.0
        segs, legend = [], []
        for j, (name, color, share) in enumerate(d["langs"]):
            name = {"Jupyter Notebook": "Jupyter"}.get(name, name)
            w = 432 * share
            segs.append(f'<rect x="{x:.1f}" y="190" width="{w:.1f}" height="10" fill="{esc(color)}"/>')
            label = f"{name} {share*100:.0f}%"
            legend.append(f'<rect x="{lx:.0f}" y="208" width="8" height="8" fill="{esc(color)}"/>'
                          f'<text x="{lx+12:.0f}" y="216" font-family="{MONO}" font-size="10" fill="#c9d1d9">{esc(label)}</text>')
            lx += 12 + len(label) * 6.1 + 12
            x += w
        body.append(f'<g clip-path="url(#lc)">{"".join(segs)}</g>')
        body.append("".join(legend))
    right = "AWAITING FIRST SYNC" if seed else f'{d["contribs"]:,} CONTRIBS / YR'
    return frame(480, 232, f"GITHUB · {GH_USER.upper()}", "#00f0ff", right, "".join(body),
                 "GitHub stats for " + GH_USER)


def render_leetcode(d):
    seed = d is None
    cx, cy, r, sw = 92, 126, 50, 11
    circ = 2 * math.pi * r
    colors = {"Easy": "#00b8a3", "Medium": "#ffc01e", "Hard": "#ff375f"}
    body = [f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="none" stroke="#161b22" stroke-width="{sw}"/>']
    solved_all = None if seed else d["solved"].get("All", 0)
    if not seed and solved_all:
        start = 0.0
        for diff in ("Easy", "Medium", "Hard"):
            share = d["solved"].get(diff, 0) / solved_all
            seg = circ * share
            if seg > 0:
                body.append(f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="none" stroke="{colors[diff]}" stroke-width="{sw}" '
                            f'stroke-dasharray="{seg:.2f} {circ-seg:.2f}" stroke-dashoffset="{-start:.2f}" transform="rotate(-90 {cx} {cy})">'
                            f'<animate attributeName="stroke-dasharray" values="0 {circ:.2f};{seg:.2f} {circ-seg:.2f};{seg:.2f} {circ-seg:.2f};0 {circ:.2f}" '
                            f'keyTimes="0;.15;.9;1" dur="9s" repeatCount="indefinite"/></circle>')
            start += seg
    body.append(f'<text x="{cx}" y="{cy+8}" text-anchor="middle" font-family="{MONO}" font-size="28" font-weight="700" fill="#ffffff">{fmt(solved_all)}</text>'
                f'<text x="{cx}" y="{cy+26}" text-anchor="middle" font-family="{MONO}" font-size="10" fill="#8b95a8" letter-spacing="2">SOLVED</text>')
    for i, diff in enumerate(("Easy", "Medium", "Hard")):
        y = 80 + i * 40
        s = None if seed else d["solved"].get(diff, 0)
        t = None if seed else d["total"].get(diff, 0)
        w = 0 if seed or not t else round(100 * s / t, 1)
        c = colors[diff]
        body.append(f'<text x="176" y="{y+10}" font-family="{MONO}" font-size="13" fill="{c}" letter-spacing="1">{diff.upper()}</text>'
                    f'<rect x="256" y="{y}" width="100" height="12" fill="#161b22" stroke="{c}" stroke-opacity=".4"/>'
                    f'<rect x="256" y="{y}" width="{w}" height="12" fill="{c}"><animate attributeName="width" values="0;{w};{w};0" keyTimes="0;.18;.9;1" dur="9s" begin="{i*0.25}s" repeatCount="indefinite"/></rect>'
                    f'<text x="456" y="{y+10}" text-anchor="end" font-family="{MONO}" font-size="12" fill="#c9d1d9">{fmt(s)} / {fmt(t)}</text>')
    foot = []
    if not seed and d.get("rank"):
        foot.append(f"GLOBAL RANK #{d['rank']:,}")
    if not seed and d.get("rating"):
        foot.append(f"CONTEST {d['rating']}")
    if foot:
        body.append(f'<text x="176" y="212" font-family="{MONO}" font-size="12" fill="#ffc01e" letter-spacing="1">{esc("  ·  ".join(foot))}</text>')
    right = "AWAITING FIRST SYNC" if seed else "DSA GRIND"
    return frame(480, 232, f"LEETCODE · {LC_USER.upper()}", "#ffc01e", right, "".join(body),
                 "LeetCode stats for " + LC_USER)


# ---------------------------------------------------------------------- main
def write(name, svg):
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / name).write_text(svg, encoding="utf-8")
    print(f"wrote {name}")


def main():
    if "--seed" in sys.argv:
        write("github-stats.svg", render_github(None))
        write("leetcode.svg", render_leetcode(None))
        return
    jobs = [("github-stats.svg", fetch_github, render_github), ("leetcode.svg", fetch_leetcode, render_leetcode)]
    for name, fetch, render in jobs:
        try:
            write(name, render(fetch()))
        except Exception as exc:  # keep the previous card if a source is down
            print(f"WARNING: could not refresh {name}: {exc}")
            if not (OUT / name).exists():
                write(name, render(None))


if __name__ == "__main__":
    main()
