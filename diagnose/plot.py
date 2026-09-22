"""diagnose.plot — matplotlib dashboards, animated farm-board GIFs, payback chart.

Matplotlib is imported lazily inside the functions (with the Agg backend) so
the rest of the package never pays for importing it or needs a display.
Split from the monolith diagnose.py.
"""
from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional

from diagnose.analysis import _agent_seat, _shed_total, replay_to_summary
from diagnose.config import (
    ANIMALS,
    MARKET_PARAMS,
    PRICE_FLOOR,
    PRODUCTS,
    SHED_CAPACITY,
    TURNS_PER_DAY,
    _SHOP_TITLE,
    _SPIKEY_PRODUCTS,
)
from diagnose.games import load_replay

def _tile_count_weeds(tiles):
    n = 0
    for row in tiles or []:
        for t in row:
            if isinstance(t, dict) and t.get("kind") == "WEED":
                n += 1
    return n



def _collect_step_series(replay):
    """One pass over a replay → per-step curves for BOTH seats + shared market.

    Returns dict (plain lists, index = step number 0..n-1):
      xs            step numbers              n_steps       number of steps
      money[seat]   money per step, per seat  shed[seat]    shed total per seat
      weeds[seat]   WEED count per seat       prices[p]     market price/step
      shop_steps    [(step, frozenset)] where the unlocked-shop set grew
    Prices/shops are shared by both players, so they are captured once (from the
    seat-0 observation). Money/shed/weeds are captured per seat.
    """
    steps = replay["steps"]
    xs = []
    money, shed, weeds = {0: [], 1: []}, {0: [], 1: []}, {0: [], 1: []}
    prices = {p: [] for p in PRODUCTS}
    shop_sets = []
    for idx, s in enumerate(steps):
        for seat in (0, 1):
            if seat >= len(s):
                money[seat].append(0.0); shed[seat].append(0); weeds[seat].append(0)
                if seat == 0:                      # keep axes length consistent
                    xs.append(idx)
                    for p in PRODUCTS:
                        prices[p].append(MARKET_PARAMS[p]["base"])
                    shop_sets.append(frozenset())
                continue
            o = s[seat].get("observation") or {}
            farms = o.get("farms") or []
            money[seat].append(farms[seat].get("money", 0.0) if seat < len(farms) else 0.0)
            shed[seat].append(_shed_total(o.get("private") or {}))
            me = farms[seat] if seat < len(farms) else {}
            weeds[seat].append(_tile_count_weeds(me.get("tiles", [])))
            if seat == 0:                          # shared market/town: read once
                px = (o.get("market") or {}).get("prices") or {}
                for p in PRODUCTS:
                    prices[p].append(px.get(p, MARKET_PARAMS[p]["base"]))
                town = o.get("town") or {}
                shop_sets.append(frozenset(town.get("unlocked_shops") or []))
                xs.append(idx)
    shop_steps, prev = [], frozenset()
    for i, ss in enumerate(shop_sets):
        new = ss - prev
        if new:
            shop_steps.append((xs[i], new))
        prev = ss
    return {"xs": xs, "money": money, "shed": shed, "weeds": weeds,
            "prices": prices, "shop_steps": shop_steps, "n_steps": len(steps)}



