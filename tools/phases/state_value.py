#!/usr/bin/env python
"""state_value — price the d5 state, and see which d5 features predict the finish.

Why this exists
---------------
`phase_map` tells you the opening is structurally deficient. It cannot tell you what
a deficient opening is *worth*, because it only counts things. The opening is
**6.5% of the season's revenue gap** (measured: -$5,280 of -$81,050), while a
whole-game margin has sigma ~= $10k on 12 games — so any A/B judged on the final
bank is underpowered by construction (both opening A/Bs so far had p > 0.05 or a
sign that flipped with the sample).

Two ways to get power back, both computed here:

1. **Price the d5 state** (policy-free floor + net asset value). The d5 state's
   liquidation value is a *low-variance* readout: it is cash plus the shed marked at
   the d5 price, both directly observed. If the opening has a real defect, it shows
   up here long before it shows up in the terminal bank.

2. **Continue the game from d5 under a frozen policy.** A prefix roll-out is
   deterministic (the agent is stateless), so we can re-run the first 144 steps
   exactly and then hand the remaining 576 to a different policy. The terminal banks
   under `live` / `nobuy` / `liquidate` give the *option value* still embedded in the
   d5 state: `max(term) - min(term)` is what the d5 position is still worth in
   decisions, and `term_liquidate - d5_liquid` is what the season still has to add.

3. **Regress the terminal bank on the d5 state.** The DAG asserts which structural
   quantities matter; this measures it. Standardised coefficients on d5 cash / shed
   value / crop units / herd units / land tiles say which of them the *market*
   actually pays for, and R^2 says how much of the finish was already determined by
   day 5. A high R^2 with the DAG's favoured node at ~0 is the graph being wrong.

Usage
-----
    # our arm, live roll-outs (one 720-step game per opponent x seed)
    PYTHONPATH=. python -m tools.phases.state_value --pa 1-2 --batch 2

    # add the frozen continuations (3x the compute, one per continuation)
    PYTHONPATH=. python -m tools.phases.state_value --pa 1-2 --batch 2 \\
        --cont live,nobuy,liquidate

    # the #1's own d5 state, from his leaderboard replays (no continuation needed)
    PYTHONPATH=. python -m tools.phases.state_value --ref-from replays/DSM/v1 --ref-max 40

Notes on the valuation model (every term is an assumption, printed, never combined
silently):
  * cash and shed are exact and policy-free (marked at the d5 market price).
  * crops are marked at expected *gross* revenue; WATER is a free action in this
    engine, so there is no cash cost to subtract, only risk (a plant that dies
    returns 0). We mark single-harvest crops at their peak yield while they are
    still inside the harvest window and ongoing crops at their remaining production
    days x per-yield units.
  * animals are marked at remaining production x price, minus one wheat per animal
    per remaining day at the d5 wheat price (COW/SHEEP/GOOSE: first yield d8/d6/d4,
    interval 2/3/1, $160/$200/$50).
  * land is reported as a *capacity* count, never folded into NAV: a tile is only
    worth what you plant on it, and that is a decision, not a state.
"""
from __future__ import annotations

import argparse
import inspect
import json
import os
import statistics as st
import sys
from collections import Counter
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from kaggle_environments import make                      # noqa: E402

from tools.diagnose.agents import load_agent, load_public_agent   # noqa: E402
from tools.phases.phase_map import _make_seeds, _parse_pa_arg, _seat_of   # noqa: E402

DAY = 24
SEASON_DAYS = 30
CUT_DAY = 5
CUT_STEP = (CUT_DAY + 1) * DAY          # the first step of d6
DEFAULT_SEED = 4362837462
TEST_SEAT = 1

