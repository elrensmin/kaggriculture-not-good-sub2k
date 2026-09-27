#!/usr/bin/env python
"""phase_map — run a phase, measure its STRUCTURE, walk the causal graph to the root.

The thesis this tool implements: *everything downstream has roots in the beginning,
but you only find the root by connecting the measurements*. So it does three things:

  1. **Runs the agent in-memory** against the public field with the episode
     truncated at the phase boundary (d5 / d17 / the bell). The agent is stateless
     and never reads the horizon, so a truncated game has the same d0..N behaviour
     as a full one -- and it is ~5x cheaper. No replay files, no CSVs: the metrics
     are read straight out of ``env.steps``.
  2. **Measures only structural metrics** (land, crew, crops, animals, water, feed,
     weeds, shed, throughput) against the #1's measured per-day state, reduced over
     the phase with the same aggregation.
  3. **Walks the causal DAG** in ``dag.py`` and separates:
       * **ROOT**     — deficient with no deficient ancestor: fix here;
       * **symptom**  — deficient only because an ancestor is;
       * **blast radius** — how many deficient nodes a root explains.

Usage:
  PYTHONPATH=. python -m tools.phases.phase_map --phase phase1
  PYTHONPATH=. python -m tools.phases.phase_map --phase phase1 --pa 1-12 --batch 4
  PYTHONPATH=. python -m tools.phases.phase_map --phase all --batch 2      # one full run
  PYTHONPATH=. python -m tools.phases.phase_map --phase phase2 --trace      # print the DAG
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
import multiprocessing as mp
import os
import statistics as st
from collections import Counter, defaultdict

from tools.diagnose.agents import load_agent, load_public_agent
from tools.diagnose.config import PUBLIC_AGENT_MAP, TEST_SEAT
from tools.diagnose.games import run_game
from tools.diagnose.runbook import _make_seeds, _parse_pa_arg

from .dag import DSM_DAILY, DSM_DAILY_SOURCE, DSM_D5_STATE, EDGES, METRICS, PHASES
from tools.diagnose.window import parse_days, describe

DAY = 24


# ---------------------------------------------------------------------------
# extraction — per-game, per-day structural series, read from the in-memory env
# ---------------------------------------------------------------------------
def _stock(obs, seat):
    """Standing state at one frame."""
    f = obs["farms"][seat]
    shed = (obs.get("private") or {}).get("shed") or {}
    # The town's revealed shops. These are the ONLY exogenous input in the game (the
    # day's unlock is drawn from the same RNG as weed spawn, so it is coupled to our
    # own empty-tile count) -- and until this was added the DAG's two latent nodes,
    # `shops unlocked` and `YARN_STORE unlocked`, read 0 for BOTH arms, which made
    # them permanently "ok" and hid every shop-conditioned question.
    town = obs.get("town") or {}
    unlocked = {s for s in (town.get("unlocked_shops") or []) if s}
    st = {
        "quadrants": len(f.get("unlocked_quadrants") or []),
        # NOT `hands`: _end_of_day wipes the crew, so the last frame of a day can
        # read 0. extract() keeps the day's PEAK separately (see stock:hands).

        "shed_total": sum(v for v in shed.values() if v > 0),
        "owned": 0, "empty": 0, "planted": 0, "weed": 0,
        "structures": 0, "coop": 0, "pasture": 0, "animals": 0,
        "shops": len(unlocked),
        "yarn": 1 if any("YARN" in s for s in unlocked) else 0,
    }
    for row in f["tiles"]:
        for t in row:
            if t == "LOCKED":
                continue
            st["owned"] += 1
            if t is None:
                st["empty"] += 1
            elif isinstance(t, dict):
                kind = t.get("kind")
                if kind == "PLANT":
                    st["planted"] += 1
                    st["plant_" + t["crop"]] = st.get("plant_" + t["crop"], 0) + 1
                elif kind == "WEED":
                    st["weed"] += 1
                elif kind in ("COOP", "PASTURE"):
                    st["structures"] += 1
                    st["coop" if kind == "COOP" else "pasture"] += 1
                if "animal" in t:
                    st["animals"] += 1
                    st["animal_" + t["animal"]] = st.get("animal_" + t["animal"], 0) + 1
    return st


def _plant_to_weed(prev_tiles, tiles):
    """Count PLANT tiles that became WEED: the decay death (2 unwatered nights)."""
    n = 0
    for y, row in enumerate(tiles):
        if y >= len(prev_tiles):
            break
        for x, t in enumerate(row):
            if x >= len(prev_tiles[y]):
                continue
            p = prev_tiles[y][x]
            if isinstance(t, dict) and t.get("kind") == "WEED" \
                    and isinstance(p, dict) and p.get("kind") == "PLANT":
                n += 1
    return n


def _steps_of(obj):
    """`steps` from a live kaggle env OR from a parsed replay dict.

    Same shape either way, so one extractor serves both the live-run path and the
    replay path (which is what lets us point the same DAG at an opponent's games).
    """
    return obj.steps if hasattr(obj, "steps") else obj.get("steps", [])


def extract(env, seat):
    """{day: {stock:..., flow:Counter, unit_turns, pass}} for one game."""
    steps = _steps_of(env)
    days = {}
    prev_tiles = None
    for t in range(len(steps)):
        frame = steps[t]
        if len(frame) <= seat:
            continue
        obs = frame[seat].get("observation")
        if not obs:
            continue
        d = t // DAY
        rec = days.setdefault(d, {"flow": Counter(), "unit_turns": 0, "pass": 0, "stock": {}})
        # the action decided FROM this observation lives at t+1 (verified pairing)
        if t + 1 < len(steps) and len(steps[t + 1]) > seat:
            act = steps[t + 1][seat].get("action") or {}
            cmds = [act.get("farmer") or ["PASS"]] + list(act.get("hands") or [])
            for c in cmds:
                op = c[0] if c else "PASS"
                rec["flow"][op] += 1
                rec["unit_turns"] += 1
                if op == "PASS":
                    rec["pass"] += 1
        tiles = obs["farms"][seat]["tiles"]
        if prev_tiles is not None:
            rec["flow"]["__died"] += _plant_to_weed(prev_tiles, tiles)
        prev_tiles = tiles
        rec["stock"] = _stock(obs, seat)          # last frame of the day wins
        # the crew peak for the day: _end_of_day clears `hands`, so the literal last
        # frame is not a valid "hands at end of day" reading
        rec["hands_max"] = max(rec.get("hands_max", 0), len(obs["farms"][seat].get("hands") or []))
        rec["money_end"] = float(obs["farms"][seat].get("money") or 0.0)
    return days


# ---------------------------------------------------------------------------
# per-metric reduction
# ---------------------------------------------------------------------------
def _series(days, src):
    """The per-day series a metric reads: a list of (day, value)."""
    kind, _, key = src.partition(":")
    out = []
    for d in sorted(days):
        rec = days[d]
        if kind == "stock":
            if key == "hands":
                out.append((d, float(rec.get("hands_max", 0))))
            else:
                out.append((d, float(rec["stock"].get(key, 0))))
        elif kind == "flow":
            out.append((d, float(rec["flow"].get(key, 0))))
        elif kind == "derived":
            if key == "idle_pct":
                ut = rec["unit_turns"]
                out.append((d, 100.0 * rec["pass"] / ut if ut else 0.0))
            elif key == "plants_died":
                out.append((d, float(rec["flow"].get("__died", 0))))
            elif key == "water_per_tile":
                planted = rec["stock"].get("planted", 0)
                out.append((d, rec["flow"].get("WATER", 0) / planted if planted else 0.0))
            elif key == "harvest_per_planted":
                planted = rec["stock"].get("planted", 0)
                out.append((d, rec["flow"].get("HARVEST", 0) / planted if planted else 0.0))
            elif key == "cash_commit":
                out.append((d, 0.0))                      # filled per game below
            elif key == "open_dist":
                # L1 distance from the #1's invariant d5 state (see dag.DSM_D5_STATE).
                # Emitted only up to d5: it is a d5 reading, and `agg="last"` on a window
                # that SPANS phases would otherwise read it at d17.
                if d > 5:
                    continue
                st = rec["stock"]
                out.append((d, float(sum(abs(st.get(k, 0) - v)
                                         for k, v in DSM_D5_STATE.items()))))
    return out


def _agg(series, how):
    vals = [v for _, v in series]
    if not vals:
        return 0.0
    if how == "sum":
        return float(sum(vals))
    if how == "max":
        return float(max(vals))
    if how == "last":
        return float(vals[-1])
    if how == "mean":
        return float(sum(vals) / len(vals))
    return float(st.median(vals))


def _pnum(phase):
    """'phase1' -> 1 (the registry keys metrics by phase NUMBER). None if custom."""
    try:
        return int(str(phase)[-1])
    except (ValueError, IndexError):
        return None


def _pnums(phase, day0, day1):
    """The metric phases a window covers (a custom window can span two phases)."""
    n = _pnum(phase)
    if n is not None:
        return {n}
    out = set()
    for p, spec in PHASES.items():
        if p == phase or "name" in spec and p == "custom":
            continue
        pd0, pd1 = spec["days"]
        if not (pd1 < day0 or pd0 > day1):
            out.add(int(str(p)[-1]))
    return out or {1}


def reduce_game(days, phase, day0, day1):
    """One game -> {metric_key: value} for the phase's day range."""
    pnums = _pnums(phase, day0, day1)
    window = {d: r for d, r in days.items() if day0 <= d <= day1}
    out = {}
    for key, m in METRICS.items():
        if m["phase"] not in pnums:
            continue
        out[key] = _agg(_series(window, m["src"]), m["agg"])
    # opening cash commitment: fraction of the $3,000 bank spent during day 0
    if 1 in pnums:
        out["cash_commit"] = _cash_commit(days)
    return out


def _cash_commit(days):
    """Fraction of the $3,000 opening bank spent by the end of day 0."""
    rec = days.get(0)
    if not rec or "money_end" not in rec:
        return 0.0
    return max(0.0, min(1.0, (3000.0 - rec["money_end"]) / 3000.0))


# ---------------------------------------------------------------------------
# the #1's target for the same reduction
# ---------------------------------------------------------------------------
def _dsm_series(m, day0, day1):
    out = []
    for d in range(day0, day1 + 1):
        row = DSM_DAILY.get(d)
        if not row:
            continue
        k = m["target_key"]
        if k == "animals":
            v = row["cow"] + row["sheep"] + row["goose"]
        elif k == "owned":
            v = row["quad"] * 25
        elif k in row:
            v = row[k]
        else:
            continue          # this day has no measurement for this metric
        out.append((d, float(v)))
    return out


def _status(m, ours, target):
    """OK / WARN / BAD / '-' (descriptive: no target in the #1's table)."""
    if target is None:
        return "-", 0.0
    tol = m["tol"]
    allowed = abs(target) * tol if tol < 1 else float(tol)
    allowed = max(allowed, 1e-9)
    diff = ours - target
    better = m["better"]
    if better == "higher":
        short = target - ours
        if short > allowed:
            return "BAD", short
        if short > allowed / 2:
            return "WARN", short
    elif better == "lower":
        over = ours - target
        if over > allowed:
            return "BAD", over
        if over > allowed / 2:
            return "WARN", over
    else:  # range
        if abs(diff) > allowed:
            return "BAD", abs(diff)
        if abs(diff) > allowed / 2:
            return "WARN", abs(diff)
    return "OK", 0.0


# ---------------------------------------------------------------------------
# running games, or reading saved replays
# ---------------------------------------------------------------------------
_AGENT = None


def _seat_of(rep, spec):
    """Which seat to analyse. ``auto`` finds the configured team (default DSM), else TEST_SEAT."""
    if spec not in (None, "auto"):
        return int(spec)
    return team_mod.seat_of_names((rep.get("info") or {}).get("TeamNames") or [],
                                  fallback=TEST_SEAT)


def _reduce_obj(obj, seat, phase, day0, day1):
    return reduce_game(extract(obj, seat), phase, day0, day1)


def reduce_replays(paths, phase, seat="auto"):
    """Reduce a list of replay JSONs, one per game, with the phase's DAG metrics."""
    from tools.diagnose.games import load_replay
    spec = PHASES[phase]
    day0, day1 = spec["days"]
    out = []
    for p in paths:
        rep = load_replay(p)
        out.append(_reduce_obj(rep, _seat_of(rep, seat), phase, day0, day1))
    return out


def _worker(task):
    """Run one (opponent, seed) truncated at the phase boundary and reduce it."""
    pa, seed, steps, phase, day0, day1 = task
    global _AGENT
    if _AGENT is None:
        _AGENT = load_agent(fresh=True)
    opp = load_public_agent(pa)
    env = run_game(_AGENT, opp, seed=seed, episode_steps=steps, seat=TEST_SEAT, audit=False)
    return _reduce_obj(env, TEST_SEAT, phase, day0, day1)


def run_phase(phase, pa_indices, seeds, workers=None):
    """→ list of per-game metric dicts, one per (opponent, seed)."""
    spec = PHASES[phase]
    steps, (day0, day1) = spec["steps"], spec["days"]
    tasks = [(pa, s, steps, phase, day0, day1) for pa in pa_indices for s in seeds]
    w = int(workers or os.cpu_count() or 1)
    out = []
    if w <= 1 or len(tasks) <= 1:
        for t in tasks:
            out.append(_worker(t))
    else:
        ctx = mp.get_context("fork")
        with ctx.Pool(processes=min(w, len(tasks))) as pool:
            out = list(pool.imap_unordered(_worker, tasks))
    global _AGENT
    _AGENT = None
    return out


def _full_worker(task):
    """Run one game to the BELL and return its extracted day series (unreduced).

    This is what makes `--phase all` cheap: one full run yields all three phases,
    because each phase is just a day window over the same game.
    """
    pa, seed, steps = task
    global _AGENT
    if _AGENT is None:
        _AGENT = load_agent(fresh=True)
    opp = load_public_agent(pa)
    env = run_game(_AGENT, opp, seed=seed, episode_steps=steps, seat=TEST_SEAT, audit=False)
    return extract(env, TEST_SEAT)


def extract_games(pa_indices, seeds, workers=None, steps=None):
    """Run every (opponent, seed) ONCE to `steps` and return their day series."""
    steps = steps or PHASES["phase3"]["steps"]
    tasks = [(pa, s, steps) for pa in pa_indices for s in seeds]
    w = int(workers or os.cpu_count() or 1)
    if w <= 1 or len(tasks) <= 1:
        out = [_full_worker(t) for t in tasks]
    else:
        ctx = mp.get_context("fork")
        with ctx.Pool(processes=min(w, len(tasks))) as pool:
            out = list(pool.imap_unordered(_full_worker, tasks))
    global _AGENT
    _AGENT = None
    return out


def extract_replays(paths, seat="auto"):
    """Parse each replay ONCE -> [(day series, seat)] for every phase to reuse."""
    from tools.diagnose.games import load_replay
    out = []
    for p in paths:
        rep = load_replay(p)
        out.append(extract(rep, _seat_of(rep, seat)))
    return out


# ---------------------------------------------------------------------------
# the causal graph
# ---------------------------------------------------------------------------
def _graph():
    parents, children = defaultdict(set), defaultdict(set)
    mech = {}
    for a, b, why in EDGES:
        parents[b].add(a)
        children[a].add(b)
        mech[(a, b)] = why
    return parents, children, mech


def _reach(start, adj):
    out, stack = set(), list(adj.get(start, ()))
    while stack:
        n = stack.pop()
        if n in out:
            continue
        out.add(n)
        stack.extend(adj.get(n, ()))
    return out


def analyse(phase, per_game, ref_game=None):
    """Aggregate + status, then separate roots from symptoms.

    ``ref_game`` is an optional list of per-game metric dicts for the REFERENCE arm
    (e.g. the #1's own replays). When given, each target is that arm's median for the
    same metric and phase -- the same reduction applied to real measured games, which
    is strictly better than the transcribed table and removes any transcription risk.
    """
    # the keys are exactly what reduce_game emitted for this window (works for a
    # custom --days window that spans two phases)
    keys = [k for k in METRICS if per_game and k in per_game[0]]
    if not keys:
        n = _pnum(phase)
        keys = [k for k, m in METRICS.items() if n is not None and m["phase"] == n]
    rows = {}
    for k in keys:
        vals = [g[k] for g in per_game if k in g]
        ours = st.median(vals) if vals else 0.0
        m = METRICS[k]
        if ref_game is not None:
            _rv = [g[k] for g in ref_game if k in g]
            target = st.median(_rv) if _rv else None
        else:
            series = _dsm_series(m, *PHASES[phase]["days"])
            target = _agg(series, m["agg"]) if series else None
        status, gap = _status(m, ours, target)
        # keep the raw per-game vector: a median over a bimodal population hides the
        # very thing we are hunting (some games the calendar fills, some it does not).
        rvals = None
        if ref_game is not None:
            rvals = [g[k] for g in ref_game if k in g]
        rows[k] = dict(key=k, ours=ours, target=target, status=status, gap=gap,
                       vals=vals, rvals=rvals, **m)

    bad = {k for k, r in rows.items() if r["status"] == "BAD"}
    parents, children, mech = _graph()
    # every metric is a node even across phases; a bad ancestor in ANY phase counts
    roots = []
    for k in sorted(bad):
        anc = _reach(k, parents) & bad
        anc.discard(k)
        if not anc:
            blast = _reach(k, children) & bad
            roots.append((k, blast))
    roots.sort(key=lambda kv: (-len(kv[1]), kv[0]))
    return rows, bad, roots, (parents, children, mech)


# ---------------------------------------------------------------------------
# printing
# ---------------------------------------------------------------------------
def _fmt(v):
    if v is None:
        return "    -"
    if abs(v) >= 100:
        return f"{v:>7.0f}"
    if abs(v) >= 10:
        return f"{v:>7.1f}"
    return f"{v:>7.2f}"


def print_table(phase, rows, n_games, source, target_label):
    spec = PHASES[phase]
    d0, d1 = spec["days"]
    print(f"\n############ {phase} ({spec['name']}, d{d0}-d{d1}) — "
          f"{n_games} games ({source}) ############")
    print(f"   {spec['question']}")
    print(f"   reference: {target_label}")
    print(f"   both arms reduced over d{d0}-d{d1} with the SAME aggregation\n")
    print(f"   {'metric':<30}{'ours':>8}{'#1':>8}{'ratio':>8}  {'':<4} {'owner'}")
    print("   " + "-" * 108)
    order = sorted(rows.values(), key=lambda r: ({"BAD": 0, "WARN": 1, "-": 2, "OK": 3}[r["status"]],
                                                 r["key"]))
    for r in order:
        t = r["target"]
        ratio = (r["ours"] / t) if (t not in (None, 0)) else float("nan")
        rs = f"{ratio:>7.2f}x" if t not in (None, 0) else "      -"
        mark = {"BAD": "BAD ", "WARN": "WARN", "OK": "ok  ", "-": "·   "}[r["status"]]
        print(f"   {r['label']:<30}{_fmt(r['ours'])}{_fmt(t)}{rs}  {mark} {r['owner']}")
    return order



def _pct(xs, f):
    """Percentile with nearest-rank, so p90 of 12 games is the 11th value, not an interp."""
    if not xs:
        return float("nan")
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(round(f * (len(xs) - 1))))]


