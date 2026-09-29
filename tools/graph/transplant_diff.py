"""tools/graph/transplant_diff.py -- the TRANSPLANT DIFFERENCE DETECTOR.

WHAT THIS IS FOR
----------------
Run OUR planner on BOEY's states and report **discrete** points of disagreement. This is a
difference detector, NOT a gradient.

Why not a gradient: a priority kernel is a RANKING, not a smooth parameterisation. Scaling a
priority changes nothing until it crosses a neighbour, then behaviour jumps. Measured (PA=1
seed 700, see todo.md): multiplying priorities by graph pressure is harmful at EVERY cap
(1.0 $58,899 / 1.1 $50,716 / 1.25 $47,228 / 1.5 $37,175 -- monotone), and replacing the kernel
with normalised dollars loses the survival ordering (deaths 59 -> 94). So `his_share /
our_share` is a valid measurement but cannot be followed as a gradient. The useful output is
instead the discrete difference: "on this state, at this hour, he did X and we did Y".

EVERY DISAGREEMENT IS CLASSIFIED, because the classes have different owners:
  (a) MISSING CAPABILITY -- he has a job type we never generate            -> graph fix
  (b) RANKING            -- we generate it but choose something else       -> the only place
                                                                            weights are legitimate
  (c) REACHABILITY       -- we rank it right but no unit gets there        -> scheduler/routing
  (d) STATE DIVERGENCE   -- our board is not his, so the question is moot  -> the control problem

USAGE
    PYTHONPATH=. python -m tools.graph.transplant_diff --max-games 4 --days 0-12
    PYTHONPATH=. python -m tools.graph.transplant_diff --section diff  --days 6-10 --every 1
    PYTHONPATH=. python -m tools.graph.transplant_diff --section caps
    PYTHONPATH=. python -m tools.graph.transplant_diff --section reach --days 11-20
    PYTHONPATH=. python -m tools.graph.transplant_diff --section state --days 0-14
"""
from __future__ import annotations

import argparse
import glob
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src import priors, scheduler                                  # noqa: E402
from src.state import State                                        # noqa: E402

ACTS = ("WATER", "HARVEST", "PLANT", "FERTILIZE", "FEED", "CARE", "COLLECT_FERTILIZER",
        "DIG", "PLACE", "PICKUP", "DROP", "BUILD_PASTURE", "BUILD_COOP")
REPLAYS = "replays/Boey/v1"


# --------------------------------------------------------------------------- replay helpers
def his_seat(rep):
    """Which seat is Boey. Tries the metadata names first, then an economy heuristic.

    Returns (seat_index, method). Never guesses silently -- the caller counts the methods so a
    heuristic that only ever fires is visible rather than assumed.
    """
    blob = " ".join(str(rep.get(k, "")) for k in ("description", "title", "name")).lower()
    for tag in ("boey", "dsm"):
        if tag in blob:
            # the name usually appears with the seat order; fall back to the heuristic for the index
            break
    info = rep.get("info") or {}
    teams = None
    if isinstance(info, dict):
        for key in ("TeamNames", "teamNames", "teams", "Agents", "agents"):
            if key in info:
                teams = info[key]
                break
    if isinstance(teams, (list, tuple)) and len(teams) >= 2:
        for i, t in enumerate(teams[:2]):
            if "boey" in str(t).lower() or "dsm" in str(t).lower():
                return i, "info"
    # heuristic: he is the seat that OWNS LAND EARLY (2 quadrants by d8 is his signature) and is
    # fully invested (near-zero cash while owning 25+ tiles)
    best, best_score = 0, -1.0
    for seat in (0, 1):
        try:
            obs = rep["steps"][8 * 24][seat]["observation"]
            st = State(obs)
            owned = sum(1 for y, row in enumerate(st.tiles) for x in range(len(row))
                        if st.owned((x, y)))
            cash = float(getattr(st, "money", 0.0))
            score = float(owned) - min(cash, 3000.0) / 100.0
        except Exception:                                          # noqa: BLE001
            continue
        if score > best_score:
            best, best_score = seat, score
    return best, "heuristic"