# ---- crop and animal payoff tables (GAME_DYNAMICS.md §crops / §animals) --------
# name: (first_yield_day, interval, max_yields, peak_single_harvest, window_end_age)
CROP = {
    "WHEAT":      dict(ongoing=False, peak=4, last_age=4),   # max_yield 6 fertilised
    "CARROT":     dict(ongoing=False, peak=3, last_age=3),
    "MELON":      dict(ongoing=False, peak=6, last_age=12),
    "STRAWBERRY": dict(ongoing=True, first=10, interval=2, yields=4),
    "TOMATO":     dict(ongoing=True, first=8, interval=1, yields=4),
}
ANIMAL = {
    "COW":   dict(first_day=8,  interval=2, price="MILK"),
    "SHEEP": dict(first_day=6,  interval=3, price="WOOL"),
    "GOOSE": dict(first_day=4,  interval=1, price="EGG"),
}
FEED_PER_DAY = 1.0


# ---------------------------------------------------------------------------
# the d5 state and its price
# ---------------------------------------------------------------------------
def _tile_animal(t):
    return t.get("animal") or t.get("animal_type")


def crops_value(tiles, day, prices):
    """Expected remaining GROSS revenue of every standing plant, + units counted."""
    dollars = 0.0
    units = 0
    detail = Counter()
    for row in tiles:
        for t in row:
            if not (isinstance(t, dict) and t.get("kind") == "PLANT"):
                continue
            crop = t.get("crop")
            spec = CROP.get(crop)
            if spec is None:
                continue
            detail[crop] += 1
            price = float(prices.get(crop) or 0)
            ready = int(t.get("yield_units") or 0)
            if ready > 0:
                units += ready
                dollars += ready * price
                continue
            age = day - int(t.get("planted_day") or day)
            if spec["ongoing"]:
                # production days left in the season for an ongoing crop
                first, iv, ny = spec["first"], spec["interval"], spec["yields"]
                left = 0
                for k in range(ny):
                    if first + k * iv >= age and day + (first + k * iv - age) <= SEASON_DAYS - 1:
                        left += 1
                units += left
                dollars += left * price
            else:
                if age <= spec["last_age"]:
                    units += spec["peak"]
                    dollars += spec["peak"] * price
    return dollars, units, detail


def herd_value(tiles, day, prices):
    """Expected remaining net revenue of every animal (production - feed)."""
    dollars = 0.0
    units = 0
    detail = Counter()
    feed_price = float(prices.get("WHEAT") or 0)
    for row in tiles:
        for t in row:
            if not isinstance(t, dict):
                continue
            a = _tile_animal(t)
            if not a or a not in ANIMAL:
                continue
            detail[a] += 1
            spec = ANIMAL[a]
            n = 0
            for d in range(day + 1, SEASON_DAYS):
                age = d - int(t.get("born_day") or t.get("placed_day") or day)
                if age >= spec["first_day"] and (age - spec["first_day"]) % spec["interval"] == 0:
                    n += 1
            units += n
            dollars += n * float(prices.get(spec["price"]) or 0)
            dollars -= FEED_PER_DAY * max(0, SEASON_DAYS - 1 - day) * feed_price
    return dollars, units, detail


