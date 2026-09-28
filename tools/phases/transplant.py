#!/usr/bin/env python
"""transplant — separate a midgame STATE from a midgame POLICY.

The question every arm has failed to answer
-------------------------------------------
Nine structural arms lost money while moving their mechanism. `state_value --cross` can
separate state from policy, but only at **d5** and only against `SCRATCH_PARAMS` arms. What
we have never asked is: *if OUR agent were handed the reference's day-N farm, in the
reference's own game, against the reference's own opponent — would it still lose?*

  control    replay BOTH seats' recorded actions to the bell. Must reproduce the replay's
             final money EXACTLY. This is the validity gate: if control does not
             reproduce, the harness is wrong and every treatment number is meaningless.
  treatment  replay both seats to the cut, transplant the reference's observation into his
             own seat, then play OUR agent in that seat and continue the opponent's
             recorded actions. Same opponent, same world at the cut, different policy.

`--prefix ours` is the complementary measurement: OUR agent plays the seat for d0..cut
(against the opponent's recorded actions) and the state gap at the cut is reported. That is
the checkpoint target -- close it to <1 % per metric, 5 days at a time.

Rigor: run it over a random sample of the reference's episodes (`--n`, seeded) or all of them
(`--all`), and always read the control column first. Use `--workers` for the full set.

Usage
-----
  PYTHONPATH=. python -m tools.phases.transplant --ref-from replays/Boey/v1 --n 24 --cut-day 10
  PYTHONPATH=. python -m tools.phases.transplant --ref-from replays/Boey/v1 --n 24 \
      --cut-day 10 --mode treatment --prefix ours      # d10 state-gap checkpoint
"""
from __future__ import annotations

import argparse
import collections
import glob as globmod
import json
import multiprocessing as mp
import random
import statistics as st
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from kaggle_environments import make                                   # noqa: E402

from tools import team as team_mod                                     # noqa: E402

STEPS = 720
DAY = 24
_AGENT = None


def _agent():
    global _AGENT
    if _AGENT is None:
        from tools.diagnose.agents import load_agent
        _AGENT = load_agent(fresh=True)
    return _AGENT


def _recorded(rep, t, seat):
    """The action taken at step `t` by `seat` (lives at steps[t+1], the verified pairing)."""
    steps = rep["steps"]
    if t + 1 >= len(steps) or len(steps[t + 1]) <= seat:
        return None
    return steps[t + 1][seat].get("action")


def _final_money(rep, seat):
    steps = rep["steps"]
    if len(steps[-1]) <= seat:
        return 0.0
    return float(steps[-1][seat]["observation"]["farms"][seat].get("money") or 0.0)


def _selfplay(rep):
    names = (rep.get("info") or {}).get("TeamNames") or []
    return len(names) >= 2 and names[0] == names[1]


def _transplant(env, obs_src, seat):
    """Overwrite `seat`'s live state from a recorded observation.

    The engine keeps the live state INSIDE the observation objects (`farms`, `market`,
    `town` are shared list/dict objects across both seats; `private` is per seat), so this
    is a plain in-place write. `farms` and the market/town dicts MUST be mutated in place,
    not rebound, or seat 0 would keep pointing at the old objects.
    """
    dst = env.state[seat]["observation"]
    dst["farms"][seat] = json.loads(json.dumps(obs_src["farms"][seat]))
    for k in ("shed", "seeds", "inventories"):
        dst["private"][k] = json.loads(json.dumps(obs_src["private"][k]))
    for k, v in obs_src["market"].items():
        dst["market"][k] = json.loads(json.dumps(v))
    for k, v in obs_src["town"].items():
        dst["town"][k] = json.loads(json.dumps(v))
    dst["day"] = obs_src.get("day")
    dst["hour"] = obs_src.get("hour")


