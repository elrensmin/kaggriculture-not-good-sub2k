"""diagnose.batch — the serial run + the parallel old/new compare wrappers."""
from __future__ import annotations

from pathlib import Path
from typing import Callable, List, Optional

from diagnose.agents import load_public_agent
from diagnose.config import EPISODE_STEPS, PUBLIC_AGENT_MAP, TEST_SEAT, _E1_DEFAULT, _GRID_WORKERS
from diagnose.games import run_game, save_replay
from diagnose.parallel import run_parallel_tasks
from diagnose.runbook import _make_seeds

def batch_run(
    agent: Callable,
    agent_label: str,
    pa_indices: List[int],
    n_seeds: int,
    run_dir: Path,
    episode_steps: int = EPISODE_STEPS,
    seed: Optional[int] = None,
):
    run_dir = Path(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    seeds = _make_seeds(n_seeds, seed)
    saved = []
    for pa in pa_indices:
        opp = load_public_agent(pa)
        opp_name = PUBLIC_AGENT_MAP[pa][0]
        for s in seeds:
            env = run_game(agent, opp, seed=s, episode_steps=episode_steps, seat=TEST_SEAT, audit=True)
            meta = {
                "agent": agent_label,
                "opponent": opp_name,
                "opponent_idx": pa,
                "seed": s,
                "seat": TEST_SEAT,
                "episode_steps": episode_steps,
            }
            path = run_dir / f"{agent_label}_vs_{opp_name}_seed{s}.json"
            save_replay(env, path, meta)
            saved.append(path)
            reward = env.steps[-1][TEST_SEAT].reward
            print(f"  saved {path.name}  reward={reward:.0f}")
    return saved, seeds



def compare_batch(
    pa_indices: List[int],
    n_seeds: int,
    run_dir: Path,
    episode_steps: int = EPISODE_STEPS,
    seed: Optional[int] = None,
    workers: Optional[int] = None,
):
    """Run old and new agents against the same (shared) seeds and public agents,
    executing the two batches in parallel when workers > 1."""
    run_dir = Path(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    seeds = _make_seeds(n_seeds, seed)
    if workers is None:
        workers = _GRID_WORKERS
    tasks = [
        # (task_id, label, combo, pa_indices, seeds, cdir, seat, episode_steps)
        (0, "old", None, pa_indices, seeds, run_dir, TEST_SEAT, episode_steps),
        (1, "new", dict(_E1_DEFAULT), pa_indices, seeds, run_dir, TEST_SEAT, episode_steps),
    ]
    by_id = run_parallel_tasks(tasks, workers=workers)
    results = {"old": by_id.get(0, []), "new": by_id.get(1, [])}
    for label, paths in results.items():
        for p in paths:
            print(f"  saved {p.name}")
    return results, seeds