def ops_of(action, with_pos=False):
    """[(op, pos)] for every unit action, plus the market list separately."""
    out, mkt = [], []
    if not isinstance(action, dict):
        return out, mkt
    for key in ("farmer", "hands"):
        for u in (action.get(key) or []):
            if isinstance(u, list) and u:
                pos = (u[1], u[2]) if len(u) >= 3 and isinstance(u[1], int) else None
                out.append((str(u[0]), pos if with_pos else None))
    for m in (action.get("market") or []):
        if isinstance(m, list) and m:
            mkt.append(str(m[0]))
    return out, mkt


def plan_jobs(state):
    """The jobs our planner would have on offer this turn, WITHOUT running the full scheduler.

    `scheduler.plan` returns an ACTION, which has already discarded the jobs that lost. To tell
    (a)/(b) apart -- "we never generate it" vs "we generate it and rank it lower" -- we need the
    offer list too. Gathered from the same layers `scheduler.plan` uses.
    """
    try:
        from src import crop_plan, herd_plan, opening, endgame
        jobs = []
        for fn in (getattr(crop_plan, "jobs", None), getattr(herd_plan, "jobs", None),
                   getattr(endgame, "jobs", None)):
            if fn is None:
                continue
            try:
                jobs.extend(list(fn(state)))
            except Exception:                                      # noqa: BLE001
                pass
        return jobs
    except Exception:                                              # noqa: BLE001
        return []


def sample(rep, seat, days, hour):
    """[(day, step_t, his_obs, his_action)] sampled once per day, with the ACTION SHIFT applied.

    A kaggle step records the action that PRODUCED its observation, so the action decided from
    `steps[t]["observation"]` lives at `steps[t+1]["action"]`. Using the same index would compare
    our decision against his PREVIOUS decision.
    """
    out = []
    for d in range(days[0], days[1] + 1):
        t = d * 24 + hour
        if t + 1 >= len(rep["steps"]):
            break
        try:
            obs = rep["steps"][t][seat]["observation"]
            act = rep["steps"][t + 1][seat]["action"]
        except Exception:                                          # noqa: BLE001
            continue
        if not isinstance(obs, dict) or not isinstance(act, dict):
            continue
        out.append((d, t, obs, act))
    return out


# --------------------------------------------------------------------------- sections
def section_diff(states, days, top=12):
    """The discrete disagreement, classified.

    Clean rule per sample, per op -- his count minus ours tells the DIRECTION, and the job offer
    list plus our PASS share tells the OWNER:

      deficit op not on offer at all                 -> (a) MISSING CAPABILITY   graph fix
      deficit op on offer, our units sat idle        -> (c) REACHABILITY         scheduler/routing
      deficit op on offer, our units did other work  -> (b) RANKING              weighting
    """
    print("=" * 100)
    print("DIFF -- on HIS states, what he did vs what we would do  (the discrete disagreement)")
    print("=" * 100)
    conf = Counter()                 # (his_op, our_op) for UNMATCHED actions
    cls = Counter()
    cls_examples = defaultdict(Counter)
    per_day = defaultdict(Counter)
    matched = total_h = 0
    for d, st, his_acts, our_acts, jobs in states:
        h = Counter(o for o, _ in his_acts)
        o_ = Counter(o for o, _ in our_acts)
        on_offer = Counter(str(getattr(j, "op", "")) for j in jobs)
        total_h += sum(v for k, v in h.items() if k in ACTS)
        idle = o_.get("PASS", 0)
        for op in ACTS:
            nh, no = h.get(op, 0), o_.get(op, 0)
            matched += min(nh, no)
            if nh > no:
                # we under-delivered this op. Who owns the gap?
                if on_offer.get(op, 0) <= 0:
                    kind = "(a) missing capability"
                elif idle > 0:
                    kind = "(c) reachability"
                else:
                    kind = "(b) ranking"
                cls[kind] += nh - no
                cls_examples[kind][op] += nh - no
                idle = max(0, idle - 1)
            # unmatched pairs, for the confusion table
            rem_h, rem_o = nh - min(nh, no), no - min(nh, no)
            other = next((k for k, v in o_.items() if v > 0 and k in ACTS and k != op), "PASS")
            if rem_h > 0 and rem_o <= 0:
                conf[(op, other)] += rem_h
                per_day[d][(op, other)] += rem_h
            elif rem_o > 0 and rem_h <= 0:
                conf[(other, op)] += rem_o
    print(f"  matched unit-actions: {matched}/{total_h} = "
          f"{matched / max(1, total_h):.1%} of HIS actions we reproduce exactly")
    print()
    print("  WHERE WE DIFFER  (he did / we did instead, most common mismatches)")
    print(f"  {'he did':<22} {'we did':<22} {'n':>5}")
    shown = 0
    for (a, b), n in conf.most_common(40):
        if a == b:
            continue
        print(f"  {a:<22} {b:<22} {n:>5}   <<<")
        shown += 1
        if shown >= top:
            break
    print()
    print("  CLASSIFICATION OF THE UNDER-DELIVERY  (this decides where the fix goes)")
    for k in ("(a) missing capability", "(b) ranking", "(c) reachability"):
        v = cls.get(k, 0)
        ex = ", ".join(f"{op} x{n}" for op, n in cls_examples[k].most_common(4))
        print(f"    {k:<24} {v:>5}   {ex}")
    print()
    print("  per-day mismatches, top 3:")
    for d in sorted(per_day):
        items = ", ".join(f"{a}->{b} x{n}" for (a, b), n in per_day[d].most_common(3))
        if items:
            print(f"    d{d:<3} {items}")