def _snapshot(obs, seat):
    """The quantities the phase-1/phase-2 handoff is judged on, from one observation."""
    farm = obs["farms"][seat]
    unlocked = set(farm.get("unlocked_quadrants") or [])
    crops = collections.Counter()
    planted = empty = structs = animals = 0
    for y, row in enumerate(farm["tiles"]):
        for x, t in enumerate(row):
            owned = (("N" if y < 5 else "S") + ("W" if x < 5 else "E")) in unlocked
            if isinstance(t, dict):
                if t.get("kind") == "PLANT":
                    planted += 1
                    crops[t["crop"]] += 1
                elif t.get("kind") in ("COOP", "PASTURE"):
                    structs += 1
                if "animal" in t:
                    animals += 1
            elif t is None and owned:
                empty += 1
    priv = obs.get("private") or {}
    shed = priv.get("shed") or {}
    return {
        "money": float(farm.get("money") or 0.0),
        "animals": animals, "structs": structs, "planted": planted, "empty": empty,
        "wheat": crops.get("WHEAT", 0), "straw": crops.get("STRAWBERRY", 0),
        "melon": crops.get("MELON", 0), "tomato": crops.get("TOMATO", 0),
        "carrot": crops.get("CARROT", 0),
        "quadrants": len(farm.get("unlocked_quadrants") or []),
        "hands": len(farm.get("hands") or []),
        "shed_total": int(sum(v for v in shed.values() if v > 0)),
        "yarn": 1 if any("YARN" in str(s) for s in
                         ((obs.get("town") or {}).get("unlocked_shops") or [])) else 0,
    }


def _post_metrics(env, seat, cut_day):
    """Per-op totals for the days AFTER the cut, so treatment can be diffed against the
    control -- and the control IS the reference's own play (it reproduces exactly)."""
    from tools.phases.phase_map import extract
    days = extract(env, seat)
    ops = ("WATER", "HARVEST", "PLANT", "FEED", "CARE", "COLLECT_FERTILIZER",
           "MOVE", "PICKUP", "DROP", "FERTILIZE")
    out = {op: 0 for op in ops}
    out.update({"died": 0, "ut": 0})
    for d, r in days.items():
        if d <= cut_day:
            continue
        out["ut"] += r["unit_turns"]
        out["died"] += r["flow"].get("__died", 0)
        for op in ops:
            out[op] += r["flow"].get(op, 0)
    for lbl, key in (("animals", "animals"), ("wheatT", "plant_WHEAT"),
                     ("planted", "planted")):
        vals = [r["stock"].get(key, 0) for d, r in days.items() if d > cut_day]
        out[lbl] = max(vals) if vals else 0
    acts = sum(out[o] for o in ops if o != "MOVE")
    out["moves_per_act"] = round(out["MOVE"] / acts, 2) if acts else 0.0
    return out


def run_one(path, cut_day, mode, prefix="recorded"):
    """Returns a result dict. `mode` is 'control' or 'treatment'."""
    from tools.diagnose.games import load_replay
    rep = load_replay(Path(path))
    seat = team_mod.seat_of_names(
        (rep.get("info") or {}).get("TeamNames") or [], fallback=0)
    seed = (rep.get("info") or {}).get("seed")
    cut_step = (cut_day + 1) * DAY
    env = make("kaggriculture", configuration={"episodeSteps": STEPS, "seed": seed})
    env.reset()
    agent = _agent()
    transplanted = False
    state_gap = {}
    for t in range(STEPS):
        obs = [env.state[i]["observation"] for i in range(2)]
        if t == cut_step:
            # What OUR prefix produced, against what HIS replay shows, at the same cut in
            # the same episode. `--prefix recorded` makes this identically zero (the
            # validity path); `--prefix ours` measures the handoff.
            live = _snapshot(env.state[seat]["observation"], seat)
            ref = _snapshot(rep["steps"][cut_step][seat]["observation"], seat)
            state_gap = {k: live[k] - ref[k] for k in ref}
            state_gap["_live"] = live
            state_gap["_ref"] = ref
            if mode == "treatment" and prefix == "recorded":
                _transplant(env, rep["steps"][cut_step][seat]["observation"], seat)
                obs[seat] = env.state[seat]["observation"]
                transplanted = True
        acts = [None, None]
        acts[1 - seat] = _recorded(rep, t, 1 - seat)
        if t < cut_step:
            acts[seat] = (agent(obs[seat]) if prefix == "ours"
                          else _recorded(rep, t, seat))
        elif mode == "control":
            acts[seat] = _recorded(rep, t, seat)
        else:
            acts[seat] = agent(obs[seat])
        if acts[seat] is None or acts[1 - seat] is None:
            break
        env.step(acts)
        if env.done:
            break
    final_us = float(env.state[seat]["observation"]["farms"][seat].get("money") or 0.0)
    final_opp = float(env.state[1 - seat]["observation"]["farms"][1 - seat].get("money") or 0.0)
    ref_final = _final_money(rep, seat)
    ref_opp = _final_money(rep, 1 - seat)
    try:
        post = _post_metrics(env, seat, cut_day)
    except Exception:                             # noqa: BLE001
        post = {}
    return {
        "file": Path(path).name, "mode": mode, "seat": seat, "seed": seed,
        "cut_day": cut_day, "transplanted": transplanted, "post": post,
        "prefix": prefix, "state_gap": state_gap,
        "final_us": final_us, "final_opp": final_opp,
        "ref_final": ref_final, "ref_opp": ref_opp,
        "reproduced": abs(final_us - ref_final) < 1.0 and abs(final_opp - ref_opp) < 1.0,
        "delta_vs_ref": final_us - ref_final,
        "win": final_us > final_opp,
    }


