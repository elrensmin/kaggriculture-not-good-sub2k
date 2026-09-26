#!/usr/bin/env python
"""Build (and optionally submit) a single-file Kaggle Kaggriculture agent.

The agent is the ``src`` package: a stack of small modules that import each other
with relative imports (``from . import params``, ``from .job import Job``). Kaggle
wants ONE file exposing ``agent(observation, configuration)``.

The build therefore embeds every ``src/*.py`` source, base64-encoded, and installs
them at import time as submodules of a synthetic package, so their relative imports
resolve exactly as they do in the repo:

    _kagg_agent            <- src/__init__.py, exposes ``agent``
    _kagg_agent.params     <- src/params.py
    _kagg_agent.scheduler  <- src/scheduler.py
    ...

Module order is derived by a topological sort of the relative imports (Kahn), so
adding a module to ``src/`` needs no edit here. The bundle imports nothing from the
repo at runtime; it only needs ``kaggle_environments``.

Usage:
  python package.py                        # -> dist/submission.py
  python package.py --check                # + play one seeded game vs a public agent
                                           #   and assert bundle == local src.agent
  python package.py --push                 # HUMAN ONLY: submit via the kaggle CLI

The agent has NO permission to push: ``--push`` is the operator's call and is never
run automatically. ``--check`` is opt-in too; a plain build stops after writing.
"""
from __future__ import annotations

import argparse
import ast
import base64
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent
SRC = ROOT / "src"
DEFAULT_OUT = ROOT / "dist" / "submission.py"
PKG = "_kagg_agent"


# ---------------------------------------------------------------------------
# source discovery + ordering
# ---------------------------------------------------------------------------
def _local_deps(tree: ast.AST) -> set:
    """Names this module imports relatively: `from . import a, b` / `from .x import y`."""
    deps = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.level == 1:
            if node.module:
                deps.add(node.module.split(".")[0])
            for alias in node.names:
                deps.add(alias.name.split(".")[0])
    return deps


def collect_sources(src_dir: pathlib.Path):
    """Return (order, sources) with `order` a topological sort of the local imports."""
    sources, deps = {}, {}
    for path in sorted(src_dir.glob("*.py")):
        name = path.stem if path.stem != "__init__" else "__init__"
        sources[name] = path.read_text(encoding="utf-8")
        tree = ast.parse(sources[name])
        deps[name] = {d for d in _local_deps(tree)
                      if d in {p.stem for p in src_dir.glob("*.py")} or d == "__init__"}
    deps = {k: {d for d in v if d != k} for k, v in deps.items()}

    # Kahn: emit a module only once every module it imports has been emitted.
    remaining = {k: set(v) for k, v in deps.items() if k != "__init__"}
    order = []
    while remaining:
        ready = sorted(k for k, v in remaining.items() if not (v - set(order)))
        if not ready:                                   # cycle: fall back to lexical
            ready = sorted(remaining)
        for k in ready:
            order.append(k)
            remaining.pop(k, None)
    return order, sources


# ---------------------------------------------------------------------------
# the bundle
# ---------------------------------------------------------------------------
_BOOTSTRAP = '''"""Single-file Kaggle Kaggriculture agent (auto-generated).

Do not edit: rebuild with `python package.py`. The real source is the `src/`
package in the project repo; this file embeds it and installs each module under a
synthetic package so the relative imports resolve unchanged.
"""
import base64 as _b64
import sys as _sys
import types as _types

_PKG = {pkg!r}
_SOURCES = {{
{sources}
}}
_ORDER = {order!r}

_pkg = _types.ModuleType(_PKG)
_pkg.__path__ = []
_sys.modules[_PKG] = _pkg

for _name in _ORDER:
    _m = _types.ModuleType(_PKG + "." + _name)
    _m.__package__ = _PKG
    _m.__file__ = "<" + _PKG + "/" + _name + ".py>"
    _sys.modules[_PKG + "." + _name] = _m
    setattr(_pkg, _name, _m)

for _name in _ORDER:
    exec(compile(_SOURCES[_name], "<" + _PKG + "/" + _name + ".py>", "exec"),
         _sys.modules[_PKG + "." + _name].__dict__)

_pkg.__package__ = _PKG
exec(compile(_SOURCES["__init__"], "<" + _PKG + "/__init__.py>", "exec"), _pkg.__dict__)

agent = _pkg.agent
'''


