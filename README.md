# Kaggriculture

A productionized, refactored Kaggle agent for the **kaggriculture** competition
environment, together with a deterministic A/B test harness (`diagnose.py`) for
developing and measuring improvements without touching the production agent.

## Overview

- **`main.py`** — the production agent: a ~6,400-line, 45-layer refactor of the
  original notebook `agent`, proven behavior-identical to its source. Do not
  edit it while experimenting.
- **`route_tape.py`** — a pre-computed opening route tape. Read-only data.
- **`agent.py`** — the experiment workspace: a **patch layer on top of `main.py`**.
  `agent.patch(action, observation, configuration)` receives the action `main.py`
  produced and may alter it. Editing `patch()` is how you iterate.
- **`public_agents/`** — 13 reference/opponent agents used as adversaries in runs.
- **`diagnose.py`** — the diagnostic / A/B harness. Its module docstring documents
  the full CLI, seating, outputs and reproducibility.
- **`diag-replays/`** — saved game replays and per-run CSVs (gitignored).

## Development model

The golden rule: **never modify `main.py` or `route_tape.py`**. Every experiment
goes into `agent.py` as a patch. The harness runs:

- `--old`     → `main.py` alone
- `--new`     → `main.py` + `agent.patch()`
- `--compare` → both on the same seeds, side by side

Because `--new`/`--compare` exercise *everything `main.py` does plus your
patch*, results are measured against real production behavior rather than an
isolated stub. Improving a patch means it has to beat `--old`, and regressions
are caught directly.

## Quick start

```bash
# A/B old vs new on one seed (deterministic)
python diagnose.py --compare --pa 1 --seed 42

# Test a patch over multiple opponents and seeds
python diagnose.py --new --pa 1-6 --batch 3 --seed 7

# Re-diagnose a saved run (regenerates CSVs; --render prints the day report)
python diagnose.py --replay-dir diag-replays/run-1 --render

# Sweep our agent against ALL 13 public agents over several seeds, and get a
# per-opponent wins/losses + averages summary:
./sweep.sh new          # our patched agent (main.py + agent.patch())
./sweep.sh old          # the production main.py agent
./sweep.sh new 100 5    # start seed 100, 5 seeds per opponent

# Live public-agent index mapping
python -c "import diagnose; print(diagnose.public_agent_names())"
```

Full flag reference, seating convention, output formats and reproducibility are
in `diagnose.py`'s module docstring (`python -m diagnose --help`).

## Files at a glance

| file | role | editable while experimenting? |
|------|------|------------------------------|
| `main.py` | production agent | **NO** |
| `route_tape.py` | opening route data | **NO** |
| `agent.py` | your patch over `main.py` ('new') | **YES** |
| `diagnose.py` | diagnostic / A/B harness | yes |
| `sweep.sh` | run `new`/`old` against all public agents over multiple seeds | yes |
| `public_agents/*.py` | opponent agents | yes |
| `README.md`, `AGENTS.md` | docs | yes |

## Running / requirements

- Python 3.13; deps pinned in `pyproject.toml` / `uv.lock` (notably
  `kaggle_environments`). A ready venv is in `.venv`.
- From the repo root: `source .venv/bin/activate`, then the `python diagnose.py ...`
  commands above.

## Further reading

- **Operating rules & patch workflow**: `AGENTS.md` (the handover guide).
- **Harness CLI / outputs / seating / reproducibility**: top-of-file docstring in
  `diagnose.py`.
