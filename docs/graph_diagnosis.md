# Graph diagnosis — the state graph as the decision engine

Produced by `tools/graph/graph_diag.py`. Every number below is reproduced by a command in this
document. Read this before adding any rule: it is the record of *which* decisions the graph can
and cannot reach, and of the structural bugs that block it.

```bash
# the run all tables below come from
PYTHONPATH=. python -m tools.diagnose --scratch --pa 2,3 --batch 1 --seed 700 --run-dir diag-replays/gd
PYTHONPATH=. python -m tools.graph.graph_diag --run-dir diag-replays/gd --section plug
PYTHONPATH=. python -m tools.graph.graph_diag --run-dir diag-replays/gd --section break --days 0-20
PYTHONPATH=. python -m tools.graph.graph_diag --run-dir diag-replays/gd --section demand --days 4-12 --every 2
PYTHONPATH=. python -m tools.graph.graph_diag --run-dir diag-replays/gd --section seed --days 2-14
```

---

## 0. What was broken and is now fixed

| # | defect | evidence | fix |
|---|---|---|---|
| 1 | **The graph was not wired to the market at all.** Only 4 of 27 `src/` modules imported it, and **none** of the order-emitting ones (`budget`, `crop_plan`, `herd_plan`, `sell_policy`, `trade`, `endgame`). It could steer the crew's job priority and nothing else. | `--section plug`: `MARKET surfaces importing it: 0/9` | one choke point, `state_graph.apply_to_market`, called from `emit.assemble`. `emit` truncates at `MAX_ORDERS`, so the order of that list **is** the funding priority — one adapter, no seven-way drift. |
| 2 | **`dry_plants` counted `not watered_today`.** At hour 0 *every* plant on the farm satisfies that, so the node was maximally deficient every morning, WATER saturated against the pressure cap, and the crew was pinned to watering while PLANT / HARVEST / FERTILIZE starved. | `--section break`: **broke at d1 and stayed broken 16/17 games** — the earliest break in the graph, and not a defect at all | `_dying_today`: only plants at `age >= water_window.end` that are still dry and not yet harvestable — the true "becomes a weed tonight" set. `consecutive_unwatered` cannot separate the set (it reads 1 at the start of every day for every living plant). **Now: never breaks, 0/21.** |
| 3 | **Two nodes had no live reader — they were DEAD.** `revenue_per_day` and `labour` never evaluated, so they were never deficient, so they never emitted a pressure — which silently removed **SELL, HARVEST and HIRE** from the graph's reach entirely and severed `output_per_day -> revenue_per_day -> money` **in the middle**. A deficient bank could not blame production; production could never push the market. | `python -c "from src import state_graph as s; print(set(s.NODES)-set(s._LIVE))"` returned those two | `_sellable_value` (shed + standing-ripe, priced at the live book, stateless) and `s.unit_count()`. All 15 op classes are now reachable. **The check must return empty — add it to any new node.** |

Effect of the three fixes on the run above (2 games, seed 700, PA 2/3):

| | baseline | graph wired |
|---|---|---|
| our bank | $44,341 / $34,233 | **$58,209 / $65,553** |
| sell revenue | — | $98,314 / $104,325 |
| idle share | ~60 % moves | **2.5 % / 2.2 %** |

---

## 1. THE PHANTOM LAND RESERVATION STARVES SEED — the core loop is blocked

`--section seed` prints the seed decision as the graph sees it:

