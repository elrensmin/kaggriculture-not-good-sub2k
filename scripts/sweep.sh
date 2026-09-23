#!/usr/bin/env bash
#
# Sweep our agent (new or old) against ALL public agents over multiple seed runs
# to get a sense of overall performance.
#
# Usage:
#   ./sweep.sh new [SEED=42] [BATCH=3]
#   ./sweep.sh old [SEED=42] [BATCH=3]
#
#   new/old   which agent to run (--new = main.py + agent.patch(), --old = main.py)
#   SEED      starting seed; the run uses seed, seed+1, ... seed+BATCH-1 (deterministic)
#   BATCH     number of seeds per public agent (default 3)
#
# Results land in diag-replays/sweep_<mode>_s<SEED>_b<BATCH>/ as per-seed day
# CSVs plus a games.csv with per-game final_money / opponent_final / result. A
# per-opponent summary (wins-losses and averages) is printed at the end.
set -euo pipefail
# Resolve to the repo ROOT (this script lives in scripts/), so `python -m`
# sees the diagnose/ package no matter where the script is invoked from.
HERE="$(cd "$(dirname "$0")" && pwd)"
cd "$HERE/.."

MODE="${1:-}"
SEED="${2:-42}"
BATCH="${3:-3}"

if [[ "$MODE" != "new" && "$MODE" != "old" ]]; then
  echo "usage: $0 <new|old> [seed=42] [batch=3]" >&2
  exit 2
fi

# Use the project venv if present and not already active.
if [[ -d .venv && -z "${VIRTUAL_ENV:-}" ]]; then
  source .venv/bin/activate
fi

RUN_DIR="diag-replays/sweep_${MODE}_s${SEED}_b${BATCH}"
export SWEEP_RUN_DIR="$RUN_DIR"

echo "== Sweeping ALL public agents with the '${MODE}' agent =="
echo "   opponents : 1-13  (see: python -c \"import diagnose; print(diagnose.public_agent_names())\")"
echo "   seeds     : ${SEED} .. $((SEED + BATCH - 1))   (batch=${BATCH})"
echo "   run dir   : ${RUN_DIR}"
echo "   (this runs 13 opponents x ${BATCH} seeds = $((13 * BATCH)) games; give it time)"
echo

python -m diagnose --${MODE} --pa 1-13 --batch "${BATCH}" --seed "${SEED}" --run-dir "${RUN_DIR}"

echo
echo "=============================================================="
echo " SWEEP SUMMARY  (${MODE} agent)  seeds ${SEED}..$((SEED + BATCH - 1))"
echo "=============================================================="
python - <<'PY'
import csv, collections, os, pathlib
p = pathlib.Path(os.environ["SWEEP_RUN_DIR"]) / "games.csv"
rows = list(csv.DictReader(open(p)))
if not rows:
    print("games.csv is empty — nothing summarized"); raise SystemExit
def money(v):
    try: return float(v)
    except (TypeError, ValueError): return None
fares = [money(r["final_money"]) for r in rows]
n = len(fares); avg = sum(fares) / n if n else 0
res = collections.Counter(r["result"] for r in rows)
print(f"games       : {n}   agent={rows[0]['agent'].upper()}")
print(f"overall     : WIN={res.get('WIN',0)}  LOSS={res.get('LOSS',0)}  TIE={res.get('TIE',0)}   "
      f"avg final_money=${avg:,.0f}")
print()
print(f"{'opponent':42s} {'games':>5} {'W-L':>5} {'avg_our':>12} {'avg_opp':>12}")
by = collections.defaultdict(list)
for r in rows: by[r["opponent"]].append(r)
for opp, rr in sorted(by.items()):
    w = sum(1 for x in rr if x["result"] == "WIN")
    l = sum(1 for x in rr if x["result"] == "LOSS")
    mo = sum(money(x["final_money"]) for x in rr) / len(rr)
    oo = sum(money(x["opponent_final"]) for x in rr) / len(rr)
    print(f"{opp:42s} {len(rr):>5} {f'{w}-{l}':>5} {mo:>12,.0f} {oo:>12,.0f}")
print(f"\nresults: {os.environ['SWEEP_RUN_DIR']}/")
PY
