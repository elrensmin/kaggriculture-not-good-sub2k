#!/usr/bin/env python3
"""Pull a team's top-scoring submission — and its episode replays — into replays/<team_name>/.

Uses the `kaggle` python package (authenticated via ~/.kaggle/access_token or
kaggle.json / KAGGLE_USERNAME+KAGGLE_KEY). Unlike the raw submission *.py file
(which Kaggle does not serve to others), a team's **episode replays** are public
and downloadable individually — via the same data behind a leaderboard URL like
https://www.kaggle.com/competitions/kaggriculture/leaderboard?submissionId=...&episodeId=...

For each requested team id it:
  1. resolves the team name,
  2. lists the team's public submissions and picks the highest `public_score`,
  3. lists that submission's episodes,
  4. downloads the replay of the selected episode(s) into replays/<team_name>/,
  5. writes replays/<team_name>/index.json (submission id + episode list).

Episode replay selection:
  --episodes latest   download only the most recent completed episode (default)
  --episodes N        download the N most recent completed episodes
  --episodes all      download every completed episode (can be many / large)
  --episode ID        download one specific episode id

Usage:
    python tools/pull_top_submissions.py --team 16732748 --team 16730612
    python tools/pull_top_submissions.py --top 3 --episodes all --out replays
    python tools/pull_top_submissions.py --submission 56468867 --episode 112413080

Requires: the kaggle package (`uv pip install kaggle` or `.venv/bin/pip install kaggle`).
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import os
import pathlib
import re
import sys
import tempfile
import zipfile

import kaggle

COMPETITION = "kaggriculture"


def slugify(name: str) -> str:
    s = re.sub(r"[^A-Za-z0-9._-]+", "_", name or "team").strip("._")
    return s or "team"


def is_completed(ep) -> bool:
    return str(getattr(ep, "state", "")).endswith("COMPLETED")


def fetch_id_name_map(api, competition: str) -> dict:
    """Map team_id -> team_name for every leaderboard team from the standings CSV."""
    mapping = {}
    with tempfile.TemporaryDirectory() as d:
        api.competition_leaderboard_download(competition, path=d, quiet=True)
        z = pathlib.Path(d) / f"{competition}.zip"
        if not z.exists():
            return mapping
        zf = zipfile.ZipFile(z)
        for n in zf.namelist():
            if not n.endswith(".csv"):
                continue
            for row in csv.DictReader(io.TextIOWrapper(zf.open(n), encoding="utf-8-sig")):
                try:
                    mapping[int(row["TeamId"])] = row["TeamName"]
                except (KeyError, ValueError):
                    continue
    return mapping


def resolve(api, comp: str, args) -> list:
    """Return a list of (team_id, submission_id, team_name) to pull.

    Determined from --team ids, --top N, or a direct --submission id."""
    target = []
    if args.submission:
        name = (args.name or slugify(f"subm_{args.submission}"))
        target.append((None, int(args.submission), args.name or f"submission_{args.submission}"))
    if args.team or args.top:
        if not args.team:
            # --top N: take the N highest-score teams from the leaderboard.
            rows = []
            page = api.competition_leaderboard_view(comp, page_size=200, page_token=None)
            for e in (page or []):
                if e is None:
                    continue
                rows.append((int(getattr(e, "team_id", 0)), float(getattr(e, "score", 0) or 0)))
            rows.sort(key=lambda x: x[1], reverse=True)
            args.team = [tid for tid, _ in rows[: args.top]]
        name_map = fetch_id_name_map(api, comp)
        for team_id in args.team:
            subs = api.competition_team_submissions(int(team_id)) or []
            if not subs:
                print(f"! team {team_id}: no public submissions; skipping")
                continue
            top = max(subs, key=lambda s: float(getattr(s, "public_score", 0) or 0))
            subm_id = int(getattr(top, "id", 0))
            name = name_map.get(team_id) or f"team_{team_id}"
            target.append((int(team_id), subm_id, name))
    return target


def choose_episodes(epis, args):
    """Select which completed episodes to download, per --episode/--episodes."""
    if args.episode:
        for e in epis:
            if int(getattr(e, "id", 0)) == args.episode:
                return [e]
        print(f"! episode {args.episode} not found in this submission's episodes")
        return []
    completed = [e for e in epis if is_completed(e)]
    mode = args.episodes
    if mode == "latest":
        return completed[:1]
    if mode == "all":
        return completed
    # numeric N -> last N completed (most recent first)
    n = int(mode)
    return completed[: max(0, n)]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--team", type=int, action="append", help="team id (repeatable)")
    ap.add_argument("--top", type=int, default=0, help="pull the top N leaderboard teams instead of --team")
    ap.add_argument("--submission", type=int, default=0, help="pull episodes for a direct submission id")
    ap.add_argument("--name", default="", help="team/submission name for the folder (with --submission)")
    ap.add_argument("--episodes", default="latest",
                    help="'latest' | 'all' | <N> (default latest)")
    ap.add_argument("--episode", type=int, default=0, help="download one specific episode id")
    ap.add_argument("--competition", default=COMPETITION)
    ap.add_argument("--out", default="replays", help="output root (default replays)")
    args = ap.parse_args()

    if not (args.team or args.top or args.submission):
        ap.error("provide --team <id> (repeatable), --top <n>, or --submission <id>")
    if args.episode and args.episodes != "latest":
        ap.error("use only one of --episode / --episodes")

    api = kaggle.KaggleApi()
    api.authenticate()
    out_root = pathlib.Path(args.out)

    for team_id, subm_id, name in resolve(api, args.competition, args):
        team_dir = out_root / slugify(name)
        team_dir.mkdir(parents=True, exist_ok=True)

        try:
            epis = api.competition_list_episodes(subm_id) or []
        except Exception as ex:  # noqa: BLE001
            print(f"! {name}: can't list episodes for submission {subm_id}: {ex}")
            continue

        picked = choose_episodes(epis, args)
        if not picked:
            print(f"! {name} (subm {subm_id}): no matching COMPLETED episodes")
            continue

        downloaded = []
        failed = []
        for ep in picked:
            eid = int(getattr(ep, "id", 0))
            try:
                api.competition_episode_replay(eid, path=str(team_dir), quiet=False)
                downloaded.append(eid)
            except Exception as ex:  # noqa: BLE001
                print(f"!   episode {eid} download failed: {ex}")
                failed.append(eid)

        index = {
            "team_id": team_id,
            "team_name": name,
            "submission_id": subm_id,
            "total_episodes": len(epis),
            "downloaded_episodes": downloaded,
            "failed_episodes": failed,
        }
        (team_dir / "index.json").write_text(json.dumps(index, indent=2))
        print(f"  {name:<24} (subm {subm_id}): {len(downloaded)}/{len(picked)} episodes -> {team_dir}")

    print(f"\ndone -> {out_root}/")
    print("(each episode is a full game replay; open replays/<team_name>/episode-<id>-replay.json)")


if __name__ == "__main__":
    main()