def price_d5(obs, seat):
    """The d5 state as a priced vector. Every term is reported, none is hidden."""
    farm = obs["farms"][seat]
    priv = obs.get("private") or {}
    prices = (obs.get("market") or {}).get("prices") or {}
    day = int(obs.get("day") or CUT_DAY)
    tiles = farm["tiles"]

    cash = float(farm.get("money") or 0.0)
    shed = {k: int(v) for k, v in (priv.get("shed") or {}).items() if v}
    # seed stock is a real asset too, marked at the buy price
    shed_value = sum(q * float(prices.get(p) or 0) for p, q in shed.items() if p in prices)

    crop_val, crop_units, crop_detail = crops_value(tiles, day, prices)
    herd_val, herd_units, herd_detail = herd_value(tiles, day, prices)

    owned = empty = weeds = structures = 0
    for row in tiles:
        for t in row:
            if t == "LOCKED":
                continue
            owned += 1
            if t is None:
                empty += 1
            elif isinstance(t, dict):
                if t.get("kind") == "WEED":
                    weeds += 1
                elif t.get("kind") in ("COOP", "PASTURE"):
                    structures += 1

    quadrants = len(farm.get("unlocked_quadrants") or [])
    return {
        "day": day,
        "cash": cash,
        "shed_value": shed_value,
        "shed_units": sum(shed.values()),
        "liquid": cash + shed_value,                 # policy-free floor
        "crop_value": crop_val,
        "crop_units": crop_units,
        "crop_tiles": sum(crop_detail.values()),
        "herd_value": herd_val,
        "herd_units": herd_units,
        "animals": sum(herd_detail.values()),
        "nav": cash + shed_value + crop_val + herd_val,
        "capacity_tiles": owned,
        "empty_tiles": empty,
        "weeds": weeds,
        "structures": structures,
        "quadrants": quadrants,
        "hands": len(farm.get("hands") or []),
        "crops": dict(crop_detail),
        "herd": dict(herd_detail),
        "prices": prices,
    }


# ---------------------------------------------------------------------------
# continuations
# ---------------------------------------------------------------------------
def _pass_action(obs):
    farm = obs["farms"][obs.get("player", TEST_SEAT)]
    return {"farmer": ["PASS"], "hands": [["PASS"] for _ in farm.get("hands") or []],
            "market": []}


def _strip_buys(action):
    """Keep unit actions; keep only SELL orders in the market list."""
    out = dict(action or {})
    out["market"] = [o for o in (action or {}).get("market") or []
                     if o and o[0] == "SELL"]
    return out


def _liquidate(action, obs, seat, step):
    """Sell the whole shed for a few turns, then do nothing at all.

    Pure liquidation floor: no watering, no harvesting, no hiring. It prices the
    d5 *state* (cash + shed), not the d5 *plan*.
    """
    if step >= CUT_STEP + 4:
        return _pass_action(obs)
    base = _pass_action(obs)
    shed = (obs.get("private") or {}).get("shed") or {}
    base["market"] = [["SELL", p, 1000] for p, q in shed.items() if q > 0][:10]
    return base


def _nobuy(action, obs, seat, step):
    """Our own plan, but forbidden to spend: can the d5 state sustain itself?"""
    return _strip_buys(action)


CONT = {
    "live":      lambda a, obs, seat, step: a,
    "nobuy":     _nobuy,
    "liquidate": _liquidate,
}


def _terminal(env, seat):
    last = env.state[seat]
    r = last.get("reward")
    if r is not None:
        return float(r)
    return float((last.get("observation") or {}).get("farms", [{}])[seat].get("money") or 0.0)


def _call(fn, obs):
    """Call an agent with the config only if it accepts one.

    `env.run` passes `(observation, configuration)`, but some public agents define
    `agent(observation)` only. Inspecting the signature (rather than catching
    TypeError) keeps a genuine TypeError raised *inside* an agent from being masked.
    """
    try:
        n = len([p for p in inspect.signature(fn).parameters.values()
                 if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)])
    except (TypeError, ValueError):
        n = 1
    return fn(obs, {}) if n >= 2 else fn(obs)


def rollout(agent, opp_fn, seed, cont="live", cut_step=CUT_STEP, steps=720,
            seat=TEST_SEAT, post_fn=None):
    """One game, with the policy swapped at `cut_step`. Returns (env, d5 snapshot).

    `post_fn` overrides the continuation entirely: that is how `--cross` holds the
    policy after d5 FIXED while the prefix changes, which is the only way to tell a
    better d5 *state* from a better post-d5 *policy*.
    """
    env = make("kaggriculture", configuration={"episodeSteps": steps, "seed": seed})
    env.reset()
    switch = CONT[cont]
    snapshot = None
    for t in range(steps):
        obs = [env.state[i]["observation"] for i in range(2)]
        a_opp = _call(opp_fn, obs[1 - seat])
        if t < cut_step:
            a_us = _call(agent, obs[seat])
        elif post_fn is not None:
            a_us = _call(post_fn, obs[seat])
        else:
            a_us = switch(_call(agent, obs[seat]), obs[seat], seat, t)
        acts = [None, None]
        acts[seat] = a_us
        acts[1 - seat] = a_opp
        env.step(acts)
        if t == cut_step - 1:
            # the state AFTER the last d5 action: day-5 end-of-day has run (the
            # 23:00 drop, weeds and refresh), so this is exactly `steps[144]` of a
            # saved replay. Capturing it before the step would be one hour early
            # and would not line up with the replay path.
            snapshot = json.loads(json.dumps(env.state[seat]["observation"]))
        if env.done:
            break
    return env, snapshot


