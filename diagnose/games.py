"""diagnose.games — episode runner, market audit and replay persistence.

Splits game execution / replay IO out of the original monolith diagnose.py.
"""
from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from kaggle_environments import make
from kaggle_environments.envs.kaggriculture.kaggriculture import (
    ANIMALS,
    MARKET_PARAMS,
    PRICE_FLOOR,
    PRODUCTS,
)
import kaggle_environments.envs.kaggriculture.kaggriculture as _ENV

from diagnose.config import EPISODE_STEPS

def run_game(
    agent: Callable,
    opponent: Callable,
    seed: Optional[int] = None,
    episode_steps: int = EPISODE_STEPS,
    seat: int = 0,
    audit: bool = False,
):
    """Run a seeded game and return the Kaggle env object.

    If ``audit`` is True, wrap the env to record committed market sells and
    shed overflow discards.  The audit is attached to ``env._diagnose_audit``
    and merged into replay metadata by ``save_replay``."""
    conf = {"episodeSteps": episode_steps, "seed": seed}
    env = make("kaggriculture", configuration=conf)
    ctx = _MarketAudit() if audit else None
    if ctx is not None:
        ctx.wrap_env(env)
    with ctx or _NoOpContext():
        if seat == 0:
            env.run([agent, opponent])
        else:
            env.run([opponent, agent])
    if audit and ctx is not None:
        env._diagnose_audit = dict(ctx.events)
    return env



class _NoOpContext:
    def __enter__(self): return self
    def __exit__(self, *exc): return False


def save_replay(env, path: Path, metadata: Optional[Dict[str, Any]] = None):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    replay = env.toJSON()
    if metadata:
        replay["_diagnose_meta"] = dict(metadata)
    audit = getattr(env, "_diagnose_audit", None)
    if audit:
        replay["_diagnose_meta"]["audit"] = audit
    with open(path, "w") as f:
        json.dump(replay, f, indent=2)
    return path



