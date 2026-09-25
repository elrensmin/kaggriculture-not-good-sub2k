"""tools/margin.py — the fast readout: how often we win and by how much.

Reads one or more harness run directories (``games.csv``) and prints, PER ARM:

  * W / L / T counts and the seed+opponent pairing
  * the margin distribution (``final_money - opponent_final``) as percentiles,
    with the median prominent — the median is the low-noise readout
  * **median margin when we win** and **when we lose** (the "and by how much")
  * the structural guards side by side (floor sales, discards, overflow days,
    escapes, stranded at bell) so a margin move is never read without them

With ``--vs OTHER`` it also pairs the same seed+opponent across the two arms and
reports the per-game delta: how many games flipped, the median delta, and the
win-rate change. Nothing is pooled across arms; pairing is always same-seed.

The margin is a *diagnostic of win probability*, never the score (see AGENTS.md,
"never trust cross-game averages" / wins-not-money). Use it to see whether a
structural change moved Pr[win], then judge the guards.

Run with ``PYTHONPATH=src:.`` (or just ``.venv/bin/python tools/margin.py``).
"""
from __future__ import annotations

import argparse
import csv
import os
import sys
from collections import defaultdict


def _f(row, *names, default=0.0):
    for n in names:
        if n in row and row[n] not in ("", None):
            try:
                return float(row[n])
            except (TypeError, ValueError):
                pass
    return default


def load(run_dir):
    """Return (rows, path) for a run dir or a direct games.csv path."""
    path = run_dir
    if os.path.isdir(path):
        path = os.path.join(path, "games.csv")
    if not os.path.isfile(path):
        raise SystemExit(f"no games.csv at {path}")
    rows = list(csv.DictReader(open(path)))
    for r in rows:
        r["_margin"] = _f(r, "final_money") - _f(r, "opponent_final")
    return rows, path


def _key(r, i):
    """Pairing key: seed + opponent (+ seat when present). Falls back to index."""
    seed = r.get("seed") or r.get("id") or r.get("episode")
    opp = r.get("opponent") or r.get("public_agent") or ""
    seat = r.get("seat")
    if seed in (None, "", "None"):
        return ("idx", i)
    return (str(seed), str(opp), str(seat))


def _pct(sorted_vals, q):
    if not sorted_vals:
        return 0.0
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    pos = q * (len(sorted_vals) - 1)
    lo = int(pos)
    hi = min(lo + 1, len(sorted_vals) - 1)
    frac = pos - lo
    return sorted_vals[lo] * (1 - frac) + sorted_vals[hi] * frac


GUARDS = [
    ("floor_sales", "floor u"),
    ("discarded_units_total", "discard u"),
    ("shed_overflow_days", "ovf days"),
    ("animal_escapes", "escapes"),
    ("idle_share_pct", "idle%"),
]


def _guard_totals(rows):
    out = {}
    for col, _ in GUARDS:
        vals = [_f(r, col) for r in rows]
        # idle_share_pct is already a per-game percentage -> median is meaningful;
        # the rest are totals across the run, so report the sum.
        out[col] = sum(vals) if col != "idle_share_pct" else _pct(sorted(vals), 0.5)
    out["stranded_at_bell"] = sum(_f(r, "stranded_at_bell") for r in rows)
    return out


