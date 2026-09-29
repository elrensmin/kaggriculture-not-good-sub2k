#!/usr/bin/env python
"""state_sheet — the day-end STATE sheet: every quantity we can measure, per day.

Why this exists
---------------
`phase_map` reduces a phase to ONE number per metric and walks the DAG to a root.
`boey_bench` shows Boey's day-wise defect surface. Neither shows OUR day-by-day state
next to his, broken down by species, seed and hire — which is the sheet you reach for
when a phase root says "animals on board 0.53x" and you need to see *which* animals,
on *which* days, with *how much seed in hand and how many hands hired*.

This is the canonical extractor (`phase_map.extract`) plus the breakdowns it does not
carry, all on the same replay/steps:

  STATE      money, quadrants, owned, planted, empty, weeds, structures, shed
  ANIMALS    COW / SHEEP / GOOSE, owned total (board + shed + inventory) AND on-board
  CROPS      WHEAT / MELON / STRAWBERRY / TOMATO / CARROT standing tiles
  SEEDS      held (day-end) AND bought (per-day), by species
  HIRES      hires per day, hands peak
  OPS        PLANT / WATER / HARVEST / FEED / CARE / COLLECT / FERT / PLACE /
             DROP / PICKUP / MOVE / PASS, unit-turns, idle share
  MONEY      sell revenue (estimated), trade net (exact), money delta

Every cell is the MEDIAN across games, day by day. Point it at our saved replays
(`--dir diag-replays/<arm>`) and the reference (`--ref-from replays/DSM/v1`) and it
prints ours/ref side by side.

Usage
-----
  PYTHONPATH=. python -m tools.phases.state_sheet --dir diag-replays/_probe \
      --ref-from replays/DSM/v1 --ref-max 8
  PYTHONPATH=. python -m tools.phases.state_sheet --pa 2,9 --batch 2 \
      --ref-from replays/DSM/v1 --ref-max 8 --days 0-10
"""
from __future__ import annotations

import argparse
import collections
import glob as globmod
import statistics as st
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from kaggle_environments.envs.kaggriculture.kaggriculture import ANIMALS, CROPS  # noqa: E402

from tools import team as team_mod                                          # noqa: E402
from tools.diagnose.config import TEST_SEAT                                  # noqa: E402
from tools.diagnose.games import load_replay                                 # noqa: E402
from tools.diagnose.runbook import _make_seeds, _parse_pa_arg                # noqa: E402
from tools.diagnose.window import parse_days, in_window                     # noqa: E402
from tools.phases import phase_map                                           # noqa: E402
from tools.phases.phase_map import (_MOVES, _owned_animals, _steps_of,       # noqa: E402
                                    _stock)

DAY = 24

_SPECIES = list(ANIMALS)          # GOOSE, COW, SHEEP
_CROPS = list(CROPS)              # WHEAT, CARROT, TOMATO, STRAWBERRY, MELON


# ---------------------------------------------------------------------------
# extraction — `phase_map.extract` (the canonical rec) + the breakdowns it lacks
# ---------------------------------------------------------------------------
def _augment(env, seat):
    """One extra pass over the same steps: seeds, seed buys, animal buys, hires, shed.

    ``phase_map.extract`` already records the standing STOCK (board animals and crops,
    money, shed total) and the FLOW (all ops, revenue, trade net). What it does not
    carry — and what a state sheet needs — is the *inventory* and *purchase* breakdown:
    the seed held and bought per species, the animals bought per species, the hires per
    day, and the shed item-by-item.
    """
    steps = _steps_of(env)
    extra = {}
    prev = None
    for t in range(len(steps)):
        frame = steps[t]
        if len(frame) <= seat:
            continue
        obs = frame[seat].get("observation")
        if not obs:
            continue
        d = t // DAY
        e = extra.setdefault(d, {"seed_buys": collections.Counter(),
                                 "animal_buys": collections.Counter()})
        priv = obs.get("private") or {}
        e["seeds"] = dict(priv.get("seeds") or {})
        e["shed_items"] = dict(priv.get("shed") or {})
        e["owned_animals"] = _owned_animals(obs, seat)   # board + shed + inventory
        # `hires_today` is the per-day HIRE-order counter (it resets to 0 each morning),
        # so the last frame of the day is the number of orders the agent issued that day.
        e["hires_today"] = int(obs["farms"][seat].get("hires_today") or 0)
        if prev is not None:
            pseeds = (prev.get("private") or {}).get("seeds") or {}
            for c in _CROPS:
                dd = int((priv.get("seeds") or {}).get(c, 0)) - int(pseeds.get(c, 0))
                if dd > 0:
                    e["seed_buys"][c] += dd
            pa_ = _owned_animals(prev, seat)
            ca_ = _owned_animals(obs, seat)
            for a in _SPECIES:
                dd = ca_[a] - pa_[a]
                if dd > 0:
                    e["animal_buys"][a] += dd
        prev = obs
    return extra


