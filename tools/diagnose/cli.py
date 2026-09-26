"""diagnose.cli — the harness entry point (``python -m tools.diagnose``).

Three things, and only three:

  * **run** the agent under test (the ``src`` package) against public opponents,
    in parallel, and write replays + ``games.csv`` + per-day CSVs;
  * **--replay-dir**: re-diagnose saved replays into those same CSVs without
    re-running any game (``--lb`` for leaderboard replays, which carry no seed);
  * **--graph / --animals**: render the dashboards, farm-board GIFs and the
    animal-care payback chart from saved replays.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from .agents import public_agent_names
from .analysis import _agent_seat, replay_to_summary
from .config import PUBLIC_AGENT_MAP
from .games import load_replay
from .parallel import run_labeled_batch
from .plot import graph_batch, plot_animal_care_payback
from .render import render
from .report import print_game_table, write_run_csv
from .runbook import _most_recent_run_dir, _new_run_dir, _parse_pa_arg


def _check_pa(pa_indices):
    for pa in pa_indices:
        if pa not in PUBLIC_AGENT_MAP:
            print(f"Unknown public agent #{pa}. Available:\n{public_agent_names()}")
            sys.exit(1)


def _process_replay_dir(run_dir: Path, paths, args, render_verbose: bool = True):
    """Diagnose one directory of saved replays: write the run CSVs, print the
    per-game summary table, and (single-dir) honour --render or --graph."""
    if not args.graph:
        rows = write_run_csv(run_dir, paths, workers=getattr(args, "workers", None),
                             lb=getattr(args, "lb", False))
        print(f"\nPer-game summary ({run_dir})  —  {len(rows)} games:")
        print_game_table(rows)
        if args.render and paths and render_verbose:
            replay = load_replay(paths[-1])
            frames, days, _ = replay_to_summary(replay, seat=_agent_seat(replay))
            print(f"\n--- rendered: {paths[-1].name} ---")
            render(days, frames)
    if args.graph and paths:
        print(f"\nRendering PNG dashboards + farm GIFs into {run_dir}:")
        graph_batch(paths, run_dir, gif_fps=args.gif_fps)


def cli():
    parser = argparse.ArgumentParser(description="Kaggriculture diagnostic harness")
    parser.add_argument("--scratch", action="store_true",
                        help="Run the agent under test (src/). This is the default and "
                             "the only agent; the flag is kept for explicit scripts.")
    parser.add_argument("--pa", default="1", help="Public agent indices, e.g. 1,2,3 or 1-3")
    parser.add_argument("--batch", type=int, default=1, help="Number of seeds per opponent")
    parser.add_argument("--seed", type=int, default=None,
                        help="Fixed seed for a deterministic run (used verbatim: seed, seed+1, ...)")
    parser.add_argument("--run-dir", help="Directory to save replays (default: next diag-replays/run-N)")
    parser.add_argument("--workers", type=int, default=None,
                        help="Parallel workers for game execution (default: all cores)")
    parser.add_argument("--replay-dir", help="Diagnose saved replays instead of running games")
    parser.add_argument("--lb", action="store_true",
                        help="Leaderboard mode: local leaderboard replays carry no seed, so key "
                             "each per-day CSV on the episode id from the filename and label seats "
                             "with the real team names from info.TeamNames")
    parser.add_argument("--render", action="store_true",
                        help="Print the full day-by-day report for the last replay")
    parser.add_argument("--graph", action="store_true",
                        help="Render per-game dashboard PNG + animated farm-board GIF from saved replays")
    parser.add_argument("--animals", action="store_true",
                        help="Render the season-constant animal CARE payback chart "
                             "(fed-only vs fed+cared cumulative cash) as animal_care_payback.png")
    parser.add_argument("--gif-fps", type=float, default=1.5,
                        help="Farm-board GIF playback speed in frames/sec (default 1.5 ≈ 0.67s/day; "
                             "raise to 4-5 for a quicker skim)")
    args = parser.parse_args()

    # ---- graph-only modes: no games are run, replays are read from disk -------
    if args.animals:
        out_dir = Path(args.run_dir or ".")
        out_dir.mkdir(parents=True, exist_ok=True)
        chart = plot_animal_care_payback(out_dir / "animal_care_payback.png")
        if chart:
            print(f"  wrote {chart.name}")
        return

    if args.replay_dir or args.graph:
        auto_picked = not args.replay_dir
        run_dir = Path(args.replay_dir) if args.replay_dir else _most_recent_run_dir()
        if run_dir is None:
            print("No replay dir found; pass --replay-dir <dir>.")
            return
        paths = sorted(run_dir.glob("*.json"))
        if not paths:
            # No replays directly here — likely a tree of batches. Recurse and
            # process every leaf dir that holds replays.
            leaves = {}
            for p in sorted(run_dir.rglob("*.json")):
                leaves.setdefault(p.parent, []).append(p)
            if not leaves:
                print(f"No replay JSONs found in {run_dir} (directly or in subdirs)")
                return
            for sub in sorted(leaves):
                print(f"\n{'=' * 66}\n  {sub.relative_to(run_dir)} — {len(leaves[sub])} replays"
                      f"\n{'=' * 66}")
                _process_replay_dir(sub, leaves[sub], args, render_verbose=False)
            return
        # Bare `--graph` must not silently render a huge default dir — ask for an
        # explicit --replay-dir instead.
        if args.graph and auto_picked and len(paths) > 8:
            print(f"auto-picked {run_dir} has {len(paths)} replays; pass --replay-dir "
                  f"{run_dir} explicitly to graph them (or cap it).")
            return
        _process_replay_dir(run_dir, paths, args)
        return

    # ---- the vanilla run -----------------------------------------------------
    pa_indices = _parse_pa_arg(args.pa)
    _check_pa(pa_indices)

    run_dir = Path(args.run_dir) if args.run_dir else _new_run_dir()
    print(f"Saving replays to {run_dir}  (workers={args.workers or os.cpu_count()})")

    saved, _seeds = run_labeled_batch(pa_indices, args.batch, run_dir, seed=args.seed,
                                      workers=args.workers, label="scratch")
    rows = write_run_csv(run_dir, saved, workers=args.workers)
    print("\nPer-game summary:")
    print_game_table(rows)

    if args.render and saved:
        sample = saved[-1]
        replay = load_replay(sample)
        frames, days, _ = replay_to_summary(replay, seat=_agent_seat(replay))
        print(f"\n--- rendered: {sample.name} ---")
        render(days, frames)


if __name__ == "__main__":
    cli()
