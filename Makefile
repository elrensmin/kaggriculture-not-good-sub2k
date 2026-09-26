# Makefile for the Kaggriculture diagnostic harness
#
# The agent under test is the `src` package; the harness is `tools.diagnose`.
# Every target defaults to `.venv/bin/python` when present, else `python3`; point
# `PY` at `uv run python` to route everything through uv
# (e.g.  make scratch PY='uv run python').
#
# Overridable knobs per target:
#   PA     public-agent selector (default 2; "1-12" for the whole field)
#   BATCH  seeds/opponent (default 2)     SEED  starting seed (default 700)
#   WORKERS parallel workers (default: all cores)
#   DIR    --replay-dir for replay/graph  ARGS  raw CLI args for `diag`

# Prefer the repo .venv (complete env) when it exists, else the ambient python.
PY        ?= $(if $(wildcard .venv/bin/python),.venv/bin/python,python3)
RUN       := $(PY) -m tools.diagnose

PA        ?= 2
BATCH     ?= 2
SEED      ?= 700
WORKERS   ?=
WF         = $(if $(WORKERS),--workers $(WORKERS))
ARGS      ?=
DIR       ?=

.DEFAULT_GOAL := help

.PHONY: help diag scratch sweep replay replay-lb graph animals \
	package package-check verify install clean

help: ## Show every target
	@grep -E '^[a-zA-Z][a-zA-Z_-]*:.*##' $(MAKEFILE_LIST) \
		| sed 's/:.*##/:/' | column -t -s':'

# ---- the vanilla run ---------------------------------------------------------
diag: ## Run the harness with arbitrary args:  make diag ARGS="--pa 1-12 --batch 3"
	$(RUN) $(ARGS)

scratch: ## Run the agent under test against PA public agents:  make scratch PA=1-12 BATCH=8
	$(RUN) --scratch --pa $(PA) --batch $(BATCH) --seed $(SEED) $(WF)

sweep: ## Sweep the agent over ALL public agents:  make sweep SEED=4362837462 BATCH=15
	./scripts/sweep.sh $(SEED) $(BATCH)

# ---- re-diagnose saved replays (no games re-run) -----------------------------
replay: ## Re-diagnose a saved run dir:  make replay DIR=diag-replays/v0-us
	$(RUN) --replay-dir $(DIR)

replay-lb: ## Re-diagnose leaderboard replays (no seed; keyed on episode id)
	$(RUN) --replay-dir $(DIR) --lb

graph: ## Dashboards + farm-board GIFs for a saved run dir:  make graph DIR=diag-replays/v0-us
	$(RUN) --replay-dir $(DIR) --graph

animals: ## Render the animal CARE payback chart into DIR (or .)
	$(RUN) --animals $(if $(DIR),--run-dir $(DIR),)

# ---- packaging (local builds only; NEVER pushes) ----------------------------
package: ## Build dist/submission.py (no push)
	$(PY) package.py --out dist/submission.py

package-check: ## Build + verify bundle fidelity vs a public opponent (seed 42)
	$(PY) package.py --check --out dist/submission.py

# ---- hygiene -----------------------------------------------------------------
verify: ## Compile every module + import the harness and the agent
	$(PY) -m compileall -q src tools package.py
	$(PY) -c "import src; assert callable(src.agent); from tools import diagnose; \
		n=len(diagnose.PUBLIC_AGENT_MAP); assert n>=12, n; \
		print('OK: src.agent + tools.diagnose, public agents:', n)"

install: ## Install/refresh the runtime dependency (use uv or pip; see README)
	$(PY) -m pip install -U "kaggle-environments>=1.32.7"

clean: ## Remove __pycache__ dirs and the built bundle
	rm -rf $(shell find . -type d -name __pycache__) \
		dist/submission.py
