"""diagnose.render — terminal board rendering + per-day report printout."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from .analysis import summarize

def _fmt_money(v: float) -> str:
    return f"{v:,.0f}"



def _tile_char(t):
    if t is None:
        return "."
    if t == "LOCKED":
        return "#"
    if isinstance(t, dict):
        k = t.get("kind")
        if k == "WEED":
            return "x"
        if k == "PLANT":
            return t["crop"][0].lower()
        if "animal" in t:
            return t["animal"][0]
        if k == "COOP":
            return "C"
        if k == "PASTURE":
            return "P"
    return "?"



def render_map(tiles: List[List[Any]], title: str = ""):
    if title:
        print(title)
    header = "    " + " ".join(str(i % 10) for i in range(len(tiles[0])))
    print(header)
    for y, row in enumerate(tiles):
        print(f" {y:2d}  " + " ".join(_tile_char(t) for t in row))



def render_legend():
    """Print the legend for the 10×10 board grid and the per-day lines once, so a
    long --render report can be read without re-opening this file."""
    print("BOARD GRID LEGEND  (one char per tile; the 10×10 map is row 0 = top)")
    print("  '.' = open/owned tile     '#' = LOCKED (unbought)     'x' = WEED")
    print("  lowercase crop letter:  w wheat · c carrot · t tomato · s strawberry · m melon")
    print("  UPPERCASE animal letter: G goose · C cow · S sheep    C/P = empty COOP / PASTURE")
    print("  ? = unknown tile")
    print("DAY LINE FIELDS")
    print("  money start->end delta (rev/exp)   shed total   weeds   planted/harvested")
    print("  hands hired · land unlocked · shops unlocked   (! = a defect on that day)")




def render_day(day: Dict[str, Any], frames: Optional[List[Dict[str, Any]]] = None):
    print(f"\n=== Day {day['day']:2d}  steps {day['first_step']}-{day['last_step']} ===")
    print(f"  money  ${_fmt_money(day['start_money'])} -> {_fmt_money(day['end_money'])}  "
          f"delta {_fmt_money(day['money_delta'])}  (rev {_fmt_money(day['revenue'])}  exp {_fmt_money(day['expenses'])})")
    print(f"  shed   {day['start_shed_total']} -> {day['end_shed_total']}  max {day['max_shed_total']}")
    print(f"  weeds  {day['weeds_start']} -> {day['weeds_end']}  max {day['weeds_max']}")
    print(f"  hands  {day['hands_start']} -> {day['hands_end']}  hires {day['hires']}  land {day['land_unlocks']}  "
          f"shops {day['shop_unlocks']}")
    if day["plants_planted"]:
        print(f"  planted {dict(day['plants_planted'])}")
    if day["plants_harvested"]:
        print(f"  harvested {dict(day['plants_harvested'])}")
    if day["animals_placed"]:
        print(f"  placed {dict(day['animals_placed'])}")
    if day["market_orders"]:
        print(f"  market orders {len(day['market_orders'])}")
    if day["idle_turns"]:
        print(f"  !!! idle turns: {day['idle_turns']}")
    if day["floor_sales"]:
        print(f"  !!! floor sales: {dict(day['floor_sales'])}")
    if day["animals_escaped"]:
        print(f"  !!! animal escapes: {day['animals_escaped']}")
    if day["plants_died"]:
        print(f"  !!! plants died to weeds: {day['plants_died']}")
    if frames:
        # End-of-day map
        last = [f for f in frames if f["day"] == day["day"]][-1]
        render_map(last["tiles"], title=f"  end-of-day map (crops={len(last['crops'])}, animals={len(last['animals'])}, weeds={last['weeds']})")



def render(days: List[Dict[str, Any]], frames: Optional[List[Dict[str, Any]]] = None, span: Optional[slice] = None):
    if frames is None:
        frames = []
    if span is not None:
        days = days[span]
    render_legend()
    for day in days:
        render_day(day, frames)
    print("\n--- summary ---")
    for k, v in summarize(days, frames).items():
        print(f"  {k}: {v}")


# ---------------------------------------------------------------------------
# CSV export
# ---------------------------------------------------------------------------
