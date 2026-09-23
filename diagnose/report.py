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
    game_summary_from,
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



def _episode_id_from_name(name: str) -> Optional[str]:
    """Pull the numeric id out of a replay filename (e.g. episode-112413080-replay.json
    -> '112413080'), used as the CSV key for --lb leaderboard replays that carry
    no seed (info/configuration seed are null in lb replays)."""
    import re
    digs = re.findall(r"\d+", name)
    return digs[-1] if digs else None


def _replay_csv_worker(job):
    """Analyze ONE replay file (load + per-seat days + game row), run in a pool.

    job = (path_str, seats_request | None, lb | None). Seats: an explicit list
    wins; else the replay's stored _diagnose_meta seat (our own runs); else BOTH
    seats (foreign/opponent replays with no meta, where we don't know the
    alignment). In leaderboard (lb) mode the seed is null in the json, so the
    per-day CSV is keyed on the episode id from the filename, and per-seat rows
    are labelled with the real team names from info.TeamNames."""
    path_str, seats_request, lb = job
    replay = load_replay(Path(path_str))
    meta = replay.get("_diagnose_meta", {})
    info = replay.get("info", {}) or {}
    team_names = info.get("TeamNames") or [a.get("Name") for a in (info.get("Agents") or [])] or []

    if meta.get("seed") is not None:
        seed = str(meta["seed"])
    elif lb:
        seed = _episode_id_from_name(Path(path_str).name) or "unknown"
    elif info.get("seed") is not None:
        seed = str(info["seed"])
    else:
        seed = "unknown"

    if seats_request is not None:
        seat_list = list(seats_request)
    elif meta.get("seat") is not None:
        seat_list = [int(meta["seat"])]
    else:
        seat_list = [0, 1]

    def _team(seat):
        return team_names[seat] if 0 <= seat < len(team_names) and team_names[seat] else "unknown"

    if not replay.get("steps"):
        return {"multi": False, "seed": seed, "game_rows": [], "day_rows": []}

    game_rows, day_rows = [], []
    for seat in seat_list:
        agent = meta.get("agent") or _team(seat)
        opp = meta.get("opponent") or _team(1 - seat)
        base = {"agent": agent, "opponent": opp, "seed": seed}
        try:
            frames, days, summary = replay_to_summary(replay, seat)
            grow = game_summary_from(replay, seat=seat, days=days, summary=summary)
        except Exception:  # noqa: BLE001 — one bad file must not kill the pool
            continue
        grow.update({"seat": seat, "agent": agent, "opponent": opp, "seed": seed})
        game_rows.append(grow)
        for d in days:
            row = dict(base)
            row["seat"] = seat
            dd = dict(d)
            dd["market_orders"] = len(d.get("market_orders") or [])
            row.update(_flatten(dd))
            day_rows.append(row)
    return {"multi": len(seat_list) > 1, "seed": seed,
            "game_rows": game_rows, "day_rows": day_rows}


def write_run_csv(run_dir: Path, paths: List[Path], workers: Optional[int] = None,
                  seats: Optional[List[int]] = None, lb: bool = False) -> List[Dict[str, Any]]:
    """Write per-seed days CSVs and games.csv for the analysed seat(s).

    - days_seed<S>.csv — per-day view; one file per distinct key (a seed for
      local runs; an episode id for --lb leaderboard runs).
    - games.csv         — one compact row per replay/seat (W/L/T tag included).

    Each replay file is analysed INDEPENDENTLY, so the batch is fanned out
    across cores (default: all cores). Returns the game rows (so the caller can
    print the table without re-analysing). When a run has multiple seats — e.g.
    a foreign/opponent replay with no stored seat — both seats are written and
    a "seat" column is prefixed to both CSVs."""
    run_dir = Path(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    jobs = [(str(p), seats, lb) for p in paths]
    results = []
    if len(jobs) == 1 or (workers is not None and workers <= 1):
        results = [_replay_csv_worker(j) for j in jobs]
    else:
        import multiprocessing as mp
        import os
        w = int(workers if workers is not None else (os.cpu_count() or 1))
        ctx = mp.get_context("fork")
        with ctx.Pool(processes=max(1, min(w, len(jobs)))) as pool:
            results = list(pool.imap(_replay_csv_worker, jobs, chunksize=1))

    game_rows = []
    day_by_seed: Dict[str, List[Dict[str, Any]]] = {}
    multi = any(r.get("multi") for r in results)
    for r in results:
        game_rows.extend(r["game_rows"])
        day_by_seed.setdefault(r["seed"], []).extend(r["day_rows"])

    def _write(rows, name, cols):
        if not rows:
            return
        path = run_dir / name
        cols = list(cols)
        with open(path, "w", newline="") as f:
            wcsv = csv.DictWriter(f, fieldnames=cols)
            wcsv.writeheader()
            # Prune each row to the columns being written: single-seat runs add a
            # "seat" key to every row but don't emit the column unless multi-seat.
            wcsv.writerows({k: r.get(k) for k in cols} for r in rows)
        print(f"  wrote {path.name} ({len(rows)} rows)")

    for seed in sorted(day_by_seed):
        cols = _day_columns()
        if multi:
            cols = ["seat"] + cols
        _write(day_by_seed[seed], f"days_seed{seed}.csv", cols)
    gcols = _game_columns()
    if multi:
        gcols = ["seat"] + gcols
    _write(game_rows, "games.csv", gcols)
    return game_rows
