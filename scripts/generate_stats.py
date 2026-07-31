#!/usr/bin/env python3
"""Generate the profile README stat cards (assets/github-stats.svg, assets/top-langs.svg).

Fetches stats from the GitHub GraphQL API and renders flat navy SVG cards
matching the hand-made badges in assets/. Stdlib only.
"""

import json
import os
import sys
import urllib.request
from datetime import date, timedelta
from pathlib import Path
from xml.sax.saxutils import escape

LOGIN = os.environ.get("GH_STATS_LOGIN", "vpoonyak")
NAVY = "#0b1f3a"
ACCENT = "#0056b3"
LABEL_COLOR = "#c7d3e3"
VALUE_COLOR = "#6fb1ff"
FONT = "Verdana,Geneva,DejaVu Sans,sans-serif"
CARD_HEIGHT = 195
ASSETS = Path(__file__).resolve().parent.parent / "assets"

QUERY = """
query($login: String!, $after: String) {
  user(login: $login) {
    contributionsCollection {
      totalCommitContributions
      contributionCalendar {
        weeks { contributionDays { date contributionCount } }
      }
    }
    pullRequests { totalCount }
    issues { totalCount }
    repositoriesContributedTo(
      includeUserRepositories: false
      contributionTypes: [COMMIT, PULL_REQUEST, ISSUE, REPOSITORY]
    ) { totalCount }
    repositories(first: 100, after: $after, ownerAffiliations: OWNER, isFork: false) {
      pageInfo { hasNextPage endCursor }
      nodes {
        stargazerCount
        languages(first: 10, orderBy: {field: SIZE, direction: DESC}) {
          edges { size node { name color } }
        }
      }
    }
  }
}
"""


def graphql(token: str, variables: dict) -> dict:
    body = json.dumps({"query": QUERY, "variables": variables}).encode()
    req = urllib.request.Request(
        "https://api.github.com/graphql",
        data=body,
        headers={
            "Authorization": f"bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": LOGIN,
        },
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        payload = json.loads(resp.read())
    if payload.get("errors"):
        raise RuntimeError(f"GraphQL errors: {payload['errors']}")
    return payload["data"]["user"]


def fetch_stats(token: str) -> dict:
    user = graphql(token, {"login": LOGIN, "after": None})
    repos = user["repositories"]["nodes"]
    page = user["repositories"]["pageInfo"]
    while page["hasNextPage"]:
        nxt = graphql(token, {"login": LOGIN, "after": page["endCursor"]})
        repos.extend(nxt["repositories"]["nodes"])
        page = nxt["repositories"]["pageInfo"]

    languages: dict[str, dict] = {}
    for repo in repos:
        for edge in repo["languages"]["edges"]:
            name = edge["node"]["name"]
            entry = languages.setdefault(
                name, {"size": 0, "color": edge["node"]["color"] or "#8b949e"}
            )
            entry["size"] += edge["size"]

    days = [
        d
        for week in user["contributionsCollection"]["contributionCalendar"]["weeks"]
        for d in week["contributionDays"]
        if date.fromisoformat(d["date"]) <= date.today()
    ]
    days.sort(key=lambda d: d["date"])
    streak = 0
    for i, day in enumerate(reversed(days)):
        if day["contributionCount"] > 0:
            streak += 1
        elif i == 0:
            continue  # no contribution yet today doesn't break the streak
        else:
            break

    return {
        "stars": sum(r["stargazerCount"] for r in repos),
        "commits": user["contributionsCollection"]["totalCommitContributions"],
        "prs": user["pullRequests"]["totalCount"],
        "issues": user["issues"]["totalCount"],
        "contributed_to": user["repositoriesContributedTo"]["totalCount"],
        "streak": streak,
        "languages": languages,
    }


def fmt(value: int) -> str:
    return f"{value / 1000:.1f}k" if value >= 1000 else str(value)


def card(width: int, title: str, body: str) -> str:
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{CARD_HEIGHT}" '
        f'viewBox="0 0 {width} {CARD_HEIGHT}" role="img" aria-label="{escape(title)}">'
        f"<title>{escape(title)}</title>"
        f'<g shape-rendering="crispEdges">'
        f'<rect width="{width}" height="{CARD_HEIGHT}" fill="{NAVY}"/>'
        f'<rect x="24" y="50" width="36" height="3" fill="{ACCENT}"/>'
        f"</g>"
        f'<g font-family="{FONT}" text-rendering="geometricPrecision">'
        f'<text x="24" y="40" font-size="14" font-weight="bold" fill="#ffffff" '
        f'letter-spacing="1">{escape(title.upper())}</text>'
        f"{body}</g></svg>\n"
    )


def render_stats_card(stats: dict) -> str:
    rows = [
        ("Stars", fmt(stats["stars"])),
        ("Commits (past year)", fmt(stats["commits"])),
        ("Pull requests", fmt(stats["prs"])),
        ("Issues", fmt(stats["issues"])),
        ("Contributed to", fmt(stats["contributed_to"])),
        ("Current streak", f"{stats['streak']} day" + ("" if stats["streak"] == 1 else "s")),
    ]
    body = ""
    for i, (label, value) in enumerate(rows):
        y = 80 + i * 20
        body += (
            f'<text x="24" y="{y}" font-size="12" fill="{LABEL_COLOR}">{escape(label)}</text>'
            f'<text x="426" y="{y}" font-size="12" font-weight="bold" fill="{VALUE_COLOR}" '
            f'text-anchor="end">{escape(value)}</text>'
        )
    return card(450, f"{LOGIN} - GitHub stats", body)


def render_langs_card(languages: dict) -> str:
    total = sum(lang["size"] for lang in languages.values()) or 1
    top = sorted(languages.items(), key=lambda kv: kv[1]["size"], reverse=True)[:6]
    top_total = sum(lang["size"] for _, lang in top) or 1

    bar_x, bar_width, body = 24, 252, ""
    x = bar_x
    for i, (_, lang) in enumerate(top):
        w = round(bar_width * lang["size"] / top_total)
        if i == len(top) - 1:
            w = bar_x + bar_width - x  # absorb rounding drift
        body += (
            f'<rect x="{x}" y="64" width="{w}" height="10" fill="{lang["color"]}" '
            f'shape-rendering="crispEdges"/>'
        )
        x += w

    for i, (name, lang) in enumerate(top):
        y = 98 + i * 16
        pct = 100 * lang["size"] / total
        body += (
            f'<rect x="24" y="{y - 9}" width="9" height="9" fill="{lang["color"]}" '
            f'shape-rendering="crispEdges"/>'
            f'<text x="39" y="{y}" font-size="11" fill="{LABEL_COLOR}">{escape(name)}</text>'
            f'<text x="276" y="{y}" font-size="11" font-weight="bold" fill="{VALUE_COLOR}" '
            f'text-anchor="end">{pct:.1f}%</text>'
        )
    return card(300, "Top languages", body)


def main() -> None:
    token = os.environ.get("GH_STATS_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if not token:
        sys.exit("Set GH_STATS_TOKEN or GITHUB_TOKEN")
    stats = fetch_stats(token)
    (ASSETS / "github-stats.svg").write_text(render_stats_card(stats))
    (ASSETS / "top-langs.svg").write_text(render_langs_card(stats["languages"]))
    print(f"Wrote github-stats.svg and top-langs.svg for {LOGIN}: "
          f"{ {k: v for k, v in stats.items() if k != 'languages'} }")


if __name__ == "__main__":
    main()