def _worker(task):
    path, cut_day, mode, prefix = task
    try:
        return run_one(path, cut_day, mode, prefix)
    except Exception as exc:                      # noqa: BLE001
        return {"file": Path(path).name, "mode": mode, "error": repr(exc)}


_GAP_KEYS = ("money", "animals", "structs", "planted", "empty", "wheat", "straw",
             "melon", "tomato", "carrot", "quadrants", "shed_total", "yarn")


def _summ(rows, mode):
    ok = [r for r in rows if "error" not in r]
    err = [r for r in rows if "error" in r]
    print(f"\n############ {mode} — {len(ok)} games ({len(err)} errored) ############")
    if err:
        for r in err[:3]:
            print(f"   ERROR {r['file']}: {r['error']}")
    if not ok:
        return
    if mode == "control":
        rep_ok = sum(1 for r in ok if r["reproduced"])
        print(f"   REPRODUCED EXACTLY: {rep_ok}/{len(ok)}")
        for r in [r for r in ok if not r["reproduced"]][:5]:
            print(f"   MISMATCH {r['file']}: ours {r['final_us']:.0f} vs replay "
                  f"{r['ref_final']:.0f}  d={r['delta_vs_ref']:+.0f}")
        if rep_ok != len(ok):
            print("   !! control failed -- the harness does not reproduce the episode. "
                  "Treatment numbers are NOT interpretable until this is fixed.")
        return
    d = [r["delta_vs_ref"] for r in ok]
    wins = sum(1 for r in ok if r["win"])
    better = sum(1 for r in ok if r["delta_vs_ref"] > 0)
    print(f"   our final vs the reference's own final: median {st.median(d):+,.0f}, "
          f"mean {st.mean(d):+,.0f}")
    print(f"   we out-earn the reference in {better}/{len(ok)}; "
          f"we beat the OPPONENT in {wins}/{len(ok)}")
    print(f"   reference beat the opponent in "
          f"{sum(1 for r in ok if r['ref_final'] > r['ref_opp'])}/{len(ok)}")
    print(f"   transplanted {sum(1 for r in ok if r['transplanted'])}/{len(ok)}")


def _print_state_gap(rows, cut_day):
    """Our prefix's state vs his, at the cut -- the checkpoint target.

    The `%` column is `|ours - his| / his`; the target is <= 1 %. Metrics where he holds 0
    are judged absolutely (we must also hold ~0), since a ratio is undefined.
    """
    ok = [r for r in rows if r.get("state_gap")]
    if not ok:
        return
    print(f"\n   -- STATE GAP at d{cut_day} (our prefix vs his replay, same episode) --")
    print(f"   {'metric':<14}{'ours':>12}{'his':>12}{'delta':>10}{'gap%':>9}")
    within = total = 0
    for k in _GAP_KEYS:
        o = st.median([r["state_gap"]["_live"].get(k, 0) for r in ok])
        h = st.median([r["state_gap"]["_ref"].get(k, 0) for r in ok])
        if abs(h) > 1e-9:
            pct = (o - h) / h * 100.0
            txt = f"{pct:+.1f}%"
            good = abs(pct) <= 1.0
        else:
            txt = "n/a" if abs(o) > 1e-9 else "0.0%"
            good = abs(o) <= 1e-9
        total += 1
        within += 1 if good else 0
        print(f"   {k:<14}{o:>12.1f}{h:>12.1f}{o - h:>+10.1f}{txt:>9}  "
              f"{'OK' if good else 'gap'}")
    print(f"   {'WITHIN 1 %':<14}{within:>12}/{total}")