| day | empty | gap | lead | band | land reservation | **seed budget** | seeds | money | diagnosis |
|---|---|---|---|---|---|---|---|---|---|
| d2 | 1 | 26 | 3 | 1.56 | $1,000 | **−$1,431** | 1 | $19 | PRESSURED BUT UNFUNDED |
| d3 | 4 | 29 | 2 | 3.17 | $1,000 | **−$1,175** | 2 | $162 | PRESSURED BUT UNFUNDED |
| d4 | 3 | 28 | 1 | 3.22 | $1,000 | **−$927** | 1 | $283 | PRESSURED BUT UNFUNDED |
| d5 | 3 | 28 | 0 | 3.28 | $1,000 | **−$678** | 1 | $322 | PRESSURED BUT UNFUNDED |
| d7 | **19** | 44 | 1 | 3.39 | $2,000 | **−$1,923** | 11 | $77 | PRESSURED BUT UNFUNDED |
| d8 | 15 | 40 | 0 | 3.44 | $2,000 | +$417 | 13 | $2,417 | can buy 41 wheat |
| d9 | **22** | 47 | 0 | 3.50 | $4,000 | **−$3,938** | 14 | **$62** | PRESSURED BUT UNFUNDED |
| d10 | 12 | 37 | 0 | 3.55 | $4,000 | **−$3,978** | 13 | $22 | PRESSURED BUT UNFUNDED |
| d13 | 4 | 4 | −1 | 2.26 | $0 | **+$8,770** | 17 | $8,770 | seed in hand |

**The bug.** The seed allocator reserves the **full nominal price** of the next quadrant
(`params.LAND_COST`) whether or not that quadrant is affordable. At d9 we hold **$62** against a
**$4,000** SE quadrant, so the reservation is $3,938 of pure fiction — a claim on cash that cannot
be spent — and it zeroes the seed budget while **22 owned tiles sit bare** and the graph presses
BUY_SEED at band 3.50 (near its cap).

**Why it is the core loop.** The chain is `seed -> production -> revenue -> land`. Reserving cash
for land we cannot afford blocks the very seed that would earn the money to buy it. The farm is
locked: bare tiles earn nothing, so the quadrant stays unaffordable, so the reservation keeps
starving seed. `empty` breaks at **d2 and stays broken in 13/21 games**.

**Confirmed by the control:** d13/d14, when the land schedule is empty, reservation $0, seed
budget **+$8,770**, and `empty` falls to 4–5. Cash was never the constraint; the phantom
reservation was.

**Fix direction (not yet applied).** Reserve an atomic claim only to the extent it is
**actually imminent and affordable** — i.e. the amount `budget`'s own purchase rule would commit
this turn (`money >= LAND_COST + reserve`), not the list price. A reservation for a purchase that
cannot occur must be zero. Equivalently: the reservation is a *liability only once funded*.

---

## 2. Demanded but NOT DELIVERED — two chains have no actuator

`--section demand`. `band` is the graph's pressure; `per day` is the mean op count over all 24
hours across 2 games.

| op | band | delivered/day | share | verdict |
|---|---|---|---|---|
| `BUILD_COOP` | 1.14 → 1.60 | **0.0** (d4, d8), 0.5 (d10, d12) | 0–1.8 % | *** NOT DELIVERED *** |
| `BUILD_PASTURE` | 1.14 → 1.60 | **0.0** (d4, d8), 0.5 (d10, d12) | 0–1.2 % | *** NOT DELIVERED *** |
| `DIG` | **4.00** (d12), 2.63 (d10) | 1.0 | 1.2 % | thin — and 4.00 is the **highest band in the graph** |

- **BUILD_COOP / BUILD_PASTURE**: demand band 1.14–1.60, delivery **zero**. This is the animals
  chain and it is why `animals` and `structures` both **break at d3 and stay broken in 18/21
  games**. The graph asks; no layer listens; nothing builds.
- **DIG**: at d12 the graph emits its single highest pressure in the whole system (**band 4.00**)
  and the crew digs **1 tile a day**. `weeds` breaks at **d10** (11/21). The biggest demand in the
  graph is the least delivered.

Both are the same defect class: a node whose ops are licensed but whose actuator is not
connected. `--section demand` exists to make exactly this visible.

---

## 3. Ordered with NO graph pressure — unsteered spend

Orders issued on turns when the graph has **no opinion at all**:

| op | turns/day it is ordered | graph pressure |
|---|---|---|
| `HIRE` | **24** (every turn of d10 and d12) | none |
| `BUY_ANIMAL` | 4 (d10), 2 (d12), 11 (d4) | none |
| `BUY_LAND` | 1 (d6) | none |

