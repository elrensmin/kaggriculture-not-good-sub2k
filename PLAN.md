# PLAN — Where we are & where to resume (handover)

> **State:** paused mid-task by user request; workspace is in a clean, reproducible
> state. Everything below is the authoritative record of what was uncovered and what
> was being attempted, so the next session can pick up immediately.
>
> **Golden rule (AGENTS.md):** never edit `main.py` or `route_tape.py` while
> experimenting. All experiments live in `agent.py` (patch `--new`) or in
> `route_tape_v2.py` (the swappable experimental tape).

---

## 1. Immediate status — run these to re-familiarize

```bash
# Plumbing smoke (must reproduce the baseline): both of these must print the SAME money
.venv/bin/python diagnose.py --tape v1 --old --pa 4 --seed 42 --batch 1 --run-dir /tmp/x1
.venv/bin/python diagnose.py --tape v2 --old --pa 4 --seed 42 --batch 1 --run-dir /tmp/x2
#   -> v1 : 91678 / 92166   and   v2 : 91678 / 92166   (identical; v2 == v1 today)
```

- `main.py` reads the production tape module name from the `KAGGICULTURE_TAPE`
  env var at import, so `route_tape_v2.py` can be selected/reloaded without
  touching `main.py` (PLAN P1.3, delivered).
- `diagnose.py` gained a `--tape {v1,v2}` flag that enforces the env var and
  clears the import cache before each (re)load, so a tape edit is picked up on
  the next run.
- `route_tape_v2.py` is currently **byte-identical** to `route_tape.py`
  (`md5 fc29a5de09176eec27fe0bdcaad39665` on both). It is the *designated* place
  to try tape experiments.
- To make a tape experiment: append a post-decoding mutation block to
  `route_tape_v2.py` (it builds `ROUTES`/`SHOP_ROUTES` from compressed data, then
  has a small post-processing loop you can extend), then run `--tape v2` and
  compare against the `--tape v1` baseline. Always revert/probe against seed 42
  first.

---

## 2. The task that was in flight

Original objective (from the goal tracker):

> Wire `route_tape_v2.py` into `main.py` via a `--tape {v1,v2}` switch, then use
> `route_tape_v2.py` + `main.py` changes to fix the weed/cow-pasture build defect
> that causes the seed-43-style losses vs seat-0 clones, and confirm the fix gates
> cleanly across all 13 public agents and a multi-seed set (win without
> regressions).

- The `--tape {v1,v2}` plumbing is **DONE and smoke-verified**.
- The weed-fix half is **investigated to a dead end** — see §4. The conclusion is
  that the specific spare-pasture / weed-recovery redundancy **cannot be added
  within the rigid position tape without regressions**, so the current
  recommendation is to **accept seed-43 as weed-RNG** and pivot the v2 tape to
  system-level levers (§5). Confirm this read before spending more cycles on it.

---

## 3. Delivered changes in this session

| file | change | status |
|---|---|---|
| `main.py` | tape module selected via `KAGGICULTURE_TAPE` env; `route_tape_v2` importable without editing `main.py` | delivered, verified (91678/92166 == baseline) |
| `diagnose.py` | `--tape {v1,v2}` enforces env + clears import cache before reload | delivered |
| `route_tape_v2.py` | experimental tape; **currently == v1 (safe baseline)** | delivered, unchanged |
| `agent.py` | contains only the I1 wheat patch + docstring (a weed patch was attempted then reverted — see §4) | `--new` only |

Note: `git status` shows `M agent.py`, `M diagnose.py`, `M main.py` — all
intended. `route_tape.py` / `route_tape_v2.py` are untouched from baseline.

---

## 4. The weed / cow-pasture defect — full investigation record

### 4.1 Symptom (seed 43, our agent as seat 1 vs a same-code seat-0 clone)

| | seat0 (wins) | seat1 (us) |
|---|---|---|
| reward | $93,295 | $89,507 |
| pastures | 12 | 11 |

~$3.8k loss despite both seats running identical code — it is pure RNG, not a
policy difference.

### 4.2 Root cause (located precisely via instrumented run, route 2)

- A cow pasture **#5** is (re)built at **step 33** by hand 1.
- That tile rolls a weed. `BUILD_PASTURE` on `None` becomes `DIG` (queue a
  build) that same turn; the queued build is replayed by `_weed_repair` at the
  next step where the hand is at a no-op **on that tile**.
- The tape's next action for that hand is **step 34 = `SOUTH` (a move)**, so the
  hand leaves the tile **before `_weed_repair` can replay** → queued build
  dropped.
