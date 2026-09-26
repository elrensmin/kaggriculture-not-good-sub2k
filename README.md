# Kaggriculture

A Kaggle agent for the **kaggriculture** competition, together with a diagnostic
harness for measuring it without guessing.

## Layout

| path | role |
|------|------|
| `src/` | **the agent.** An onion of small layers (params/market/state/routing → budget/crop_plan/herd_plan/layout → sell_policy/endgame/scheduler/emit). `src/__init__.py` exposes `agent(observation, configuration)`. `action(t) = f(state(t))` — stateless, no route tape, no chassis, no patch layer. |
| `tools/diagnose/` | the harness. Run the agent over a batch of public opponents in parallel, re-diagnose saved replays, render graph dashboards. Run via `python -m tools.diagnose`. |
| `tools/labour`, `tools/market`, `tools/report`, `tools/gates` | read-only analysis tools (wasted turns, selling/pricing, ours-vs-DSM, acceptance gates). |
| `public_agents/` | the 12 public "cloning" opponents used as adversaries. |
| `package.py` | build the **single-file** Kaggle submission from the `src/` package (human-only push). |
| `Makefile`, `scripts/sweep.sh` | run entry points. |
| `diag-replays/` | saved local game replays and per-run CSVs (gitignored). |
| `replays/DSM/v1/` | the #1 team's 123 leaderboard episodes — read-only reference data. |
| `docs/DSM-vs-us(v0).md` | the data-backed diagnosis of this agent against the #1, with the open fix list. |
| `docs/dsm_v1.md` | the #1 team's full anatomy (what we are copying). |

## Development model

The agent is **stateless**: every turn it rebuilds a `State` snapshot from the
observation and plans from scratch. There is nothing to keep valid between turns,
so any layer can be changed and re-run — a bug is a local fix, never a corrupted
trajectory.

Two rules that matter:

- **Judge on `result` (WIN/LOSS), never on a cross-game average.** The ladder is a
  win/loss rating; margin is the low-noise *readout*, not the score. See the
  anti-goal in `AGENTS.md`.
- **A/B on identical seeds.** `src/params.py` is env-overridable, so two
  configurations can be measured from one tree; `tools/report/arm_diff.py` diffs
  them on matched `(opponent, seed)` pairs with a sign test.

## Quick start

```bash
# Run the agent against public agent 2 over 12 seeds (parallel across all cores)
python -m tools.diagnose --scratch --pa 2 --batch 12 --seed 700

# The whole public field
python -m tools.diagnose --scratch --pa 1-12 --batch 8 --seed 4362837462

# Re-diagnose a saved run (regenerates the CSVs; --render prints the day report)
python -m tools.diagnose --replay-dir diag-replays/v0-us --render

# Leaderboard analysis: lb replays carry no seed, so per-day CSVs are keyed on the
# episode id and labelled from info.TeamNames; both seats are analysed.
python -m tools.diagnose --replay-dir replays/DSM/v1 --lb

# Sweep the agent against ALL 12 public agents + a per-opponent W-L summary
./scripts/sweep.sh 4362837462 15        # start seed, seeds per opponent

# Read the pool arm against DSM: POOL header, p10..p90 ladders, MARGIN read,
# per-opponent table
PYTHONPATH=. python -m tools.report.dsm_profile --compare \
  --run-dir diag-replays/sweep_s4362837462_b15

# Live public-agent index mapping
python -c "from tools import diagnose; print(diagnose.public_agent_names())"
```

> `python -m tools.diagnose` is the canonical entry point. On import it puts the
> **repo root** on `sys.path`, so `import src` (the agent) and `import tools.*`
> resolve no matter how the CLI is launched — plain python, `uv run`, or a
> fork-parallel worker.

> NOTE: `--pa 2 --batch 24` is 24 games against ONE opponent. DSM's 123 episodes
> span 66 teams, so a single-opponent arm is not a comparable sample —
> `dsm_profile` prints a POOL header that says which one you are looking at.

Full flag reference and reproducibility notes: `python -m tools.diagnose --help`
and `tools/diagnose/cli.py`.

## Pulling live tournament opponents (Kaggle API)

Two helper scripts in `tools/fetch/` fetch the current leaderboard and an
opponent's episode replays straight from Kaggle using the `kaggle` python package
(auth from `~/.kaggle/access_token` or `kaggle.json` /
`KAGGLE_USERNAME`+`KAGGLE_KEY`; the package is in `.venv`).

