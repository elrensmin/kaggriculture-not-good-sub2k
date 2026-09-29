"""tools/audit/duplicate_owners.py -- find DUPLICATE OWNERS and dead code in `src/`.

WHY THIS EXISTS
---------------
This codebase's recurring failure is not a wrong constant, it is TWO owners of one decision.
Measured examples, all found by hand and all expensive:

  * `opening.crop_target` (a table clamped at d5, authored for a 25-tile farm) and
    `crop_plan.plant_queue` both decided the standing-crop target. The first was dead, so
    changing it produced a BYTE-IDENTICAL game and cost a whole experiment.
  * `P_FEED = 100` is the highest priority in the game and reproduces the policy gap almost
    exactly -- and changing it 100/88/78 is BYTE-IDENTICAL. The knob looks live (`job.py`
    captures it, `phase_band` routes through `params.at`) but FEED's effective ordering comes
    from somewhere else. Tuning it is wasted effort until the real owner is found.
  * `revenue_per_day` and `labour` were nodes with no live reader -- dead, so they emitted no
    pressure and silently removed SELL/HARVEST/HIRE from the graph.

A duplicate owner is worse than dead code: dead code is inert, but a duplicate owner makes the
LIVE one untunable while looking tunable. So this tool reports, in order of what wastes the most
time: duplicate owners first, then dead knobs, then unreachable code.

WHAT IT REPORTS
  1. DUP OWNERS (ops)      which functions construct a job/order for each op class -- >1 = flag
  2. DUP OWNERS (names)    the same function name defined in 2+ modules
  3. DEAD KNOBS            params defined but never read anywhere in the repo
  4. UNREACHABLE           functions not reachable from `scheduler.plan` by the call graph
  5. ORPHAN MODULES        src modules no other module imports

USAGE
    PYTHONPATH=. python -m tools.audit.duplicate_owners
    PYTHONPATH=. python -m tools.audit.duplicate_owners --section ops
    PYTHONPATH=. python -m tools.audit.duplicate_owners --section knobs --limit 60
    PYTHONPATH=. python -m tools.audit.duplicate_owners --reach-from scheduler.plan
"""
from __future__ import annotations

import argparse
import ast
import re
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"

# op classes we care about -- the decision surface. Derived from the Job()/order strings found
# in the source, so a new op appears automatically.
OP_HINT = re.compile(r"^[A-Z][A-Z_]{2,}$")


def parse(path):
    try:
        return ast.parse(path.read_text())
    except Exception as exc:                                       # noqa: BLE001
        print(f"  !! could not parse {path}: {exc}", file=sys.stderr)
        return None


def module_functions(tree):
    """{func_name: node} for module-level defs, including async."""
    out = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            out[node.name] = node
    return out


def calls_in(node):
    """Every plain name called anywhere inside `node` (shallow call graph)."""
    out = set()
    for n in ast.walk(node):
        if isinstance(n, ast.Call):
            f = n.func
            if isinstance(f, ast.Name):
                out.add(f.id)
            elif isinstance(f, ast.Attribute):
                out.add(f.attr)
    return out


def string_literals(node):
    return {n.value for n in ast.walk(node)
            if isinstance(n, ast.Constant) and isinstance(n.value, str)}


# --------------------------------------------------------------------------- 1. op owners
ACTS = ("WATER", "HARVEST", "PLANT", "FERTILIZE", "FEED", "CARE", "COLLECT_FERTILIZER",
        "DIG", "PLACE", "PICKUP", "DROP", "BUILD_PASTURE", "BUILD_COOP")
MARKET = ("SELL", "BUY_SEED", "BUY_LAND", "BUY_ANIMAL", "BUY_PRODUCT", "HIRE")
OPS = set(ACTS) | set(MARKET)


def emits_ops(node):
    """The op classes this function can actually EMIT.

    Precise by construction, not by string matching: an op is emitted either as the op argument
    of a `Job(prio, pos, OP, ...)` construction, or as the first element of a market order list
    like `["BUY_SEED", crop, n]`. Matching any uppercase literal instead picks up ITEM names
    (WHEAT, COW, FERTILIZER) and reports nonsense.
    """
    # A MARKET ORDER IS A LIST. Value claims and schedules are TUPLES:
    #   emitting an order  -> out.append(["BUY_SEED", crop, n])          <- counts
    #   a value claim      -> out.append(("BUY_SEED", crop, npv, cost))   <- does NOT count
    #   a schedule         -> out.append(("BUY_LAND", off, q))            <- does NOT count
    # Matching tuples too reported `plan.capex` and `state_graph.schedule` as LAND/SEED buyers
    # when neither places an order -- two false positives that would have sent us editing code
    # that was already correct.
    out = set()
    for n in ast.walk(node):
        if isinstance(n, ast.Call):
            fname = n.func.id if isinstance(n.func, ast.Name) else (
                n.func.attr if isinstance(n.func, ast.Attribute) else None)
            if fname == "Job":
                args = n.args
                if len(args) >= 3 and isinstance(args[2], ast.Constant) \
                        and isinstance(args[2].value, str):
                    out.add(args[2].value)
        if isinstance(n, ast.List) and n.elts:
            first = n.elts[0]
            if isinstance(first, ast.Constant) and isinstance(first.value, str) \
                    and first.value in MARKET:
                out.add(first.value)
    return out & OPS