class _MarketAudit:
    """Record *committed* market sells and inventory discards during a game.

    The env's tape uses sentinel quantities (e.g. SELL WHEAT 1000) meaning
    "dump everything".  This audit patches the env's interpreter so every
    step is annotated with the current step/player state, then wraps
    _commit_unit and the inventory drop paths to count the units that
    actually left the shed and what overflowed."""

    def __init__(self):
        self.events: Dict[int, Dict[int, Dict[str, Any]]] = defaultdict(
            lambda: defaultdict(
                lambda: {
                    "sells": defaultdict(lambda: {"qty": 0, "revenue": 0.0, "floor": 0, "below": 0, "above": 0}),
                    "discards": 0,
                    "discard_items": defaultdict(int),
                }
            )
        )
        self._ctx: Dict[str, Any] = {}
        self._orig_commit: Optional[Callable] = None
        self._orig_drop: Optional[Callable] = None
        self._orig_ua: Optional[Callable] = None
        self._wrapped_interpreter: Optional[Callable] = None

    def __enter__(self):
        self._orig_commit = _ENV._commit_unit
        self._orig_drop = _ENV._drop_inventories_to_shed
        self._orig_ua = _ENV._apply_unit_action
        _ENV._commit_unit = self._commit_unit
        _ENV._drop_inventories_to_shed = self._drop_inventories_to_shed
        _ENV._apply_unit_action = self._apply_unit_action
        return self

    def __exit__(self, *exc):
        _ENV._commit_unit = self._orig_commit
        _ENV._drop_inventories_to_shed = self._orig_drop
        _ENV._apply_unit_action = self._orig_ua

    def wrap_env(self, env):
        """Wrap the env instance's interpreter to record step/player context."""
        orig = env.interpreter

        def wrapped(state, env_):
            try:
                self._ctx["step"] = int(state[0].observation.get("step", 0))
                self._ctx["farms"] = [s.observation.farms[i] for i, s in enumerate(state)]
                self._ctx["privates"] = [s.observation.private for s in state]
            except Exception:
                self._ctx.clear()
            return orig(state, env_)

        self._wrapped_interpreter = wrapped
        env.interpreter = wrapped

    def _seat(self, farm=None, private=None) -> Optional[int]:
        if farm is not None:
            for i, f in enumerate(self._ctx.get("farms", ())):
                if f is farm:
                    return i
        if private is not None:
            for i, p in enumerate(self._ctx.get("privates", ())):
                if p is private:
                    return i
        return None

    def _commit_unit(self, op, item, price, farm, private, market, shed_capacity=100):
        ok = self._orig_commit(op, item, price, farm, private, market, shed_capacity)
        step = self._ctx.get("step")
        if step is None:
            return ok
        seat = self._seat(farm=farm, private=private)
        if seat is None:
            return ok
        if ok and op == "SELL" and item in PRODUCTS:
            rec = self.events[step][seat]["sells"][item]
            rec["qty"] += 1
            rec["revenue"] += price
            if price <= PRICE_FLOOR:
                rec["floor"] += 1
            if price < MARKET_PARAMS[item]["base"]:
                rec["below"] += 1
            else:
                rec["above"] += 1
        return ok

    @staticmethod
    def _inv_totals(private):
        tot = {}
        for inv in (private["inventories"] or []):
            for item, n in (inv or {}).items():
                tot[item] = tot.get(item, 0) + n
        return tot

    @staticmethod
    def _discard_items(private, before_inv, before_shed):
        """Per-item units that left inventory but were not deposited into the shed.

        The env's DROP / deposit paths discard anything that does not fit in the
        shed; this isolates WHICH item overflowed (e.g. all-fertilizer gluts),
        not just a scalar count.
        """
        after_inv = _MarketAudit._inv_totals(private)
        after_shed = dict(private["shed"])
        items = set(before_inv) | set(before_shed) | set(after_inv) | set(after_shed)
        out = {}
        for it in items:
            inv_dec = before_inv.get(it, 0) - after_inv.get(it, 0)
            shed_inc = after_shed.get(it, 0) - before_shed.get(it, 0)
            d = max(0, inv_dec - shed_inc)
            if d:
                out[it] = d
        return out

    def _apply_unit_action(self, farm, private, idx, action, board_size, day, turns_per_day, shed_capacity=100):
        op = action[0] if isinstance(action, list) and action else None
        # Only deposit paths can overflow: DROP, and PLACE of a non-animal via
        # the shed-adjacent branch.  FEED/FERTILIZE/PLACE-animal also consume
        # inventory but are legitimate uses, not discards.
        deposit = op == "DROP" or (
            op == "PLACE" and len(action) > 1 and action[1] not in ANIMALS
        )
        before_inv = self._inv_totals(private)
        before_shed = dict(private["shed"])
        self._orig_ua(farm, private, idx, action, board_size, day, turns_per_day, shed_capacity)
        if not deposit:
            return
        discarded = self._discard_items(private, before_inv, before_shed)
        if discarded:
            step = self._ctx.get("step")
            seat = self._seat(private=private)
            if step is not None and seat is not None:
                self.events[step][seat]["discards"] += sum(discarded.values())
                for it, n in discarded.items():
                    self.events[step][seat]["discard_items"][it] += n

    def _drop_inventories_to_shed(self, private, capacity):
        before_inv = self._inv_totals(private)
        before_shed = dict(private["shed"])
        self._orig_drop(private, capacity)
        discarded = self._discard_items(private, before_inv, before_shed)
        if discarded:
            step = self._ctx.get("step")
            seat = self._seat(private=private)
            if step is not None and seat is not None:
                self.events[step][seat]["discards"] += sum(discarded.values())
                for it, n in discarded.items():
                    self.events[step][seat]["discard_items"][it] += n



def load_replay(path: Path) -> Dict[str, Any]:
    with open(path) as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Frame builder: per-step state + transitions
# ---------------------------------------------------------------------------
