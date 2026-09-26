#!/usr/bin/env bash
#
# Sweep the agent under test (the `src` package) against ALL public agents over
# multiple seed runs to get a sense of overall performance.
#
# Usage:
#   ./sweep.sh [SEED=42] [BATCH=3]
#
#   SEED   starting seed; the run uses seed, seed+1, ... seed+BATCH-1 (deterministic)
#   BATCH  number of seeds per public agent (default 3)
#
# Results land in diag-replays/sweep_s<SEED>_b<BATCH>/ as per-seed day CSVs plus a
# games.csv with per-game final_money / opponent_final / result. A per-opponent
# summary is printed at the end.
set -euo pipefail
# Resolve to the repo ROOT (this script lives in scripts/), so `python -m`
# sees the diagnose/ package no matter where the script is invoked from.
HERE="$(cd "$(dirname "$0")" && pwd)"
cd "$HERE/.."

SEED="${1:-42}"
BATCH="${2:-3}"

# Use the project venv if present and not already active.
if [[ -d .venv && -z "${VIRTUAL_ENV:-}" ]]; then
  source .venv/bin/activate
fi

RUN_DIR="diag-replays/sweep_s${SEED}_b${BATCH}"
export SWEEP_RUN_DIR="$RUN_DIR"

echo "== Sweeping ALL public agents with the agent under test (src/) =="
echo "   opponents : 1-12  (see: python -c \"from tools import diagnose; print(diagnose.public_agent_names())\")"
echo "   seeds     : ${SEED} .. $((SEED + BATCH - 1))   (batch=${BATCH})"
echo "   run dir   : ${RUN_DIR}"
echo "   (this runs 12 opponents x ${BATCH} seeds = $((12 * BATCH)) games; give it time)"
echo

python -m tools.diagnose --scratch --pa 1-12 --batch "${BATCH}" --seed "${SEED}" --run-dir "${RUN_DIR}"

echo
echo "=============================================================="
echo " SWEEP SUMMARY  seeds ${SEED}..$((SEED + BATCH - 1))"
echo "=============================================================="
python - <<'PY'
import csv, collections, os, pathlib

p = pathlib.Path(os.environ["SWEEP_RUN_DIR"]) / "games.csv"
rows = list(csv.DictReader(open(p)))
if not rows:
    print("games.csv is empty — nothing summarized"); raise SystemExit

PCTS = (.10, .25, .50, .75, .90)

def q(xs, f):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(f * len(xs)))] if xs else 0.0

def ladder(xs):
    return " ".join(f"{q(xs, f):>9.0f}" for f in PCTS)

def money(v):
    try: return float(v)
    except (TypeError, ValueError): return None

def margin(r):
    a, b = money(r["final_money"]), money(r.get("opponent_final") or 0)
    return None if (a is None or b is None) else a - b

# Episode key: a pool run reuses the same seed list for every opponent, so
# (opponent, seed) is the episode -- `seed` alone is NOT unique.
eps = {}
for r in rows:
    eps.setdefault((r["opponent"], r["seed"]), r)
mgn = [m for m in (margin(r) for r in eps.values()) if m is not None]
wins = [m for m in mgn if m > 0]
loss = [m for m in mgn if m < 0]
res = collections.Counter(r["result"] for r in eps.values())

print(f"games.csv   : {len(rows)} rows   episodes={len(eps)}   "
      f"agent={rows[0]['agent'].upper()}")
print(f"W-L-T       : {res.get('WIN',0)}-{res.get('LOSS',0)}-{res.get('TIE',0)}   "
      f"win%={100.0*res.get('WIN',0)/max(1,len(eps)):.1f}")
print(f"margin      :{'p10':>9s} {'p25':>9s} {'p50':>9s} {'p75':>9s} {'p90':>9s}")
print(f"  all       : {ladder(mgn)}")
if wins:
    print(f"  wins      : {ladder(wins)}")
if loss:
    print(f"  losses    : {ladder(loss)}")
print(f"target read : p10={q(mgn,.10):,.0f}  max_loss={(min(mgn) if mgn else 0):,.0f}  "
      f"losing<-4k={100.0*sum(1 for m in mgn if m < -4000)/max(1,len(mgn)):.1f}%  "
      f"median_win={q(wins,.5):,.0f}  wins>30k="
      f"{100.0*sum(1 for m in wins if m > 30000)/max(1,len(wins)):.1f}%")
print()
print("-- per opponent (median margin, NOT a pooled average) --")
print(f"{'opponent':42s} {'n':>4} {'W-L-T':>8} {'p10mgn':>10} {'p50mgn':>10} "
      f"{'p90mgn':>10} {'worst':>10}")
by = collections.defaultdict(list)
for r in eps.values():
    by[r["opponent"]].append(r)
meds = []
for opp, rr in sorted(by.items(), key=lambda kv: (-len(kv[1]), kv[0])):
    mm = [m for m in (margin(x) for x in rr) if m is not None]
    if not mm:
        continue
    c = collections.Counter(x["result"] for x in rr)
    wlt = "{}-{}-{}".format(c.get("WIN", 0), c.get("LOSS", 0), c.get("TIE", 0))
    meds.append(q(mm, .5))
    print(f"{opp[:42]:42s} {len(rr):>4} {wlt:>8} {q(mm,.10):>10,.0f} "
          f"{q(mm,.5):>10,.0f} {q(mm,.90):>10,.0f} {min(mm):>10,.0f}")
if meds:
    print(f"MEDIAN-OF-PER-OPPONENT-MEDIANS {q(meds,.5):,.0f}  "
          f"(best {max(meds):,.0f} / worst {min(meds):,.0f} over {len(meds)} opponents)")

print(f"\nresults: {os.environ['SWEEP_RUN_DIR']}/")
print("Next, read it against DSM (POOL header + p10/p25/p50/p75/p90 ladders +")
print("MARGIN target read + PER-OPPONENT table):")
print("  PYTHONPATH=. python -m tools.report.dsm_profile --compare "
      f"--run-dir {os.environ['SWEEP_RUN_DIR']} --agent {rows[0]['agent']}")
PY