def section_ops(mods):
    print("=" * 100)
    print("1. DUPLICATE OWNERS -- which functions can EMIT each op class")
    print("=" * 100)
    owners = defaultdict(set)
    for mod, _tree, funcs in mods:
        for fname, fnode in funcs.items():
            for op in emits_ops(fnode):
                owners[op].add(f"{mod}.{fname}")
    # DELIBERATE FALLBACKS. An emitter that fires ONLY when no other layer supplied the op is
    # structurally correct -- it is a floor, not a second owner. Declared here so the audit's
    # target ("every op at exactly 1") stays meaningful instead of being fudged.
    FALLBACK = {
        "DIG": "state_graph.deficit_jobs",   # returns [] whenever a layer already emitted DIG
    }
    for op, fb in FALLBACK.items():
        if op in owners and fb in owners[op] and len(owners[op]) > 1:
            owners[op] = {f"{fb} [FALLBACK]"} if len(owners[op]) == 2 else owners[op]
    dup = {op: sorted(set(o)) for op, o in owners.items() if len(set(o)) > 1}
    print(f"  op classes emitted anywhere : {len(owners)}")
    print(f"  with MORE THAN ONE emitter   : {len(dup)}")
    print()
    print(f"  {'op':<20} {'emitters':>8}  functions")
    for op in sorted(dup, key=lambda o: -len(dup[o])):
        names = dup[op]
        print(f"  {op:<20} {len(names):>8}  {', '.join(names)[:90]}")
    print()
    single = sorted(set(owners) - set(dup))
    print(f"  SINGLE OWNER (safe to tune): {', '.join(single) or 'none'}")
    print()
    print("  READ: >1 emitter means a change to one may be inert because the other supplies the")
    print("  jobs. This is exactly how `P_FEED=100/88/78` came back BYTE-IDENTICAL. Before tuning")
    print("  any constant for an op, prove which emitter reaches `scheduler.plan` (section 4).")


# --------------------------------------------------------------------------- 2. dup names
def section_names(mods):
    print()
    print("=" * 100)
    print("2. DUPLICATE OWNERS -- the same function name defined in 2+ modules")
    print("=" * 100)
    byname = defaultdict(list)
    for mod, _tree, funcs in mods:
        for fname in funcs:
            byname[fname].append(mod)
    dups = {k: v for k, v in byname.items() if len(v) > 1}
    if not dups:
        print("  none")
        return
    print(f"  {'function':<28} modules")
    for k in sorted(dups):
        print(f"  {k:<28} {', '.join(dups[k])}")
    print()
    print("  Not always wrong (a per-layer `jobs()` is intentional), but the same name doing the")
    print("  same job in two layers is the classic split owner. Check each pair by hand.")


# --------------------------------------------------------------------------- 3. dead knobs
def section_knobs(limit):
    print()
    print("=" * 100)
    print("3. DEAD KNOBS -- `params` names never referenced outside their own definition")
    print("=" * 100)
    p = SRC / "params.py"
    tree = parse(p)
    if tree is None:
        return
    names = []
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name) and t.id.isupper():
                    names.append(t.id)
    # every other file in the repo (any text) is a candidate reader
    files = [f for f in ROOT.rglob("*.py")
             if f != p and ".git" not in f.parts and "__pycache__" not in f.parts]
    md = [f for f in ROOT.rglob("*.md") if ".git" not in f.parts]
    texts = {f: f.read_text(errors="ignore") for f in files}
    mdtext = "\n".join(f.read_text(errors="ignore") for f in md)
    dead, docsonly, live = [], [], 0
    for n in names:
        pat = re.compile(rf"\b{re.escape(n)}\b")
        hits = [f for f, t in texts.items() if pat.search(t)]
        # a knob read through `at("NAME", day)` is live even though it is a string literal
        if f'"{n}"' in mdtext and not hits:
            docsonly.append(n)
        elif not hits:
            dead.append(n)
        else:
            live += 1
    print(f"  total UPPER names in params.py : {len(names)}")
    print(f"  referenced somewhere in code   : {live}")
    print(f"  DEAD (no code reference)       : {len(dead)}")
    print(f"  doc-only reference             : {len(docsonly)}")
    print()
    if dead:
        print(f"  DEAD -- safe to delete (showing {min(limit, len(dead))} of {len(dead)}):")
        for n in dead[:limit]:
            print(f"    {n}")
        if len(dead) > limit:
            print(f"    ... and {len(dead) - limit} more (raise --limit)")
    if docsonly:
        print()
        print(f"  DOC-ONLY -- referenced in a .md but no code reads it (a knob the docs promise "
              f"and the code ignores, or a stale doc):")
        for n in docsonly[:limit]:
            print(f"    {n}")
    print()
    print("  CAVEAT: `NAME` is live if it is read via `params.at(\"NAME\", day)` with the name as a")
    print("  STRING. This scan looks for the bare identifier, so a phase-scoped knob whose only")
    print("  reader is `at(...)` can appear dead. Confirm with a string-literal grep before deleting.")