`HIRE` being issued every single turn with no graph pressure is the largest unsteered decision in
the agent. Combined with §2 this is the same asymmetry from the other side: the graph has opinions
about the crew's *jobs* but not about *how many crew*, while the layers buy crew, animals and land
on their own authority.

---

## 4. Throughput — the `acts` head of the chain

`--section chain`, acts per day (all acting turns, MOVE excluded):

| day | d4 | d6 | d8 | d10 | d12 |
|---|---|---|---|---|---|
| ours | 34 | 42 | 53 | 85 | 84 |
| **Boey** | — | — | — | — | **127–163** |

Every point of the deficit propagates: `acts -> watering -> production -> revenue`. The graph now
pressures PLANT, HARVEST and SELL and **those are delivered** (§2 minus the two broken chains), so
the remaining throughput gap is not a priority problem — it is unit-turns and the broken
BUILD/DIG actuators starving the midgame of work.

---

## 5. Node health after the fixes

`--section break --days 0-20`:

| node | first break | days deficient | verdict |
|---|---|---|---|
| `revenue_per_day` | d1 | 20/21 | broke — conversion gap (newly live, target is his daily output value) |
| `empty` | **d2** | 13/21 | broke — §1, the phantom reservation |
| `planted` | d2 | 18/21 | broke — downstream of `empty` |
| `animals` | d3 | 18/21 | broke — §2, BUILD never delivered |
| `structures` | d3 | 18/21 | broke — §2 |
| `labour` | d4 | 3/21 | mild |
| `weeds` | d10 | 11/21 | broke — §2, DIG not delivered |
| `unfed` | d1 | 4/21 | mild |
| `money` | d0 | 14/21 | broke (a stock that starts at 0 — read with `revenue_per_day`) |
| **`dry_plants`** | **never** | **0/21** | **ok — fixed** |
| `shed` | never | 0/21 | ok |
| `quadrants` | never | 0/13 | ok |
| `melon_tiles` | never | 0/4 | ok |

A node that **breaks and stays broken** is a root the graph failed to close. That is a structural
bug, never a tuning problem: no knob moves `empty` when the seed budget is arithmetically
negative.

---

## 6. Tool caveats (both were real, both fixed)

- **Divide by games, not rows.** The first version divided per-day totals by *every* row in the
  run, under-reporting acts by ~21×. Always divide by the number of games contributing to that day.
- **Scan all 24 hours for market orders.** Sampling the market list at hour 23 shows no `BUY_SEED`
  even on days the farm buys seed all morning; the tool then cried `*** MISSING ***` on a decision
  that was in fact being made. Market ops are counted across the whole day; state is sampled at
  one hour.

## 7. The invariants to keep

```bash
# 1. no dead nodes -- must print an empty set
python -c "from src import state_graph as s; print(set(s.NODES)-set(s._LIVE))"
# 2. the market is under the graph -- 0/9 must become 9/9
PYTHONPATH=. python -m tools.graph.graph_diag --run-dir <arm> --section plug
# 3. no demand without delivery
PYTHONPATH=. python -m tools.graph.graph_diag --run-dir <arm> --section demand
# 4. no order without a pressure
#    (--section demand flags these as "ordered on N turns with NO graph pressure")
```

---

# Round 2 — the decision engine, measured

All on `PA=1 --batch 1 --seed 700`, the fast loop.

## Applied

1. **Wired the market into the graph** (`GRAPH_MARKET`, `state_graph.apply_to_market` from
   `emit.assemble`). The single choke point; `emit` truncates at `MAX_ORDERS`, so list order IS
   funding priority. **Measured positive — kept.**
2. **`dry_plants` reader fixed** — counted `not watered_today`, which at hour 0 is *every plant*,
   so WATER saturated the cap every morning and starved PLANT/HARVEST/FERTILIZE. Broke d1, 16/17
   games. Now reads only plants at `age >= water_window.end`, dry, not harvestable. **0/21.**