def _print_divergence(rows, cut_day):
    ctrl = {r["file"]: r for r in rows
            if r.get("mode") == "control" and "error" not in r}
    pair = [(ctrl[r["file"]], r) for r in rows
            if r.get("mode") == "treatment" and "error" not in r
            and r["file"] in ctrl]
    if not pair:
        return
    print("\n   -- POLICY DIVERGENCE after the cut (control = the reference's own play) --")
    keys = ["ut", "WATER", "HARVEST", "PLANT", "FEED", "CARE",
            "COLLECT_FERTILIZER", "FERTILIZE", "MOVE", "moves_per_act",
            "PICKUP", "DROP", "died", "animals", "wheatT", "planted"]
    print(f"   {'metric':<22}{'his (control)':>14}{'ours (treat)':>14}{'delta':>10}")
    for k in keys:
        c = st.median([a["post"].get(k, 0) for a, _b in pair if a.get("post")])
        t = st.median([b["post"].get(k, 0) for _a, b in pair if b.get("post")])
        print(f"   {k:<22}{c:>14.1f}{t:>14.1f}{t - c:>+10.1f}")


def run_public(pa, seed, cut_day, seat=1):
    """Our agent vs a PUBLIC opponent, snapshot at the cut day.

    The replay path answers "can we clone the reference"; this answers "is the d10 state
    we reach robust across opponents and seeds" -- i.e. is our revenue at the checkpoint
    low-variance, or does it swing with who we are playing.
    """
    from tools.diagnose.agents import load_public_agent
    opp = load_public_agent(pa)
    env = make("kaggriculture", configuration={"episodeSteps": STEPS, "seed": seed})
    env.reset()
    agent = _agent()
    cut_step = (cut_day + 1) * DAY
    for _t in range(cut_step):
        obs = [env.state[i]["observation"] for i in range(2)]
        acts = [None, None]
        acts[seat] = agent(obs[seat])
        acts[1 - seat] = opp(obs[1 - seat])
        env.step(acts)
        if env.done:
            break
    return {"pa": pa, "seed": seed,
            "us": _snapshot(env.state[seat]["observation"], seat),
            "opp": _snapshot(env.state[1 - seat]["observation"], 1 - seat)}


def _worker_public(task):
    pa, seed, cut_day = task
    try:
        return run_public(pa, seed, cut_day)
    except Exception as exc:                      # noqa: BLE001
        return {"pa": pa, "seed": seed, "error": repr(exc)}


def _ref_snapshots(paths, cut_day, maxn=120):
    """The reference's own state at the same cut, for the public-agent comparison."""
    from tools.diagnose.games import load_replay
    out = []
    for p in paths[:maxn]:
        try:
            rep = load_replay(Path(p))
            s = team_mod.seat_of_names(
                (rep.get("info") or {}).get("TeamNames") or [], fallback=0)
            out.append(_snapshot(rep["steps"][(cut_day + 1) * DAY][s]["observation"], s))
        except Exception:
            continue
    return out


