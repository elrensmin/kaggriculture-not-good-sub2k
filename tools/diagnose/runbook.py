"""diagnose.runbook — run-dir / seed / --pa parsing bookkeeping."""
from __future__ import annotations

import random
from pathlib import Path
from typing import List, Optional

from .config import REPLAY_ROOT

def _new_run_dir() -> Path:
    idx = 1
    while True:
        p = REPLAY_ROOT / f"run-{idx}"
        if not p.exists():
            return p
        idx += 1



def _most_recent_run_dir() -> Optional[Path]:
    """Newest diag-replays/run-N holding replay JSONs (for --graph without --replay-dir)."""
    if not REPLAY_ROOT.exists():
        return None
    cands = sorted((p for p in REPLAY_ROOT.iterdir()
                    if p.is_dir() and (p / "*.json").glob and list(p.glob("*.json"))),
                   key=lambda p: p.stat().st_mtime, reverse=True)
    return cands[0] if cands else None



def _parse_pa_arg(arg: str) -> List[int]:
    """Parse --pa '1' or '1,2,3' or '1-3'."""
    out = []
    for part in arg.split(","):
        if "-" in part:
            a, b = part.split("-", 1)
            out.extend(range(int(a), int(b) + 1))
        else:
            out.append(int(part))
    return out



def _make_seeds(n_seeds: int, seed: Optional[int]) -> List[int]:
    """Seed set for a run.

    With --seed given: use seed, seed+1, ... seed+n-1 literally (deterministic,
    and the passed value is used verbatim). Without it: random seeds.
    """
    if seed is None:
        return [random.randint(0, 1_000_000_000) for _ in range(n_seeds)]
    return [seed + i for i in range(n_seeds)]
