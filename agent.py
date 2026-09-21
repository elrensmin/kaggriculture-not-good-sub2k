"""Patch layer for the new agent candidate.

The new agent is NOT a standalone replay of main.py. It is the full production
agent from main.py with this patch layered *on top*: diagnose.py runs main's
agent (``main._original_agent``) and then hands the produced action to
``patch()``, which may alter it.

So `python diagnose.py --new` runs **everything in main.py + this patch**, and
the ``--new`` side of ``python diagnose.py --compare`` does the same, so every
improvement/regression is measured relative to the exact production behavior.

Edit ``patch()`` for your experiment. Returning ``action`` unchanged is a no-op.

-------------------------------------------------------------------------------
NEVER TRUST AVERAGES ACROSS GAMES.
This environment is dynamic: random-seeded games across the whole public
leaderboard, with live, moving prices. Averaging a score is NOT signal — it
regresses our score. The matchup (which public agent) and any single seed's
price action can inflate or crush any run, so optimizing for any mean just
chases noise and misdirection.

Always look for what actually costs money in EVERY game:
  * system-level / structural defects — scheduling, routing, stock/inventory,
    market entry-exit, crop/animal lifecycle handling that is wrong regardless
    of seed or opponent;
  * concrete per-game / per-day / per-step inefficiencies — idle steps, shed
    overflow, plants dying, missed harvests, unfed/unwatered animals,
    floor-price or below-base sales, escaped animals, suboptimal market timing.

Judge a patch on whether it removes a concrete inefficiency or fixes a systemic
defect you can point at in a specific game — never on whether some average went
up.
-------------------------------------------------------------------------------

Experiment in this file
=======================
Extracted the one **additional layer** the reference notebook
``kaggriculture-top-2-master-engine-v4.ipynb`` carries that ``main.py`` does
not: the ``_ASTRA_I1`` "seven-turn / one-growth-refresh" opening extension.

The reference agent's opening tape (HybridOpening, installed live by
``main.layer_44_alt``) harvests the day-zero temporary wheat on **day 2** (step
~54), yielding 2 wheat. ``_ASTRA_I1`` instead lets that temporary wheat sit one
more growth refresh and harvests it on **day 3** (step ~87, watered again at
step ~86), which raises its yield to ~3-4, then re-runs the day-3 hand[0] route
to water/harvest/restore-pasture/deliver, and on the drop (step 91) sells the
extra delivered wheat. Net: more opening wheat sold without losing the pasture
build — a small but real, seed-independent efficiency.

Empirics — clean ``--compare`` (old vs new, same process / same seed set, F2
  wobble eliminated), vs master-engine-v3: +18, +29, +28, +15, +22, +17 (6/6
  seeds improved); vs cloning-agent +21/+21/+19, vs top-2-master-engine-v4
  +21/+59/+19 (6/6); vs one-more-wheat +16/+32 (2/3, one seed −123 with +3
  floor sales). No new escapes/overflow/unwatered in any game. The isolated
  per-process head-to-head also puts the reference ahead on every seed (the
  +223../+967 spread there is F2 order wobble on top of the +1 wheat).

Port method: the workspace ``main.layer_44_alt`` re-installs the base
HybridOpening tape at step 0 of every game, so this patch applies the I1 tape
edits *on top* at step 0 (mirroring the reference ``_alt_install``), then
replicates the reference ``_ASTRA_I1`` runtime post-process (steps 87-92)
inside ``patch()``. The installed-tape shape the I1 edits assert on is exactly
what ``layer_44_alt`` produces, so no ``main.py`` change is needed.
"""
from __future__ import annotations

import main as _main

# ---------------------------------------------------------------------------
# _ASTRA_I1 — extend the opening temporary-wheat crop by one growth refresh.
# ---------------------------------------------------------------------------
_I1_REPORT = dict(
    installed=0, harvested_units=0, delivered_units=0,
    pasture_restored=0, sale_units=0, errors=0,
)
_I1_STATE = {}


def _i1_install(mode):
    """Apply the reference I1 tape edits on top of the base HybridOpening tape.

    Runs after ``main.layer_44_alt`` installed the base opening, so the shape
    asserts below must already hold (they mirror the reference ```_alt_install``).
    """
    try:
        tape = _main._IMPL.chassis.routes[0]
        expected = [['HARVEST'], ['BUILD_PASTURE'], ['EAST'], ['EAST'], ['DROP']]
        assert [tape[s]['hands'][0] for s in range(53, 58)] == expected
        assert all(tape[s]['hands'][0] == ['PASS'] for s in range(84, 92))
        commands = [['EAST'], ['EAST'], ['WATER'], ['HARVEST'],
                    ['BUILD_PASTURE'], ['EAST'], ['EAST'], ['DROP']]
        for s in range(53, 58):
            tape[s]['hands'][0] = ['PASS']
        for s, command in zip(range(84, 92), commands):
            tape[s]['hands'][0] = command
        _I1_REPORT['installed'] += 1
        return True
    except Exception:
        # Tape shape not as expected (e.g. a reinstall didn't produce the base
        # opening). Fall back to the untouched production tape — never corrupt.
        _I1_REPORT['errors'] += 1
        return False