- The hand only returns to that tile much later; `_weed_repair` finally rebuilds
  at **step 89** → pasture **+55 steps late** → cow placed a full day late.
- Net effect: **one cow housed a day late → one cow's entire season of milk
  missed** (~$130/day × 29 days ≈ $3.8k).

### 4.3 Daily-gap trace (the decisive fact)

A per-day money/pasture trace (seed 43, seat1 vs seat0) shows:

- The gap is **created on DAY 1**: seat1 has **4 pastures** where seat0 has **5**.
- It then persists at a steady **~$130/day** for the whole season — exactly one
  cow's lost milk, every day, no recovery.

→ Because the deficit begins on **day 1**, only an **early (day-1)**
redundant/spare pasture helps. A spare pasture from the day-6 expansion (the
only region with free empty tiles) is **useless against this early deficit**.

### 4.4 Why every attempt fails (all proven, not speculated)

| attempt | mechanism | result |
|---|---|---|
| **A. Runtime weed patch in `agent.py`** (force an early extra build) | overrides the hand's move to build sooner | reached **12 pastures (goal met)** but **lost $28,883** — the forced build desyncs the rigid position tape and cascades through the whole day-6 opening |
| **B. Spare pasture via a "free" empty tile** | scan for a day-1 idle hand standing on an empty tile to add a redundant pasture | **no clean candidate exists** on route 2's day-1 window — every idle unit parks on an occupied tile, so adding a pasture requires moving a unit (→ desync) |
| **C. Compensated-slack tape edit (the plausible one)** | keep pasture builder idle on its tile through day 1 (steps 34–40 → PASS) so a weeded build recovers at the first idle no-op (step 41) | **seed 42 (healthy) regressed 91678 → 91401 (−277)**: the builder skips its essential day-1 `PICKUP WHEAT` / `FEED` / `CARE` chores, so **every clean game regresses**. Fails the gate immediately. |

### 4.5 Conclusion (definitive)

The weed-caused loss **cannot be fixed within the rigid tape**:

- The builder hand has **no spare labour** — its day-1 chores (feed/care/pickup)
  are all essential to the healthy path. Giving the tape a budgeted recovery step
  for the weed costs those chores on *every* clean game (C).
- Any *conditional* recovery requires runtime position-shifting, which is exactly
  the mechanism that desynced in (A).
- The tape is static and identical for both seats, so a tape change affects both
  seats symmetrically and cannot be limited to the unlucky seat/game.

**Resolution:** treat the seed-43 loss as **weed-RNG** — a rare, small
(~$3.8k/seed), per-game event that identical-code clones hit at random against
each other. It is not a system defect worth chasing inside the tape.

---

## 5. Where to resume (recommended next steps)

1. **Keep the `--tape {v1,v2}` lever** as the sanctioned way to try tape changes
   (it is in place and verified).
2. **Do NOT** sink more effort into the seed-43 weed redundancy — §4.5 gives the
   reason, backed by a measured healthy-path regression.
3. **Use `route_tape_v2.py` for genuine system-level levers** that help every
   game regardless of seed/opponent (the AGENTS.md anti-goal: hunt structural
   defects, never chase averages):
   - **L2 — market/router mix:** selling into scarcity vs glut for the premium
     goods (strawberry/melon/milk/wool crash to $1 over-supply; carrot/tomato/egg
     spike under shortage). Tape-level reordering of sales into the scarcity
     window.
   - **L3 — labour/animal/crop lifecycle:** shed overflow/discards, plants dying
     / missed harvests, unfed/unwatered animals, fertilizer collection.
4. **Each lever, gated (acceptance criteria from the original plan):**
   - Change one lever at a time in `route_tape_v2.py`.
   - A/B across all **13 public agents × ≥3 seeds** each (39 games per side),
     via `./sweep.sh` plus an explicit same-tape head-to-head to isolate the
     $/unit timing margin.
   - Judge per game, never an averaged mean. **Accept only if** the *targeted*
     defect improves in the large majority of games **and** no game acquires a
     new structural defect (no new escape/overflow/floor dump). Otherwise revert
     `route_tape_v2.py` to the last accepted revision.
   - On a clear, stable win, promote into `main.py` (or the tape) as the new
     baseline and clear the experiment.

---

## 6. Reference details for resuming (do not lose these)

### 6.1 Route-2 day-1 schedule (hand 1 = the pasture builder, the weed-fix target)