def build(out: pathlib.Path) -> pathlib.Path:
    order, sources = collect_sources(SRC)
    if "__init__" not in sources or "params" not in sources:
        raise SystemExit("src/ looks wrong (need at least __init__.py and params.py)")
    lines = []
    for name in list(order) + ["__init__"]:
        blob = base64.b64encode(sources[name].encode("utf-8")).decode("ascii")
        lines.append(f'    {name!r}: _b64.b64decode({blob!r}).decode("utf-8"),')
    body = _BOOTSTRAP.format(pkg=PKG, sources="\n".join(lines), order=list(order))
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(body, encoding="utf-8")
    compile(body, str(out), "exec")          # syntax check; real check is --check
    print(f"[package] wrote {out} ({out.stat().st_size:,} bytes, "
          f"{len(order)} modules: {' -> '.join(order)})")
    return out


# ---------------------------------------------------------------------------
# --check: bundle vs the local src.agent, same seed, fresh process
# ---------------------------------------------------------------------------
def _run_bundle(bundle: pathlib.Path, opp: int, seed: int):
    script = f"""
import sys
sys.path.insert(0, {str(ROOT)!r})
import importlib.util
spec = importlib.util.spec_from_file_location("bundle", {str(bundle)!r})
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

from tools import diagnose
import src
opponent = diagnose.load_public_agent({opp!r})
from kaggle_environments import make
conf = {{"episodeSteps": diagnose.EPISODE_STEPS, "seed": {seed!r}}}

env_a = make("kaggriculture", debug=False, configuration=dict(conf))
env_a.run([mod.agent, opponent])
env_b = make("kaggriculture", debug=False, configuration=dict(conf))
env_b.run([src.agent, opponent])

def money(e):
    for info in reversed(e.steps):
        row = info[0]
        ob = row.get("observation") if isinstance(row, dict) else None
        if ob is None:
            continue
        try:
            return ob["farms"][0]["money"]
        except Exception:
            continue
    return None

print("RESULT %r %r" % (money(env_a), money(env_b)))
"""
    run = subprocess.run([sys.executable, "-c", script], cwd=str(ROOT),
                         capture_output=True, text=True, timeout=1800)
    for line in run.stdout.splitlines():
        print("   [bundle] " + line)
    if run.returncode != 0:
        raise RuntimeError("bundle run failed:\n" + run.stderr[-4000:])
    last = [ln for ln in run.stdout.splitlines() if ln.startswith("RESULT ")]
    if not last:
        raise RuntimeError("no RESULT line emitted")
    a, b = (float(x) for x in last[-1].split()[1:])
    return a, b


def check(bundle: pathlib.Path, opp: int, seed: int) -> bool:
    print(f"[check] bundle vs local src.agent, public-agent#{opp}, seed {seed}, fresh process...")
    am, bm = _run_bundle(bundle, opp, seed)
    same = (am is not None and bm is not None and abs(am - bm) < 1e-6)
    print(f"[check] bundle={am} local={bm} -> {'IDENTICAL' if same else 'MISMATCH'}")
    return same


# ---------------------------------------------------------------------------
# --push (human only)
# ---------------------------------------------------------------------------
def _find_kaggle() -> str:
    import shutil
    exe = shutil.which("kaggle")
    if exe:
        return exe
    venv = ROOT / ".venv" / "bin" / "kaggle"
    if venv.exists():
        return str(venv)
    raise SystemExit("[push] 'kaggle' CLI not found. Install it (e.g. `uv pip install kaggle`).")


def push(bundle: pathlib.Path, competition: str, message: str) -> None:
    kaggle_exe = _find_kaggle()
    home_kg = pathlib.Path.home() / ".kaggle"
    have_env = bool(__import__("os").environ.get("KAGGLE_USERNAME")
                    and __import__("os").environ.get("KAGGLE_KEY"))
    if not (have_env or (home_kg / "kaggle.json").exists() or (home_kg / "access_token").exists()):
        raise SystemExit("[push] Kaggle credentials not found; refusing to submit.")
    cmd = [kaggle_exe, "competitions", "submit", "-c", competition, "-f", str(bundle)]
    if message:
        cmd += ["-m", message]
    print(f"[push] running: {' '.join(cmd)}")
    run = subprocess.run(cmd, capture_output=True, text=True)
    print(run.stdout)
    if run.returncode != 0:
        raise SystemExit("[push] kaggle submit failed:\n" + run.stderr)
    print("[push] submitted.")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    ap.add_argument("--check", action="store_true",
                    help="play one seeded game and assert bundle == local src.agent")
    ap.add_argument("--opp", type=int, default=4, help="public agent index for --check")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--push", action="store_true", help="HUMAN ONLY: submit via the kaggle CLI")
    ap.add_argument("--competition", default="kaggriculture")
    ap.add_argument("-m", "--message", default="")
    ns = ap.parse_args(argv)

    out = build(pathlib.Path(ns.out))
    if ns.check and not check(out, ns.opp, ns.seed):
        raise SystemExit("[package] --check reported a bundle/local mismatch")
    if ns.push:
        push(out, ns.competition, ns.message or "auto-built src agent")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