def section_caps(states):
    print()
    print("=" * 100)
    print("CAPS -- capability gaps: ops he uses that we NEVER emit, and vice versa")
    print("=" * 100)
    his, ours = Counter(), Counter()
    for _d, _st, his_acts, our_acts, _j in states:
        his.update(o for o, _ in his_acts)
        ours.update(o for o, _ in our_acts)
    print(f"  {'op':<20} {'his':>7} {'ours':>7}  verdict")
    for op in sorted(set(his) | set(ours)):
        if op not in ACTS and op != "MOVE":
            continue
        hv, ov = his.get(op, 0), ours.get(op, 0)
        if hv and not ov:
            v = "*** WE NEVER DO IT *** (a) missing capability"
        elif ov and not hv:
            v = "we do it, he never does -- spurious"
        else:
            v = ""
        print(f"  {op:<20} {hv:>7} {ov:>7}  {v}")


def section_reach(rows, days, every=2):
    print()
    print("=" * 100)
    print("REACH -- (c) do we RANK the work and still fail to REACH it?")
    print("=" * 100)
    print("  `emitted` = jobs on offer. `acted` = jobs actually performed. A large gap with")
    print("  low MOVE share means the plan is fine and the ASSIGNMENT is losing the work.")
    per = defaultdict(lambda: defaultdict(float))
    n = 0
    for d, st, _h, our_acts, jobs in rows:
        n += 1
        c = Counter(o for o, _ in our_acts)
        per[d]["emitted"] += len(jobs)
        per[d]["acted"] += sum(c.get(o, 0) for o in ACTS)
        per[d]["move"] += c.get("MOVE", 0)
        per[d]["pass"] += c.get("PASS", 0)
        per[d]["units"] += float(st.unit_count())
    print(f"\n  {'day':>4} {'jobs on offer':>14} {'acted':>7} {'moves':>7} {'pass':>6} {'units':>6} {'acted/unit':>11}")
    for d in sorted(per):
        if d % every:
            continue
        v = per[d]
        u = max(1.0, v["units"])
        print(f"  {d:>4} {v['emitted'] / max(1, n):>14.1f} {v['acted'] / max(1, n):>7.1f} "
              f"{v['move'] / max(1, n):>7.1f} {v['pass'] / max(1, n):>6.1f} {u:>6.1f} "
              f"{v['acted'] / u:>11.2f}")