# --------------------------------------------------------------------------- 4. reachability
def section_reach(mods, reach_from):
    print()
    print("=" * 100)
    print(f"4. UNREACHABLE -- not reachable from `{reach_from}` by the call graph")
    print("=" * 100)
    edges = {}
    for mod, _tree, funcs in mods:
        for fname, fnode in funcs.items():
            edges[f"{mod}.{fname}"] = {c for c in calls_in(fnode)}
    # also allow entry via a short (unqualified) name
    byshort = defaultdict(set)
    for key in edges:
        byshort[key.split(".")[-1]].add(key)
    target = None
    for key in edges:
        if key.endswith(reach_from):
            target = key
    if target is None:
        print(f"  entry `{reach_from}` not found among module-level defs")
        return
    seen, stack = {target}, [target]
    while stack:
        cur = stack.pop()
        for callee in edges.get(cur, ()):
            for cand in byshort.get(callee, ()):
                if cand not in seen:
                    seen.add(cand)
                    stack.append(cand)
    unreach = sorted(k for k in edges if k not in seen)
    print(f"  module-level functions : {len(edges)}")
    print(f"  reachable from entry   : {len(seen)}")
    print(f"  UNREACHABLE            : {len(unreach)}")
    print()
    print("  CAVEAT: this is a NAME-based call graph, so dynamic dispatch (`getattr`, dicts of")
    print("  callables, `fn(state)` behind a variable) makes a LIVE function look unreachable.")
    print("  Treat the list as candidates to inspect, never as a delete list.")
    print()
    bymod = defaultdict(list)
    for k in unreach:
        m, f = k.split(".", 1)
        bymod[m].append(f)
    for m in sorted(bymod):
        print(f"    {m:<20} {', '.join(sorted(bymod[m]))[:110]}")


# --------------------------------------------------------------------------- 5. orphans
def section_orphans(mods):
    print()
    print("=" * 100)
    print("5. ORPHAN MODULES -- no other `src/` module imports it")
    print("=" * 100)
    imported = set()
    for _mod, tree, _f in mods:
        for n in ast.walk(tree):
            if isinstance(n, ast.ImportFrom):
                if n.module:
                    imported.add(n.module.split(".")[-1])
                for al in n.names:
                    imported.add(al.name)
            elif isinstance(n, ast.Import):
                for al in n.names:
                    imported.add(al.name.split(".")[-1])
    names = sorted({m[:-3] for m, _t, _f in mods})
    orph = [n for n in names if n not in imported and n != "__init__"]
    print(f"  src modules: {len(names)}   never imported by another src module: {len(orph)}")
    for n in orph:
        # is it referenced anywhere else in the repo?
        hits = subprocess.run(
            ["grep", "-rl", f"import {n}\\|from . import.*\\b{n}\\b", str(ROOT)],
            capture_output=True, text=True).stdout.strip().splitlines()
        where = [Path(h).name for h in hits if "src/" in h and Path(h).name != f"{n}.py"]
        print(f"    {n:<20} also referenced from: {', '.join(where[:4]) or 'NOWHERE'}")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--section", default="all",
                    choices=["all", "ops", "names", "knobs", "reach", "orphans"])
    ap.add_argument("--limit", type=int, default=40)
    ap.add_argument("--reach-from", default="scheduler.plan")
    a = ap.parse_args(argv)

    mods = []
    for f in sorted(SRC.glob("*.py")):
        t = parse(f)
        if t is not None:
            mods.append((f.stem, t, module_functions(t)))
    print(f"scanned {len(mods)} modules in src/\n")

    if a.section in ("all", "ops"):
        section_ops(mods)
    if a.section in ("all", "names"):
        section_names(mods)
    if a.section in ("all", "knobs"):
        section_knobs(a.limit)
    if a.section in ("all", "reach"):
        section_reach(mods, a.reach_from)
    if a.section in ("all", "orphans"):
        section_orphans(mods)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
