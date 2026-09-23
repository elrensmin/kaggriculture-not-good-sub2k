# Makefile for the Kaggriculture diagnostic harness
#
# Run any harness command with ease. Every target defaults to `.venv/bin/python`
# when present (the complete env), else the ambient `python3`; point `PY` at
# `uv run python` to route everything through uv
# (e.g.  make compare PY='uv run python' ).
#
# Overridable knobs per target:
#   PA   public-agent index (default 13)      BATCH  seeds/opponent (default 2)
#   SEED starting seed (default 700)          WORKERS parallel workers (default: all cores)
#   GRIDPARAMS  --grid-params spec            MODE   new|old for `sweep`
#   DIR   --replay-dir for render/graph       ARGS   raw CLI args for `diag`

# Prefer the repo .venv (complete env: kaggle + matplotlib + pandas) when it
# exists, else fall back to the ambient python. Override on the CLI if needed:
#   make compare PY=python3
#   make compare PY='uv run python'
PY        ?= $(if $(wildcard .venv/bin/python),.venv/bin/python,python3)
RUN       := $(PY) -m diagnose

PA        ?= 13
BATCH     ?= 2
SEED      ?= 700
WORKERS   ?=
WF         = $(if $(WORKERS),--workers $(WORKERS))
GRIDPARAMS ?= price_frac=[0.0,0.3,0.6,1.0];hold_cap=[0,5,10,20]
EXP       ?= floor
MODE      ?= new
ARGS      ?=
DIR       ?=

.DEFAULT_GOAL := help

.PHONY: help diag new old compare grid xray render graph animals sweep \
	package package-check verify install clean

help: ## Show every target
	@grep -E '^[a-zA-Z][a-zA-Z_-]*:.*##' $(MAKEFILE_LIST) \
		| sed 's/:.*##/:/' | column -t -s':'

# ---- generic harness passthrough ---------------------------------------------
diag: ## Run the harness with arbitrary args:  make diag ARGS="--old --pa 1-13 --batch 3"
	$(RUN) $(ARGS)

new: ## Run the patched agent (main.py + agent.py) against a public opponent
	$(RUN) --new --pa $(PA) --batch $(BATCH) --seed $(SEED) $(WF)

old: ## Run main.py alone against a public opponent
	$(RUN) --old --pa $(PA) --batch $(BATCH) --seed $(SEED) $(WF)

compare: ## Same-seed A/B old vs new (paired, hedged verdict)
	$(RUN) --compare --pa $(PA) --batch $(BATCH) --seed $(SEED) $(WF)

grid: ## Sweep an --exp param space (hedged, per-opponent):  make grid PA=... EXP=floor GRIDPARAMS='...'
	$(RUN) --grid --exp $(EXP) --pa $(PA) --batch $(BATCH) --seed $(SEED) $(WF) \
		--grid-params '$(GRIDPARAMS)'

xray: ## Per-step patch() investigation (action diffs + money curve)
	$(RUN) --xray --pa $(PA) --seed $(SEED) $(WF)

replay:
	$(RUN) --replay-dir $(DIR)

replay-lb:
	$(RUN) --replay-dir $(DIR) --lb

render: ## Re-diagnose a saved run dir:  make render DIR=diag-replays/run-1
	$(RUN) --replay-dir $(DIR) --render

graph: ## Dashboards + farm-board GIFs for a saved run dir:  make graph DIR=diag-replays/run-1
	$(RUN) --replay-dir $(DIR) --graph

animals: ## Standalone animal CARE payback chart (animal_care_payback.png)
	$(RUN) --animals --pa $(PA)

# ---- packaging (local builds only; NEVER runs --push automatically) ----------
package: ## Build dist/submission.py (no push)
	$(PY) package.py --out dist/submission.py

package-check: ## Build + verify bundle fidelity vs a public opponent (seed 42)
	$(PY) package.py --check --out dist/submission.py

# ---- hygiene ------------------------------------------------------------------
verify: ## Compile every module + import the harness
	$(PY) -m py_compile diagnose/*.py package.py
	$(PY) -c "import diagnose; n=len(diagnose.PUBLIC_AGENT_MAP); assert n>=13, n; print('diagnose import OK, public agents:', n)"

install: ## Install/refresh the runtime dependency (use uv or pip; see README)
	$(PY) -m pip install -U "kaggle-environments>=1.32.7"

clean: ## Remove __pycache__ dirs and default run outputs
	rm -rf $(shell find . -type d -name __pycache__) \
		dist/submission.py
