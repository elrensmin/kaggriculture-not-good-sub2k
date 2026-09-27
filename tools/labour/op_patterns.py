#!/usr/bin/env python
"""op_patterns — the *structure* of a worker's turn stream, ours vs DSM.

`movement.py` gives the aggregate split (movement / PASS / productive) and
moves-per-act. That is not enough to copy DSM: the aggregate says he walks less, it
does not say *how his turns are arranged*. This tool measures the arrangement.

Four things, per arm:

  1. **Act run lengths.** A run is a maximal block of consecutive productive acts
     with no MOVE in between (so a run of 1 is strict act->move alternation, DSM's
     measured signature; a run of 4 is his "whole stack of ops on one animal tile").
     Reported as a distribution, a mean, and the share of all acts that sit in a
     run of >=2 / >=3 / >=4.
  2. **What follows an act.** Immediately after a productive act: another act, a
     MOVE, a PASS, or the end of the day. This is the coupling strength between
     adjacent work — DSM chains, we break and travel.
  3. **Per-act-type follow-up.** For each op (HARVEST, WATER, FEED, CARE, ...), the
     share of occurrences immediately followed by another act. A type that is almost
     always followed by a MOVE is a type we are paying travel for on every unit.
  4. **A raw trace.** The op sequence (with positions) of the busiest unit on a
     chosen day, both arms, side by side — the artifact behind claims like DSM's
     day-12 `WATER NORTH HARVEST SOUTH DROP PICKUP FEED CARE` at one animal tile.

Seats: ours is seat 1 by default (`--seat`); DSM is detected from
`info.TeamNames`. An arm with no TeamNames (our runs) falls back sensibly.

Usage:
  PYTHONPATH=. python -m tools.labour.op_patterns \\
      --dir diag-replays/v0-us --glob 'scratch_vs_*.json' \\
      --dsm-dir replays/DSM/v1 --dsm-max 40 --day 12
"""
from __future__ import annotations

try:
    from tools import team as team_mod
except ImportError:  # bare-script execution: add the repo root to sys.path
    import pathlib as _pl
    import sys as _sys
    _sys.path.insert(0, str(_pl.Path(__file__).resolve().parents[2]))
    from tools import team as team_mod

import argparse
import glob as globmod
from collections import Counter, defaultdict
from pathlib import Path

from tools import diagnose
from tools.diagnose.window import parse_days, in_window, describe

_WINDOW = None


def _in(day):
    return in_window(day, _WINDOW)


MOVES = {"NORTH", "SOUTH", "EAST", "WEST"}
ANIMAL_PRODUCT = {"GOOSE": "EGG", "COW": "MILK", "SHEEP": "WOOL"}


def _dsm_seat(rep):
    return team_mod.seat_of_names((rep.get("info") or {}).get("TeamNames") or [], fallback=0)


