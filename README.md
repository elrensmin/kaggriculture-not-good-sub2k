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
  produced and may alter it. Editing `patch()` is how you iterate. Reset to a
  clean template after the last patch was promoted into `main.py`.
- **`public_agents/`** — 13 reference/opponent agents used as adversaries in runs.
- **`diagnose.py`** — the diagnostic / A/B harness. Its module docstring documents
  the full CLI, seating, outputs and reproducibility.
- **`fetch_lb_tapes.py`** — pulls the **full replays** of our real leaderboard
  games (default: our top-scoring COMPLETE submission) into `replays/lb/`.
- **`diagnose_lb.py`** — reuses `diagnose.py`'s analysis to report my-game and
  opponent-game inefficiency statistics per cached lb replay.
- **`diag-replays/`** — saved local game replays and per-run CSVs (gitignored).

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

## Packaging for Kaggle

The working agent is three files (`main.py` chassis + `agent.py` patch +
`route_tape`) and ships to Kaggle as **one self-contained `.py`**. Use
`package_agent.py`:

```bash
python package_agent.py                       # build dist/submission.py (no push)
python package_agent.py --tape v2             # embed route_tape_v2.py instead
python package_agent.py --check               # build + prove it == local --new
python package_agent.py --push -m "message"   # build + submit to Kaggle
```

The generated `dist/submission.py` embeds `route_tape`, `main`, and
`agent.patch` as synthetic `sys.modules` entries (dependency order) and exposes
the public `agent(observation, configuration)` built exactly like the harness's
`--new --tape v1` candidate — i.e. `agent.patch(main._original_agent(...))`.

`--check` loads the bundle in a separate process and compares its final money to
the local `--new` run on the same seed/opponent (byte-identical when it passes).
`--push` submits via the `kaggle` CLI and refuses without
`~/.kaggle/kaggle.json` **or** `KAGGLE_USERNAME`/`KAGGLE_KEY` **or** a
`~/.kaggle/access_token` (the current token format).

## Real leaderboard (lb) diagnostics

Our submitted agent runs in the wild against real opponents on real seeds; those
episodes are the true test of a promoted patch. `fetch_lb_tapes.py` caches the
**full** replay of those games, and `diagnose_lb.py` runs the same analysis
`diagnose.py` uses (`replay_to_summary`) on **our** seat and the **opponent's**
seat to hunt system-level inefficiencies.

```bash
# Pull our top-scoring COMPLETE submission's lb games (requires ~/.kaggle)
python fetch_lb_tapes.py                 # --all = every COMPLETE submission
python fetch_lb_tapes.py --list          # show what's cached

# Analyze cached lb games: our stats + the opponent's, per game (never averaged)
python diagnose_lb.py                    # compact table of our inefficiencies
python diagnose_lb.py --detail           # full our-vs-them side-by-side per game
python diagnose_lb.py --csv replays/lb/lb-stats.csv
```

## Files at a glance

| file | role | editable while experimenting? |
|------|------|------------------------------|
| `main.py` | production agent | **NO** |
| `route_tape.py` | opening route data | **NO** |
| `agent.py` | your patch over `main.py` ('new') | **YES** |
| `diagnose.py` | diagnostic / A/B harness | yes |
| `fetch_lb_tapes.py` | pull full lb replays of our top-scoring submission | yes |
| `diagnose_lb.py` | per-game efficiency report, our & opponent seats | yes |
| `sweep.sh` | run `new`/`old` against all public agents over multiple seeds | yes |
| `package_agent.py` | build + verify + optionally push the single-file Kaggle submission | yes |
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
