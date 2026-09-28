"""propagation_rules — the DATA for the propagation graph. Edit this, not the engine.

`tools/phases/propagate.py` composes a proposed change through the game's structural
mechanics without running a game. This file is the model: which quantity feeds which, by
how much, with what lag, and which hard limits bind.

Three kinds of edge:

  exact      an engine rule, true by construction. `animals +1` IS `+1 FEED, +1 CARE,
             +1 COLLECT` every day the animal exists. No measurement needed.
  measured   a local rate we have measured; the number carries a tolerance and a source.
  threshold  a hard gate that inverts the direction once crossed (the herd feed gate is
             the one that has actually bitten us).

`mode` says how a source delta accrues:
  level      the source is a persisting STATE delta, so it produces `coef * src` per day.
             `+5 animals` from d10 is `+5 FEED/day` from d10 -- NOT a running sum.
  oneoff     the source delta is consumed once, on the day it changes
             (`+5 animals` is `+5 PLACE`, not `+5 PLACE/day`).

Every constant here is either an engine fact or a measured rate with its source; nothing
is fitted. Keep it that way -- if a number is unknown, leave the edge out rather than
guess, because a wrong edge is worse than a missing one.
"""
from __future__ import annotations

# ---------------------------------------------------------------------------
# Nodes. ``key`` matches the DAG metric key where one exists, so a propagation result
# and a `phase_map` row are the same quantity. ``src`` is the phase_map source string.
# ``better`` is carried for reporting only.
# ---------------------------------------------------------------------------
NODES = {
    "empty_tiles2":   ("empty owned tiles", "stock:empty", "lower"),
    "wheat_tiles2":   ("WHEAT tiles", "stock:plant_WHEAT", "higher"),
    "planted_tiles2": ("planted tiles", "stock:planted", "higher"),
    "animals2":       ("animals on board", "stock:animals", "higher"),
    "plant_ops2":     ("PLANT ops", "flow:PLANT", "higher"),
    "water_ops2":     ("WATER ops", "flow:WATER", "higher"),
    "harvests2":      ("HARVEST ops", "flow:HARVEST", "higher"),
    "feed_ops2":      ("FEED ops", "flow:FEED", "higher"),
    "care_ops2":      ("CARE ops", "flow:CARE", "higher"),
    "collect_ops2":   ("COLLECT_FERTILIZER ops", "flow:COLLECT_FERTILIZER", "higher"),
    "place_ops2":     ("PLACE ops", "flow:PLACE", "higher"),
}

# Concrete engine constants used by rules and thresholds. Kept beside the rules so a
# reader can see every number the model assumes.
ANIMALS_PER_DAY_OPS = ("feed_ops2", "care_ops2", "collect_ops2")   # engine: 1 each/day
WHEAT_TILES_PER_ANIMAL = 1.7     # src/params.py -- the feed gate the farm actually runs
TURNS_PER_HAND_DAY = 24          # engine: one action per unit per turn
OPS_PER_WHEAT_TILE_DAY = 0.70    # measured `crop_cycle`, Boey; ours 0.59 before fertilize

# ---------------------------------------------------------------------------
# RULES. (src, dst, coef, lag, mode, kind, note)
# ---------------------------------------------------------------------------
RULES = [
    # ---- exact engine rules: one animal is one of each daily op ----
    ("animals2", "feed_ops2", 1.0, 0, "level", "exact",
     "engine: every animal eats 1 wheat/day -> a FEED op"),
    ("animals2", "care_ops2", 1.0, 0, "level", "exact",
     "engine: CARE is one op/animal/day and banks the production bonus"),
    ("animals2", "collect_ops2", 1.0, 0, "level", "exact",
     "engine: 1 fertilizer available/animal/day"),
    ("animals2", "place_ops2", 1.0, 1, "oneoff", "exact",
     "engine: one PLACE per animal bought into the shed, on the day it lands"),

    # ---- measured agronomy -> work supply ----
    ("plant_ops2", "wheat_tiles2", 3.0, 0, "level", "measured",
     "a sustained +1 PLANT/day holds ~cycle_days standing tiles (wheat cycle ~3-4 d, "
     "source tools/labour/crop_cycle.py). The WHEAT share only -- the model over-states "
     "if the queue is mixed, so read it as an upper bound"),
    ("wheat_tiles2", "harvests2", OPS_PER_WHEAT_TILE_DAY / 3.0, 2, "level", "measured",
     "a wheat tile turns over ~3 units per 3-5 day cycle = ~0.23 HARVEST ops/tile/day "
     "(source tools/labour/crop_cycle.py, Boey d6-17)"),
    ("planted_tiles2", "water_ops2", 0.78, 0, "level", "measured",
     "WATER ops per planted tile per day (reference 0.79, ours 0.64 -- phase_map "
     "water_per_tile). Read the CAPACITY flag before believing it: if turns are short, "
     "this water does not happen"),
]

# ---------------------------------------------------------------------------
# THRESHOLDS. A gate that binds in the direction that matters, evaluated per day.
#   cap(node, day) -> the maximum delta the model will allow, or None for no cap.
# Expressed as small named functions so the arithmetic is auditable.
# ---------------------------------------------------------------------------
def herd_gate_cap(base_animals, base_wheat, wheat_delta, day):
    """The midgame herd feed gate: `animals <= floor(wheat_tiles / 1.7) - 1`.

    MEASURED (`tools/phases/herd_gate.py`, 8 games): from d13 to d17 `W` fails every day
    (20 wheat tiles against `1.7 * (13+1) = 23.8`) while cash and the buy window are both
    green and `bought = 0`. The gate is a standing-TILE proxy for feed, so it is the
    threshold this model exists to expose. Returns the ABSOLUTE cap for the day, or None
    before the gate applies.
    """
    if day < 6:
        return None
    return int((base_wheat + wheat_delta) / WHEAT_TILES_PER_ANIMAL) - 1


# Season target the herd buys toward (src/params.HERD, YARN world -- 95/96 of our games).
HERD_SEASON_TARGET = 9 + 10 + 6      # COW 9 + SHEEP 10 + GOOSE 6 = 25

THRESHOLDS = [
    dict(node="animals2", name="herd_gate",
         desc="animals <= floor(wheat_tiles / WHEAT_TILES_PER_ANIMAL) - 1",
         fn=herd_gate_cap, ceiling=HERD_SEASON_TARGET, fill=True),
]

# ---------------------------------------------------------------------------
# CAPACITY. The crew-turn budget is the thing that makes a structural change fail even
# when every gate passes. Unit-turns are FIXED (`hands * 24`, measured identical on both
# arms: 3,077 vs 3,044 over d6-17), so an extra act has to be paid for out of walking:
# `extra_turns = d_acts * (1 + moves_per_act)` must fit inside `pass + avoidable moves`.
# The avoidable share is `hop_regret`'s measured 30.2 % (Boey 21.1 %).
# ---------------------------------------------------------------------------
AVOIDABLE_MOVE_FRAC = 0.302

CAPACITY = {
    "turns_per_hand_day": TURNS_PER_HAND_DAY,
    "avoidable_move_frac": AVOIDABLE_MOVE_FRAC,
    "note": "extra_turns = d_acts*(1+moves_per_act); spare = pass + avoidable*moves",
}