def _units(steps, seat):
    """Yield (step, day, unit_index, pos, op, item) for every unit-turn.

    PAIRING (verified against the replay, 437/450 moves = 97.1 %): a
    kaggle_environments step records the action that *produced* its observation, so
    the action taken FROM ``steps[t]["observation"]`` is
    ``steps[t + 1][seat]["action"]``. Pairing ``obs[t]`` with ``action[t]``
    (same-index) matches only 53.3 % and silently mis-assigns every position/op
    pair. Everything that conditions an op on a *tile* must use this shifted form.
    """
    for s in range(len(steps) - 1):
        if not _in(s // 24):  # window-guard
            continue
        if len(steps[s]) <= seat or len(steps[s + 1]) <= seat:
            continue
        obs = steps[s][seat].get("observation")
        act = steps[s + 1][seat].get("action") or {}
        if not obs:
            continue
        farm = obs["farms"][seat]
        pos = [tuple(farm["farmer"])] + [tuple(p) for p in farm.get("hands") or []]
        cmds = [act.get("farmer") or ["PASS"]] + list(act.get("hands") or [])
        for ui, cmd in enumerate(cmds):
            if ui >= len(pos):
                break
            op = cmd[0] if isinstance(cmd, list) and cmd else "PASS"
            item = cmd[1] if isinstance(cmd, list) and len(cmd) > 1 else None
            yield s, s // 24, ui, pos[ui], op, item


def analyse(steps, seat):
    """Per-arm structural summary, keyed by unit index for the trace."""
    runs = Counter()               # run length -> count of runs
    acts_in_run = Counter()        # run length -> number of acts inside such runs
    after_act = Counter()          # what immediately follows a productive act
    per_op = defaultdict(Counter)  # op -> Counter(following class)
    acts = moves = passes = 0
    traces = defaultdict(list)     # (day, unit) -> [(hour, pos, op, item)]
    op_counts = Counter()

    for s, day, ui, pos, op, item in _units(steps, seat):
        traces[(day, ui)].append((s % 24, pos, op, item))
        if op in MOVES:
            moves += 1
        elif op == "PASS":
            passes += 1
        else:
            acts += 1
            op_counts[op] += 1

    # Walk each unit's stream, PER DAY (hands respawn at the shed at day end, so a
    # transition across the boundary is not a real chain), to classify runs and
    # follow-ups.
    by_unit = defaultdict(list)
    for s, day, ui, pos, op, item in _units(steps, seat):
        by_unit[(ui, day)].append(op)
    for _key, ops in by_unit.items():
        n = len(ops)
        i = 0
        while i < n:
            if ops[i] in MOVES or ops[i] == "PASS":
                i += 1
                continue
            j = i
            while j + 1 < n and ops[j + 1] not in MOVES and ops[j + 1] != "PASS":
                j += 1
            ln = j - i + 1
            runs[ln] += 1
            acts_in_run[ln] += ln
            i = j + 1
        for i, op in enumerate(ops):
            if op in MOVES or op == "PASS":
                continue
            if i + 1 < n:
                nop = ops[i + 1]
                cls = "MOVE" if nop in MOVES else ("PASS" if nop == "PASS" else "ACT")
            else:
                cls = "END"
            per_op[op][cls] += 1
            after_act[cls] += 1
    return {
        "acts": acts, "moves": moves, "passes": passes,
        "runs": runs, "acts_in_run": acts_in_run,
        "after_act": after_act, "per_op": per_op,
        "traces": traces, "op_counts": op_counts,
    }


def _merge(dst, src):
    for k in ("runs", "acts_in_run", "after_act", "op_counts"):
        dst[k].update(src[k])
    for op, c in src["per_op"].items():
        dst["per_op"][op].update(c)
    dst["acts"] += src["acts"]
    dst["moves"] += src["moves"]
    dst["passes"] += src["passes"]
    dst["traces"].update(src["traces"])
    return dst


def _new():
    return {"acts": 0, "moves": 0, "passes": 0, "runs": Counter(),
            "acts_in_run": Counter(), "after_act": Counter(),
            "per_op": defaultdict(Counter), "traces": defaultdict(list),
            "op_counts": Counter()}


def _report(label, a, out):
    def p(line=""):
        out.append(line)

    tot = a["acts"] + a["moves"] + a["passes"] or 1
    nruns = sum(a["runs"].values()) or 1
    total_acts = a["acts"] or 1
    p(f"\n############ {label}  (unit-turns {tot:,}) ############")
    p(f"  acts {a['acts']:,}  moves {a['moves']:,}  PASS {a['passes']:,}"
      f"   -> moves/act {a['moves']/max(1,a['acts']):.2f}")
    p(f"  runs (consecutive acts with no MOVE between): {nruns:,}"
      f"   mean run length {total_acts/nruns:.2f}")
    p("  -- run-length distribution --")
    p(f"     {'len':>4}{'runs':>10}{'acts in them':>14}{'% of acts':>11}")
    for ln in sorted(a["runs"])[:8]:
        n = a["runs"][ln]
        ia = a["acts_in_run"][ln]
        p(f"     {ln:>4}{n:>10,}{ia:>14,}{100*ia/total_acts:>10.1f}%")
    longer = sum(v for k, v in a["runs"].items() if k >= 8)
    if longer:
        ia = sum(v for k, v in a["acts_in_run"].items() if k >= 8)
        p(f"     {'8+':>4}{longer:>10,}{ia:>14,}{100*ia/total_acts:>10.1f}%")
    for thr in (2, 3, 4):
        # acts_in_run[k] already holds the TOTAL acts in runs of length k.
        ia = sum(v for k, v in a["acts_in_run"].items() if k >= thr)
        p(f"     acts sitting in a run of >={thr}: {100*ia/total_acts:5.1f}%")
    p("  -- what immediately follows a productive act --")
    fa = sum(a["after_act"].values()) or 1
    for cls in ("ACT", "MOVE", "PASS", "END"):
        n = a["after_act"].get(cls, 0)
        p(f"     {cls:<6}{n:>9,}  ({100*n/fa:5.1f}%)")
    p("  -- per-act-type: share immediately followed by another ACT --")
    rows = []
    for op, c in a["per_op"].items():
        n = sum(c.values()) or 1
        rows.append((c.get("ACT", 0) / n, op, sum(c.values())))
    for share, op, n in sorted(rows, reverse=True):
        p(f"     {op:<22}{n:>8,}  chained {100*share:5.1f}%")


def _trace(label, a, day, unit, out):
    out.append(f"\n---- raw op trace: {label}, day {day} ----")
    keys = [k for k in a["traces"] if k[0] == day]
    if not keys:
        out.append("     (no data for this day)")
        return
    if unit is None:
        # busiest unit that day (most acts)
        def acts_of(k):
            return sum(1 for (_, _, op, _) in a["traces"][k] if op not in MOVES and op != "PASS")
        key = max(keys, key=acts_of)
    else:
        key = (day, unit)
    seq = sorted(a["traces"][key])
    out.append(f"     unit {key[1]}  ({len(seq)} turns; {sum(1 for x in seq if x[2] not in MOVES and x[2] != 'PASS')} acts)")
    toks = []
    for h, pos, op, item in seq:
        t = op if item is None else f"{op}:{item}"
        toks.append(f"h{h:02d}@{pos[0]},{pos[1]}:{t}")
    for i in range(0, len(toks), 4):
        out.append("       " + "  ".join(toks[i:i + 4]))


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dir", required=True, help="our run dir (replay JSONs)")
    ap.add_argument("--days", default=None, help="restrict analysis to day window, e.g. 0-5 or 0-5,12-17")
    ap.add_argument("--glob", default="*_vs_*.json")
    ap.add_argument("--seat", type=int, default=1, help="our seat (default 1)")
    ap.add_argument("--dsm-dir", default="replays/DSM/v1")
    ap.add_argument("--dsm-max", type=int, default=40)
    ap.add_argument("--day", type=int, default=12)
    ap.add_argument("--unit", type=int, default=None,
                    help="unit index for the trace (0=farmer); default = busiest that day")
    ap.add_argument("--out", default=None)
    ap.add_argument("--team", default=None,
                    help="leaderboard team to analyse (default: DSM / $KAGG_OPPONENT)")
    args = ap.parse_args()
    team_mod.set_team(args.team)

    global _WINDOW
    _WINDOW = parse_days(args.days)
    if _WINDOW:
        print("window:", describe(_WINDOW))

    ours, dsm = _new(), _new()
    n_ours = n_dsm = 0
    for p in sorted(globmod.glob(str(Path(args.dir) / args.glob))):
        try:
            rep = diagnose.load_replay(Path(p))
        except Exception as e:  # noqa: BLE001
            print("ERR", Path(p).name, e)
            continue
        _merge(ours, analyse(rep["steps"], args.seat))
        n_ours += 1
    dsm_paths = sorted(globmod.glob(str(Path(args.dsm_dir) / "*.json")))[:args.dsm_max]
    for p in dsm_paths:
        try:
            rep = diagnose.load_replay(Path(p))
        except Exception as e:  # noqa: BLE001
            print("ERR", Path(p).name, e)
            continue
        _merge(dsm, analyse(rep["steps"], _dsm_seat(rep)))
        n_dsm += 1

    out = ["op_patterns — act-run structure and per-op chaining, ours vs DSM",
           f"ours: {args.dir}  ({n_ours} games)",
           f"dsm : {args.dsm_dir}  ({n_dsm} games, capped {args.dsm_max})"]
    _report("ours", ours, out)
    _report("dsm", dsm, out)
    _trace("ours", ours, args.day, args.unit, out)
    _trace("dsm", dsm, args.day, args.unit, out)

    out.append("\n############ side by side ############")
    no, nd = max(1, n_ours), max(1, n_dsm)

    def mean_run(a):
        nr = sum(a["runs"].values()) or 1
        return a["acts"] / nr

    def chain(a):
        fa = sum(a["after_act"].values()) or 1
        return 100 * a["after_act"].get("ACT", 0) / fa

    rows = [
        ("unit-turns / game", (ours["acts"] + ours["moves"] + ours["passes"]) / no,
         (dsm["acts"] + dsm["moves"] + dsm["passes"]) / nd),
        ("moves/act", ours["moves"] / max(1, ours["acts"]), dsm["moves"] / max(1, dsm["acts"])),
        ("mean act-run length", mean_run(ours), mean_run(dsm)),
        ("act -> ACT next %", chain(ours), chain(dsm)),
    ]
    out.append(f"   {'metric':<24}{'ours':>12}{'dsm':>12}")
    for lbl, x, y in rows:
        out.append(f"   {lbl:<24}{x:>12,.2f}{y:>12,.2f}")

    text = "\n".join(out)
    print(text)
    if args.out:
        import os
        os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
        with open(args.out, "w") as fh:
            fh.write(text + "\n")
        print(f"\nwrote {args.out}")


if __name__ == "__main__":
    main()