def report(name, rows):
    n = len(rows)
    margins = sorted(r["_margin"] for r in rows)
    wins = [r["_margin"] for r in rows if r["_margin"] > 0]
    losses = [r["_margin"] for r in rows if r["_margin"] < 0]
    ties = n - len(wins) - len(losses)
    g = _guard_totals(rows)

    print(f"\n=== {name}   ({n} games) ===")
    print(f"  W/L/T          {len(wins)}/{len(losses)}/{ties}"
          f"   win rate {100.0 * len(wins) / n:.0f}%")
    print(f"  median margin  ${_pct(margins, 0.5):>12,.0f}"
          f"   mean ${sum(margins) / n:>12,.0f}")
    print(f"  median WIN     ${_pct(sorted(wins), 0.5) if wins else 0:>12,.0f}"
          f"   (best ${max(wins) if wins else 0:,.0f})")
    print(f"  median LOSS    ${_pct(sorted(losses), 0.5) if losses else 0:>12,.0f}"
          f"   (worst ${min(losses) if losses else 0:,.0f})")
    print(f"  p10/p25/p75/p90 ${_pct(margins, .10):>9,.0f}"
          f" ${_pct(margins, .25):>9,.0f} ${_pct(margins, .75):>9,.0f}"
          f" ${_pct(margins, .90):>9,.0f}")
    print("  guards         " + "  ".join(
        f"{label} {g[col]:,.0f}" if col != "idle_share_pct"
        else f"{label} {g[col]:.1f}" for col, label in GUARDS)
        + f"  stranded ${g['stranded_at_bell']:,.0f}")
    return dict(n=n, wins=len(wins), losses=len(losses), ties=ties,
                median=_pct(margins, 0.5), rows=rows)


def paired(name_a, a, name_b, b):
    ka = {_key(r, i): r for i, r in enumerate(a)}
    kb = {_key(r, i): r for i, r in enumerate(b)}
    shared = [k for k in ka if k in kb]
    if not shared:
        print(f"\n-- {name_b} vs {name_a}: no shared seed+opponent keys, cannot pair")
        return
    deltas = [kb[k]["_margin"] - ka[k]["_margin"] for k in shared]
    flips_to_win = sum(1 for k in shared
                       if ka[k]["_margin"] <= 0 < kb[k]["_margin"])
    flips_to_loss = sum(1 for k in shared
                        if ka[k]["_margin"] > 0 >= kb[k]["_margin"])
    wa = sum(1 for k in shared if ka[k]["_margin"] > 0)
    wb = sum(1 for k in shared if kb[k]["_margin"] > 0)
    ds = sorted(deltas)
    print(f"\n-- paired: {name_b} vs {name_a}  ({len(shared)}/{len(a)} games matched)")
    print(f"   wins    {wa} -> {wb}   (+{flips_to_win} flipped to WIN, "
          f"-{flips_to_loss} flipped to LOSS)")
    print(f"   median delta ${_pct(ds, 0.5):>12,.0f}   mean ${sum(ds) / len(ds):>12,.0f}")
    print(f"   p25/p75 delta ${_pct(ds, .25):>10,.0f} ${_pct(ds, .75):>10,.0f}"
          f"   worse in {sum(1 for d in ds if d < 0)}/{len(ds)},"
          f" better in {sum(1 for d in ds if d > 0)}/{len(ds)}")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("dirs", nargs="+", help="run dir(s) or games.csv path(s)")
    ap.add_argument("--vs", default=None,
                    help="pair every arm against this run dir (same seed+opponent)")
    ap.add_argument("--split", action="store_true",
                    help="also split each arm into YARN / no-YARN games when the "
                         "yarn signal is available in the CSV")
    args = ap.parse_args(argv)

    arms = []
    for d in args.dirs:
        rows, path = load(d)
        arms.append((os.path.basename(os.path.dirname(path)) or d, rows, path))

    results = []
    for name, rows, _ in arms:
        results.append(report(name, rows))
        if args.split:
            for label, want in (("YARN", True), ("no-YARN", False)):
                sub = [r for r in rows if _is_yarn(r) is want]
                if sub:
                    report(f"{name} [{label}]", sub)

    if args.vs:
        base_name, base_rows, _ = arms[0]
        for name, rows, _ in arms[1:]:
            paired(base_name, base_rows, name, rows)
    elif len(arms) > 1:
        base_name, base_rows, _ = arms[0]
        for name, rows, _ in arms[1:]:
            paired(base_name, base_rows, name, rows)
    return results


def _is_yarn(r):
    """Best-effort YARN signal from a games.csv row. Returns True/False/None."""
    for col in ("yarn", "has_yarn", "yarn_store"):
        if col in r and r[col] not in ("", None):
            return str(r[col]).strip().lower() in ("1", "true", "yes")
    shops = r.get("shop_unlocks") or r.get("shops") or ""
    if shops:
        return "YARN" in shops.upper()
    return None


if __name__ == "__main__":
    main(sys.argv[1:])
