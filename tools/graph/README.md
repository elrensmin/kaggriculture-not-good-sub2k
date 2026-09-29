# tools/graph — the decision-engine diagnostics

Three tools that answer one question: **is the state graph actually driving the agent, and where
does it diverge from Boey?** They exist because the graph spent a long time computing pressures
that no layer consumed, and nothing reported the disagreement.

Run everything from the repo root with `PYTHONPATH=.`.

| tool | question |
|---|---|
| `graph_diag.py` | Is the graph wired up, and which of its demands are not delivered? |
| `transplant_diff.py` | On BOEY's states, where do we choose differently from him? |
| `../audit/duplicate_owners.py` | Which decisions have more than one owner, and what is dead? |

---

## 1. `graph_diag.py` — troubleshoot the graph as a decision channel

Six sections. `--section all` runs the lot; each is independently useful.

```bash
PYTHONPATH=. python -m tools.graph.graph_diag --run-dir diag-replays/<arm> --section plug
PYTHONPATH=. python -m tools.graph.graph_diag --run-dir diag-replays/<arm> --section nodes  --days 0-17
PYTHONPATH=. python -m tools.graph.graph_diag --run-dir diag-replays/<arm> --section demand --days 4-12 --every 2
PYTHONPATH=. python -m tools.graph.graph_diag --run-dir diag-replays/<arm> --section break  --days 0-20
PYTHONPATH=. python -m tools.graph.graph_diag --run-dir diag-replays/<arm> --section chain
PYTHONPATH=. python -m tools.graph.graph_diag --run-dir diag-replays/<arm> --section seed   --days 2-14
```

| section | what it prints |
|---|---|
| `plug` | **static, code-level audit**: which `src/` modules import the graph and which entry points they call. A decision surface that does not import it cannot be steered by it. |
| `nodes` | per day, every node: ours / his target / deviation / urgency / effective pressure / root-or-symptom / op classes. The ideal trajectory evaluated against live state. |
| `demand` | **the central-nervous-system test.** Ops the graph demands (from `pressures`) vs ops actually performed, plus market orders issued. Flags `*** NOT DELIVERED ***` and `ordered with NO graph pressure`. |
| `break` | the first day each node goes deficient **and stays** deficient. A node that breaks and stays broken is a root the graph failed to close — a structural bug, never a tuning problem. |
| `chain` | `acts -> watering -> production -> revenue` per day, in that order. Never read the money row before the acts row. |
| `seed` | the seed decision as the graph sees it: `gap` (projected empty), `lead` (days until the remedy must be in hand), `band` (BUY_SEED pressure), `budget` (after atomic reservation). |

### What it has already found
* **`plug`**: only 4 of 27 `src/` modules imported the graph, and **none** of the order-emitting
  ones — the graph could steer the crew's job priority and nothing else.
* **`break`**: `dry_plants` broke on **d1 and stayed broken in 16/17 games** because its reader was
  `not watered_today`, which at hour 0 is *every plant on the farm*. WATER saturated the pressure
  cap every morning and starved PLANT / HARVEST / FERTILIZE.
* **`break`**: `revenue_per_day` and `labour` were **dead** — no `_LIVE` reader, so they never
  evaluated, never pressed, and silently removed **SELL, HARVEST and HIRE** from the graph's reach
  while severing `output_per_day -> revenue_per_day -> money` in the middle.
* **`demand`**: `DIG` carried the **single highest pressure in the whole graph** (band 4.00 at d12)
  and the crew dug **1.0 tile a day**, because `crop_plan` only emits DIG for a tile that is
  *already* a weed.
* **`demand`**: `BUILD_COOP` / `BUILD_PASTURE` demanded at 1.14–1.60, delivered **ZERO** →
  `animals` and `structures` broke at d3, 18/21.
* **`seed`**: at d9 we held **$62** against a **$4,000** quadrant, and the allocator reserved the
  full list price anyway, giving a seed budget of **−$3,938** with 22 owned tiles bare.

### Two measurement rules the tool learned the hard way
* **Divide by games, not rows.** The first version divided per-day totals by every row in the run
  and under-reported acts by ~21×.
* **Scan all 24 hours for market orders.** Sampling the market list at one hour shows no
  `BUY_SEED` even on days the farm buys seed all morning, and the tool then cried
  `*** MISSING ***` on a decision that *was* being made.

---

## 2. `transplant_diff.py` — the difference detector (a detector, NOT a gradient)

Runs **our** planner on **Boey's** states (`replays/Boey/v1`, 359 episodes) and reports discrete
disagreements. This is deliberately *not* a training loop.

**Why not a gradient.** A priority kernel is a **ranking**, not a smooth parameterisation: scaling a
priority changes nothing until it crosses a neighbour, then behaviour jumps. Measured — multiplying
priorities by graph pressure is harmful at **every** cap (1.0 `$58,899` / 1.1 `$50,716` / 1.25
`$47,228` / 1.5 `$37,175`, monotone), and replacing the kernel with normalised dollars loses the
survival ordering (deaths 59 → 94). So `his_share / our_share` is a valid *measurement* and cannot
be *followed*. The useful output is the discrete difference.

