# Kaggriculture

A productionized, refactored Kaggle agent for the **kaggriculture** competition
environment, together with a deterministic A/B test harness (the `diagnose`
package) for developing and measuring improvements without touching the
production agent.

## Layout

The runnable code lives in a `src/` layer plus a `diagnose` package:

| path | role |
|------|------|
| `src/main.py` | **production agent** — ~6,400-line, 45-layer refactor of the original notebook `agent`, proven behavior-identical. Do **not** edit while experimenting. |
| `src/route_tape.py` | pre-computed opening route tape. **Read-only data.** |
| `src/agent.py` | **experiment workspace** — a patch layer on top of `main.py`. `agent.patch(action, observation, configuration)` receives the action `main.py` produced and may alter it. Editing `patch()` is how you iterate; reset to a clean template after a patch is promoted into `main.py`. |
| `public_agents/` | 13 reference/opponent agents used as adversaries in runs. |
| `diagnose/` | the diagnostic / A-B harness, split from the old single-file `diagnose.py` into focused modules. Run via `python -m diagnose`. |
| `package.py` | build (and optionally push, human-only) the **single-file** Kaggle submission from `src/main.py` + `src/agent.py` + `src/route_tape.py`. |
| `Makefile` | run any harness command with ease (see below). |
| `diag-replays/` | saved local game replays and per-run CSVs (gitignored). |

## Development model

The golden rule: **never modify `src/main.py` or `src/route_tape.py`**. Every
experiment goes into `src/agent.py` as a patch. The harness runs:

- `--old`     → `main.py` alone
- `--new`     → `main.py` + `agent.patch()`
- `--compare` → both on the same seeds, side by side

Because `--new`/`--compare` exercise *everything `main.py` does plus your patch*,
results are measured against real production behavior rather than an isolated
stub. Improving a patch means it has to beat `--old`, and regressions are caught
directly.

## Quick start

```bash
# A/B old vs new on one seed (deterministic)
python -m diagnose --compare --pa 1 --seed 42

# Test a patch over multiple opponents and seeds
python -m diagnose --new --pa 1-6 --batch 3 --seed 7

# Re-diagnose a saved run (regenerates CSVs; --render prints the day report)
python -m diagnose --replay-dir diag-replays/run-1 --render

# Sweep our agent against ALL 13 public agents over several seeds, and get a
# per-opponent wins/losses + averages summary:
./sweep.sh new          # our patched agent (main.py + agent.patch())
./sweep.sh old          # the production main.py agent
./sweep.sh new 100 5    # start seed 100, 5 seeds per opponent

# Live public-agent index mapping
python -c "import diagnose; print(diagnose.public_agent_names())"
```

> `python -m diagnose` is the canonical entry point. The harness adds both the
> repo root and `src/` to `sys.path` on import, so `import main` / `import agent`
> / `import route_tape` resolve no matter how the CLI is launched (plain python,
> `uv run`, or a fork-parallel worker).

Full flag reference, seating convention, output formats and reproducibility are
in `diagnose/cli.py` and the package docstring (`python -m diagnose --help`).

## Makefile

Everything above (and the grid/xray/graph/package workflows) is wrapped as a
`make` target so you can run it with ease:

```bash
make help                  # list every target
make compare PA=13 BATCH=2 SEED=700     # same-seed A/B for opponent 13
make new PA=1-6 BATCH=3 SEED=7          # patched agent across several oppos
make old                                # production main.py alone
make grid PA=1,2,8 BATCH=8 SEED=700     # sweep agent E1_PARAMS (hedged)
make xray PA=13 SEED=700                # per-step patch() investigation
make render DIR=diag-replays/run-1      # re-diagnose a saved run
make graph DIR=diag-replays/run-1       # dashboards + farm-board GIFs
make animals                            # animal CARE payback chart
make sweep                              # all 13 public agents (or MODE=old)
make package                            # build dist/submission.py (no push)
make package-check                      # build + prove bundle == local --new
make verify                             # compile everything + import the harness
make install                            # install/refresh kaggle-environments
```

Targets default to the ambient `python3` and to `PA=13`, default `BATCH`=2,
`SEED`=700, `WORKERS`=all cores. Override any knob on the command line:

```bash
make compare PA=1,2,3 BATCH=12 SEED=700 WORKERS=4
make grid  PA=9,12 BATCH=8 GRIDPARAMS='min_sell_frac=[0.9,1.0];shed_cap_frac=[0.9,0.95]'
make diag ARGS="--old --pa 1-13 --batch 8 --seed 42 --workers 2"
```

### Multiple uv runs

`uv` is supported but not required. To drive every target through uv, point `PY`
at `uv run python` (either per-invocation or forever in your shell):

```bash
make compare PY='uv run python'         # one uv run for this target
export PY='uv run python'               # every later make uses uv
make new PA=1-6 BATCH=3 SEED=7
```

Run the CLI directly under uv the same way:

```bash
uv run python -m diagnose --compare --pa 13 --batch 12 --seed 700
uv run python package.py --check
```

`pyproject.toml` marks the project as a **non-package** (`[tool.uv] package = false`)
and only asks for `kaggle-environments>=1.32.7`, so `uv sync` installs the single
runtime dependency without hunting for a build target. Use whichever runner you
prefer — the harness behaves identically under plain python and uv.

## Packaging for Kaggle

The working agent is three files (`src/main.py` chassis + `src/agent.py` patch +
`src/route_tape.py`) and ships to Kaggle as **one self-contained `.py`**. Use
`package.py` (v1 `route_tape` only):

```bash
make package                            # build dist/submission.py (no push)
python package.py --check               # build + prove it == local --new
python package.py --push -m "message"   # build + submit to Kaggle (human only)
```

`dist/submission.py` embeds `route_tape`, `main`, and `agent.patch` as synthetic
`sys.modules` entries (dependency order) and exposes the public
`agent(observation, configuration)` built exactly like the harness's `--new`
candidate — i.e. `agent.patch(main._original_agent(...))`. `--check` loads the
bundle in a separate process and compares its final money to the local `--new`
run on the same seed/opponent. `--push` submits via the `kaggle` CLI and refuses
without `~/.kaggle/kaggle.json` **or** `KAGGLE_USERNAME`/`KAGGLE_KEY` **or** a
`~/.kaggle/access_token`. See the guard in `AGENTS.md` — the agent never pushes.

## Files at a glance

| path | role | editable while experimenting? |
|------|------|------------------------------|
| `src/main.py` | production agent | **NO** |
| `src/route_tape.py` | opening route data | **NO** |
| `src/agent.py` | your patch over `main.py` ('new') | **YES** |
| `diagnose/` | diagnostic / A-B harness (package, `python -m diagnose`) | yes |
| `Makefile` | run any harness command with ease | yes |
| `sweep.sh` | run `new`/`old` against all public agents over multiple seeds | yes |
| `package.py` | build + verify (+ human-only push) the single-file submission | yes |
| `public_agents/*.py` | opponent agents | yes |
| `README.md`, `AGENTS.md`, `docs/` | docs | yes |

## Running / requirements

- Python ≥ 3.12; runtime dependency `kaggle_environments` (≥ 1.32.7), pinned in
  `pyproject.toml`.
- From the repo root, run the `python -m diagnose ...` / `make ...` commands
  above. A ready venv is in `.venv` (`source .venv/bin/activate`).

## Further reading

- **Operating rules & patch workflow**: `AGENTS.md` (the handover guide).
- **Harness CLI / outputs / seating / reproducibility**: `diagnose/cli.py` and
  `python -m diagnose --help`.