# ---------------------------------------------------------------------------
# the reference arm: read the d5 + terminal state out of saved replays
# ---------------------------------------------------------------------------
def _steps_of(rep):
    return rep.steps if hasattr(rep, "steps") else rep.get("steps", [])


def from_replay(path, seat="auto"):
    from tools.diagnose.games import load_replay
    rep = load_replay(Path(path))
    steps = _steps_of(rep)
    s = _seat_of(rep, seat)
    if len(steps) <= CUT_STEP or len(steps[CUT_STEP]) <= s:
        return None
    obs = steps[CUT_STEP][s]["observation"]
    v = price_d5(obs, s)
    v["term_live"] = float(steps[-1][s].get("reward") or
                           steps[-1][s]["observation"]["farms"][s].get("money") or 0.0)
    v["term_nobuy"] = v["term_liquidate"] = None
    v["opponent"] = (rep.get("info") or {}).get("TeamNames", [None, None])[1 - s]
    v["seed"] = (rep.get("info") or {}).get("seed")
    return v


def _worker(task):
    pa, seed, conts = task
    global _AGENT
    if _AGENT is None:
        _AGENT = load_agent(fresh=True)
    opp = load_public_agent(pa)
    out = {}
    for c in conts:
        env, snap = rollout(_AGENT, opp, seed, cont=c)
        if snap is not None:
            v = price_d5(snap, TEST_SEAT)
        else:                                   # pragma: no cover - defensive
            v = {"nav": 0.0}
        v["term_" + c] = _terminal(env, TEST_SEAT)
        v["opponent"] = pa
        v["seed"] = seed
        out[c] = v
    # the d5 snapshot is identical across continuations (same seed, same prefix):
    # keep the first, and attach every terminal to it
    base = dict(out[conts[0]])
    for c in conts:
        base["term_" + c] = out[c]["term_" + c]
    return base


_AGENT = None


# ---------------------------------------------------------------------------
# reporting
# ---------------------------------------------------------------------------
VECTORS = (
    ("cash", "dollars in the bank at d5"),
    ("shed_value", "shed marked at the d5 price"),
    ("crop_units", "standing crop units expected"),
    ("herd_units", "animal production days remaining"),
    ("capacity_tiles", "owned (+25/quadrant) -- capacity, not value"),
)