def section_state(rows, days, every=2):
    print()
    print("=" * 100)
    print("STATE -- (d) is our board even HIS board? ours vs the priors, per day")
    print("=" * 100)
    per = defaultdict(lambda: defaultdict(list))
    for d, st, _h, _a, _j in rows:
        empty = sum(1 for y, row in enumerate(st.tiles) for x, t in enumerate(row)
                    if t is None and st.owned((x, y)))
        planted = sum(1 for row in st.tiles for t in row
                      if isinstance(t, dict) and t.get("kind") == "PLANT")
        structs = sum(1 for row in st.tiles for t in row
                      if isinstance(t, dict) and t.get("kind") in ("COOP", "PASTURE"))
        quad = len(st.unlocked)
        per[d]["empty"].append(empty)
        per[d]["planted"].append(planted)
        per[d]["structs"].append(structs)
        per[d]["quadrants"].append(quad)
        per[d]["money"].append(float(getattr(st, "money", 0.0)))
    def med(v):
        v = sorted(v)
        return v[len(v) // 2] if v else 0.0
    print(f"\n  {'day':>4} | {'empty ours/his':>16} {'planted ours/his':>18} "
          f"{'structs ours/his':>18} {'quad ours/his':>14} | verdict")
    for d in sorted(per):
        if d % every:
            continue
        v = per[d]
        e, p, s_, q = med(v["empty"]), med(v["planted"]), med(v["structs"]), med(v["quadrants"])
        he, hp = priors.crop_target(d, "empty"), priors.crop_target(d, "planted")
        hs, hq = priors.crop_target(d, "structs"), priors.crop_target(d, "n_quadrants")
        bad = []
        if e > he + 2:
            bad.append("empty")
        if hp - p > 4:
            bad.append("under-planted")
        if hs - s_ > 3:
            bad.append("under-built")
        print(f"  {d:>4} | {e:>7.0f}/{he:<8.0f} {p:>8.0f}/{hp:<9.0f} "
              f"{s_:>8.0f}/{hs:<9.0f} {q:>6.0f}/{hq:<7.0f} | {', '.join(bad) or 'aligned'}")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--replays", default=REPLAYS)
    ap.add_argument("--max-games", type=int, default=4)
    ap.add_argument("--days", default="0-12")
    ap.add_argument("--every", type=int, default=2)
    ap.add_argument("--hour", type=int, default=12)
    ap.add_argument("--section", default="all",
                    choices=["all", "diff", "caps", "reach", "state"])
    a = ap.parse_args(argv)
    days = tuple(int(x) for x in a.days.split("-"))

    files = sorted(glob.glob(str(Path(a.replays) / "*.json")))[:a.max_games]
    if not files:
        print(f"no replays in {a.replays}", file=sys.stderr)
        return 1
    rows, methods, errors = [], Counter(), Counter()
    for f in files:
        try:
            rep = json.load(open(f))
        except Exception:                                          # noqa: BLE001
            errors["unreadable replay"] += 1
            continue
        seat, method = his_seat(rep)
        methods[method] += 1
        for d, t, obs, act in sample(rep, seat, days, a.hour):
            try:
                st = State(obs)
            except Exception:                                      # noqa: BLE001
                errors["State()"] += 1
                continue
            try:
                our_action = scheduler.plan(st)
            except Exception as e:                                 # noqa: BLE001
                errors[f"plan(): {type(e).__name__}"] += 1
                continue
            our_acts, _mkt = ops_of(our_action, with_pos=True)
            his_acts, _hmkt = ops_of(act, with_pos=True)
            jobs = plan_jobs(st)
            rows.append((d, st, his_acts, our_acts, jobs))

    if not rows:
        print("no comparable steps produced", file=sys.stderr)
        for k, v in errors.items():
            print(f"   {k}: {v}", file=sys.stderr)
        return 1

    print(f"replays {len(files)}  |  his-seat detection: "
          f"{', '.join(f'{k}={v}' for k, v in methods.items())}  |  samples {len(rows)}")
    if errors:
        print("WARNINGS (a non-zero plan() count means OUR PLANNER IS CRASHING and the agent is "
              "degrading to PASS):")
        for k, v in errors.most_common():
            print(f"   {k}: {v}")
    print()

    if a.section in ("all", "diff"):
        section_diff(rows, days)
    if a.section in ("all", "caps"):
        section_caps(rows)
    if a.section in ("all", "reach"):
        section_reach(rows, days, max(1, a.every))
    if a.section in ("all", "state"):
        section_state(rows, days, max(1, a.every))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
