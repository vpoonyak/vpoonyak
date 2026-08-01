#!/usr/bin/env python3
"""Generate the profile README stat cards (assets/github-stats.svg, assets/top-langs.svg).

Fetches stats from the GitHub GraphQL API and renders a "GitHub vitals"
monitor card (ECG-style contribution trace + lab-panel stats) and a top
languages card, both in the flat navy style of the hand-made badges in
assets/. Also appends a daily snapshot to data/*.csv for future trend
charts. Stdlib only.
"""

import json
import os
import sys
import urllib.request
from datetime import date
from pathlib import Path
from xml.sax.saxutils import escape

LOGIN = os.environ.get("GH_STATS_LOGIN", "vpoonyak")
NAVY = "#0b1f3a"
ACCENT = "#0056b3"
LABEL_COLOR = "#a9bcd4"
MUTED = "#7d93b3"
VALUE_COLOR = "#ffffff"
TRACE_COLOR = "#6fb1ff"
HAIRLINE = "#17345a"
GRID = "#122a4d"
FONT = "Verdana,Geneva,DejaVu Sans,sans-serif"
ASSETS = Path(__file__).resolve().parent.parent / "assets"
DATA = Path(__file__).resolve().parent.parent / "data"

# Fixed categorical palette validated for CVD separation and 3:1 contrast on the
# navy surface (dataviz six-checks validator); assigned to languages by rank so
# adjacent bar segments always differ, unlike GitHub's language colors.
PALETTE = ["#3987e5", "#d95926", "#199e70", "#c98500", "#d55181", "#008300"]

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

    languages: dict[str, int] = {}
    for repo in repos:
        for edge in repo["languages"]["edges"]:
            name = edge["node"]["name"]
            languages[name] = languages.get(name, 0) + edge["size"]

    weeks = user["contributionsCollection"]["contributionCalendar"]["weeks"]
    days = [
        d
        for week in weeks
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

    weekly = [
        sum(d["contributionCount"] for d in w["contributionDays"]) for w in weeks
    ]

    return {
        "stars": sum(r["stargazerCount"] for r in repos),
        "commits": user["contributionsCollection"]["totalCommitContributions"],
        "prs": user["pullRequests"]["totalCount"],
        "issues": user["issues"]["totalCount"],
        "repos": len(repos),
        "streak": streak,
        "languages": languages,
        "daily": [(d["date"], d["contributionCount"]) for d in days[-90:]],
        "weekly": weekly,
    }


def fmt(value: int) -> str:
    return f"{value / 1000:.1f}k" if value >= 1000 else str(value)


def render_vitals_card(stats: dict) -> str:
    W, H = 750, 220
    px0, px1, py0, py1 = 24, 452, 72, 184
    rx0, rx1 = 492, 726

    daily = stats["daily"]
    counts = [c for _, c in daily]
    vmax = max(counts + [1])
    n = max(len(daily), 2)

    # ECG grid (recessive, monitor-style)
    plot = ""
    for frac in (1 / 3, 2 / 3):
        gy = round(py0 + (py1 - py0) * frac)
        plot += f'<rect x="{px0}" y="{gy}" width="{px1 - px0}" height="1" fill="{GRID}"/>'
    for i in range(15, len(daily), 15):
        gx = round(px0 + (px1 - px0) * i / (n - 1))
        plot += f'<rect x="{gx}" y="{py0}" width="1" height="{py1 - py0}" fill="{GRID}"/>'
    plot += f'<rect x="{px0}" y="{py1}" width="{px1 - px0}" height="1" fill="{HAIRLINE}"/>'

    # Contribution trace
    pts = []
    for i, (_, c) in enumerate(daily):
        x = px0 + (px1 - px0) * i / (n - 1)
        y = py1 - (py1 - py0 - 8) * c / vmax
        pts.append((round(x, 1), round(y, 1)))
    points = " ".join(f"{x},{y}" for x, y in pts)
    plot += (
        f'<polyline points="{points}" fill="none" stroke="{TRACE_COLOR}" '
        f'stroke-opacity="0.35" stroke-width="2" stroke-linejoin="round" '
        f'stroke-linecap="round"/>'
        f'<polyline class="sweep" points="{points}" fill="none" stroke="{TRACE_COLOR}" '
        f'stroke-width="2" stroke-linejoin="round" stroke-linecap="round" '
        f'pathLength="1000"/>'
    )

    if max(counts, default=0) > 0:
        i_peak = counts.index(max(counts))
        peak_x = min(max(pts[i_peak][0], px0 + 20), px1 - 20)
        plot += (
            f'<text x="{peak_x}" y="{pts[i_peak][1] - 6}" font-size="9" fill="{MUTED}" '
            f'text-anchor="middle">peak {max(counts)}</text>'
        )

    for i, (dstr, _) in enumerate(daily):
        d = date.fromisoformat(dstr)
        if d.day == 1:
            mx = min(max(pts[i][0], px0 + 12), px1 - 12)
            plot += (
                f'<text x="{mx}" y="200" font-size="9" fill="{MUTED}" '
                f'text-anchor="middle">{d.strftime("%b").upper()}</text>'
            )

    # Lab panel: weekly commits vs 52-week reference range
    weekly = stats["weekly"]
    cur_week = weekly[-1] if weekly else 0
    completed = weekly[:-1] if len(weekly) > 1 else weekly
    lo, hi = min(completed, default=0), max(completed, default=0)
    pos = 0.5 if hi == lo else (min(max(cur_week, lo), hi) - lo) / (hi - lo)
    tick_x = round(rx0 + (rx1 - rx0 - 3) * pos)

    panel = (
        f'<text x="{rx0}" y="82" font-size="10" fill="{MUTED}" letter-spacing="1">'
        f"CONTRIB — THIS WEEK</text>"
        f'<text x="{rx1}" y="84" font-size="18" font-weight="bold" fill="{VALUE_COLOR}" '
        f'text-anchor="end">{cur_week}</text>'
        f'<rect x="{rx0}" y="96" width="{rx1 - rx0}" height="4" fill="{GRID}"/>'
        f'<rect x="{tick_x}" y="92" width="3" height="12" fill="{TRACE_COLOR}"/>'
        f'<text x="{rx0}" y="116" font-size="8" fill="{MUTED}">52-WK LOW {lo}</text>'
        f'<text x="{rx1}" y="116" font-size="8" fill="{MUTED}" text-anchor="end">HIGH {hi}</text>'
        f'<rect x="{rx0}" y="126" width="{rx1 - rx0}" height="1" fill="{HAIRLINE}"/>'
        f'<text x="{rx0}" y="145" font-size="10" fill="{MUTED}" letter-spacing="1">'
        f"CURRENT STREAK</text>"
        f'<text x="{rx1}" y="145" font-size="13" font-weight="bold" fill="{TRACE_COLOR}" '
        f'text-anchor="end">{stats["streak"]} day{"" if stats["streak"] == 1 else "s"}</text>'
        f'<rect x="{rx0}" y="156" width="{rx1 - rx0}" height="1" fill="{HAIRLINE}"/>'
    )
    tiles = [
        ("STARS", fmt(stats["stars"])),
        ("PRS", fmt(stats["prs"])),
        ("REPOS", fmt(stats["repos"])),
        ("COMMITS 1Y", fmt(stats["commits"])),
    ]
    for i, (label, value) in enumerate(tiles):
        tx = rx0 + i * 60
        panel += (
            f'<text x="{tx}" y="176" font-size="8" fill="{MUTED}" letter-spacing="1">'
            f"{escape(label)}</text>"
            f'<text x="{tx}" y="196" font-size="16" font-weight="bold" '
            f'fill="{VALUE_COLOR}">{escape(value)}</text>'
        )

    today = date.today().isoformat()
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" '
        f'viewBox="0 0 {W} {H}" role="img" aria-label="{LOGIN} GitHub vitals">'
        f"<title>{LOGIN} — GitHub vitals</title>"
        f"<style>@media (prefers-reduced-motion: no-preference){{"
        f".sweep{{stroke-dasharray:200 800;stroke-dashoffset:200;"
        f"animation:ecg 6s linear infinite;}}}}"
        f"@keyframes ecg{{to{{stroke-dashoffset:-800;}}}}</style>"
        f'<g shape-rendering="crispEdges">'
        f'<rect width="{W}" height="{H}" fill="{NAVY}"/>'
        f'<rect x="24" y="48" width="36" height="3" fill="{ACCENT}"/>'
        f"</g>"
        f'<g font-family="{FONT}" text-rendering="geometricPrecision">'
        f'<text x="24" y="38" font-size="14" font-weight="bold" fill="{VALUE_COLOR}" '
        f'letter-spacing="1">{LOGIN.upper()} — GITHUB VITALS</text>'
        f'<text x="{rx1}" y="38" font-size="9" fill="{MUTED}" text-anchor="end" '
        f'letter-spacing="1">90-DAY TELEMETRY · {today}</text>'
        f'<text x="{px0}" y="64" font-size="9" fill="{MUTED}" letter-spacing="1">'
        f"DAILY CONTRIBUTIONS</text>"
        f"{plot}{panel}</g></svg>\n"
    )


