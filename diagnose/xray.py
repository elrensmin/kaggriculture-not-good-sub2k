"""diagnose.xray — per-step patch() investigation (action diffs + money curves)."""
from __future__ import annotations

import copy
from pathlib import Path

from diagnose.agents import _reload_main_if_needed, load_public_agent
from diagnose.analysis import replay_to_summary
from diagnose.config import EPISODE_STEPS, PUBLIC_AGENT_MAP, TEST_SEAT
from diagnose.games import run_game, save_replay

def _action_diff(day, step, old, new):
    """Return a human-readable diff between two actions, or None if equal."""
    if old == new:
        return None
    lines = []
    keys = set(old) | set(new)
    for k in sorted(keys, key=lambda x: {"farmer": 0, "hands": 1, "market": 2}.get(x, 9)):
        ov, nv = old.get(k), new.get(k)
        if ov != nv:
            lines.append(f"      {k}: old={ov if k != 'market' else _succinct_market(ov)}"
                         f" | new={nv if k != 'market' else _succinct_market(nv)}")
    return "\n".join(lines)



def _succinct_market(market):
    m = market or []
    return ";".join("".join(str(x) for x in o) if o else "_" for o in m)



def xray_game(pa: int, seed: int):
    """Run old (main.py) and new (main.py + agent.patch) on the same seed.

    Returns a dict with per-step action traces + the patch's before/after ledger
    so callers can print what changed (and where that first breaks).
    """
    main = _reload_main_if_needed(fresh=True)
    import agent as amod
    base = main._original_agent
    orig_patch = getattr(amod, "patch", None)
    if orig_patch is None:
        raise TypeError("agent.py must expose patch(action, observation, configuration=None)")

    opp = load_public_agent(pa)
    opp_name = PUBLIC_AGENT_MAP[pa][0]

    # --- old trace (every step's final action) ---
    old_acts = []

    def old_agent(obs, configuration=None):
        a = base(obs, configuration)
        old_acts.append(copy.deepcopy(a))
        return a

    # --- new trace + patch after/before ledger ---
    new_acts = []
    new_prices = []          # live market prices (new game) at each step
    patch_ledger = []        # list of (step, day, before, after)

    def rec_patch(action, observation, configuration=None):
        out = orig_patch(action, observation, configuration)
        return out

    def _mkt_prices(obs):
        try:
            return {k: int(v) for k, v in (obs.get("market", {}).get("prices", {}) or {}).items()}
        except Exception:
            return {}

    def new_agent(obs, configuration=None):
        raw = base(obs, configuration)
        new_prices.append(_mkt_prices(obs))
        patched = rec_patch(raw, obs, configuration)
        new_acts.append(copy.deepcopy(patched))
        patch_ledger.append(copy.deepcopy((raw, patched)))
        return patched

    env_old = run_game(old_agent, opp, seed=seed, episode_steps=EPISODE_STEPS, seat=TEST_SEAT, audit=True)
    env_new = run_game(new_agent, opp, seed=seed, episode_steps=EPISODE_STEPS, seat=TEST_SEAT, audit=True)

    # Build the patch "direct" ledger: steps where patch() returned something != input.
    # (raw, patched) rows are aligned to new_acts by step.
    direct = []
    for i, (raw, patched) in enumerate(patch_ledger):
        if raw != patched:
            direct.append(i)

    # Divergence: compare final old vs new action streams (both length 719).
    n = min(len(old_acts), len(new_acts))
    diverged = []
    for i in range(n):
        if old_acts[i] != new_acts[i]:
            diverged.append(i)

    return {
        "pa": pa, "opponent": opp_name, "seed": seed,
        "n": n,
        "old_final": env_old.steps[-1][TEST_SEAT].reward,
        "new_final": env_new.steps[-1][TEST_SEAT].reward,
        "old_acts": old_acts, "new_acts": new_acts, "new_prices": new_prices,
        "patch_ledger": patch_ledger,
        "direct_steps": direct,
        "divergence": diverged,
        "env_old": env_old, "env_new": env_new,
    }