def print_spread(phase, rows, ref_label=None):
    """Per-metric distribution, ours (and the reference arm when one was given).

    Why this exists: `print_table` reports medians, and a median over a bimodal
    population hides exactly the defect worth chasing -- e.g. the planted-tile count
    after the opening is ~11 in every game, but the *empty tile* count and `plants
    died` split into two clusters that a single number averages away.
    """
    def block(title, key):
        print(f"   {'metric':<30}{'p10':>9}{'p25':>9}{'med':>9}{'p75':>9}{'p90':>9}"
              f"{'min':>9}{'max':>9}   {title}")
        for r in sorted(rows.values(), key=lambda r: r["key"]):
            xs = r.get(key) or []
            if not xs:
                continue
            cells = "".join(f"{_pct(xs, f):>9.1f}" for f in (.1, .25, .5, .75, .9))
            print(f"   {r['label']:<30}{cells}{min(xs):>9.1f}{max(xs):>9.1f}")
        print()

    print(f"\n############ {phase}: distribution, not just the median ############")
    block("ours", "vals")
    if any(r.get("rvals") for r in rows.values()):
        print(f"   -- reference arm{' (' + ref_label + ')' if ref_label else ''} --")
        block("reference", "rvals")


def print_trace(phase, rows, bad, roots, g):
    """Every deficient metric, traced UPSTREAM all the way to its origins.

    Reading it: '-> x' means x is an ancestor (an upstream cause). A chain that
    starts on a deficient metric and ends on an exogenously-deficient one is the
    chain to attack; the last node printed is the furthest upstream cause the graph
    knows about. Ancestors outside this phase are shown too (that is how a
    beginning defect shows up as a downstream consequence).
    """
    parents, children, mech = g
    print(f"\n############ causal trace ({phase}) ############")
    print("   each deficient metric traced UP its causes; the deepest line is the "
          "furthest upstream\n")

    def label(k):
        return METRICS[k]["label"] if k in METRICS else k

    def status_of(k):
        if k in rows:
            return rows[k]["status"]
        return METRICS[k]["phase"] if k in METRICS else "?"

    for k in sorted(bad):
        print(f"   {label(k)} = {rows[k]['ours']:.2f}"
              f" vs {rows[k]['target']:.2f}   [ BAD ]")
        # (node, depth, seen, child) -- `child` is what we walked down from, so the
        # mechanism printed is the real parent->child edge.
        stack = [(p, 1, set(), k) for p in sorted(parents.get(k, ()))]
        paths = []
        while stack:
            n, depth, seen, child = stack.pop()
            if n in seen:
                continue
            seen = seen | {n}
            paths.append((depth, n, mech.get((n, child), ""), seen))
            for p in sorted(parents.get(n, ())):
                stack.append((p, depth + 1, seen, n))
        # print shallowest-first, so the convergence point is visible
        for depth, n, why, _ in sorted(paths)[:10]:
            tag = rows[n]["status"] if n in rows else f"phase{METRICS[n]['phase']}"
            print(f"      {'   ' * (depth - 1)}<- {label(n):<30} [{tag}]  {why}")
        if len(paths) > 10:
            print(f"      ... {len(paths) - 10} more ancestor nodes")
        print()

    if roots:
        print(f"############ ROOTS — fix these, not their symptoms ############\n")
        for i, (k, blast) in enumerate(roots, 1):
            r = rows[k]
            t = r["target"]
            tgt = "no target" if t is None else f"{r['ours']:.2f} vs {t:.2f}"
            print(f" {i}. {r['label']}  ({tgt})")
            print(f"    {r['desc']}")
            print(f"    owner: {r['owner']}")
            if blast:
                names = ", ".join(rows[b]["label"] if b in rows else b for b in sorted(blast))
                print(f"    explains {len(blast)} other deficient metric(s): {names}")
            fed = [b for b in children.get(k, ()) if b in rows]
            if fed:
                print("    downstream mechanisms:")
                for b in sorted(fed)[:6]:
                    print(f"      -> {rows[b]['label']}: {mech.get((k, b), '')}")
            print()
    else:
        print(" no roots: no metric is deficient with a healthy upstream chain.\n")


