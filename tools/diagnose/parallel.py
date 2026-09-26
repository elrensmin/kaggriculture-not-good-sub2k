"""diagnose.parallel — fork-based parallel game-batch execution.

The agent under test is stateless (``action(t) = f(state(t))``), so a batch is a
set of independent games and the only thing worth caching per process is the
agent function itself. One task is created PER OPPONENT so the pool actually
spreads across cores, and ``run_parallel_tasks`` is the single fork point.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from .agents import load_agent, load_public_agent
from .config import EPISODE_STEPS, PUBLIC_AGENT_MAP, TEST_SEAT
from .games import run_game, save_replay
from .runbook import _make_seeds

# Per-worker agent cache: a forked process loads the agent once and reuses it for
# every batch it handles. Module-global on purpose so the parent's copy can be
# dropped once the pool is gone.
_AGENT = None


def _get_agent():
    global _AGENT
    if _AGENT is None:
        _AGENT = load_agent(fresh=True)
    return _AGENT


def _batch_exec_worker(task):
    """Run ONE batch (a single opponent over all seeds) in a worker.

    task = (task_id, label, pa_indices, seeds, cdir, seat, episode_steps).
    Returns (task_id, [saved replay paths]).
    """
    task_id, label, pa_indices, seeds, cdir, seat, episode_steps = task
    cdir = Path(cdir)
    cdir.mkdir(parents=True, exist_ok=True)
    agent = _get_agent()
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
    """Run independent game-batches across cores.

    ``tasks`` = a list of ``_batch_exec_worker`` tuples. Returns
    ``{task_id: [paths]}`` in completion order. Falls back to serial when trivial.
    """
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
    global _AGENT
    _AGENT = None
    return out


def run_labeled_batch(pa_indices, n_seeds, run_dir, seed=None,
                      seat=TEST_SEAT, workers=None, label="agent"):
    """Run the agent over pa_indices x n_seeds in parallel.

    Returns (saved_paths, seeds). One task per opponent so the pool spreads the
    batch across cores.
    """
    seeds = _make_seeds(n_seeds, seed)
    cdir = Path(run_dir)
    cdir.mkdir(parents=True, exist_ok=True)
    tasks = [
        (i, label, [pa], seeds, cdir, seat, EPISODE_STEPS)
        for i, pa in enumerate(pa_indices)
    ]
    by_id = run_parallel_tasks(tasks, workers=workers)
    saved = [p for lst in by_id.values() for p in lst]
    return saved, seeds