def _ols(rows, features, target):
    """Plain OLS on standardised features: ([slopes], R^2, n, kept_features).

    Features with no spread at the cut day carry no information and would only
    make the design singular (at d5 `capacity_tiles` is 25 in nearly every game),
    so they are dropped and reported as such.
    """
    ys = [r[target] for r in rows if target in r and r.get(target) is not None]
    if len(ys) < 3:
        return None
    X0 = [[r.get(f, 0.0) or 0.0 for f in features] for r in rows
          if target in r and r.get(target) is not None]
    Y = [r[target] for r in rows if target in r and r.get(target) is not None]
    keep = [i for i in range(len(features))
            if st.pstdev([x[i] for x in X0]) > 1e-9]
    dropped = [features[i] for i in range(len(features)) if i not in keep]
    if not keep or len(Y) < len(keep) + 2:
        return None
    X = [[x[i] for i in keep] for x in X0]
    kept = [features[i] for i in keep]
    p = len(kept)
    mu = [st.mean(col) for col in zip(*X)]
    sd = [st.pstdev(col) or 1.0 for col in zip(*X)]
    Z = [[(x[i] - mu[i]) / sd[i] for i in range(p)] + [1.0] for x in X]
    my = st.mean(Y)
    Yc = [y - my for y in Y]
    # normal equations with a small ridge for stability on tiny samples
    A = [[sum(Z[k][i] * Z[k][j] for k in range(len(Z))) + (1e-6 if i == j else 0)
          for j in range(p + 1)] for i in range(p + 1)]
    b = [sum(Z[k][i] * Yc[k] for k in range(len(Z))) for i in range(p + 1)]
    for i in range(p + 1):                        # Gaussian elimination
        piv = max(range(i, p + 1), key=lambda r: abs(A[r][i]))
        A[i], A[piv] = A[piv], A[i]
        b[i], b[piv] = b[piv], b[i]
        if abs(A[i][i]) < 1e-12:
            continue
        for r in range(i + 1, p + 1):
            f = A[r][i] / A[i][i]
            for c in range(i, p + 1):
                A[r][c] -= f * A[i][c]
            b[r] -= f * b[i]
    coef = [0.0] * (p + 1)
    for i in reversed(range(p + 1)):
        s = b[i] - sum(A[i][j] * coef[j] for j in range(i + 1, p + 1))
        coef[i] = s / A[i][i] if abs(A[i][i]) > 1e-12 else 0.0
    pred = [sum(Z[k][i] * coef[i] for i in range(p + 1)) + my for k in range(len(Z))]
    ss_res = sum((Y[k] - pred[k]) ** 2 for k in range(len(Y)))
    ss_tot = sum((y - my) ** 2 for y in Y) or 1.0
    return coef[:p], 1 - ss_res / ss_tot, len(Y), kept, dropped


def _med(rows, key):
    xs = [r[key] for r in rows if r.get(key) is not None]
    return st.median(xs) if xs else float("nan")



# ---------------------------------------------------------------------------
# --cross: prefix/continuation 2x2
# ---------------------------------------------------------------------------
def _load_with(params):
    """Re-execute `src` under `params` and return its agent.

    A params change is a different module state, so every `src.*` module is dropped
    and re-imported. Agents already returned keep the old modules alive through their
    ``__globals__``, which is exactly what lets arm C run a combo prefix and a neutral
    continuation in one process.
    """
    os.environ.pop("SCRATCH_PARAMS", None)
    if params:
        os.environ["SCRATCH_PARAMS"] = params
    for m in [m for m in sys.modules if m == "src" or m.startswith("src.")]:
        del sys.modules[m]
    import src
    return src.agent


def _cross_worker(task):
    pa, seed, params, post = task
    from tools.diagnose.agents import load_public_agent
    opp = load_public_agent(pa)
    neutral = _load_with(None)
    a = _terminal(rollout(neutral, opp, seed)[0], TEST_SEAT)
    armed = _load_with(params)
    b = _terminal(rollout(armed, opp, seed)[0], TEST_SEAT)
    neutral2 = _load_with(post)
    c = _terminal(rollout(armed, opp, seed, post_fn=neutral2)[0], TEST_SEAT)
    os.environ.pop("SCRATCH_PARAMS", None)
    return {"pa": pa, "seed": seed, "A": a, "B": b, "C": c,
            "d_state": c - a, "d_policy": b - c, "d_total": b - a}