def print_dag(phase=None):
    """Print the causal graph; with `phase`, only that phase's subgraph.

    A pruned view is how you read the opening in isolation: it keeps every metric
    the phase-1 window actually measures, plus (separately) the edges *leaving* the
    window, which are the hypotheses that the opening roots the rest of the season.
    """
    parents, children, mech = _graph()
    keep = None
    if phase:
        pnum = _pnum(phase)
        if pnum is None:
            keep = {k for k, m in METRICS.items() if phase in (m.get("label") or "")}
        else:
            keep = {k for k, m in METRICS.items() if m.get("phase") == pnum}
    title = "the causal DAG" if not phase else f"the causal DAG — {phase} subgraph only"
    print(f"############ {title} ############\n")
    for k in METRICS:
        if keep is not None and k not in keep:
            continue
        kids = sorted(b for b in children.get(k, ())
                      if keep is None or b in keep or b in METRICS)
        inside = [b for b in kids if keep is None or b in keep]
        if not inside:
            continue
        print(f"  {METRICS[k]['label']}")
        for b in inside:
            label = METRICS[b]["label"] if b in METRICS else b
            print(f"     -> {label:<32} {mech.get((k, b), '')}")
    if keep is not None:
        out = []
        for k in sorted(keep):
            for b in sorted(children.get(k, ())):
                if b in keep:
                    continue
                if b in METRICS:
                    label = f"{METRICS[b]['label']} [p{METRICS[b].get('phase')}]"
                else:
                    label = b
                out.append(f"     {METRICS[k]['label']}  ->  [{label}]  {mech.get((k, b), '')}")
        print(f"\n  -- edges LEAVING this window (the opening's downstream reach) --")
        print("\n".join(out) if out else "     (none)")
    cyc = [k for k in METRICS if (keep is None or k in keep) and k in _reach(k, parents)]
    print(f"\n  nodes: {len(keep) if keep is not None else len(METRICS)}"
          f"   edges shown: {sum(1 for k in (keep or METRICS) for b in children.get(k, ()) if keep is None or b in keep)}")
    print(f"  feedback cycles: {cyc or 'none'}")