def _i1_sell_extra(action, item, n):
    if n <= 0:
        return action
    orders = [list(o) for o in (action.get('market') or [])]
    sell = next((o for o in orders if len(o) >= 3 and o[:2] == ['SELL', item]), None)
    if sell is not None:
        sell[2] += n
    elif len(orders) < 10:
        orders.append(['SELL', item, n])
    else:
        return action
    return dict(action, market=orders)


def _i1_run(obs, action):
    """Reference ``_ASTRA_I1`` post-process: telemetry + late extra-wheat sale."""
    seat = _int(obs.get('player', 0))
    step = _int(obs.get('step', 0))
    alt_state = getattr(_main, '_ALT_STATE', {}).get(seat, {})
    if alt_state.get('mode') != 'HybridOpening' or not _I1_REPORT['installed']:
        return action
    st = _I1_STATE.setdefault(seat, {})
    private = obs['private']
    farm = obs['farms'][seat]
    cargo = int(private['inventories'][1].get('WHEAT', 0)) if len(private['inventories']) > 1 else 0
    unit_hands = action.get('hands') or []
    farm_hands = farm.get('hands') or []
    if step == 87 and unit_hands and unit_hands[0] == ['HARVEST']:
        st['preharvest'] = cargo
    if step == 88 and 'preharvest' in st:
        _I1_REPORT['harvested_units'] = max(0, cargo - st['preharvest'])
    if step == 89:
        tile = farm['tiles'][4][2]
        _I1_REPORT['pasture_restored'] = int(isinstance(tile, dict) and tile.get('kind') == 'PASTURE')
    if step == 92 and 'predicted_delivery' in st:
        _I1_REPORT['delivered_units'] = min(st['predicted_delivery'], max(0, st['predrop'] - cargo))
    if step != 91 or not unit_hands or unit_hands[0] != ['DROP'] or not farm_hands or tuple(farm_hands[0]) != (4, 4):
        return action
    _, projected = _main._r127_fields(obs, action)
    delivered = max(0, cargo - int(projected['inventories'][1].get('WHEAT', 0)))
    st['predrop'] = cargo
    st['predicted_delivery'] = delivered
    scheduled = sum(max(0, int(o[2])) for o in action.get('market', [])
                    if len(o) >= 3 and o[:2] == ['SELL', 'WHEAT'])
    extra = min(delivered, max(0, int(projected['shed'].get('WHEAT', 0)) - scheduled))
    if not extra:
        return action
    changed = _i1_sell_extra(action, 'WHEAT', extra)
    if changed is not action:
        _I1_REPORT['sale_units'] += extra
    return changed


def _int(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return 0


def patch(action, observation, configuration=None):
    """Post-process the action produced by the full main.py agent.

    Layered on top of main's production agent: applies the reference
    ``_ASTRA_I1`` opening extension (one more growth refresh on the opening
    temporary wheat) and its late extra-wheat sale.

    (Two experiments were fully investigated via diagnose --xray and reverted:
      - L1 milk/fertilizer front-loading: a seat-0 first-mover micro edge, not
        recoverable by our own sell ordering (regressed ~-$442/seed, guarded too).
      - Weed-recovery: forcing an early pasture build after a weed-dig
        desynchronizes the worker from the fixed route tape and costs ~-$28.9k
        on the affected seed, far more than the recovered cow is worth.)
    """
    if not isinstance(observation, dict):
        return action
    step = _int(observation.get('step', 0))
    if step <= 0:
        _I1_STATE.clear()
        # layer_44_alt (runs before this patch, as the main agent parent) has
        # already installed the base HybridOpening tape; the I1 edits apply on
        # top. The shape asserts guard against any mismatch.
        _i1_install('HybridOpening')
        return action
    try:
        return _i1_run(observation, action)
    except Exception:
        _I1_REPORT['errors'] += 1
        return action


# Keep a plain `agent(observation, configuration)` entry point so main.py's own
# is_new_agent toggle (in case anyone flips it manually) resolves to the same
# behaviour: full main agent, then this patch. diagnose.py uses patch() directly.
def agent(observation, configuration=None):
    base = getattr(_main, "_original_agent", None)
    if base is None:
        # Fallback when not running inside the harness: nothing to patch.
        return {"farmer": ["PASS"], "hands": [], "market": []}
    return patch(base(observation, configuration), observation, configuration)