```
st24 HIRE          st21 market: HIRE,HIRE,HIRE
st25 h1 NORTH      st26 h1 PICKUP WHEAT   st27 h1 FEED  st28 h1 CARE
st29 h1 COLLECT_FERTILIZER   st30 h1 PLACE FERTILIZER   st31 h1 NORTH  st32 h1 NORTH
st33 h1 BUILD_PASTURE   <- (built pasture #5; weeded here on seed 43)
st34 h1 SOUTH   st35 h1 SOUTH   st36 h1 PICKUP WHEAT   st37 h1 WEST   st38 h1 FEED
st39 h1 COLLECT_FERTILIZER   st40 h1 CARE   st41-47 h1 PASS (idle tail)
st48 HIRE (+ new hand), st49+ h1 starts day-2
```
h1 is a multi-purpose day-1 hand: feed, care, water, wheat pickup are all
essential → any change that frees a step for the weed recovery drops one of these
on every clean game (this is exactly what regressed seed 42 in attempt C).

### 6.2 Day-6 (post-unlock) build positions that had *empty* tiles (seed 43)

Useful if a later-game slack (not day-1) is ever desired:
- st153: u5(5,4)None, u6(5,2)None, u7(5,4)None
- st155: u7(5,3)None, u6(6,2)None
- st160: u2(5,1)None, u6(7,1)None, u7(6,3)None
These are in the NE (unlocked day-6) region. But note §4.3: a late spare cannot
fix the early-day-1 milk deficit.

### 6.3 Earlier (broader) findings still valid

From the pre-session work (see prior PLAN.md body — kept for continuity):

- **F1 – Measurement bug:** market metrics counted *requested* qty (sentinel
  `SELL <x> 1000` = "dump all"), not *committed*; `sell_qty_*`/`floor_sales_*`
  were ~40× inflated. Fix in `diagnose.py`.
- **F2 – Non-import-idempotence:** `load_old_agent(fresh=False)`=91882 vs
  `fresh=True`=91678 on the same seed — a pure market-order reorder at call 312;
  the market is order-sensitive. `--tape v1 --old` (fresh) must be the stable,
  reproducible comparison mode.
- **F3/F4 – Metrics:** `idle_steps` meaningless (unit-level idles: 125 PASSes on
  a ready tile); "overflow days" ≠ discards (3 vs 19 units).
- **F5 – Premium glut realization (seed 42):** MILK $36 (0.23×), FERTILIZER $44
  (0.44×), WOOL $122 (0.61×), MELON $198 — i.e. timing of sales is the margin
  against a same-tape clone (91678 vs 92166 is all micro price capture).

### 6.4 Key environment facts for future tape/lever work

- **Turn processing:** 720 turns = 30 days × 24. Hands re-hired daily (fib cost
  1,1,2,3,5…), spawn shed-adjacent. Refreshes/decay only fire on the last turn of
  a day (step ≡ 0 mod 24).
- **Two consecutive unfed days → animal escapes (unrecoverable).** Newly placed
  animal survives its first day unfed (starts `consecutive_unfed=0`).
- **Two missed end-of-day water refreshes → plant becomes a weed.** Planting day
  counts as day 1 unwatered — always water on plant day.
- **Shed cap 100** non-seed items; overflow discards (no queue).
- **Market is shared, order-sensitive, per-unit lockstep (max 10/turn/player).**
  `SELL` quoted at pre-sell inventory; `BUY_PRODUCT` at post-buy. Selling at $1
  adds no supply.
- **Town demand shared & reliable:** town center consumes 1/item per day; up to 8
  shops unlock every 3 days, each consuming every 4 turns (single-product shops
  2×). Premium goods (base>100) crater to $1 on slight over-supply; carrot/tomato/
  egg spike on shortage but stay calm at base. Watch `unlocked_shops[:2]` — the
  router picks the tape from the first two shops (day 6).

---

## 7. Quick command cheat-sheet

```bash
# compare two tape modules on one seed (seed 42 is the stable anchor)
.venv/bin/python diagnose.py --tape v1 --old --pa 4 --seed 42 --batch 1 --run-dir /tmp/v1
.venv/bin/python diagnose.py --tape v2 --old --pa 4 --seed 42 --batch 1 --run-dir /tmp/v2

# full board A/B across all 13 public agents x many seeds
./sweep.sh old
./sweep.sh new

# inspect a run's per-item price realization and per-day gaps from the saved CSVs/JSON
# (run-dir contains <agent>_..._seedNN.json, days_*.csv, games.csv)
```

Live public-agent index mapping:
`python -c "import diagnose; print(diagnose.public_agent_names())"`.
