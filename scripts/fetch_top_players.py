#!/usr/bin/env python3
"""Fetch the top N players of a Kaggle Kaggriculture tournament.

Uses the `kaggle` python package (authenticated via ~/.kaggle/access_token or
kaggle.json / KAGGLE_USERNAME+KAGGLE_KEY). Prints the top N teams ranked by
leaderboard score (name, id, score) and writes them to a JSON file.

Usage:
    python scripts/fetch_top_players.py [--top N] [--competition slug] [--json path]

Example:
    python scripts/fetch_top_players.py --top 3 --json replays/top_players.json

Requires: the kaggle package (`uv pip install kaggle` or `.venv/bin/pip install kaggle`).
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys
from typing import List

import kaggle

COMPETITION = "kaggriculture"


def fetch_leaderboard(api, competition: str, max_teams: int, page_size: int = 200):
    """Yield (team_name, team_id, score) rows from the public leaderboard.

    `competition_leaderboard_view` returns a page sorted by score descending;
    we pull pages until we have at least `max_teams` ranked rows (or run out).
    """
    rows: List[dict] = []
    page_token = None
    for _ in range(100):
        page = api.competition_leaderboard_view(competition, page_size=page_size,
                                                page_token=page_token)
        page = [e for e in (page or []) if e is not None]
        for e in page:
            rows.append({
                "team_name": getattr(e, "team_name", None),
                "team_id": int(getattr(e, "team_id", 0)),
                "score": float(getattr(e, "score", 0) or 0),
                "submission_date": str(getattr(e, "submission_date", "")),
            })
        # Next-page token may be printed by the method / held on the api object.
        nxt = getattr(api, "_leaderboard_next_page_token", None)
        if not nxt:
            break
        page_token = nxt
        if len(rows) >= max_teams:
            break
    return rows


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--top", type=int, default=3, help="number of top players (default 3)")
    ap.add_argument("--competition", default=COMPETITION)
    ap.add_argument("--json", default="", help="write results JSON to this path")
    args = ap.parse_args()

    if args.top < 1:
        ap.error("--top must be >= 1")

    api = kaggle.KaggleApi()
    api.authenticate()

    all_rows = fetch_leaderboard(api, args.competition, args.top)
    if not all_rows:
        print("error: leaderboard returned no rows", file=sys.stderr)
        sys.exit(1)

    # Rows come back sorted by score desc; sort defensively and take the top.
    all_rows.sort(key=lambda r: r["score"], reverse=True)
    top = all_rows[: args.top]

    print(f"Top {len(top)} players of '{args.competition}' (by leaderboard score):\n")
    print(f"{'rank':<5}{'team name':<28}{'team id':<12}{'score':<10}")
    for i, r in enumerate(top, 1):
        name = r["team_name"] or f"(id {r['team_id']})"
        print(f"{i:<5}{name:<28}{r['team_id']:<12}{r['score']:<10.1f}")

    if args.json:
        p = pathlib.Path(args.json)
        p.parent.mkdir(parents=True, exist_ok=True)
        payload = {"competition": args.competition, "top": top}
        with open(p, "w") as f:
            json.dump(payload, f, indent=2)
        print(f"\nwrote -> {p}")


if __name__ == "__main__":
    main()