# ---------------------------------------------------------------------------
def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--phase", default="phase1", choices=("phase1", "phase2", "phase3", "all"))
    # live-run sampling
    ap.add_argument("--pa", default="1-2", help="Public agent indices (default: 1-2 for a quick check)")
    ap.add_argument("--batch", type=int, default=1, help="Seeds per opponent")
    ap.add_argument("--seed", type=int, default=4362837462)
    ap.add_argument("--workers", type=int, default=None)
    # replay mode: analyse saved games instead of running them
    ap.add_argument("--replay-dir", help="Analyse saved replay JSONs in this dir")
    ap.add_argument("--replay", action="append", default=None,
                    help="Analyse one replay JSON (repeatable)")
    ap.add_argument("--glob", default="*.json", help="Glob inside --replay-dir")
    ap.add_argument("--seat", default="auto",
                    help="Seat to analyse: auto (find DSM else seat 1) | 0 | 1")
    ap.add_argument("--max-games", type=int, default=0, help="Cap the replays analysed (0=all)")
    # the reference arm
    ap.add_argument("--ref-from", default=None,
                    help="Derive the targets from these replays instead of the table, "
                         "e.g. --ref-from replays/DSM/v1 (the #1's own games)")
    ap.add_argument("--ref-glob", default="*.json")
    ap.add_argument("--ref-max", type=int, default=12, help="Replays sampled from --ref-from")
    ap.add_argument("--ref-seat", default="auto")
    ap.add_argument("--dag", nargs="?", const="all", default=None,
                    help="Print the DAG definition and exit; optionally pruned to a phase "
                         "(--dag phase1 = the opening subgraph only)")
    ap.add_argument("--days", default=None,
                    help="custom day window, overrides --phase (e.g. 0-5 or 0-5,12-17)")
    ap.add_argument("--spread", action="store_true",
                    help="also print per-metric p10/p25/median/p75/p90/min/max for ours "
                         "(and the reference arm). Use this: a median over a bimodal "
                         "population hides the defect you are hunting.")
    ap.add_argument("--team", default=None,
                    help="leaderboard team to analyse (default: DSM / $KAGG_OPPONENT)")
    ns = ap.parse_args(argv)
    team_mod.set_team(ns.team)

    from .dag import PHASES as _PHASES

    if ns.days:
        _rng = parse_days(ns.days)
        _d0 = min(_rng[0]) if _rng else 0
        _d1 = max(_rng[-1]) if _rng else 29
        _PHASES["custom"] = {"days": (_d0, _d1), "steps": (_d1 + 1) * 24,
                             "name": f"custom {describe(_rng)}",
                             "question": "custom day window"}

    if ns.dag:
        print_dag(None if ns.dag == "all" else ns.dag)
        return 0

    phases = ["phase1", "phase2", "phase3"] if ns.phase == "all" else (
        ["custom"] if ns.days else [ns.phase])

    # ---- what are we measuring? saved replays, or a fresh run ------------------
    replay_paths = None
    if ns.replay_dir or ns.replay:
        from pathlib import Path
        if ns.replay:
            replay_paths = [Path(p) for p in ns.replay]
        else:
            replay_paths = sorted(Path(ns.replay_dir).glob(ns.glob))
        if not replay_paths:
            raise SystemExit(f"no replay JSONs in {ns.replay_dir} matching {ns.glob}")
        if ns.max_games:
            replay_paths = replay_paths[:ns.max_games]
        source = f"{len(replay_paths)} replays, seat={ns.seat}"
        print(f"phase_map — structural phase audit (REPLAY mode)")
        print(f"   replays  : {ns.replay_dir or ', '.join(str(p) for p in replay_paths)}")
        print(f"   seat     : {ns.seat}   analysed: {len(replay_paths)}")
    else:
        pa_indices = _parse_pa_arg(ns.pa)
        for pa in pa_indices:
            if pa not in PUBLIC_AGENT_MAP:
                raise SystemExit(f"unknown public agent #{pa}")
        seeds = _make_seeds(ns.batch, ns.seed)
        source = f"live, {len(pa_indices)} opponents x {len(seeds)} seeds"
        print(f"phase_map — structural phase audit (LIVE mode)")
        print(f"   opponents: {ns.pa}  seeds: {len(seeds)}  games/phase: "
              f"{len(pa_indices) * len(seeds)}")

    # ---- the reference arm (targets) -------------------------------------------
    ref_paths = None
    if ns.ref_from:
        from pathlib import Path
        ref_paths = sorted(Path(ns.ref_from).glob(ns.ref_glob))[:ns.ref_max]
        if not ref_paths:
            raise SystemExit(f"no reference replays in {ns.ref_from}")
        target_label = (f"{len(ref_paths)} replays from {ns.ref_from} "
                        f"(seat={ns.ref_seat}), reduced identically")
    else:
        target_label = f"the #1's per-day table — {DSM_DAILY_SOURCE}"

    print(f"   truncated at: " + ", ".join(f"{p}=d{PHASES[p]['days'][1]}"
                                          f"({PHASES[p]['steps']} steps)" for p in phases))
    print(f"   reference : {target_label}")

    # `--phase all` runs each game ONCE to the bell and slices the phases out of it;
    # a single phase truncates the game at its own boundary (cheaper still).
    ours_days = ref_days = None
    if len(phases) > 1 and replay_paths is None:
        ours_days = extract_games(pa_indices, seeds, ns.workers)
    elif len(phases) > 1:
        ours_days = extract_replays(replay_paths, ns.seat)
    if len(phases) > 1 and ref_paths is not None:
        ref_days = extract_replays(ref_paths, ns.ref_seat)

    for phase in phases:
        d0, d1 = PHASES[phase]["days"]
        if ours_days is not None:
            per_game = [reduce_game(g, phase, d0, d1) for g in ours_days]
        elif replay_paths is not None:
            per_game = reduce_replays(replay_paths, phase, ns.seat)
        else:
            per_game = run_phase(phase, pa_indices, seeds, ns.workers)
        if ref_days is not None:
            ref_game = [reduce_game(g, phase, d0, d1) for g in ref_days]
        elif ref_paths is not None:
            ref_game = reduce_replays(ref_paths, phase, ns.ref_seat)
        else:
            ref_game = None
        rows, bad, roots, g = analyse(phase, per_game, ref_game)
        print_table(phase, rows, len(per_game), source, target_label)
        if ns.spread:
            print_spread(phase, rows, target_label)
        print_trace(phase, rows, bad, roots, g)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
