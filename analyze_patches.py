#!/usr/bin/env python3
"""analyze_patches.py -- iterative analysis of route_tape.py + the main.py layer stack.

This tool operationalises the "analyze base -> diagnose base -> analyze patch ->
diagnose new game state -> ... -> final patch" loop the team described. It has two
modes:

  --survey     Static investigation (no games):
               * decodes route_tape.py and reports what game state the tape
                 prescribes (routes, shop-pair routing, per-day unit/market ops,
                 the common R42 opening);
               * extracts the ordered layer stack in main.py (layer_00..layer_44
                 + the promoted _ASTRA_I1 patch) and maps each layer boundary to
                 the natively-composed prefix global main.py exports.

  --iterative  Empirical loop (runs real games):
               * for a curated set of layer-prefix milestones, runs the SAME
                 opponents/seeds against each prefix (each in a fresh reload of
                 main, so the shared chassis/tape singleton is isolated);
               * reports per-game signal columns (idle, overflow, escapes, floor
                 sales, missed harvests, feed surplus, $, result) and a
                 same-seed consecutive-prefix diff, so every layer's effect is
                 isolated -- never averaged across games (see AGENTS.md).

Usage:
  python analyze_patches.py --survey
  python analyze_patches.py --iterative --pa 1,2,8 --seed 42 --batch 1
  python analyze_patches.py --survey --iterative --outdir diag-replays/iterative

Design note: main.py composes the 45 layers as `agent = layer_NN(prev)` and
EXPORTS each boundary's composed agent (e.g. _SHOP_PARENT, _V28_CORE, _I1_BASE,
_original_agent) which we replay directly as *trusted prefixes*. Each prefix runs
under a fresh `importlib.reload(main)` because the layers mutate a shared chassis
singleton and the in-memory route tape; running prefixes in one polluted module
would contaminate the results.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import diagnose as D  # noqa: E402

# --------------------------------------------------------------------------- #
# Curated prefix milestones: (global_name, short_label, "layer boundary" text)
# --------------------------------------------------------------------------- #
CURATED_PREFIXES = [
    ("_IMPL",             "BASE chassis",       "raw tape replay + reactive safety (no outer layers)"),
    ("_SHOP_PARENT",      "layer_00",           "layer_00_impl: error-safe tape passthrough"),
    ("_V28_CORE",         "layer_03",           "shop + pre-terminal + pre-room scaffolding"),
    ("_R36_SALE_PARENT",  "layer_09",           "r36 sale reorder + v231 livestock control"),
    ("_RELEASE_PARENT",   "layer_11",           "r37 market/quotes + release"),
    ("_R70_PARENT",       "layer_17",           "r53 labor + r70 fert/econ coordination"),
    ("_R97_PARENT",       "layer_20",           "r95 reserve + r97 (feed/market)"),
    ("_R127_PARENT",      "layer_40",           "the big r127 core layer"),
    ("_ALT_PARENT",       "layer_43",           "v13v entry (pre-HybridOpening)"),
    ("_I1_BASE",          "layer_44",           "HybridOpening alt tape (pre-I1, the new `old`)"),
    ("_original_agent",   "final (I1)",         "production = layer_44 + promoted _ASTRA_I1 patch"),
]

# Native-composed prefix globals, in main.py file order (from the composition).
PREFIX_ORDER = [
    "_IMPL", "_SHOP_PARENT", "_PRE_TERMINAL_AGENT", "_PRE_ROOM_AGENT", "_V28_CORE",
    "_EXPERIMENT_PARENT", "_ORDER_PARENT", "_V31_CORE", "_V231_PARENT", "_R36_SALE_PARENT",
    "_RELEASE_PARENT", "_V233_PARENT", "_R46_SHEEP_AGENT", "_R51_INPUT_PARENT",
    "_R51_WAREHOUSE_PARENT", "_R53_LABOR_PARENT", "_R70_PARENT", "_R97_PARENT",
    "_RACE_PARENT", "_R127_PARENT", "_ALT_PARENT", "_I1_BASE", "_original_agent",
]

LAYER_NAME_RE = re.compile(r"^def (layer_\d+_[\w\d]+)\(", re.M)


# --------------------------------------------------------------------------- #
# STATIC SURVEY
# --------------------------------------------------------------------------- #
def survey_tape() -> dict:
    """Decode route_tape.py / route_tape_v2.py and summarise what game state it gives."""
    tape_mod = D._tape_module()
    mod = __import__(tape_mod)
    routes = getattr(mod, "ROUTES")
    shop_routes = getattr(mod, "SHOP_ROUTES")

    # Per-route, per-day unit-command + market-order profile.
    prof = {}
    for rid in sorted(routes):
        tape = routes[rid]
        days = {}
        for t, a in enumerate(tape):
            day = t // 24
            d = days.setdefault(day, {"unit_ops": {}, "market": defaultdict(int), "n": 0})
            d["n"] += 1
            for u in [a.get("farmer") or ["PASS"]] + (a.get("hands") or []):
                op = u[0] if u else "PASS"
                d["unit_ops"][op] = d["unit_ops"].get(op, 0) + 1
            for o in a.get("market") or []:
                if len(o) >= 2:
                    d["market"][(o[0], o[1])] += max(0, o[2]) if len(o) >= 3 and isinstance(o[2], int) else 1
        prof[rid] = {
            "len": len(tape),
            "first_market": tape[0].get("market") if tape else None,
        }

    shop_map = {f"{k[0]},{k[1]}": v for k, v in sorted(shop_routes.items())}
    return {
        "module": tape_mod,
        "num_routes": len(routes),
        "route_ids": sorted(routes),
        "shop_routes_count": len(shop_routes),
        "shop_map": shop_map,
        "route_lengths": {rid: prof[rid]["len"] for rid in prof},
        "sample_first_market": {rid: prof[rid]["first_market"] for rid in list(prof)[:4]},
    }


def survey_layers() -> dict:
    """Extract the layer stack from main.py source: layer order + boundary prefixes."""
    src = (HERE / "main.py").read_text()
    layer_names = LAYER_NAME_RE.findall(src)
    # Snapshot boundaries (line-number indexed) for the native prefixes.
    boundary = {}  # prefix global -> layer-up-to
    lines = src.split("\n")
    current = None
    for i, l in enumerate(lines):
        m = re.match(r"^def (layer_\d+_[\w\d]+)\(", l)
        if m:
            current = m.group(1)
        m2 = re.match(r"^(_[A-Za-z0-9_]+)=agent\b", l)
        if m2:
            boundary[m2.group(1)] = current
    boundary["_original_agent"] = "production (layer_44 + I1)"
    boundary["_I1_BASE"] = "layer_44_alt"
    return {"num_layers": len(layer_names), "layer_names": layer_names, "boundaries": boundary}


def cmd_survey() -> None:
    tape = survey_tape()
    layers = survey_layers()
    print("=" * 72)
    print("ROUTE TAPE (what game state does the tape give?)")
    print("=" * 72)
    print(f"module={tape['module']}  routes={tape['num_routes']}  ids={tape['route_ids']}")
    print(f"length of every route: {set(tape['route_lengths'].values())}")
    print("example step-1 market (the R42 opening, identical for all routes):")
    for rid, m in list(tape["sample_first_market"].items())[:3]:
        print(f"   route {rid}: {m}")
    print(f"\nshop-pair -> route lookup: {tape['shop_routes_count']} entries")
    print(json.dumps({k: v for k, v in list(tape["shop_map"].items())[:16]}, indent=1))

    print("\n" + "=" * 72)
    print("LAYER STACK in main.py (the iterative patches others built)")
    print("=" * 72)
    print(f"total layers: {layers['num_layers']}")
    for i, n in enumerate(layers["layer_names"]):
        print(f"  {i:2d}  {n}")
    print("\nComposed-prefix globals main.py exports (trusted layer boundaries):")
    for g in PREFIX_ORDER:
        if g in layers["boundaries"]:
            print(f"   {g:<22} -> after {layers['boundaries'][g]}")


# --------------------------------------------------------------------------- #
# EMPIRICAL ITERATIVE LOOP
# --------------------------------------------------------------------------- #
def run_prefix(prefix_global: str, pa_indices, n_seeds, seed, run_dir: Path, tape_label="v1"):
    """Run the given native-composed prefix against opponents/seeds, fresh reload.

    Returns list of per-game (path, game_summary dict)."""
    import importlib

    D._TAPE_SELECTED = tape_label
    main = D._reload_main_if_needed(fresh=True)
    agent = getattr(main, prefix_global)
    if not callable(agent):
        raise RuntimeError(f"{prefix_global} not callable")

    run_dir = Path(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    seeds = D._make_seeds(n_seeds, seed)
    saved = []
    for pa in pa_indices:
        opp = D.load_public_agent(pa)
        opp_name = D.PUBLIC_AGENT_MAP[pa][0]
        for s in seeds:
            env = D.run_game(agent, opp, seed=s, seat=D.TEST_SEAT, audit=True)
            meta = {
                "agent": f"{prefix_global}@{tape_label}",
                "opponent": opp_name, "opponent_idx": pa, "seed": s,
                "seat": D.TEST_SEAT, "episode_steps": D.EPISODE_STEPS,
            }
            path = run_dir / f"{prefix_global}_{opp_name}_seed{s}.json"
            D.save_replay(env, path, meta)
            saved.append(path)
    # fresh reload cleanup (next prefix runs on its own chassis)
    importlib.invalidate_caches()
    return saved


def cmd_iterative(args) -> None:
    pa_indices = D._parse_pa_arg(args.pa)
    run_dir = Path(args.outdir)
    # choose prefixes: default curated, or override with --prefixes (comma list)
    if args.prefixes:
        chosen = [p.strip() for p in args.prefixes.split(",") if p.strip()]
        labels = {g: g for g in chosen}
    else:
        chosen, labels = [], {}
        for g, label, _txt in CURATED_PREFIXES:
            chosen.append(g)
            labels[g] = label

    rows = []
    for g in chosen:
        print(f"\n--- running prefix {g} ({labels.get(g, g)}) ...")
        saved = run_prefix(g, pa_indices, args.batch, args.seed, run_dir, tape_label=args.tape)
        for p in saved:
            row = D.game_summary(p)
            row["prefix"] = g
            row["label"] = labels.get(g, g)
            row["replay"] = str(p)
            rows.append(row)
            print(f"   {p.name}  ${row['final_money']:>7.0f}  {row['result']}  "
                  f"idle%={row['idle_share_pct']} floor=${row['floor_sales']} "
                  f"esc={row['animal_escapes']} died={row['plants_died']}")

    # Write combined JSON
    out_json = run_dir / "iteration_rows.json"
    out_json.write_text(json.dumps(rows, indent=2, default=str))
    print(f"\nwrote {out_json}")

    # Emit a markdown table grouped by (opponent, seed) across prefixes, plus
    # a consecutive prefix same-seed diff.
    md = build_iterative_md(rows, tape_label=args.tape)
    out_md = run_dir / "iteration_report.md"
    out_md.write_text(md)
    print(f"wrote {out_md}")


def build_iterative_md(rows, tape_label="v1") -> str:
    from collections import defaultdict

    lines = []
    lines.append(f"# Iterative patch analysis ({tape_label} tape)")
    lines.append("")
    lines.append("Same opponents/seeds across every prefix; each row is ONE game "
                 "(never averaged). Consecutive-prefix diff isolates one layer.")
    lines.append("")

    # Trusted build order of run prefixes (the *iterative* sequence).
    order = {g: idx for idx, (g, _l, _t) in enumerate(CURATED_PREFIXES)}
    for r in rows:
        r.setdefault("_order", order.get(r["prefix"], 999))

    groups = defaultdict(list)
    for r in rows:
        groups[(r["opponent"], r["seed"])].append(r)

    cols = ["step", "label", "final_money", "opponent_final", "result", "idle_share_pct",
            "shed_overflow_days", "discarded_units_total", "floor_sales",
            "premium_below_base_frac", "animal_escapes", "plants_died",
            "missed_harvest_eod", "feed_surplus", "sell_revenue_total"]
    for (opp, seed) in sorted(groups):
        grp = sorted(groups[(opp, seed)], key=lambda r: r["_order"])
        lines.append(f"## vs {opp} seed {seed}  (build order)")
        lines.append("")
        lines.append("| " + " | ".join(cols) + " |")
        lines.append("|" + "|".join(["---"] * len(cols)) + "|")
        prev = None
        base = grp[0]
        for r in grp:
            r["step"] = r["_order"] + 1
            lines.append("| " + " | ".join(str(r.get(c, "")) for c in cols) + " |")
            delta_base = []
            for c in ["final_money", "floor_sales", "animal_escapes", "plants_died",
                      "missed_harvest_eod", "shed_overflow_days", "discarded_units_total",
                      "feed_surplus"]:
                d = (r.get(c) or 0) - (base.get(c) or 0)
                if d:
                    delta_base.append(f"{c}{d:+}")
            if prev is not None:
                diffs = []
                for c in ["final_money", "floor_sales", "animal_escapes", "plants_died",
                          "missed_harvest_eod", "shed_overflow_days", "discarded_units_total",
                          "feed_surplus"]:
                    d = (r.get(c) or 0) - (prev.get(c) or 0)
                    if d:
                        diffs.append(f"{c}{d:+}")
            lines.append(f"  → *{r['label']}* vs-prev: " +
                         (", ".join(diffs) if prev is not None else "— (BASE)")
                         + "   | vs-BASE: " + ", ".join(delta_base))
            prev = r
        lines.append("")

    lines.append("## Signals legend")
    lines.append("- `premium_below_base_frac`: share of premium-good (strawberry/melon/milk/wool) units sold below base")
    lines.append("- `floor_sales`, `shed_overflow_days`, `discarded_units_total`: glut / shed-capacity waste")
    lines.append("- `animal_escapes`, `plants_died`, `missed_harvest_eod`: lifecycle defects")
    lines.append("- `feed_surplus`: wheat produced* minus fed (*net of audit flows; see AGENTS.md)")
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--survey", action="store_true", help="static tape + layer survey")
    ap.add_argument("--iterative", action="store_true", help="empirical per-prefix loop")
    ap.add_argument("--pa", default="1", help="public agent indices, e.g. 1,2,8 or 1-3")
    ap.add_argument("--batch", type=int, default=1, help="seeds per opponent")
    ap.add_argument("--seed", type=int, default=None, help="fixed seed")
    ap.add_argument("--prefixes", default=None, help="override prefix globals, comma list")
    ap.add_argument("--tape", choices=["v1", "v2"], default="v1")
    ap.add_argument("--outdir", default="diag-replays/iterative")
    ap.add_argument("--report", action="store_true",
                    help="regenerate iteration_report.md from saved iteration_rows.json "
                         "(no games run)")
    args = ap.parse_args()

    if args.report:
        run_dir = Path(args.outdir)
        rows = json.loads((run_dir / "iteration_rows.json").read_text())
        (run_dir / "iteration_report.md").write_text(build_iterative_md(rows))
        print("regenerated", run_dir / "iteration_report.md")
        return

    if not (args.survey or args.iterative):
        args.survey = args.iterative = True
    if args.survey:
        cmd_survey()
    if args.iterative:
        cmd_iterative(args)


if __name__ == "__main__":
    from collections import defaultdict  # noqa: E402
    main()