OTHER_COLOR = "#3d5a7e"


def render_langs_card(languages: dict) -> str:
    W, H = 750, 220
    total = sum(languages.values()) or 1
    top = sorted(languages.items(), key=lambda kv: kv[1], reverse=True)[: len(PALETTE)]

    entries = [
        (name, 100 * size / total, PALETTE[i]) for i, (name, size) in enumerate(top)
    ]
    other_pct = 100 - sum(pct for _, pct, _ in entries)
    if len(languages) > len(top):
        entries.append(("Other", other_pct, OTHER_COLOR))

    # Waffle: 10x10 grid, one cell = 1%, cells apportioned by largest remainder
    shares = [pct for _, pct, _ in entries]
    cells = [int(pct) for pct in shares]
    for i in sorted(range(len(shares)), key=lambda i: shares[i] - cells[i], reverse=True):
        if sum(cells) >= 100:
            break
        cells[i] += 1

    wx, wy, cell, gap = 24, 72, 11, 2
    body, k = "", 0
    for i, count in enumerate(cells):
        color = entries[i][2]
        for _ in range(count):
            if k >= 100:
                break
            row, col = divmod(k, 10)
            body += (
                f'<rect x="{wx + col * (cell + gap)}" y="{wy + row * (cell + gap)}" '
                f'width="{cell}" height="{cell}" fill="{color}" shape-rendering="crispEdges"/>'
            )
            k += 1

    # Legend: two columns, percentage right-aligned per column
    cols = [(190, 430), (470, 726)]
    per_col = (len(entries) + 1) // 2
    for i, (name, pct, color) in enumerate(entries):
        cx, cpct = cols[i // per_col]
        y = 88 + (i % per_col) * 30
        ink = MUTED if name == "Other" else LABEL_COLOR
        body += (
            f'<rect x="{cx}" y="{y - 10}" width="10" height="10" fill="{color}" '
            f'shape-rendering="crispEdges"/>'
            f'<text x="{cx + 17}" y="{y}" font-size="11" fill="{ink}">{escape(name)}</text>'
            f'<text x="{cpct}" y="{y}" font-size="12" font-weight="bold" fill="{VALUE_COLOR}" '
            f'text-anchor="end">{pct:.1f}%</text>'
        )

    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" '
        f'viewBox="0 0 {W} {H}" role="img" aria-label="Top languages">'
        f"<title>Top languages</title>"
        f'<g shape-rendering="crispEdges">'
        f'<rect width="{W}" height="{H}" fill="{NAVY}"/>'
        f'<rect x="24" y="48" width="36" height="3" fill="{ACCENT}"/>'
        f"</g>"
        f'<g font-family="{FONT}" text-rendering="geometricPrecision">'
        f'<text x="24" y="38" font-size="14" font-weight="bold" fill="{VALUE_COLOR}" '
        f'letter-spacing="1">TOP LANGUAGES</text>'
        f'<text x="726" y="38" font-size="9" fill="{MUTED}" text-anchor="end" '
        f'letter-spacing="1">BY CODE BYTES · PUBLIC REPOS</text>'
        f'<text x="24" y="64" font-size="9" fill="{MUTED}" letter-spacing="1">'
        f"SHARE OF CODE — 1 CELL = 1%</text>"
        f"{body}</g></svg>\n"
    )