def _draw_day_grid(ax, n_steps):
    """Vertical gridlines + day labels along a step axis."""
    for st in range(0, n_steps, TURNS_PER_DAY):
        ax.axvline(st, color="0.75", lw=0.5, zorder=0)
    ax.set_xticks(list(range(0, n_steps + 1, TURNS_PER_DAY)))
    ax.set_xticklabels([d for d in range(n_steps // TURNS_PER_DAY + 1)])
    ax.set_xlabel("day")



def _plt():
    """Import matplotlib lazily with the Agg backend so graphing works headless."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    return plt



def _sell_series(replay, seat):
    """Derive per-(day, product) realised sales straight from a replay's SELL orders.

    The day-CSV pipeline's avg-price is only populated during a live run (it uses
    a market commit audit that does not exist for saved replays). So for --graph
    we re-quote every SELL order at the market price of the step it was submitted
    on — the pre-sell price the agent actually decided to sell at. Returns a list
    of {day, product, qty, avg, floor_qty, below_qty, base}.
    """
    from collections import defaultdict
    agg = defaultdict(lambda: {"qty": 0, "revenue": 0.0, "floor": 0, "below": 0})
    for idx, s in enumerate(replay["steps"]):
        if seat >= len(s):
            continue
        ent = s[seat]
        obs = ent.get("observation") or {}
        act = ent.get("action") or {}
        # The agent's own observation does NOT carry a "step" field (only seat 0's
        # does); use the replay list index, which IS the step.
        step = idx
        px = (obs.get("market") or {}).get("prices") or {}
        for order in act.get("market") or []:
            if not order or order[0] != "SELL" or len(order) < 2:
                continue
            item = order[1]
            if item not in PRODUCTS:
                continue
            qty = int(order[2]) if len(order) > 2 else 1
            price = px.get(item, MARKET_PARAMS[item]["base"])
            a = agg[(step // TURNS_PER_DAY, item)]
            a["qty"] += qty
            a["revenue"] += qty * price
            a["floor"] += qty if price <= PRICE_FLOOR else 0
            a["below"] += qty if price < MARKET_PARAMS[item]["base"] else 0
    out = []
    for (day, item), a in sorted(agg.items()):
        out.append({"day": day, "product": item, "qty": a["qty"],
                    "avg": a["revenue"] / max(a["qty"], 1),
                    "floor_qty": a["floor"], "below_qty": a["below"],
                    "base": MARKET_PARAMS[item]["base"]})
    return out



def _seat_sells(days: List[Dict[str, Any]], committed: bool, replay, seat: int):
    """Per-day realised-sale markers for one seat.

    Prefers committed per-day data from the replay's market audit (real units at
    realised price). Replays without an audit fall back to re-quoting the request's
    SELL orders (qty = requested, so it over-counts; the legend flags that).
    Returns list of {day, product, qty, avg, floor, below}.
    """
    if committed:
        sells = []
        for d in days:
            for p in PRODUCTS:
                q = (d.get("sell_qty") or {}).get(p, 0)
                if q <= 0:
                    continue
                sells.append({
                    "day": d["day"], "product": p, "qty": q,
                    "avg": d.get(f"avg_price_{p}", 0) or 0.0,
                    "floor": (d.get("floor_sales") or {}).get(p, 0) > 0,
                    "below": (d.get("below_base_sales") or {}).get(p, 0) > 0,
                })
        sells.sort(key=lambda r: (r["day"], r["product"]))
        return sells
    sells = _sell_series(replay, seat)
    for r in sells:
        r["floor"] = r["floor_qty"] > 0
        r["below"] = r["below_qty"] > 0
    return sells



def _draw_seat_dashboard(fig, gs, data, days, sells, seat, header, committed):
    """Draw the 4 stacked panels for ONE seat into a 4×1 GridSpec `gs`.

    Panels, on a shared day axis so a defect lines up with the market action it
    caused: (0) shed vs the 100-cap + weeds/overflow, (1) market prices with
    shop-unlock ticks AND this seat's realised-sale dots (green ≥ base / orange
    below-base / red floor, size ∝ qty), (2) a defect swimlane, (3) end-of-day
    money. `data` is the once-computed shared series, `days`/`sells` are per-seat.
    """
    from matplotlib.lines import Line2D
    plt = _plt()
    xs, n = data["xs"], data["n_steps"]
    by_day = {d["day"]: d for d in days}
    day_axis = sorted(by_day)

    # ---- Panel 0: shed vs cap + weeds (this seat) ----
    ax = fig.add_subplot(gs[0])
    ax.plot(xs, data["shed"][seat], color="#1f77b4", lw=1.1, label=f"shed total (seat {seat})")
    ax.axhline(SHED_CAPACITY, color="#d62728", ls="--", lw=1.2, label=f"shed cap {SHED_CAPACITY}")
    over = [i for i, v in enumerate(data["shed"][seat]) if v > SHED_CAPACITY]
    if over:
        ax.scatter([xs[i] for i in over], [data["shed"][seat][i] for i in over],
                   color="#d62728", s=16, zorder=3,
                   label=f"overflow days: {len(set(i // TURNS_PER_DAY for i in over))}")
    axw = ax.twinx()
    axw.fill_between(xs, data["weeds"][seat], 0, color="0.55", alpha=0.35)
    axw.plot(xs, data["weeds"][seat], color="0.4", lw=0.7)
    axw.set_ylabel("weeds (gray)"); axw.set_ylim(0, max(data["weeds"][seat] + [8]) * 1.2)
    ax.set_ylabel("shed items")
    ax.set_title(f"{header} — shed pressure vs cap + weeds", loc="left", fontsize=11)
    ax.legend(loc="upper right", fontsize=8, framealpha=0.9)
    ax.set_ylim(0, max(SHED_CAPACITY * 1.15, max(data["shed"][seat] + [0]) * 1.15, 1))
    _draw_day_grid(ax, n)

    # ---- Panel 1: market prices + shop ticks + this seat's realised-sale dots ----
    ax = fig.add_subplot(gs[1])
    # Distinct hue per product so every line is identifiable; spike-prone thicker.
    price_color = {p: plt.cm.tab20(i) for p, i in zip(PRODUCTS, [0, 2, 4, 6, 8, 10, 12, 14, 16])}
    for p in PRODUCTS:
        lw = 2.0 if p in _SPIKEY_PRODUCTS else 1.1
        ax.plot(xs, data["prices"][p], color=price_color[p], lw=lw, alpha=0.95, label=p.title())
    for st, new in data["shop_steps"]:
        ax.axvline(st, color="#2ca02c", lw=0.7, alpha=0.6, zorder=1)
        ax.annotate(",".join(sorted(_SHOP_TITLE[k] for k in new)),
                    (st, ax.get_ylim()[1]), xytext=(st + 1, ax.get_ylim()[1]),
                    ha="left", va="top", fontsize=7, rotation=90, color="#2ca02c")
    for rec in sells:
        c = "#d62728" if rec["floor"] else ("#ff7f0e" if rec["below"] else "#2ca02c")
        ax.scatter(rec["day"] * TURNS_PER_DAY + 12, rec["avg"],
                   s=24 + rec["qty"] * 6, color=c, alpha=0.85, zorder=4,
                   edgecolor="black", linewidth=0.4)
    handles = [
        Line2D([], [], marker="o", ls="none", color="#2ca02c", markersize=7, label="sold ≥ base"),
        Line2D([], [], marker="o", ls="none", color="#ff7f0e", markersize=7, label="sold below base"),
        Line2D([], [], marker="o", ls="none", color="#d62728", markersize=7, label=f"sold at floor ${PRICE_FLOOR}"),
    ]
    src = "committed units @ realised price" if committed else "requested units (no audit)"
    leg_sell = ax.legend(handles=handles, loc="upper right", fontsize=8, framealpha=0.9,
                         title=f"sales · {src} · size ∝ qty", title_fontsize=8)
    ax.add_artist(leg_sell)
    ax.legend(loc="lower left", fontsize=8, framealpha=0.9, ncol=2,
              title="product (line colour)", title_fontsize=9)
    ax.set_ylabel("market price ($)")
    ax.set_title(f"{header} — market prices + shop ticks + realised-sale dots", loc="left", fontsize=11)
    _draw_day_grid(ax, n)

    # ---- Panel 2: defect swimlane (this seat) ----
    def totals(d, key):
        v = d.get(key)
        return sum(v.values()) if isinstance(v, dict) else (v or 0)
    rows = [
        ("idle", "#1f77b4", [by_day.get(dy, {}).get("idle_turns", 0) for dy in day_axis]),
        ("floor sales", "#d62728", [totals(by_day.get(dy, {}), "floor_sales") for dy in day_axis]),
        ("below-base", "#ff7f0e", [totals(by_day.get(dy, {}), "below_base_sales") for dy in day_axis]),
        ("escaped", "#8c564b", [by_day.get(dy, {}).get("animals_escaped", 0) for dy in day_axis]),
        ("plants died", "#9467bd", [by_day.get(dy, {}).get("plants_died", 0) for dy in day_axis]),
    ]
    ax = fig.add_subplot(gs[2])
    n_rows = len(rows)
    for r, (label, color, vals) in enumerate(rows):
        y = n_rows - 1 - r                     # idle on top, plants-died at bottom
        nz = [(dx, v) for dx, v in zip(day_axis, vals) if v > 0]
        if not nz:
            continue
        rowmax = max(v for _, v in nz)
        top = {dx for dx, _ in sorted(nz, key=lambda t: t[1], reverse=True)[:3]}
        for dx, v in nz:
            ax.scatter(dx * TURNS_PER_DAY + 12, y, s=40 + (v / rowmax) * 260,
                       color=color, alpha=0.35 + 0.6 * (v / rowmax), zorder=3)
            if dx in top:
                ax.text(dx * TURNS_PER_DAY + 12, y + 0.30, str(v), ha="center",
                        va="bottom", fontsize=7, zorder=4)
    ax.set_yticks([len(rows) - 1 - r for r in range(len(rows))])
    ax.set_yticklabels([lbl for lbl, _, _ in rows])
    ax.set_ylim(-0.6, n_rows + 0.15)
    for sep in range(n_rows):                 # faint row separators for readability
        ax.axhline(sep - 0.5, color="0.88", lw=0.6, zorder=1)
    ax.set_title(f"{header} — defects by day (marker size/alpha ∝ count; number = worst days)",
                 loc="left", fontsize=11)
    _draw_day_grid(ax, n)

    # ---- Panel 3: end-of-day money (this seat) ----
    ax = fig.add_subplot(gs[3])
    x = [dy * TURNS_PER_DAY for dy in day_axis]           # step axis, matches _draw_day_grid
    em = [by_day.get(dy, {}).get("end_money", 0) for dy in day_axis]
    ax.bar(x, em, width=TURNS_PER_DAY * 0.8, color="0.6")
    ax.set_ylabel("closing cash ($)")
    ax.set_ylim(0, max(em + [1]) * 1.15)
    ax.set_title(f"{header} — end-of-day money (dips = land / animals / build spend)",
                 loc="left", fontsize=9)
    _draw_day_grid(ax, n)



def plot_game(path: Path, out_dir: Optional[Path] = None):
    """Render a 1×2 side-by-side dashboard: LEFT = agent under test, RIGHT = opponent.

    Each side is the same 4-panel stack (shed, prices + realised-sale dots, defects,
    money), so identical rows let you see the difference in play at a glance. Writes
    `<stem>_graph.png` next to the JSON (or in `out_dir`); this is the --graph output.
    """
    plt = _plt()
    replay = load_replay(path)
    data = _collect_step_series(replay)
    if data["n_steps"] == 0:
        return None
    meta = replay.get("_diagnose_meta", {})
    agent_seat = _agent_seat(replay)
    opp_seat = 1 - agent_seat
    committed = bool(meta.get("audit"))
    _, days_a, _ = replay_to_summary(replay, seat=agent_seat)
    _, days_o, _ = replay_to_summary(replay, seat=opp_seat)
    sells_a = _seat_sells(days_a, committed, replay, agent_seat)
    sells_o = _seat_sells(days_o, committed, replay, opp_seat)
    try:
        final_us = data["money"][agent_seat][-1]
        final_opp = data["money"][opp_seat][-1]
    except IndexError:
        final_us = final_opp = float("nan")
    opp = meta.get("opponent", "opponent")
    seed = meta.get("seed", "?")
    tag = " (US WINS)" if final_us > final_opp else (" (OPP WINS)" if final_opp > final_us else " (TIE)")

    fig = plt.figure(figsize=(28, 12.5))
    outer = fig.add_gridspec(1, 2, wspace=0.33, top=0.92, bottom=0.05, left=0.05, right=0.98)
    ga = outer[0].subgridspec(4, 1, height_ratios=[2.0, 3.4, 2.2, 1.0], hspace=0.5)
    go = outer[1].subgridspec(4, 1, height_ratios=[2.0, 3.4, 2.2, 1.0], hspace=0.5)
    fig.suptitle(f"{meta.get('agent','?')} vs {opp} · seed {seed} · "
                 f"LEFT agent (seat {agent_seat}) · RIGHT opponent (seat {opp_seat}) · "
                 f"final ${final_us:,.0f} vs ${final_opp:,.0f}{tag}",
                 fontsize=13, fontweight="bold")
    _draw_seat_dashboard(fig, ga, data, days_a, sells_a, agent_seat, f"US · seat {agent_seat}", committed)
    _draw_seat_dashboard(fig, go, data, days_o, sells_o, opp_seat, f"OPPONENT · seat {opp_seat}", committed)

    out_path = (out_dir or path.parent) / (path.stem + "_graph.png")
    fig.savefig(out_path, dpi=110)
    plt.close(fig)
    return out_path



def graph_batch(paths: List[Path], run_dir: Path, gif_fps: float = 1.5) -> List[Path]:
    """Render per replay the 1×2 side-by-side dashboard AND an animated farm-board
    GIF (both farms + farmer/hand positions + money race, one frame per day),
    returning the paths written. `gif_fps` sets GIF playback speed. Also emits a
    season-constant animal-care payback chart once per run."""
    out = []
    try:
        rendered = plot_animal_care_payback(Path(run_dir) / "animal_care_payback.png")
        if rendered:
            out.append(rendered)
            print(f"  reference: {rendered.name}")
    except Exception as e:
        print(f"  animal-care chart FAILED: {e}")
    for p in paths:
        try:
            rendered = plot_game(p, out_dir=run_dir)
            if rendered:
                out.append(rendered)
                print(f"  graph: {rendered.name}")
        except Exception as e:  # keep one bad replay from killing the batch
            print(f"  graph FAILED {p.name}: {e}")
        try:
            rendered = plot_board_gif(p, out_dir=run_dir, fps=gif_fps)
            if rendered:
                out.append(rendered)
                print(f"  graph: {rendered.name}")
        except Exception as e:
            print(f"  board GIF FAILED {p.name}: {e}")
    return out


# ---------------------------------------------------------------------------
# --graph board montage — per-step state of the whole environment
# ---------------------------------------------------------------------------


_CROP_COLOR = {"WHEAT": "#e6b800", "CARROT": "#ff7f0e", "TOMATO": "#e03e36",
               "STRAWBERRY": "#f06292", "MELON": "#5cbb5c"}

_STRUCT_COLOR = {"COOP": "#b0bec5", "PASTURE": "#8d9aa6"}

_ANIMAL_COLOR = {"GOOSE": "#e0e0e0", "COW": "#5d4037", "SHEEP": "#c0a878"}

_ANIMAL_LETTER = {"GOOSE": "G", "COW": "C", "SHEEP": "S"}
_EMPTY, _LOCKED, _WEED = "#f5f5f5", "#3a3a3a", "#8b5a2b"



def _hex_rgb(h: str):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))



def _tile_color_letter(t):
    """Return (rgb-as-floats, overlay-letter-or-None) for one tile."""
    if t is None:
        return _hex_rgb(_EMPTY), None
    if t == "LOCKED":
        return _hex_rgb(_LOCKED), None
    if isinstance(t, dict):
        k = t.get("kind")
        if k == "WEED":
            return _hex_rgb(_WEED), None
        if k == "PLANT":
            return _hex_rgb(_CROP_COLOR.get(t.get("crop"), "#66bb6a")), (t.get("crop") or "")[:1]
        if k in ("COOP", "PASTURE"):
            a = t.get("animal")
            if a:
                return _hex_rgb(_ANIMAL_COLOR.get(a, "#9e9e9e")), _ANIMAL_LETTER.get(a, "a")
            return _hex_rgb(_STRUCT_COLOR.get(k, "#9e9e9e")), ("⌑" if k == "COOP" else "◇")
    return _hex_rgb(_EMPTY), None



def _draw_mini_map(ax, tiles):
    """Colour-coded 10×10 farm map on `ax` (crops/animals get a single-letter mark)."""
    arr, marks = [], []
    for y, row in enumerate(tiles):
        arr_row = []
        for x, t in enumerate(row):
            c, l = _tile_color_letter(t)
            arr_row.append(c)
            if l:
                marks.append((x, y, l))
        arr.append(arr_row)
    ax.imshow(arr, origin="upper", interpolation="nearest", aspect="equal")
    for x, y, l in marks:
        ax.text(x, y, l, ha="center", va="center", fontsize=6,
                color="#111111", zorder=5, fontweight="bold")
    ax.set_xticks([]); ax.set_yticks([])
    for s in ax.spines.values():
        s.set_linewidth(0.6)



def _tile_counts(tiles):
    crops, animals, weeds, struct = {}, {}, 0, {"COOP": 0, "PASTURE": 0}
    for row in tiles:
        for t in row:
            if isinstance(t, dict):
                k = t.get("kind")
                if k == "PLANT":
                    crops[t.get("crop")] = crops.get(t.get("crop"), 0) + 1
                elif k == "WEED":
                    weeds += 1
                elif k in ("COOP", "PASTURE"):
                    struct[k] += 1
                    if t.get("animal"):
                        animals[t.get("animal")] = animals.get(t.get("animal"), 0) + 1
    return crops, animals, weeds, struct



def _day_cell_readout(snap) -> str:
    shed = snap["shed"] or {}
    seeds = snap["seeds"] or {}
    crops, animals, weeds, struct = snap["counts"]
    sh = " ".join(f"{k[:1]}{v}" for k, v in shed.items() if v) or "empty"
    sd = " ".join(f"{k[:1]}{v}" for k, v in seeds.items() if v) or ""
    an = " ".join(f"{_ANIMAL_LETTER.get(k, k[:1])}{v}" for k, v in animals.items()) or "-"
    cr = " ".join(f"{k[:1]}{v}" for k, v in crops.items()) or "-"
    return (f"${snap['money']:,.0f}  shed[{sh}]  seeds[{sd}]",
            f"crops[{cr}]  animals[{an}]  weeds {weeds}  coop/past {struct['COOP']}/{struct['PASTURE']}")



def plot_board(path: Path, out_dir: Optional[Path] = None):
    """Render a per-game board montage: `_board.png`.

    Top: the shared market price curves with a marker per sampled day (so you can
    correlate state with the price action). Below: a 6×5 grid, one cell per day,
    each showing BOTH farmers' 10×10 maps (colour-coded crops / animals / weeds /
    structures / locked) plus a money · shed · seeds · weeds · crop/animals readout.
    Everything comes straight from each step's observation.
    """
    plt = _plt()
    replay = load_replay(path)
    data = _collect_step_series(replay)
    n = data["n_steps"]
    if n == 0:
        return None
    meta = replay.get("_diagnose_meta", {})
    agent_seat = _agent_seat(replay)
    opp_seat = 1 - agent_seat
    steps = replay["steps"]

    # Snapshot per day at its last step (state after that day's play).
    days = list(range(min(30, (n + TURNS_PER_DAY - 1) // TURNS_PER_DAY)))
    snap_steps = [min(d * TURNS_PER_DAY + TURNS_PER_DAY - 1, n - 1) for d in days]
    snaps = []
    for i in snap_steps:
        s = steps[i]
        row = []
        for seat in (agent_seat, opp_seat):
            if seat >= len(s):
                row.append(None)
                continue
            o = s[seat].get("observation") or {}
            me = (o.get("farms") or [])[seat] if seat < len(o.get("farms") or []) else {}
            pr = o.get("private") or {}
            tiles = list(me.get("tiles") or [])
            row.append({"money": me.get("money", 0.0),
                        "shed": pr.get("shed") or {},
                        "seeds": pr.get("seeds") or {},
                        "tiles": tiles,
                        "counts": _tile_counts(tiles)})
        snaps.append((i, row))

    ncols = 5
    nrows = (len(snaps) + ncols - 1) // ncols
    fig = plt.figure(figsize=(22, 4.6 + nrows * 3.4))
    outer = fig.add_gridspec(2, 1, height_ratios=[1.0, nrows * 3.4],
                             hspace=0.35, top=0.93, bottom=0.015, left=0.02, right=0.99)

    # ---- Top: shared market prices with per-day markers ----
    axp = fig.add_subplot(outer[0])
    price_color = {p: plt.cm.tab20(i) for p, i in zip(PRODUCTS, [0, 2, 4, 6, 8, 10, 12, 14, 16])}
    for p in PRODUCTS:
        axp.plot(data["xs"], data["prices"][p], color=price_color[p],
                 lw=1.1 if p in _SPIKEY_PRODUCTS else 0.7, alpha=0.9)
    for d, i in zip(days, snap_steps):
        axp.axvline(i, color="#d62728", lw=0.6, alpha=0.7)
        if d % 2 == 0:
            axp.text(i, axp.get_ylim()[1], str(d), fontsize=6, rotation=90,
                     ha="right", va="top", color="#d62728")
    axp.set_ylabel("market price ($)")
    axp.set_title(f"{meta.get('agent','?')} vs {meta.get('opponent','?')} · seed {meta.get('seed','?')}"
                  f" · market prices (red = sampled day)", loc="left", fontsize=11)
    _draw_day_grid(axp, n)
    axp.axhline(0, color="k", lw=0.5)

    # ---- Below: day cells, each with both maps + readout ----
    gs = outer[1].subgridspec(nrows, ncols, hspace=0.62, wspace=0.20)
    for k, (i, row) in enumerate(snaps):
        ax = fig.add_subplot(gs[k // ncols, k % ncols])
        ax.set_axis_off()
        ax.set_title(f"day {days[k]}", fontsize=10, fontweight="bold", pad=3)
        for seat_idx, seat in enumerate((agent_seat, opp_seat)):
            snap = row[seat_idx]
            if snap is None:
                continue
            lab = "US" if seat == agent_seat else "OPP"
            left = 0.02 + seat_idx * 0.50
            sub = ax.inset_axes([left, 0.34, 0.47, 0.62])
            _draw_mini_map(sub, snap["tiles"])
            sub.set_title(lab, fontsize=8, pad=1)
            l1, l2 = _day_cell_readout(snap)
            ax.text(left + 0.01, 0.24, l1, ha="left", va="top", fontsize=7,
                    transform=ax.transAxes, family="monospace")
            ax.text(left + 0.01, 0.11, l2, ha="left", va="top", fontsize=7,
                    transform=ax.transAxes, family="monospace")
        # day cell money diff
        a, o = row[0], row[1]
        if a and o:
            ax.text(0.02, 0.005, f"Δ ${o['money'] - a['money']:+,.0f}", fontsize=8,
                    transform=ax.transAxes, color="#d62728")

    out_path = (out_dir or path.parent) / (path.stem + "_board.png")
    fig.savefig(out_path, dpi=100)
    plt.close(fig)
    return out_path



def _draw_farm_with_positions(ax, tiles, farmer, hands):
    """One farm on `ax`: colour-coded 10×10 tiles plus farmer / hand position dots.

    Mirrors the notebook's `draw_farm` idea: a ripe crop (yield_units > 0) gets a
    white dot, animals are drawn in their product colour, the shed is the centre
    cross, and each worker is a shaded circle (farmer bigger than hands)."""
    ax.imshow(_tiles_to_rgb(tiles), origin="upper", interpolation="nearest", aspect="equal")
    # ripe-crop dots
    for y, row in enumerate(tiles):
        for x, t in enumerate(row):
            if isinstance(t, dict) and t.get("kind") == "PLANT" and t.get("yield_units", 0) > 0:
                ax.plot(x, y, "o", ms=3.2, mfc="white", mec="none", zorder=6)
    # animals: distinct triangle marker, one colour per species, always on top of
    # the structure cell so the herd is visible in the farm-board GIF.
    for y, row in enumerate(tiles):
        for x, t in enumerate(row):
            if isinstance(t, dict) and t.get("animal"):
                a = t.get("animal")
                ax.plot(x, y, marker="^", ms=7.0, ls="none", zorder=6,
                        mfc=_ANIMAL_COLOR.get(a, "#9e9e9e"), mec="white", mew=1.1)
    ax.plot([0, 10], [5, 5], color="0.5", lw=1.4, alpha=0.8, zorder=4)
    ax.plot([5, 5], [0, 10], color="0.5", lw=1.4, alpha=0.8, zorder=4)
    ax.text(5, 5, "shed", ha="center", va="center", fontsize=6, color="#111111", zorder=5)
    if farmer is not None:
        ax.plot(farmer[0], farmer[1], "o", ms=9.0, mfc="#1e3a8a", mec="white", mew=1.2, zorder=7)
    for hx, hy in hands or []:
        ax.plot(hx, hy, "o", ms=5.5, mfc="#1e3a8a", mec="white", mew=1.0, zorder=7)
    ax.set_xlim(-0.5, 9.5); ax.set_ylim(9.5, -0.5)
    ax.set_xticks([]); ax.set_yticks([])
    for s in ax.spines.values():
        s.set_linewidth(0.6)



def _tiles_to_rgb(tiles):
    arr = []
    for row in tiles:
        arr_row = []
        for t in row:
            c, _ = _tile_color_letter(t)
            arr_row.append(c)
        arr.append(arr_row)
    return arr



def plot_board_gif(path: Path, out_dir: Optional[Path] = None, fps: float = 1.5,
                   max_days: int = 30) -> Optional[Path]:
    """Render an animated farm-board GIF from a saved replay, `<stem>_board.gif`.

    One frame per in-game day (like the notebook's `season_gif`): BOTH farms side by
    side (tiles + ripe-crop dots + farmer/hand position markers), a money-race panel
    showing both banks through the season, and a fixed legend for what each colour /
    marker means. `fps` controls playback speed (default 2 frames/s = 0.5 s per day —
    raise it to 4-5 if you want a quicker skim). This is the `--graph` board output —
    an animation you can watch for *when* a defect appears, instead of a static PNG.
    """
    from matplotlib.patches import Patch
    from matplotlib.lines import Line2D
    plt = _plt()
    replay = load_replay(path)
    agent_seat = _agent_seat(replay)
    opp_seat = 1 - agent_seat
    meta = replay.get("_diagnose_meta", {})
    n = len(replay.get("steps", []))
    if n == 0:
        return None
    steps = replay["steps"]
    days = list(range(min(max_days, (n + TURNS_PER_DAY - 1) // TURNS_PER_DAY)))
    snap_steps = [min(d * TURNS_PER_DAY + TURNS_PER_DAY - 1, n - 1) for d in days]

    money = {seat: [] for seat in (agent_seat, opp_seat)}
    for s in steps:
        for seat in (agent_seat, opp_seat):
            if seat < len(s):
                o = s[seat].get("observation") or {}
                me = (o.get("farms") or [])[seat] if seat < len(o.get("farms") or []) else {}
                money[seat].append(me.get("money", 0.0) or 0.0)

    top = max([max(money[agent_seat] + [0])] + [max(money[opp_seat] + [0])]) * 1.08

    def _snapshot(seat, i):
        s = steps[i]
        if seat >= len(s):
            return None
        o = s[seat].get("observation") or {}
        me = (o.get("farms") or [])[seat] if seat < len(o.get("farms") or []) else {}
        if not me:
            return None
        hands = []
        for h in me.get("hands") or []:
            hp = h.get("pos") if isinstance(h, dict) else h
            if isinstance(hp, (list, tuple)) and len(hp) == 2:
                hands.append(hp)
        farmer = me.get("farmer")
        if not isinstance(farmer, (list, tuple)) or len(farmer) != 2:
            farmer = None
        return {
            "tiles": [list(r) for r in (me.get("tiles") or [])],
            "farmer": farmer,
            "hands": hands,
            "money": me.get("money", 0.0) or 0.0,
        }

    snaps = [(d, _snapshot(agent_seat, k), _snapshot(opp_seat, k)) for d, k in zip(days, snap_steps)]

    from matplotlib.animation import FuncAnimation, PillowWriter
    fig, (axA, axO, axM, axL) = plt.subplots(
        1, 4, figsize=(12.0, 3.7), gridspec_kw={"width_ratios": [1.0, 1.0, 1.2, 0.95]},
        sharey=False)

    # ---- Fixed legend (drawn once; not cleared by frame()) ----
    axL.axis("off")
    crop_handles = []
    for c in ("WHEAT", "CARROT", "TOMATO", "STRAWBERRY", "MELON"):
        crop_handles.append(Patch(facecolor=_hex_rgb(_CROP_COLOR[c]), label=c.title()))
    legend_handles = crop_handles + [
        Patch(facecolor=_hex_rgb(_WEED), label="weed"),
        Patch(facecolor=_hex_rgb(_LOCKED), label="locked (unbought)"),
        Patch(facecolor=_hex_rgb(_STRUCT_COLOR["COOP"]), label="coop / pasture"),
        Line2D([], [], marker="o", ls="none", ms=8, mfc="white", mew=0.5, mec="#555", label="ripened crop"),
        Line2D([], [], marker="o", ls="none", ms=12, mfc="#1e3a8a", mew=1.2, mec="white", label="farmer"),
        Line2D([], [], marker="o", ls="none", ms=8, mfc="#1e3a8a", mew=1.0, mec="white", label="hired hand"),
    ]
    legend_handles += [Line2D([], [], marker="^", ls="none", ms=9,
                              mfc=_hex_rgb(_ANIMAL_COLOR[a]), mew=1.0, mec="white", label=f"{a.title()} ({_ANIMAL_LETTER[a]})")
                       for a in ("GOOSE", "COW", "SHEEP")]
    legend_handles += [
        Line2D([], [], marker="o", ls="none", color="#1e3a8a", lw=2, label="US bank ($)"),
        Line2D([], [], marker="o", ls="none", color="#d62728", lw=1.6, label="OPP bank ($)"),
    ]
    axL.legend(handles=legend_handles, loc="upper left", fontsize=7.5, ncol=1,
               handleheight=1.3, frameon=False, title="Legend")

    def frame(i):
        d, sa, so = snaps[i]
        for ax in (axA, axO, axM):
            ax.clear()
        if sa:
            _draw_farm_with_positions(axA, sa["tiles"], sa["farmer"], sa["hands"])
            axA.set_title(f"US · day {d} · ${sa['money']:,.0f}", fontsize=9, fontweight="bold")
        else:
            axA.set_title(f"US · day {d}", fontsize=9)
        if so:
            _draw_farm_with_positions(axO, so["tiles"], so["farmer"], so["hands"])
            axO.set_title(f"OPP · day {d} · ${so['money']:,.0f}", fontsize=9, fontweight="bold")
        else:
            axO.set_title(f"OPP · day {d}", fontsize=9)
        k = snap_steps[i]
        axM.plot([money[agent_seat][t] for t in range(k)], color="#1e3a8a", lw=2.0, label="US")
        axM.plot([money[opp_seat][t] for t in range(k)], color="#d62728", lw=1.6, label="OPP")
        axM.set_xlim(0, n); axM.set_ylim(0, top)
        axM.set_title("Coins in the bank", fontsize=9, fontweight="bold")
        axM.set_xlabel("turn", fontsize=8); axM.grid(alpha=0.2)
        axM.legend(fontsize=7.5, loc="upper left", frameon=False)
        fig.suptitle(f"{meta.get('agent','?')} vs {meta.get('opponent','?')} · seed {meta.get('seed','?')}",
                     fontsize=11, fontweight="bold")

    anim = FuncAnimation(fig, frame, frames=len(snaps), interval=200)
    out_path = (out_dir or path.parent) / (path.stem + "_board.gif")
    anim.save(out_path, writer=PillowWriter(fps=max(fps, 1)), dpi=90)
    plt.close(fig)
    return out_path



_PRODUCT_COLOR = {"EGG": "#d4a017", "MILK": "#8d9aa6", "WOOL": "#b08d57"}



def _animal_payback(a, prod, cared):
    """Mirror _daily_refresh_animals: a cared+fed day adds 1 to a pending counter,
    and a production day pays out 1 + whatever has accumulated, capped by max_held."""
    import numpy as np
    feed_cost = MARKET_PARAMS["WHEAT"]["base"]  # optimistic: base wheat; the market quotes higher as you buy
    cash, pending = [-a["cost"]], 0
    for d in range(1, 30):
        units = 0
        if d >= a["first_yield_day"] and (d - a["first_yield_day"]) % a["interval"] == 0:
            units, pending = min(a["max_held"], 1 + pending), 0
        if cared:
            pending += 1
        cash.append(cash[-1] + units * MARKET_PARAMS[prod]["base"] - feed_cost)
    return cash



def plot_animal_care_payback(out_path: Path) -> Path:
    """Season economics of animal CARE: for each animal, cumulative cash over the
    30-day season for FED-ONLY (dotted) vs FED+CARED (solid), against a FEED_COST of
    one wheat/day, with break-even-day markers on the cared lines. Season-constant —
    identical for every replay, so it is rendered once per `--graph` run / `--animals`.
    """
    import matplotlib.patheffects as pe
    plt = _plt()
    season = list(range(0, 30))
    fig, ax = plt.subplots(figsize=(8.2, 3.6))
    end_season = {}
    for animal in ("GOOSE", "COW", "SHEEP"):
        a = ANIMALS[animal]
        prod = a["product"]
        c = _PRODUCT_COLOR[prod]
        for cared, style, width, alpha in ((False, ":", 1.6, 0.55), (True, "-", 2.2, 1.0)):
            cash = _animal_payback(a, prod, cared)
            ax.plot(season, cash, style, lw=width, color=c, alpha=alpha,
                    label=(f"{animal.title()} cared — {prod.lower()} x{1 + a['interval']} per pickup"
                           if cared else None))
            be = next((int(d) for d, cv in zip(season, cash) if cv >= 0), None)
            if be and cared:
                dx, dy, ha = {"GOOSE": (-0.4, -560, "right"), "COW": (0.4, -560, "left"),
                              "SHEEP": (0, 320, "center")}[animal]
                ax.plot(be, cash[be], "o", ms=9, color=c, mec="white", zorder=5)
                ax.text(be + dx, cash[be] + dy, f"day {be}", fontsize=9.5, color=c,
                        weight="bold", ha=ha,
                        path_effects=[pe.withStroke(linewidth=2.6, foreground="white")])
            end_season[(animal, cared)] = cash[-1]
    ax.axhline(0, color="#4A3F35", lw=1)
    ax.set_xlabel("season day (animal bought on day 0)")
    ax.set_ylabel("cumulative coins")
    ax.set_title("Care changes the ranking: solid = fed + cared, dotted = fed only")
    ax.legend(fontsize=9.5, frameon=False, loc="upper left")
    plt.savefig(out_path, dpi=110, bbox_inches="tight")
    plt.close(fig)
    for animal in ("GOOSE", "COW", "SHEEP"):
        print(f"  {animal.title():6s} end of season: "
              f"{end_season[(animal, True)]:+8,.0f} cared   {end_season[(animal, False)]:+8,.0f} fed only")
    return out_path
