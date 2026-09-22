"""diagnose.report — CSV writers, the per-game table and narrative summaries."""
from __future__ import annotations

import csv
from pathlib import Path
from typing import Any, Dict, List, Optional

from diagnose.analysis import (
    _agent_seat,
    _day_columns,
    _flatten,
    _game_columns,
    game_summary,
    replay_to_summary,
    summarize,
)
from diagnose.config import EPISODE_STEPS
from diagnose.games import load_replay

def print_game_table(rows: List[Dict[str, Any]]):
    if not rows:
        return
    cols = ["agent", "opponent", "seed", "final_money", "opponent_final", "result",
            "idle_share_pct", "idle_units_total", "shed_pressure_days", "floor_sales",
            "animal_escapes", "at_risk_of_escape", "plants_died", "missed_harvest_eod",
            "feed_surplus", "sell_revenue_total", "premium_below_base_frac",
            "discarded_units_total", "unfed_signals", "unwatered_eod"]
    widths = {c: max(len(c), max(len(str(r.get(c, ""))) for r in rows)) for c in cols}
    header = "  ".join(c.rjust(widths[c]) for c in cols)
    print(header)
    print("  ".join("-" * widths[c] for c in cols))
    for r in rows:
        print("  ".join(str(r.get(c, "")).rjust(widths[c]) for c in cols))



def narrative_summary(days: List[Dict[str, Any]], frames: Optional[List[Dict[str, Any]]] = None, metadata: Optional[Dict[str, Any]] = None) -> str:
    """Return a concise, LLM-readable narrative of a single replay."""
    s = summarize(days, frames)
    lines = []
    meta = metadata or {}
    lines.append(f"# Kaggriculture replay summary")
    lines.append(f"- Agent: {meta.get('agent', 'unknown')} vs {meta.get('opponent', 'unknown')} (seat {meta.get('seat', 0)})")
    lines.append(f"- Seed: {meta.get('seed', 'unknown')}, Steps: {meta.get('episode_steps', EPISODE_STEPS)}")
    lines.append(f"- Final money: ${s['final_money']:,.0f} over {s['days']} days (avg daily delta ${s['avg_daily_delta']:+,.0f})")
    lines.append("")
    lines.append("## Economic performance")
    lines.append(f"- Sell revenue (committed): ${s['sell_revenue_total']:,.0f} | Itemized costs: ${s['itemized_costs_total']:,.0f}  (net ${s['sell_revenue_total'] - s['itemized_costs_total']:,.0f})")
    lines.append(f"- Costs: seeds ${s['seed_cost_total']:,.0f} | animals ${s['animal_cost_total']:,.0f} | product ${s['product_cost_total']:,.0f} | hiring ${s['hire_cost_total']:,.0f} | land ${s['land_cost_total']:,.0f}")
    lines.append(f"- Hires: {s['hires_total']} | Land unlocks: {s['land_unlocks_total']}")
    lines.append("")
    lines.append("## Inefficiency signals")
    lines.append(f"- Idle-labour share: {s['idle_pct']}  ({s['idle_units_total']} unit-PASS turns of {s['unit_turns_total']}, {s['idle_units_ready_total']} on ready produce)")
    lines.append(f"- Feed self-sufficiency: wheat produced* {s['wheat_produced_total']} | fed {s['wheat_fed_total']} | bought {s['wheat_bought_total']} | sold {s['wheat_sold_total']} | surplus {s['feed_surplus_total']:+.0f}   (*=net of audit flows; see AGENTS.md)")
    lines.append(f"- Shed pressure days (>=95): {s['shed_pressure_days']} | Overflow days (=100): {s['shed_overflow_days']} | Discarded items: {s['discarded_items']}")
    lines.append(f"- Floor-price sales: {s['floor_sales']} | Below-base sales: {s['below_base_sales']}")
    lines.append(f"- Premium below-base realized frac: {s['premium_below_base_frac']:.3f}")
    lines.append(f"- Animal escape events: {s['animal_escapes']} {s['animals_escaped_by']} | Unfed at EOD: {s['unfed_at_eod']} | At risk of escape: {s['at_risk_of_escape']}")
    lines.append(f"- Plants died to weeds: {s['plants_died_to_weeds']} | Harvests: {s['harvests_total']} | Unwatered at end-of-day: {s['unwatered_crop_eod']} | Missed harvests at EOD: {s['missed_harvest_eod']}")
    lines.append(f"- Weed peak count: {s['weeds_peak']}")
    lines.append("")
    lines.append("## Day-by-day money curve")
    for d in days:
        delta = d['money_delta']
        delta_str = f"{delta:+,.0f}"
        lines.append(f"- Day {d['day']:2d}: ${d['end_money']:>9,.0f}  delta {delta_str:>10s}  "
                     f"shed {d['max_shed_total']:>3d}  weeds {d['weeds_max']:>2d}  "
                     f"idle {d['idle_turns']:>2d}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Batch runner + CLI
# ---------------------------------------------------------------------------



def write_run_csv(run_dir: Path, paths: List[Path]):
    """Write per-seed days CSVs and games.csv for the agent under test.

    - days_seed<S>.csv — per-day view of OUR agent (its stored seat, normally 1);
      one file per distinct seed, so each game's daily data stays separated.
    - games.csv         — one compact row per replay for OUR agent (includes the
      opponent's final revenue and a WIN / LOSS / TIE tag).

    Per-step detail stays in the JSON replays (no steps.csv).
    """
    run_dir = Path(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    days_by_seed: Dict[str, List[Dict[str, Any]]] = {}
    games_rows = []
    for path in paths:
        replay = load_replay(path)
        meta = replay.get("_diagnose_meta", {})
        agent_seat = _agent_seat(replay)
        _, days, _ = replay_to_summary(replay, seat=agent_seat)
        games_rows.append(game_summary(path))
        seed = str(meta.get("seed", "unknown"))
        base = {
            "agent": meta.get("agent", "unknown"),
            "opponent": meta.get("opponent", "unknown"),
            "seed": meta.get("seed", "unknown"),
        }
        seed_rows = days_by_seed.setdefault(seed, [])
        for d in days:
            row = dict(base)
            dd = dict(d)
            dd["market_orders"] = len(d.get("market_orders") or [])
            row.update(_flatten(dd))
            seed_rows.append(row)

    def _write(rows, name, cols):
        if not rows:
            return
        path = run_dir / name
        with open(path, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=cols)
            w.writeheader()
            w.writerows(rows)
        print(f"  wrote {path.name} ({len(rows)} rows)")

    for seed in sorted(days_by_seed):
        _write(days_by_seed[seed], f"days_seed{seed}.csv", _day_columns())
    _write(games_rows, "games.csv", _game_columns())
