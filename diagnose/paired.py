"""diagnose.paired — same-seed A/B delta report + wins-not-money paired verdict."""
from __future__ import annotations

from pathlib import Path
from typing import List

from diagnose.analysis import _agent_seat, game_summary, replay_to_summary
from diagnose.games import load_replay

def _money_curve(path: Path):
    replay = load_replay(path)
    _, days, _ = replay_to_summary(replay, seat=_agent_seat(replay))
    return {d["day"]: d["end_money"] for d in days}



def _paired_verdict(diffs):
    """Statistical verdict on paired per-seed deltas, following wins-not-money.

    Rule: keep the change iff (1) the mean delta is more than 2 standard errors
    from zero (|t| = |mean|/SE > 2) AND (2) a majority of seeds lean the same way
    as the mean. Aggregating per opponent first (never pooled) keeps the spread
    honest; pairing old/new on the SAME seed cancels that seed's luck.
    """
    import statistics as st
    import math
    diffs = [float(d) for d in diffs if d is not None]
    n = len(diffs)
    base = {"n": n, "mean": 0.0, "sd": 0.0, "se": 0.0, "t": 0.0,
            "frac_same_sign": 0.0, "keep": False, "note": ""}
    if n == 0:
        base["note"] = "no paired seeds"
        return base
    mean = sum(diffs) / n
    base["mean"] = mean
    if n == 1:
        base["mean"] = mean
        base["se"] = float("inf")
        base["note"] = "single paired seed — cannot estimate SE; re-run with more seeds (--batch 12)"
        return base
    sd = st.stdev(diffs)
    base["sd"] = sd
    se = sd / math.sqrt(n)
    base["se"] = se
    base["t"] = mean / se if se > 0 else float("inf") if mean != 0 else 0.0
    sign = 1 if mean > 0 else (-1 if mean < 0 else 0)
    if sign == 0:
        base["note"] = "zero mean — a change, not an effect"
        return base
    same = sum(1 for d in diffs if (d > 0) == (sign == 1))
    base["frac_same_sign"] = same / n
    mag_signif = abs(base["t"]) > 2.0 if base["t"] != float("inf") else (mean != 0)
    consensus = base["frac_same_sign"] > 0.5
    base["keep"] = bool(mag_signif and consensus)
    if not mag_signif:
        base["note"] = "mean within 2 SE of zero — no reliable effect"
    elif not consensus:
        base["note"] = "mean > 2 SE but seeds disagree in sign — treat with caution"
    else:
        base["note"] = "clear — mean > 2 SE and majority of seeds agree in sign"
    return base



def _print_verdict(lines, label):
    v = _paired_verdict([r["delta"] for r in lines])
    win_n = sum(1 for r in lines if r.get("result_new") == "WIN")
    tie_n = sum(1 for r in lines if r.get("result_new") == "TIE")
    loss_n = v["n"] - win_n - tie_n
    verdict = "KEEP" if v["keep"] else "REJECT"
    print(f"\n  {label}: n={v['n']}  mean Δ=${v['mean']:+,.0f}  "
          f"SE=${v['se']:,.0f}  t={v['t']:+.2f}  same-sign {v['frac_same_sign']:.0%}")
    print(f"            win {win_n} / tie {tie_n} / loss {loss_n}  →  {verdict} ({v['note']})")
    return v



def ab_delta_report(paths: List[Path], per_day: bool = False):
    """Print same-seed old-vs-new deltas for a compare run."""
    from collections import defaultdict
    pairs = defaultdict(lambda: {"old": None, "new": None})
    for p in paths:
        meta = load_replay(p).get("_diagnose_meta", {})
        pairs[(meta.get("opponent"), meta.get("seed"))][meta.get("agent")] = p

    print("\n--- A/B old vs new (same seeds) ---")
    cols = ["opponent", "seed", "old_final", "new_final", "delta",
            "idle_delta", "floor_delta", "unwatered_delta", "escapes_delta", "harvest_delta"]
    rows = []
    for key, d in sorted(pairs.items()):
        if not d["old"] or not d["new"]:
            continue
        o = game_summary(d["old"]); n = game_summary(d["new"])
        rows.append({
            "opponent": key[0], "seed": key[1],
            "old_final": o["final_money"], "new_final": n["final_money"],
            "delta": n["final_money"] - o["final_money"],
            "result_old": o["result"], "result_new": n["result"],
            "idle_delta": n["idle_steps"] - o["idle_steps"],
            "floor_delta": n["floor_sales"] - o["floor_sales"],
            "unwatered_delta": n["unwatered_eod"] - o["unwatered_eod"],
            "escapes_delta": n["animal_escapes"] - o["animal_escapes"],
            "harvest_delta": n["harvests"] - o["harvests"],
        })
    if rows:
        widths = {c: max(len(c), max(len(str(r.get(c, ""))) for r in rows)) for c in cols}
        print("  ".join(c.rjust(widths[c]) for c in cols))
        print("  ".join("-" * widths[c] for c in cols))
        for r in rows:
            print("  ".join(str(r.get(c, "")).rjust(widths[c]) for c in cols))
    else:
        print("  (no paired old/new replays found)")

    if per_day:
        for key, d in sorted(pairs.items()):
            if not d["old"] or not d["new"]:
                continue
            om = _money_curve(d["old"]); nm = _money_curve(d["new"])
            print(f"\n  per-day money (opponent={key[0]}, seed={key[1]})")
            print("    day     old       new        Δ")
            for day in sorted(set(om) | set(nm)):
                o = om.get(day, 0); n = nm.get(day, 0)
                print(f"    {day:3d}  {o:>9,.0f}  {n:>9,.0f}  {n - o:>9,}")

    # Paired verdict across seeds — wins-not-money decision rule.
    from collections import defaultdict
    if rows:
        by_opp = defaultdict(list)
        for r in rows:
            by_opp[r["opponent"]].append(r)
        print("\n--- paired verdict (KEEP iff |mean Δ| > 2·SE AND majority of seeds agree in sign) ---")
        for opp in sorted(by_opp):
            _print_verdict(by_opp[opp], f"{opp}")
        print()
        _print_verdict(rows, "ALL OPPONENTS")
    return rows


# ---------------------------------------------------------------------------
# --grid — sweep the agent.py E1_PARAMS space, reusing the paired --compare design
# ---------------------------------------------------------------------------
