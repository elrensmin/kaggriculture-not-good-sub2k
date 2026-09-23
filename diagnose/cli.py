"""diagnose.cli — argparse entry point for the harness (python -m diagnose)."""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import diagnose.config as _cfg
from diagnose.agents import public_agent_names
from diagnose.analysis import _agent_seat, game_summary, replay_to_summary
from diagnose.batch import compare_batch
from diagnose.config import PUBLIC_AGENT_MAP, _E1_DEFAULT
from diagnose.games import load_replay
from diagnose.grid import grid_search
from diagnose.parallel import run_labeled_batch
from diagnose.paired import ab_delta_report
from diagnose.plot import graph_batch, plot_animal_care_payback
from diagnose.render import render
from diagnose.report import narrative_summary, print_game_table, write_run_csv
from diagnose.runbook import _most_recent_run_dir, _new_run_dir, _parse_pa_arg, _make_seeds
from diagnose.xray import xray_batch


def _process_replay_dir(run_dir: Path, paths, args, render_verbose: bool = True):
    """Diagnose one directory of saved replay JSONs: write the run CSVs, print the
    per-game summary table, honour --compare, and (single-dir) --render or --graph.
    In tree mode (render_verbose=False) we skip the verbose per-replay day dump so
    a grid of subdirs stays a quick stats read."""
    if not args.graph:
        rows = write_run_csv(run_dir, paths, workers=getattr(args, "workers", None),
                             lb=getattr(args, "lb", False))
        print(f"\nPer-game summary ({run_dir})  —  {len(rows)} games:")
        print_game_table(rows)
        if args.compare and paths:
            ab_delta_report(paths, per_day=args.render)
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
    parser.add_argument("--old", action="store_true", help="Run the old/main.py agent")
    parser.add_argument("--new", action="store_true",
                        help="Run main.py patched with agent.py (runs everything in main + patch)")
    parser.add_argument("--compare", action="store_true", help="A/B old vs new on the same seeds")
    parser.add_argument("--grid", action="store_true",
                        help="Sweep the agent.py param space via paired compare; writes grid/grid.csv")
    parser.add_argument("--exp", default="floor", choices=("e1", "floor", "grow", "wool"),
                        help="Which experiment's param space/target/guards --grid uses (e1 | floor | grow | wool)")
    parser.add_argument("--grid-params", default=None,
                        help="Param space for --grid (e.g. 'price_frac=[0,0.3,0.6,1.0];hold_cap=[0,10,20,40]')")
    parser.add_argument("--workers", type=int, default=None,
                        help="Parallel workers for --grid game execution (default: all cores)")
    parser.add_argument("--pa", default="1", help="Public agent indices, e.g. 1,2,3 or 1-3")
    parser.add_argument("--batch", type=int, default=1, help="Number of seeds per opponent")
    parser.add_argument("--seed", type=int, default=None,
                        help="Fixed seed for a deterministic run (used verbatim: seed, seed+1, ...)")
    parser.add_argument("--run-dir", help="Directory to save replays (default: next diag-replays/run-N)")
    parser.add_argument("--replay-dir", help="Diagnose saved replays instead of running games")
    parser.add_argument("--lb", action="store_true",
                        help="Leaderboard mode: local leaderboard replays carry no seed, so key "
                             "each per-day CSV on the episode id from the filename and label seats "
                             "with the real team names from info.TeamNames")
    parser.add_argument("--render", action="store_true", help="Print full day-by-day report for the last replay")
    parser.add_argument("--llm", action="store_true", help="Write per-game narrative .md files")
    parser.add_argument("--xray", action="store_true",
                        help="Investigate a patch: per-step patch() moves, old-vs-new action "
                             "divergence, and day-by-day money for the same seed")
    parser.add_argument("--graph", action="store_true",
                        help="Render per-game dashboard PNG + animated farm-board GIF from saved replays")
    parser.add_argument("--animals", action="store_true",
                        help="Render the season-constant animal CARE payback chart "
                             "(fed-only vs fed+cared cumulative cash) as animal_care_payback.png")
    parser.add_argument("--gif-fps", type=float, default=1.5,
                        help="Farm-board GIF playback speed in frames/sec (default 1.5 ≈ 0.67s/day; "
                             "raise to 4-5 for a quicker skim)")
    args = parser.parse_args()

    if args.grid:
        if not (args.pa and args.batch >= 2):
            print("--grid needs --pa N and --batch >= 2 (SE must be estimable).")
            return
        pa_indices = _parse_pa_arg(args.pa)
        for pa in pa_indices:
            if pa not in PUBLIC_AGENT_MAP:
                print(f"Unknown public agent #{pa}. Available:\n{public_agent_names()}")
                sys.exit(1)
        global _GRID_WORKERS
        _cfg._GRID_WORKERS = args.workers
        run_dir = Path(args.run_dir) if args.run_dir else _new_run_dir()
        print(f"Grid replays -> {run_dir}  (workers={_cfg._GRID_WORKERS or os.cpu_count()})")
        grid_search(pa_indices, args.batch, run_dir, seed=args.seed, spec=args.grid_params, exp=args.exp)
        return

    if args.replay_dir or (args.graph and not args.old and not args.new and not args.compare
                           and not args.xray):
        auto_picked = not args.replay_dir
        run_dir = Path(args.replay_dir) if args.replay_dir else _most_recent_run_dir()
        if run_dir is None:
            print("No replay dir found; pass --replay-dir <dir>.")
            return
        paths = sorted(run_dir.glob("*.json"))
        if not paths:
            # No replays directly here — likely a tree of batches (grid/: baseline/,
            # combo0/, combo1/, ...). Recurse and process every leaf dir with replays.
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
        # Bare `--graph` must not silently render a huge default dir (e.g. a full
        # 39-replay sweep) — ask for an explicit --replay-dir instead.
        if args.graph and auto_picked and len(paths) > 8:
            print(f"auto-picked {run_dir} has {len(paths)} replays; pass --replay-dir "
                  f"{run_dir} explicitly to graph them (or cap it).")
            return
        # --graph only renders PNGs/GIFs from the saved replays; it does NOT rewrite
        # the CSVs or print the per-game table (the graph reads the JSONs directly).
        _process_replay_dir(run_dir, paths, args)
        return

    if args.animals and not (args.old or args.new or args.compare):
        out_dir = Path(args.run_dir) if args.run_dir else Path(".")
        out_dir.mkdir(parents=True, exist_ok=True)
        chart = plot_animal_care_payback(out_dir / "animal_care_payback.png")
        if chart:
            print(f"  wrote {chart.name}")
        return

    pa_indices = _parse_pa_arg(args.pa)
    for pa in pa_indices:
        if pa not in PUBLIC_AGENT_MAP:
            print(f"Unknown public agent #{pa}. Available:\n{public_agent_names()}")
            sys.exit(1)

    run_dir = Path(args.run_dir) if args.run_dir else _new_run_dir()
    print(f"Saving replays to {run_dir}")

    if args.xray:
        seeds = _make_seeds(args.batch, args.seed)
        saved = xray_batch(pa_indices, seeds, run_dir)
        write_run_csv(run_dir, saved)
        return

    if args.compare:
        results, seeds = compare_batch(pa_indices, args.batch, run_dir, seed=args.seed, workers=args.workers)
        all_paths = results["old"] + results["new"]
        rows = write_run_csv(run_dir, all_paths, workers=args.workers)
        print("\nPer-game summary:")
        print_game_table(rows)
        ab_delta_report(all_paths, per_day=args.render)
        if args.render and all_paths:
            replay = load_replay(all_paths[-1])
            frames, days, _ = replay_to_summary(replay, seat=_agent_seat(replay))
            print(f"\n--- rendered: {all_paths[-1].name} ---")
            render(days, frames)
        if args.llm:
            for p in all_paths:
                replay = load_replay(p)
                frames, days, _ = replay_to_summary(replay, seat=_agent_seat(replay))
                md_path = p.with_suffix(".md")
                md_path.write_text(narrative_summary(days, frames, metadata=replay.get("_diagnose_meta", {})))
                print(f"  wrote {md_path.name}")
        return

    if args.new and args.old:
        print("Use --compare for both; use only --old or --new otherwise.")
        sys.exit(1)
    label = "new" if args.new else "old"
    combo = dict(_E1_DEFAULT) if label == "new" else None
    saved, seeds = run_labeled_batch(label, pa_indices, args.batch, run_dir,
                                     seed=args.seed, combo=combo, workers=args.workers)
    rows = write_run_csv(run_dir, saved, workers=args.workers)
    print("\nPer-game summary:")
    print_game_table(rows)

    if args.render and saved:
        sample = saved[-1]
        replay = load_replay(sample)
        frames, days, _ = replay_to_summary(replay, seat=0)
        print(f"\n--- rendered: {sample.name} ---")
        render(days, frames)

    if args.llm and saved:
        for p in saved:
            replay = load_replay(p)
            frames, days, _ = replay_to_summary(replay, seat=_agent_seat(replay))
            md_path = p.with_suffix(".md")
            md_path.write_text(narrative_summary(days, frames, metadata=replay.get("_diagnose_meta", {})))
            print(f"  wrote {md_path.name}")


if __name__ == "__main__":
    cli()
