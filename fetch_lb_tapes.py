"""Cache our real leaderboard (lb) episode replays from Kaggle.

Every rated episode runs our submitted agent against a real leaderboard
opponent on a real seed. This downloads each episode's FULL replay and stores a
JSON record under ``replays/lb/`` that keeps the complete per-step observation +
action data, so the lb diagnostic (``diagnose_lb.py``) can reuse the exact
analysis machinery in ``diagnose.py`` (``replay_to_summary`` -> build_frames /
build_days / summarize) on **our** seat and on the **opponent's** seat to hunt
system-level inefficiencies. This is the true test of a promoted patch: these
are the games our agent actually played in the wild.

The fetch is resumable: already-cached episodes are skipped by name, so re-running
only pulls what's new. Requires Kaggle credentials (~/.kaggle).

Selection:
    Default (no flags)        -> the single highest-public-score COMPLETE
                                 submission (our current top-scoring submitted
                                 agent). This is the recommended scope.
    --all                    -> every COMPLETE submission that has a public score.
    --ref N [N ...]          -> exactly the given submission refs.

Usage:
    python fetch_lb_tapes.py            # our top-scoring COMPLETE submission
    python fetch_lb_tapes.py --all      # every COMPLETE submission
    python fetch_lb_tapes.py --ref 56227700 --limit 50
    python fetch_lb_tapes.py --list     # show cached tapes
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent  # this file lives at the project root
LB_DIR = ROOT / "replays" / "lb"
OUR_TEAM_ID = 16745419
COMPETITION = "kaggriculture"


def is_complete(sub) -> bool:
    status = getattr(sub, "status", None)
    name = getattr(status, "name", None) if status is not None else None
    if name is None and isinstance(status, str):  # tolerate a plain enum string
        name = status
    return (name or "").upper() == "COMPLETE"


def public_score(sub) -> float:
    """Numeric public score; 0 when absent/unparseable."""
    v = getattr(sub, "public_score", None)
    if v is None:
        return 0.0
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def our_submissions(api) -> list:
    subs = api.competition_submissions(COMPETITION) or []
    return [s for s in subs if is_complete(s) and public_score(s) > 0]


def top_submission(subs: list):
    """Highest-public-score COMPLETE submission (ties -> first found)."""
    return max(subs, key=public_score) if subs else None


def cache_record(api, episode, our_team_id: int = OUR_TEAM_ID,
                 our_ref: int | None = None) -> dict | None:
    """Download one episode and store the full replay + seat metadata.

    Returns ``None`` when our team is absent, the episode is malformed, or the
    download fails; the caller treats that as a resumable skip."""
    agents = [a.to_dict() for a in episode.agents]
    me = next((a for a in agents if a.get("teamId") == our_team_id), None)
    if me is None:
        return None
    opp = next((a for a in agents if a is not me), None)
    if opp is None:
        return None

    with tempfile.TemporaryDirectory() as tmp:
        path = api.competition_episode_replay(episode.id, path=tmp)
        if path is None:
            candidates = list(Path(tmp).glob("*.json"))
            if not candidates:
                return None
            path = str(candidates[0])
        replay = json.loads(Path(path).read_text(encoding="utf-8"))

    seed = int((replay.get("info") or {}).get("seed") or 0)
    names = (replay.get("info") or {}).get("TeamNames") or [None, None]
    return {
        "episode_id": episode.id,
        "our_ref": our_ref,
        "seed": seed,
        "names": names,
        "team_ids": [a.get("teamId") for a in agents],
        "rewards": [float(r) for r in replay["rewards"]],
        "our_seat": agents.index(me),
        "opponent_seat": agents.index(opp),
        "opponent_name": opp.get("teamName"),
        "opponent_team_id": opp.get("teamId"),
        "opponent_reward": float(opp.get("reward") or 0),
        "our_reward": float(me.get("reward") or 0),
        # Full replay: per-step observation+action for BOTH seats. This is what
        # diagnose_lb.py reads. (A separate compact tape path lives in an older
        # revision of this script; the diagnostic needs the full observations.)
        "replay": replay,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--ref", type=int, action="append", default=None,
                    help="submission ref; default = our single top-scoring COMPLETE submission")
    ap.add_argument("--all", action="store_true",
                    help="fetch every COMPLETE submission with a public score")
    ap.add_argument("--team-id", type=int, default=OUR_TEAM_ID,
                    help="team whose seat is recorded as ours (default: this team)")
    ap.add_argument("--out", default=None, help="output dir (default replays/lb)")
    ap.add_argument("--limit", type=int, default=None, help="max new tapes per submission")
    ap.add_argument("--list", action="store_true", help="list cached tapes and exit")
    args = ap.parse_args()

    lb_dir = Path(args.out) if args.out else LB_DIR
    lb_dir.mkdir(parents=True, exist_ok=True)
    if args.list:
        files = sorted(lb_dir.glob("episode-*.json"))
        for f in files:
            d = json.loads(f.read_text(encoding="utf-8"))
            print(f"{f.name}: seed={d['seed']} opp={d['opponent_name']} "
                  f"us={d['our_reward']:,.0f} them={d['opponent_reward']:,.0f}")
        print(f"{len(files)} cached tapes")
        return 0

    from kaggle.api.kaggle_api_extended import KaggleApi

    api = KaggleApi()
    api.authenticate()

    if args.ref:
        refs = args.ref
        print("selection: explicit --ref submissions")
    else:
        subs = our_submissions(api)
        if args.all:
            refs = [s.ref for s in subs]
            print(f"selection: all {len(refs)} COMPLETE submissions")
        else:
            chosen = top_submission(subs)
            if chosen is None:
                print("no COMPLETE submission with a public score found; aborting",
                      file=sys.stderr)
                return 1
            refs = [chosen.ref]
            print(f"selection: top-scoring COMPLETE submission ref={chosen.ref} "
                  f"score={public_score(chosen):.6f}")
    print(f"submissions: {refs}")

    total_new = total_have = 0
    for ref in refs:
        try:
            episodes = api.competition_list_episodes(ref)
        except Exception as exc:  # noqa: BLE001 - one bad ref must not kill the run
            print(f"  FAILED to list episodes for ref {ref}: {exc}", file=sys.stderr)
            continue
        new = have = failed = 0
        for episode in episodes:
            out = lb_dir / f"episode-{episode.id}.json"
            if out.is_file():
                have += 1
                continue
            if args.limit is not None and new >= args.limit:
                break
            try:
                record = cache_record(api, episode, args.team_id, ref)
            except Exception as exc:  # noqa: BLE001 - resumable per-episode failure
                failed += 1
                print(f"  FAILED {episode.id}: {type(exc).__name__}: {exc}", file=sys.stderr)
                continue
            if record is None:
                continue
            out.write_text(json.dumps(record, separators=(",", ":")), encoding="utf-8")
            new += 1
            print(f"  cached {episode.id} opp={record['opponent_name']} "
                  f"({new} new, {len(episodes) - have - new} left)", flush=True)
        print(f"ref {ref}: {new} new, {have} already cached, {failed} failed of {len(episodes)}")
        total_new += new
        total_have += have

    print(f"\n{total_new} new tapes, {total_have} already cached, in {lb_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