def append_history(stats: dict) -> None:
    DATA.mkdir(exist_ok=True)
    today = date.today().isoformat()

    stats_csv = DATA / "stats-history.csv"
    header = "date,stars,commits_past_year,pull_requests,issues,public_repos,streak"
    lines = stats_csv.read_text().splitlines() if stats_csv.exists() else [header]
    lines = [l for l in lines if l and not l.startswith(today + ",")]
    lines.append(
        f"{today},{stats['stars']},{stats['commits']},{stats['prs']},"
        f"{stats['issues']},{stats['repos']},{stats['streak']}"
    )
    stats_csv.write_text("\n".join(lines) + "\n")

    lang_csv = DATA / "lang-history.csv"
    lines = lang_csv.read_text().splitlines() if lang_csv.exists() else ["date,language,bytes"]
    lines = [l for l in lines if l and not l.startswith(today + ",")]
    for name, size in sorted(stats["languages"].items(), key=lambda kv: -kv[1]):
        lines.append(f"{today},{name},{size}")
    lang_csv.write_text("\n".join(lines) + "\n")


def main() -> None:
    token = os.environ.get("GH_STATS_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if not token:
        sys.exit("Set GH_STATS_TOKEN or GITHUB_TOKEN")
    stats = fetch_stats(token)
    (ASSETS / "github-stats.svg").write_text(render_vitals_card(stats))
    (ASSETS / "top-langs.svg").write_text(render_langs_card(stats["languages"]))
    append_history(stats)
    print(f"Wrote cards and history for {LOGIN}: "
          f"{ {k: v for k, v in stats.items() if k not in ('languages', 'daily', 'weekly')} }")


if __name__ == "__main__":
    main()