def xray_report(x):
    """Print the xray investigation report for one game."""
    print(f"=== xray: {x['opponent']} seed {x['seed']} ===")
    print(f"  old final ${x['old_final']:.0f}  |  new final ${x['new_final']:.0f}  "
          f"|  delta {x['new_final'] - x['old_final']:+.0f}")

    # 1) patch ledger — steps where patch() itself changed the action.
    print("\n[1] patch() direct changes (agent.py moves), %d step(s):"
          % len(x["direct_steps"]))
    for i in x["direct_steps"]:
        raw, patched = x["patch_ledger"][i]
        diff = _action_diff(i // 24, i, raw, patched)
        stepno = i  # ledger index == step (agent called once/step for our seat)
        print(f"  step {stepno:3d} (day {stepno // 24:2d}):")
        print(diff or "      (structure equal: no visible diff)")
    # A patch may mutate state/tape at step 0 (returning the action unchanged)
    # rather than rewriting actions per-step — that shows up only as cascades.
    if not x["direct_steps"] and x.get("divergence"):
        print("  (no per-step action rewrites: the patch likely installs "
              "state/tape at step 0 and the effect surfaces as the cascade steps "
              "in [2])")

    # 2) old-vs-new divergence — where the two games first break apart.
    div = x["divergence"]
    first = div[0] if div else None
    print(f"\n[2] old-vs-new final action divergence: {len(div)} of {x['n']} steps differ"
          f"{' (first at step %d / day %d)' % (first, first // 24) if first is not None else ', identical'}")

    show = div[:40]
    if first is not None:
        direct_set = set(x["direct_steps"])
        for i in show:
            tag = "PATCH-DIRECT" if i in direct_set else "cascade"
            day = i // 24
            print(f"\n  step {i:3d} (day {day:2d}) [{tag}]")
            d = _action_diff(day, i, x["old_acts"][i], x["new_acts"][i])
            print(d)
            # If the market order set changed, show live prices for the items in play.
            om = x["old_acts"][i].get("market") or []
            nm = x["new_acts"][i].get("market") or []
            if d and (om != nm):
                prices = x["new_prices"][i] if i < len(x["new_prices"]) else {}
                sell_items = list(dict.fromkeys(o[1] for o in nm if o and o[0] == "SELL"))
                if sell_items:
                    shown = ", ".join(f"{it}:${prices.get(it, '?')}" for it in sell_items)
                    print(f"      [market prices] {shown}")
    if len(div) > len(show):
        print(f"  ... and {len(div) - len(show)} more changed steps (see --run-dir replays).")

    # 3) daily money curves.
    print("\n[3] day-by-day money (old vs new):")
    od = _money_curve_from_env(x["env_old"])
    nd = _money_curve_from_env(x["env_new"])
    first_day = (first // 24) if first is not None else None
    # Find the day where the money delta first becomes nonzero (or changes sign)
    # so the user can spot the day the patch's economic impact truly lands.
    print("    day     old       new        Δ")
    for day in sorted(set(od) | set(nd)):
        o = od.get(day, 0); n = nd.get(day, 0)
        mark = ""
        if first_day is not None and day == first_day:
            mark = "  <- first action divergence day"
        print(f"    {day:3d}  {o:>9,.0f}  {n:>9,.0f}  {n - o:>9,}{mark}")
    return x



def env_to_replay(env):
    """Return a replay (JSON-able dict) from a live env object."""
    try:
        return env.toJSON()
    except Exception:
        return {"steps": env.steps}



def _money_curve_from_env(env):
    """Return {day: end-of-day money} for TEST_SEAT from an env object via its replay."""
    try:
        _, days, _ = replay_to_summary(env_to_replay(env), seat=TEST_SEAT)
        return {d["day"]: d["end_money"] for d in days}
    except Exception:
        return {}



def xray_batch(pa_indices, seeds, run_dir):
    run_dir = Path(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    saved = []
    for pa in pa_indices:
        if pa not in PUBLIC_AGENT_MAP:
            continue
        opp_name = PUBLIC_AGENT_MAP[pa][0]
        for seed in seeds:
            x = xray_game(pa, seed)
            meta_o = {"agent": "old", "opponent": opp_name, "opponent_idx": pa, "seed": seed,
                      "seat": TEST_SEAT, "episode_steps": EPISODE_STEPS}
            meta_n = {"agent": "new", "opponent": opp_name, "opponent_idx": pa, "seed": seed,
                      "seat": TEST_SEAT, "episode_steps": EPISODE_STEPS}
            po = run_dir / f"old_vs_{opp_name}_seed{seed}.json"
            pn = run_dir / f"new_vs_{opp_name}_seed{seed}.json"
            save_replay(x["env_old"], po, meta_o)
            save_replay(x["env_new"], pn, meta_n)
            xray_report(x)
            saved.extend([po, pn])
    return saved


# ---------------------------------------------------------------------------
# --graph — matplotlib per-game dashboards from saved replays
# ---------------------------------------------------------------------------
# Goal: turn a single saved replay into PNG figures that surface SYSTEM-LEVEL
# defects you can *see* at a specific step/day (per AGENTS.md anti-goal: never
# trust cross-game averages). Reads the exact replay JSON `--old/--new/--compare`
# writes, so no extra logging is required — every series below already exists in
# each step's observation.

# Products that crash straight to the $1 floor on oversupply (above_target > 1).
# Highlighting them + shop-unlock ticks makes glut/scarcity timing visible at a glance.