def _report_cross(rows, params, post_label=None):
    print(f"\n############ 2x2 cross — prefix vs continuation (`{params}`) ############")
    print(f"   {'pa':>3}{'A base':>10}{'B arm/arm':>11}{'C arm/base':>12}"
          f"{'d_state C-A':>13}{'d_policy B-C':>14}{'d_total B-A':>13}")
    for r in sorted(rows, key=lambda r: r["pa"]):
        print(f"   {r['pa']:>3}{r['A']:>10,.0f}{r['B']:>11,.0f}{r['C']:>12,.0f}"
              f"{r['d_state']:>13,.0f}{r['d_policy']:>14,.0f}{r['d_total']:>13,.0f}")
    print()
    for k, why in (("d_state", f"the d5 STATE, held under a FIXED `{post_label or 'tree-default'}` policy"),
                   ("d_policy", "the post-d5 POLICY, from a FIXED arm state"),
                   ("d_total", "the whole arm")):
        xs = [r[k] for r in rows]
        pos = sum(1 for x in xs if x > 0)
        print(f"   median {k:<9} {st.median(xs):>10,.0f}   positive {pos}/{len(xs)}   ({why})")
    print("\n   Reading it: d_state < 0 means the arm's d5 state is worth LESS than the")
    print("   baseline's even with the policy held fixed -- so the opening is not the lever")
    print("   and no d5-state objective can rescue it. d_policy < 0 means the arm's")
    print("   post-d5 play is worse from the same state.")
    print("   CAVEAT: the fixed continuation must at least be able to SERVICE whatever the")
    print("   arm's d5 state contains. A default continuation cannot feed a herd, so a herd")
    print("   prefix measured against it is crippled by construction -- pass --cross-post to")
    print("   give the fixed policy the maintenance layers the state requires.")