def _print_public(rows, refs, cut_day):
    ok = [r for r in rows if "error" not in r]
    if not ok:
        print("   no public games")
        return
    print(f"\n   -- PUBLIC-AGENT CHECKPOINT at d{cut_day} "
          f"({len(ok)} games = opponents x seeds) --")
    print(f"   {'metric':<14}{'median':>10}{'p10':>9}{'p90':>9}{'spread':>9}"
          f"{'Boey':>10}{'gap%':>9}")
    for k in _GAP_KEYS:
        vals = sorted(r["us"].get(k, 0) for r in ok)
        med = st.median(vals)
        lo = vals[int(0.1 * (len(vals) - 1))]
        hi = vals[int(0.9 * (len(vals) - 1))]
        ref = st.median([x.get(k, 0) for x in refs]) if refs else 0.0
        spread = (hi - lo) / med * 100 if med else 0.0
        pct = f"{(med - ref) / ref * 100:+.1f}%" if abs(ref) > 1e-9 else (
            "n/a" if abs(med) > 1e-9 else "0.0%")
        print(f"   {k:<14}{med:>10.1f}{lo:>9.1f}{hi:>9.1f}{spread:>8.0f}%"
              f"{ref:>10.1f}{pct:>9}")
    mny = sorted(r["us"].get("money", 0) for r in ok)
    print("   money spread (p90-p10)/median: "
          f"{(mny[int(0.9 * (len(mny) - 1))] - mny[int(0.1 * (len(mny) - 1))]) / max(1.0, st.median(mny)) * 100:.0f}%")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ref-from", default="replays/Boey/v1")
    ap.add_argument("--glob", default="*.json")
    ap.add_argument("--n", type=int, default=12)
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--shuffle-seed", type=int, default=20260929)
    ap.add_argument("--cut-day", type=int, default=10)
    ap.add_argument("--mode", choices=("control", "treatment", "both"), default="both")
    ap.add_argument("--prefix", choices=("recorded", "ours"), default="recorded",
                    help="who plays our seat BEFORE the cut: his recorded actions "
                         "(transplant semantics) or OUR agent (state-gap checkpoint)")
    ap.add_argument("--include-selfplay", action="store_true")
    ap.add_argument("--workers", type=int, default=0)
    ap.add_argument("--out", default=None)
    ap.add_argument("--team", default=None)
    ap.add_argument("--public", action="store_true",
                    help="our agent vs PUBLIC opponents, snapshotted at the cut day "
                         "(robustness/variance of the checkpoint, not a clone test)")
    ap.add_argument("--pa", default="2,3", help="public opponents for --public")
    ap.add_argument("--batch", type=int, default=4, help="seeds/opponent for --public")
    ap.add_argument("--seed", type=int, default=4362837462, help="seed for --public")
    ap.add_argument("--ref-max", type=int, default=120,
                    help="reference replays to snapshot for the --public comparison")
    a = ap.parse_args(argv)
    # The reference is Boey by default: `--ref-from` names the arm, and the seat must be
    # HIS seat (the default resolver would fall back to DSM and we would "transplant" the
    # opponent's state).
    team_mod.set_team(a.team or "Boey")

    if a.public:
        from tools.diagnose.runbook import _make_seeds, _parse_pa_arg
        pas = _parse_pa_arg(a.pa)
        seeds = _make_seeds(a.batch, a.seed)
        tasks = [(p, s, a.cut_day) for p in pas for s in seeds]
        print(f"# public checkpoint  pa={a.pa}  batch={a.batch}  cut=d{a.cut_day}  "
              f"{len(tasks)} games")
        w = int(a.workers or 0)
        if w <= 1 or len(tasks) <= 1:
            rows = [_worker_public(t) for t in tasks]
        else:
            ctx = mp.get_context("fork")
            with ctx.Pool(processes=min(w, len(tasks))) as pool:
                rows = list(pool.imap_unordered(_worker_public, tasks))
        refs = _ref_snapshots(sorted(globmod.glob(str(Path(a.ref_from) / a.glob))),
                              a.cut_day, a.ref_max)
        _print_public(rows, refs, a.cut_day)
        if a.out:
            Path(a.out).write_text(json.dumps(rows, indent=1, default=str))
            print(f"\nwrote {a.out}")
        return 0

    paths = sorted(globmod.glob(str(Path(a.ref_from) / a.glob)))
    if not a.all:
        rnd = random.Random(a.shuffle_seed)
        paths = rnd.sample(paths, min(a.n, len(paths)))
    if not a.include_selfplay:
        # filter AFTER sampling: loading 359 large replays just to drop the mirror
        # episodes took minutes and looked like a hang.
        keep = []
        for p in paths:
            try:
                if not _selfplay(json.load(open(p))):
                    keep.append(p)
            except Exception:
                pass
        paths = keep
    print(f"# transplant  ref={a.ref_from}  {len(paths)} episodes  cut=d{a.cut_day}  "
          f"mode={a.mode}  prefix={a.prefix}")

    modes = ("control", "treatment") if a.mode == "both" else (a.mode,)
    tasks = [(p, a.cut_day, m, a.prefix) for m in modes for p in paths]
    w = int(a.workers or 0)
    if w <= 1 or len(tasks) <= 1:
        rows = [_worker(t) for t in tasks]
    else:
        ctx = mp.get_context("fork")
        with ctx.Pool(processes=min(w, len(tasks))) as pool:
            rows = list(pool.imap_unordered(_worker, tasks))
    for m in modes:
        _summ([r for r in rows if r.get("mode") == m], m)
    if a.prefix == "ours":
        _print_state_gap([r for r in rows if r.get("mode") == "treatment"], a.cut_day)
    if len(modes) == 2:
        _print_divergence(rows, a.cut_day)
    if a.out:
        Path(a.out).write_text(json.dumps(rows, indent=1, default=str))
        print(f"\nwrote {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
