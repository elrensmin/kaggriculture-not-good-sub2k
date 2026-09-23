"""diagnose.parallel — fork-based parallel game-batch execution shared by the CLI.

The ``--new``/``--old``/``--compare``/``--grid`` paths all run independent game
batches through ``run_parallel_tasks``; each forked worker reuses one main.py
load (``_get_agent_pair``) and the patch re-reads E1_PARAMS live each turn.
Split from the monolith diagnose.py.
"""
from __future__ import annotations

from pathlib import Path

from diagnose.agents import load_old_and_new, load_public_agent
from diagnose.config import EPISODE_STEPS, PUBLIC_AGENT_MAP, TEST_SEAT
from diagnose.games import run_game, save_replay
from diagnose.runbook import _make_seeds

# Per-worker agent cache (forked processes reuse one main.py load across the
# batches they handle). This is intentionally a module global here so the
# parent's copy can be cleared after the pool without a stale config module ref.
_AGENT_PAIR = None
def _get_agent_pair():
    """(old_agent, new_agent) loaded once per (forked) process and reused across
    every batch that process handles. main.py is a singleton, so reloading it per
    batch would be wasteful; one load per process is enough because the patch
    re-reads E1_PARAMS live each turn."""
    global _AGENT_PAIR
    if _AGENT_PAIR is None:
        _AGENT_PAIR = load_old_and_new(fresh=True)
    return _AGENT_PAIR



def _batch_exec_worker(task):
    """Run ONE batch (a single agent config over pa_indices x seeds) in a worker.

    task = (task_id, label, combo, pa_indices, seeds, cdir, seat, episode_steps).
    - label is "old" (production main.py only) or "new" (main.py + agent.patch).
    - combo is None for "old", or a dict of E1_PARAMS injected for "new".
    Returns (task_id, [saved replay paths]). This is the parallel unit shared by
    --grid, --compare, --new and --old; each worker reuses one main.py load via
    _get_agent_pair()."""
    task_id, label, combo, pa_indices, seeds, cdir, seat, episode_steps = task
    cdir = Path(cdir)
    cdir.mkdir(parents=True, exist_ok=True)
    if label == "new":
        import agent as _amod
        _amod.E1_PARAMS = dict(combo)
    old_agent, new_agent = _get_agent_pair()
    agent = new_agent if label == "new" else old_agent
    paths = []
    for pa in pa_indices:
        opp = load_public_agent(pa)
        opp_name = PUBLIC_AGENT_MAP[pa][0]
        for s in seeds:
            env = run_game(agent, opp, seed=s, episode_steps=episode_steps, seat=seat, audit=True)
            meta = {"agent": label, "opponent": opp_name, "opponent_idx": pa,
                    "seed": s, "seat": seat, "episode_steps": episode_steps}
            path = cdir / f"{label}_vs_{opp_name}_seed{s}.json"
            save_replay(env, path, meta)
            paths.append(path)
    return task_id, paths



def run_parallel_tasks(tasks, workers=None):
    """Run independent game-batches across cores. `tasks` = a list of
    _batch_exec_worker tuples (task_id, label, combo, pa_indices, seeds, cdir,
    seat, episode_steps). Returns {task_id: [paths]} in completion order.

    Shared by --grid (old baseline + every combo), --compare (old + new) and
    --old/--new (single batch). Each task is a fork-able unit; the number of
    workers defaults to all cores. Falls back to serial when trivial."""
    import os
    import sys
    import multiprocessing as mp
    n = len(tasks)
    if n == 0:
        return {}
    w = int(workers if workers is not None else (os.cpu_count() or 1))

    def bar(done, total, width=28):
        frac = done / total if total else 1.0
        filled = int(width * frac)
        blk = "#" * filled + "-" * (width - filled)
        return f"  [{blk}] {done:>3}/{total} {frac*100:5.1f}%"

    out = {}
    if w <= 1 or n <= 1:
        for i, t in enumerate(tasks, 1):
            tid, paths = _batch_exec_worker(t)
            out[tid] = paths
            print(f"\r{bar(i, n)}", end="", file=sys.stderr, flush=True)
    else:
        ctx = mp.get_context("fork")
        with ctx.Pool(processes=min(w, n)) as pool:
            for i, (tid, paths) in enumerate(pool.imap_unordered(_batch_exec_worker, tasks), 1):
                out[tid] = paths
                print(f"\r{bar(i, n)}", end="", file=sys.stderr, flush=True)
    print("  done.", file=sys.stderr)
    global _AGENT_PAIR
    _AGENT_PAIR = None  # do not keep a stale main instance in the caller
    return out



def run_labeled_batch(label, pa_indices, n_seeds, run_dir, seed=None, combo=None,
                      seat=TEST_SEAT, workers=None):
    """Run one label ("old"/"new", optionally with an E1_PARAMS combo) over
    pa_indices x n_seeds in parallel and return (saved_paths, seeds). The shared
    wrapper for --old / --new."""
    seeds = _make_seeds(n_seeds, seed)
    cdir = Path(run_dir)
    cdir.mkdir(parents=True, exist_ok=True)
    tasks = [(0, label, combo, pa_indices, seeds, cdir, seat, EPISODE_STEPS)]
    paths = run_parallel_tasks(tasks, workers=workers)
    return paths[0], seeds