def extract_sheet(env, seat):
    """{day: rec} = phase_map.extract (stock+flow+money) merged with the breakdowns."""
    base = phase_map.extract(env, seat)
    extra = _augment(env, seat)
    out = {}
    for d, rec in base.items():
        out[d] = dict(rec)
        out[d].update(extra.get(d, {}))
    return out


def _load_sheets(paths, seat):
    """List of games, each {day: rec}, parsed from replay JSONs."""
    games = []
    for p in paths:
        rep = load_replay(p)
        seat_i = phase_map._seat_of(rep, seat)
        games.append(extract_sheet(rep, seat_i))
    return games


def _live_sheets(pa_indices, seeds):
    """List of games, each {day: rec}, run live (sequential; small batches only)."""
    from tools.diagnose.agents import load_agent, load_public_agent
    from tools.diagnose.games import run_game
    from tools.phases.dag import PHASES
    agent = load_agent(fresh=True)
    games = []
    for pa in pa_indices:
        opp = load_public_agent(pa)
        for s in seeds:
            env = run_game(agent, opp, seed=s, episode_steps=PHASES["phase3"]["steps"],
                           seat=TEST_SEAT, audit=False)
            games.append(extract_sheet(env, TEST_SEAT))
    return games


# ---------------------------------------------------------------------------
# metrics — the thorough list. name -> (group, fn(rec) -> value)
# ---------------------------------------------------------------------------
def _idle(rec):
    ut = rec.get("unit_turns", 0)
    return 100.0 * rec.get("pass", 0) / ut if ut else 0.0


METRICS = [
    ("STATE", "money",          lambda r: r.get("money_end")),
    ("STATE", "quadrants",      lambda r: r["stock"].get("quadrants")),
    ("STATE", "owned",          lambda r: r["stock"].get("owned")),
    ("STATE", "planted",        lambda r: r["stock"].get("planted")),
    ("STATE", "empty",          lambda r: r["stock"].get("empty")),
    ("STATE", "weeds",          lambda r: r["stock"].get("weed")),
    ("STATE", "structures",     lambda r: r["stock"].get("structures")),
    ("STATE", "shed_total",     lambda r: r["stock"].get("shed_total")),
]
METRICS += [("ANIMALS", a, lambda r, a=a: (r.get("owned_animals") or {}).get(a, 0))
            for a in _SPECIES]
METRICS += [("ANIMALS", a + "_board",
             lambda r, a=a: r["stock"].get("animal_" + a, 0)) for a in _SPECIES]
METRICS += [("ANIMALS", "total", lambda r: sum((r.get("owned_animals") or {}).values()))]
METRICS += [("CROPS", c, lambda r, c=c: r["stock"].get("plant_" + c, 0)) for c in _CROPS]
METRICS += [("SEEDS", c + "_held", lambda r, c=c: (r.get("seeds") or {}).get(c, 0))
            for c in _CROPS]
METRICS += [("SEED_BUYS", c + "_buy", lambda r, c=c: (r.get("seed_buys") or {}).get(c, 0))
            for c in _CROPS]
METRICS += [("ANIMAL_BUYS", a + "_buy", lambda r, a=a: (r.get("animal_buys") or {}).get(a, 0))
            for a in _SPECIES]
METRICS += [
    ("HIRES", "hands",        lambda r: r.get("hands_max", 0)),
    ("HIRES", "hires_added",  None),   # hands held today - hands held yesterday
    ("HIRES", "hire_orders",  lambda r: r.get("hires_today", 0)),
]
for op in ("PLANT", "WATER", "HARVEST", "FEED", "CARE", "COLLECT_FERTILIZER",
           "FERTILIZE", "PLACE", "DROP", "PICKUP", "MOVE", "PASS"):
    METRICS.append(("OPS", op, lambda r, op=op: r["flow"].get(op, 0)))
METRICS += [
    ("OPS", "unit_turns",      lambda r: r.get("unit_turns", 0)),
    ("OPS", "idle_share_pct",  _idle),
    ("MONEY", "revenue",       lambda r: r["flow"].get("REVENUE", 0)),
    ("MONEY", "trade_net",     lambda r: r["flow"].get("TRADE_NET", 0)),
]