3. **Two dead nodes revived** — `revenue_per_day` and `labour` had no `_LIVE` reader, so they
   never evaluated, silently removing SELL, HARVEST and HIRE from the graph and severing
   `output_per_day -> revenue_per_day -> money`. 15/15 op classes reachable now.
4. **`benchmark.py` regenerated from EVERY measured column** (38 metrics, was 15). The generator
   now derives the list from the JSON, so a metric can never be silently dropped again. Added the
   ops-chain targets the engine needed: `n_move`, `n_pass`, `hires`, `hands_end`, `revenue`,
   `plants_planted_*`.
5. **`priors.py` extended**: `LAND_BY_QUADRANT` / `land_due_day` / `land_lead` derived from the
   measured cumulative (NE d6, **SW d8, SE d9** — `params.LAND_TARGET_DAY` had d6/d9/d10, a day
   late each), plus `acts_target` (= unit_turns − n_move − n_pass; d10 → 157, matching the
   measured 127–163), `water_target`, `hands_target`, `revenue_target`, `move_target`.
6. **The phantom land reservation fixed** in `plan.capex_intents`: reserve the next quadrant only
   when `money >= cost + reserve`. At d9 we held **$62** against a **$4,000** quadrant, so the old
   reservation was $3,938 of fiction that zeroed the seed budget while 22 tiles sat bare. A claim
   on cash we do not have is not a claim. (Inert until `CAPEX_ALLOCATOR` is on.)
7. **`deficit_jobs`** — the graph's own actuator for a demand whose precondition exists.

## Measured and REVERTED — the important negative results

**The crew priority multiplier (`apply_to_jobs`) is harmful at every cap.** Monotone:

| steering cap | money | died | revenue |
|---|---|---|---|
| 1.0 (off) | **$58,899** | 59 | **$99,078** |
| 1.1 | $50,716 | 56 | $95,313 |
| 1.25 | $47,228 | 54 | $85,257 |
| 1.5 | $37,175 | 58 | $80,002 |

It buys a few fewer deaths at a terrible exchange rate on revenue. Structural reason: every node we
are behind on (`empty`, `planted`, `animals`) is deficient **every** day, so their ops sit
permanently boosted while a *satisfied* survival node (`dry_plants`) rides at 1.0× — the crew
plants and digs while the crops go dry. `job.py` already encodes the correct relative order of the
op classes; a second, incomparable scale destroys that calibration. `STATE_GRAPH = False`.
**The end state is for the graph to REPLACE the priority kernel, not multiply it.**

**Two bugs found inside the graph while getting there:**

- **`money` and `revenue_per_day` licensed `HARVEST`.** They are a stock and a flow and can never
  be satisfied early, so HARVEST carried a permanent unearned ~2.2× boost — the exact inversion of
  the kernel (`money` eff 2.20 → HARVEST 2.2× vs `dry_plants` eff 1.00 → WATER 1.0×). Making them
  market-only (`SELL`) took the arm **$25,731 → $45,991**.
- **`deficit_jobs` fabricated BUILD jobs.** It fired on `structures`, which is a *symptom* of
  `animals` in this graph's own edges, so it built housing with no animals — consuming the crop
  tiles. **$58,209 → $27,622, revenue $98k → $71k.** `herd_plan`'s own comment records the same
  failure measured earlier. Restricting the actuator to DIG (the object exists and is itself the
  defect) fixed it. **An actuator may only fire on a ROOT, and only when the thing it acts on
  already exists.**
- **Crash-to-PASS**: `apply_to_jobs` called `params.at(...)` without `params` imported at module
  level, so it threw every turn and `src/__init__.py` degraded the whole agent to PASS — the
  `$3,000 / 0 harvests / died 0` signature. Fixed by adding `params` to the module import.

## Not done this round

- The `src/` dead-code audit (subagent stopped mid-run) — no code removed.
- The AGENTS.md per-file inventory of `src/`.
- `LAND_FROM_PRIORS` is **off** by default (unmeasured); `CAPEX_ALLOCATOR` is **off**.