```bash
PYTHONPATH=. python -m tools.graph.transplant_diff --max-games 8 --days 4-12 --hour 12 --section diff
PYTHONPATH=. python -m tools.graph.transplant_diff --section caps
PYTHONPATH=. python -m tools.graph.transplant_diff --section reach --days 11-20
PYTHONPATH=. python -m tools.graph.transplant_diff --section state --days 0-14
```

Every disagreement is classified, because the classes have different owners:

| class | meaning | owner |
|---|---|---|
| **(a) missing capability** | he has a job type we never generate | graph |
| **(b) ranking** | we generate it but choose something else | weighting — the *only* place weights are legitimate |
| **(c) reachability** | we rank it right but no unit gets there | scheduler / routing |
| **(d) state divergence** | our board is not his, so the question is moot | the control problem |

### What it has already found
**We reproduce 70.7% of his unit-actions exactly** (249/352) on his own states. The dominant
divergence is **`FEED`** — it appears in 8 of the top 12 mismatches: `CARE->FEED` ×29,
`WATER->FEED` ×22, `COLLECT_FERTILIZER->FEED` ×8, `PICKUP->FEED` ×7, `HARVEST->FEED` ×6,
`PLACE->FEED` ×5, `PLANT->FEED` ×5. Classification: **(b) ranking 84**, **(a) missing 19**
(`PLANT` ×14), **(c) 0**.

**Correcting its own first reading:** `FEED` is a **single owner** (`herd_plan.jobs`), and the knob
plumbing is fine — `P_FEED=88` really does reach `params.P_FEED`, `job.P_FEED` and
`params.at('P_FEED',10)`. Yet `P_FEED=100/88/78` are **byte-identical**. So the FEED divergence is
**job supply**, not ranking, and `P_FEED` is **inert on this seed, not proven dead**. Say "inert on
seed 700" until it is measured across seeds.

### Instrumentation rule
A kaggle step records the action that **produced** its observation, so the action decided from
`steps[t]["observation"]` lives at `steps[t+1]["action"]`. Using the same index compares our
decision against his *previous* one. The tool applies the shift.

---

## 3. `../audit/duplicate_owners.py` — duplicate owners and dead code

This codebase's most expensive bug class is **two owners of one decision**: dead code is inert, but a
duplicate owner makes the live one **untunable while looking tunable**.

```bash
PYTHONPATH=. python -m tools.audit.duplicate_owners --section ops      # who can EMIT each op
PYTHONPATH=. python -m tools.audit.duplicate_owners --section names    # same fn name, 2+ modules
PYTHONPATH=. python -m tools.audit.duplicate_owners --section knobs    # params never read
PYTHONPATH=. python -m tools.audit.duplicate_owners --section reach    # unreachable from scheduler.plan
PYTHONPATH=. python -m tools.audit.duplicate_owners --section orphans
```

**A market order is a LIST; a value claim and a schedule are TUPLES.** Matching both reported
`plan.capex` and `state_graph.schedule` as LAND/SEED *buyers* when neither places an order — two
false positives that would have sent us editing code that was already correct.

### What it has already found
At the start: **10 of 18 op classes had more than one emitter**, led by **`BUY_SEED` at 7** — the
seed decision, which is why every seed experiment that round came back weak or byte-identical (each
was one of seven competing claims).

After the consolidation round: `BUY_SEED`, `PLANT`, `BUY_LAND` and `DIG` are **single-owner**.
Remaining multi-emitter: `BUY_PRODUCT` (5), `HARVEST` (3), `SELL` (3), `HIRE` (2), `PICKUP` (2),
`BUY_ANIMAL` (2).

### Design that fixed it: one emitter, many askers
`crop_plan.seed_ask`, `opening.seed_ask`, `plan._window_ask`, `plan._lead_ask` and
`plan._capex_ask` return **`(crop, qty)` pairs and own no order**; `plan.seed_intents` is the only
place a `["BUY_SEED", …]` list is constructed. The audit counts order *lists*, so asks do not
register as emitters — which is exactly the intent.

---

## Invariants to check after any graph change

```bash
# 1. no dead nodes -- MUST print an empty set
python -c "from src import state_graph as s; print(set(s.NODES)-set(s._LIVE))"
# 2. market surfaces under the graph
PYTHONPATH=. python -m tools.graph.graph_diag --run-dir diag-replays/<arm> --section plug
# 3. no demand without delivery, and no order without a pressure
PYTHONPATH=. python -m tools.graph.graph_diag --run-dir diag-replays/<arm> --section demand
# 4. no node breaks and stays broken
PYTHONPATH=. python -m tools.graph.graph_diag --run-dir diag-replays/<arm> --section break
# 5. every op has exactly one emitter (fallbacks are allowlisted in the tool)
PYTHONPATH=. python -m tools.audit.duplicate_owners --section ops
```

**A priority knob is live only if BOTH hold:** the `NAME_P2`/`NAME_P3` names exist in `params.py`,
**and** the reader goes through `params.at(name, day)`. Three separate bugs came from violating one
half of that rule.

**A crash is silent.** `src/__init__.py` degrades any exception to a legal `PASS`, so a game ending
at **$3,000, 0 harvests, 0 deaths** is a swallowed bug, not a bad strategy. `transplant_diff` and
`graph_diag` both count planner exceptions and print them — treat any non-zero count as the bug.