```bash
# 1. Top players of the tournament (team name + id + leaderboard score)
python tools/fetch/fetch_top_players.py --top 3 --json replays/top_players.json

# 2. Pull a team's top-scoring submission's episode replays into replays/<team_name>/
python tools/fetch/pull_top_submissions.py --team 16732748 --team 16730612   # latest each
python tools/fetch/pull_top_submissions.py --top 3 --episodes all --out replays
python tools/fetch/pull_top_submissions.py --submission 56468867 --episode 112413080
```

## Makefile

Everything is wrapped as a `make` target:

```bash
make help                                # list every target
make scratch PA=2 BATCH=12 SEED=700      # run the agent vs PA 2 over 12 seeds
make scratch PA=1-12 BATCH=8             # the whole public field
make diag ARGS="--pa 1-12 --batch 4"     # raw CLI passthrough
make sweep SEED=4362837462 BATCH=15      # all public agents + per-opponent summary
make replay DIR=diag-replays/v0-us       # re-diagnose a saved run (no games)
make replay-lb DIR=replays/DSM/v1        # leaderboard replays
make graph DIR=diag-replays/v0-us        # dashboards + farm-board GIFs
make animals DIR=diag-replays/v0-us      # animal CARE payback chart
make package                             # build dist/submission.py (no push)
make package-check                       # build + prove bundle == local src.agent
make verify                              # compile + import the agent and harness
make install                             # install/refresh kaggle-environments
```

Targets default to the repo `.venv` when present, else `python3`, and to `PA=2`,
`BATCH=2`, `SEED=700`, `WORKERS`=all cores. Override any knob inline:

```bash
make scratch PA=1-12 BATCH=8 SEED=4362837462 WORKERS=4
```

### Multiple uv runs

`uv` is supported but not required. Point `PY` at `uv run python`:

```bash
make scratch PY='uv run python' PA=2 BATCH=12
uv run python -m tools.diagnose --scratch --pa 1-12 --batch 8
uv run python package.py --check
```

`pyproject.toml` marks the project as a **non-package** (`[tool.uv] package = false`)
and only asks for `kaggle-environments>=1.32.7`.

## Packaging for Kaggle

The agent is the `src/` package and ships as **one self-contained `.py`**:

```bash
make package                            # build dist/submission.py (no push)
python package.py --check               # build + prove it == local src.agent
python package.py --push -m "message"   # build + submit (HUMAN ONLY)
```

`package.py` embeds every `src/*.py` source (base64) and installs them at import
time as submodules of a synthetic package, so their relative imports
(`from . import params`, `from .job import Job`) resolve exactly as in the repo.
Module order comes from a topological sort of those imports, so adding a layer
needs no edit to `package.py`. `--check` loads the bundle in a fresh process and
asserts its final bank equals the local `src.agent`'s on the same seed/opponent.
`--push` refuses without Kaggle credentials. **The agent never pushes** — that is
the operator's call; see `AGENTS.md`.

## Files at a glance

| path | role | editable? |
|------|------|-----------|
| `src/*.py` | the agent (onion layers) | **YES — the product** |
| `src/params.py` | every tunable knob (env-overridable via `SCRATCH_PARAMS`) | YES |
| `tools/diagnose/` | harness (`python -m tools.diagnose`) | yes |
| `tools/` (rest) | analysis tools | yes |
| `Makefile`, `scripts/sweep.sh` | run entry points | yes |
| `tools/fetch/*.py` | Kaggle-API helpers (top players, episode replays) | yes |
| `package.py` | build + verify (+ human-only push) the single-file submission | yes |
| `public_agents/*.py` | opponent agents | yes |
| `GAME_DYNAMICS.md` | authoritative engine mechanics & measured payoff data | yes |
| `README.md`, `AGENTS.md`, `tools/readme.md`, `docs/` | docs | yes |
| `replays/DSM/v1/` | the #1's replays (reference data) | **NO** |

## Running / requirements

- Python ≥ 3.12; runtime dependency `kaggle_environments` (≥ 1.32.7), pinned in
  `pyproject.toml`.
- The `tools/fetch/` helpers additionally use the `kaggle` package (in `.venv`);
  they need `~/.kaggle/access_token` (or kaggle.json / `KAGGLE_USERNAME`+`KAGGLE_KEY`).
- From the repo root, run the `python -m tools.diagnose ...` / `make ...` commands
  above. A ready venv is in `.venv` (`source .venv/bin/activate`).

## Further reading

- **Operating rules & workflow**: `AGENTS.md` (the handover guide).
- **Engine mechanics & payoff data**: `GAME_DYNAMICS.md`.
- **Why we are behind, phase by phase**: `docs/DSM-vs-us(v0).md`.
- **What the #1 actually does**: `docs/dsm_v1.md`.
- **Tooling index**: `tools/readme.md`.