def report(rows, arm, conts):
    print(f"\n############ {arm} — d5 state price  ({len(rows)} games) ############")
    print(f"   {'term':<24}{'median':>12}")
    for k, why in VECTORS:
        print(f"   {k:<24}{_med(rows, k):>12,.0f}   {why}")
    print(f"   {'liquid (cash+shed)':<24}{_med(rows, 'liquid'):>12,.0f}   "
          f"the policy-free floor at d5")
    print(f"   {'nav (liquid+crops+herd)':<24}{_med(rows, 'nav'):>12,.0f}   "
          f"+- the model's assumptions")
    print(f"\n   {'continuation':<24}{'terminal':>12}{'gain over liquid':>20}")
    liq = _med(rows, "liquid")
    for c in conts:
        t = _med(rows, "term_" + c)
        print(f"   term_{c:<20}{t:>12,.0f}{t - liq:>20,.0f}")
    if len(conts) > 1:
        spread = []
        for r in rows:
            vals = [r.get("term_" + c) for c in conts if r.get("term_" + c) is not None]
            if len(vals) > 1:
                spread.append(max(vals) - min(vals))
        if spread:
            print(f"   option spread (max-min): median ${st.median(spread):,.0f} "
                  f"— what the d5 position is still worth in decisions")

    tl = _med(rows, "term_live")
    nav = _med(rows, "nav")
    print(f"\n   calibration: nav {nav:,.0f} vs realized term_live {tl:,.0f}"
          f"   ->  the model explains {nav / tl * 100 if tl else 0:.0f}% of the finish")

    print(f"\n   -- which d5 feature predicts the terminal bank (standardised OLS) --")
    feats = [k for k, _ in VECTORS]
    fit = _ols(rows, feats, "term_live")
    if fit is None:
        print("   (not enough games / no spread for a regression)")
    else:
        coef, r2, n, kept, dropped = fit
        order = sorted(zip(kept, coef), key=lambda kv: -abs(kv[1]))
        for f, c in order:
            print(f"   {f:<24}{c:>+8.1f} sd-of-terminal per sd-of-feature")
        print(f"   R^2 = {r2:.2f} over {n} games  "
              f"(how much of the finish was already set at d5)")
        if dropped:
            print(f"   dropped (no spread at d5): {', '.join(dropped)}")
    print()


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--pa", default="1-2", help="Public agent indices (default 1-2)")
    ap.add_argument("--batch", type=int, default=1, help="Seeds per opponent")
    ap.add_argument("--seed", type=int, default=DEFAULT_SEED)
    ap.add_argument("--workers", type=int, default=None)
    ap.add_argument("--cont", default="live",
                    help="continuations to run from d5: live,nobuy,liquidate")
    ap.add_argument("--ref-from", default=None,
                    help="read the d5 state from these replays instead (e.g. replays/DSM/v1)")
    ap.add_argument("--ref-glob", default="*.json")
    ap.add_argument("--ref-max", type=int, default=40)
    ap.add_argument("--ref-seat", default="auto")
    ap.add_argument("--cross-post", default="", metavar="PARAMS",
                    help="the FIXED continuation used for cell C of --cross (default: the "
                         "tree defaults). Set this whenever the arm's d5 state needs layers "
                         "the default policy lacks -- e.g. a herd prefix needs "
                         "'HERD_ENABLED=1;HERD_BUY_FROM_DAY=99' (maintain, never expand), "
                         "otherwise cell C lets the animals starve and d_state is crippled")
    ap.add_argument("--cross", default=None, metavar="PARAMS",
                    help="2x2 prefix/continuation cross against these SCRATCH_PARAMS: "
                         "separates a better d5 STATE (fixed continuation) from a better "
                         "post-d5 POLICY (fixed state)")
    ns = ap.parse_args(argv)

    conts = [c.strip() for c in ns.cont.split(",") if c.strip()]
    bad = [c for c in conts if c not in CONT]
    if bad:
        raise SystemExit(f"unknown continuation(s): {bad} (have {sorted(CONT)})")

    if ns.ref_from:
        paths = sorted(Path(ns.ref_from).glob(ns.ref_glob))[:ns.ref_max]
        if not paths:
            raise SystemExit(f"no replays in {ns.ref_from}")
        rows = [r for r in (from_replay(p, ns.ref_seat) for p in paths) if r]
        print(f"state_value — d5 state from {len(rows)} replay(s) in {ns.ref_from}")
        report(rows, f"{ns.ref_from} (measured d5 state)", ["live"])
        return 0

    pa_indices = _parse_pa_arg(ns.pa)
    seeds = _make_seeds(ns.batch, ns.seed)
    import multiprocessing as mp
    w = int(ns.workers or os.cpu_count() or 1)

    if ns.cross:
        tasks = [(pa, s, ns.cross, ns.cross_post) for pa in pa_indices for s in seeds]
        print(f"state_value --cross: {len(pa_indices)} opponent(s) x {len(seeds)} seed(s), "
              f"arm = `{ns.cross}`")
        print(f"   fixed continuation = `{ns.cross_post or '(tree defaults)'}`")
        print("   A = default prefix + default continuation (baseline)")
        print("   B = arm prefix + arm continuation  (the normal arm)")
        print("   C = arm prefix + FIXED continuation  <- isolates the d5 STATE")
        if w <= 1 or len(tasks) <= 1:
            rows = [_cross_worker(t) for t in tasks]
        else:
            with mp.get_context("fork").Pool(processes=min(w, len(tasks))) as pool:
                rows = list(pool.imap_unordered(_cross_worker, tasks))
        _report_cross(rows, ns.cross, ns.cross_post)
        return 0

    tasks = [(pa, s, conts) for pa in pa_indices for s in seeds]
    print(f"state_value — LIVE: {len(pa_indices)} opponent(s) x {len(seeds)} seed(s), "
          f"continuations={conts}")
    print(f"   one full 720-step roll-out per game; the d5 prefix is re-run per continuation")
    w = int(ns.workers or os.cpu_count() or 1)

    if w <= 1 or len(tasks) <= 1:
        rows = [_worker(t) for t in tasks]
    else:
        with mp.get_context("fork").Pool(processes=min(w, len(tasks))) as pool:
            rows = list(pool.imap_unordered(_worker, tasks))
    global _AGENT
    _AGENT = None

    report(rows, "ours (live roll-out, seat 1)", conts)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