def _aggregate(games, days):
    """{metric: {day: median}} over games, for the requested day window."""
    per = collections.defaultdict(lambda: collections.defaultdict(list))
    for g in games:
        # day-over-day deltas need the previous day's value within the SAME game
        money = {d: rec.get("money_end") for d, rec in g.items()}
        hands = {d: rec.get("hands_max") for d, rec in g.items()}
        for d, rec in g.items():
            if not in_window(d, days):
                continue
            for grp, name, fn in METRICS:
                if fn is None:            # computed below, not read off the rec
                    continue
                v = fn(rec)
                if isinstance(v, (int, float)):
                    per[name][d].append(float(v))
            pm = money.get(d - 1)
            if pm is not None and rec.get("money_end") is not None:
                per["money_delta"][d].append(float(rec["money_end"]) - float(pm))
            ph = hands.get(d - 1)
            if ph is not None and rec.get("hands_max") is not None:
                per["hires_added"][d].append(float(rec["hands_max"]) - float(ph))
    return {m: {d: st.median(vs) for d, vs in dd.items() if vs}
            for m, dd in per.items()}


# ---------------------------------------------------------------------------
# render
# ---------------------------------------------------------------------------
def _fmt(o, r):
    if o is None:
        return "-"
    if r is None:
        return f"{o:.1f}" if abs(o) >= 10 else f"{o:.2f}"
    return f"{o:.0f}/{r:.0f}" if abs(o) >= 10 or abs(r) >= 10 else f"{o:.1f}/{r:.1f}"


def render(ours, ref, days, ours_label, ref_label):
    ds = sorted({d for g in ours for d in g if in_window(d, days)} |
                {d for g in ref for d in g if in_window(d, days)})
    a = _aggregate(ours, days)
    b = _aggregate(ref, days) if ref else {}
    L = [f"# state sheet — {ours_label}  ({len(ours)} games)"
         + (f"  vs  {ref_label} ({len(ref)} games)" if ref else ""), ""]
    L.append("median per day, day by day." + ("  cell = ours/ref" if ref else ""))
    L.append("")
    cur_group = None
    for grp, name, _fn in METRICS + [("MONEY", "money_delta", None)]:
        if grp != cur_group:
            cur_group = grp
            L += [f"## {grp}", "", "| metric | " + " | ".join(f"d{d}" for d in ds) + " |",
                  "|" + "---|" * (len(ds) + 1)]
        row = [name]
        for d in ds:
            o = a.get(name, {}).get(d)
            r = b.get(name, {}).get(d) if ref else None
            row.append(_fmt(o, r))
        L.append("| " + " | ".join(row) + " |")
    L.append("")
    L.append("* ANIMALS rows are owned total (board + shed + inventory); `*_board` is "
             "on tiles only. `revenue` is estimated from SELL orders at the observed "
             "quote; `trade_net` is exact from the money ledger.")
    return "\n".join(L)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dir", default=None, help="our replay dir (saved JSONs)")
    ap.add_argument("--glob", default="*.json")
    ap.add_argument("--max-games", type=int, default=0)
    ap.add_argument("--seat", default="auto")
    ap.add_argument("--pa", default=None, help="live instead of --dir (e.g. 2,9)")
    ap.add_argument("--batch", type=int, default=1)
    ap.add_argument("--seed", type=int, default=4362837462)
    ap.add_argument("--ref-from", default=None, help="reference dir (e.g. replays/DSM/v1)")
    ap.add_argument("--ref-glob", default="*.json")
    ap.add_argument("--ref-max", type=int, default=8)
    ap.add_argument("--ref-seat", default="auto")
    ap.add_argument("--days", default="0-29")
    ap.add_argument("--out", default=None, help="write markdown here (default stdout)")
    a = ap.parse_args(argv)

    days = parse_days(a.days)
    if a.dir:
        paths = sorted(globmod.glob(str(Path(a.dir) / a.glob)))
        if a.max_games:
            paths = paths[: a.max_games]
        ours = _load_sheets(paths, a.seat)
        ours_label = Path(a.dir).name
    elif a.pa:
        ours = _live_sheets(_parse_pa_arg(a.pa), _make_seeds(a.batch, a.seed))
        ours_label = f"pa {a.pa} batch {a.batch}"
    else:
        ap.error("need --dir or --pa")

    ref = None
    ref_label = ""
    if a.ref_from:
        rpaths = sorted(globmod.glob(str(Path(a.ref_from) / a.ref_glob)))[: a.ref_max]
        if rpaths:
            ref = _load_sheets(rpaths, a.ref_seat)
            ref_label = f"{Path(a.ref_from).name} ({len(rpaths)})"

    md = render(ours, ref, days, ours_label, ref_label)
    if a.out:
        Path(a.out).write_text(md + "\n")
        print(f"wrote {a.out}")
    else:
        print(md)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
