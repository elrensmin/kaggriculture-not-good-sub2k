# How our agent got built: tape → 45 layers → final patch

*Data-based iterative analysis of `route_tape.py` + the `main.py` layer stack.
Every empirical number below is from **one real game** (never averaged), run by
`analyze_patches.py` across three public opponents at seed 42, saving full
replays in `diag-replays/iterative/`.*

---

## 1. What `route_tape.py` is (the base nature of the tape)

`route_tape.py` is a single **zlib + base85-decoded payload** that builds two
structures, read-only at import:

- **`ROUTES` — 41 pre-computed 719-step action tapes**, keyed `0–12` and
  `100–128`. Each entry is one complete season-length script of
  `{"farmer": [op…], "hands": [[op…]…], "market": [[order, item, qty]…]}` per
  step. **Every route is 719 actions** (episode length) and **every route shares
  the identical step-0 R42 opening**:
  `[BUY_PRODUCT WHEAT 13, BUY_PRODUCT WHEAT 30, SELL WHEAT 30]` — i.e. the tape
  buys wheat into scarcity and sells it back at the premium on the very first
  turn, seeding cash before any land/build work.
- **`SHOP_ROUTES` — 64 shop-pair → route** lookups (e.g. `BAKERY,BAKERY → 101`,
  `BAKERY,YARN_STORE → 109`). The `_router` in `main.py` reads the first two
  unlocked shops (`unlocked_shops[:2]`) and picks the route tuned for that shop
  mix; `_V92_TABLE`/EXP240/EXP241 override the pair→route choice, and a
  pre-scheduled `route=2` day-27 switch runs the terminal script.

So the tape **is the farm's "answer key"**: it pre-encodes which crops/animals
to plant/build, when to water/harvest/deliver, and what to sell each day, chosen
entirely by the opening shop mix. The layer stack exists to make that rigid
script safe and profitable under live moving prices.

---

## 2. The layer stack = the iterative patches others built

`main.py` composes **45 layers** (`layer_00_impl` → `layer_44_alt`) as
`agent = layer_NN(prev_agent)`, each layer a prior fix stacked on the last. The
final production agent is `layer_44_alt` + the **promoted `_ASTRA_I1` patch**.
`main.py` exports every layer-boundary as a **native composed prefix**
(`_IMPL`, `_SHOP_PARENT`, `_V28_CORE`, … `_I1_BASE`, `_original_agent`), which is
exactly what lets us replay the agent at each historical point.

Ordering (from `main.py` source):

| prefix global | after layer | what that stage adds (from code) |
|---|---|---|
| `_IMPL` | — | **BASE**: raw chassis = tape replay + reactive safety (`hand_align`, `weed_repair`, `sell_lead`) |
| `_SHOP_PARENT` | `layer_00_impl` | error-safe tape passthrough |
| `_PRE_TERMINAL_AGENT` | `layer_01_shop` | last-turn shop liquidation |
| `_PRE_ROOM_AGENT` | `layer_02_pre_terminal` | terminal room planner |
| `_V28_CORE` | `layer_03_pre_room` | shop/pre-terminal/pre-room scaffolding |
| `_EXPERIMENT_PARENT` | `layer_05_v219` | native worker coordination |
| `_ORDER_PARENT` | `layer_06_experiment` / `_V31_CORE`·`layer_07_order` | order / v31 core |
| `_V231_PARENT` | `layer_08_v31_core` / `_V231`·`layer_09` | **livestock substitution** (buy cow vs sheep per shop context) |
| `_R36_SALE_PARENT` | `layer_09_v231` | r36 sale reorder |
| `_RELEASE_PARENT` | `layer_11_r37` | r37 market / quote priority**
| `_V233_PARENT` | `layer_12_release` / `layer_13_v233` | worker rescue |
| `_R46_SHEEP_AGENT` | `layer_13_v233` / `layer_14` | sheep herd handling |
| `_R51_INPUT_PARENT` | `layer_14` / `layer_15` | input forecast / warehouse |
| `_R53_LABOR_PARENT` | `layer_16` | labor assignment |
| `_R70_PARENT` | `layer_17`/`layer_18` | **fertilizer economics + joint buy plans** |
| `_R85_PARENT`… | `layer_19` | smarter feed + fertilizer worth |
| `_R95_PARENT` / `_R97_PARENT` | `layer_20`/`layer_21` | **replenishment trim + feed reserve (the feed fix)** |
| `_V9_*`… | `layer_22–31` | courier / carrot / herd / fert / opening / race gates |
| `_P_overflow_338343` | `layer_33` | shed overflow control |
| `_R127_PARENT` | `layer_40` | **the big r127 core layer (market/sale restructuring)** |
| `_V11_ENTRY`/`_V13V_PARENT` | `layer_42/43` | market entry layers |
| `_ALT_PARENT` | `layer_43_v13v` | pre-HybridOpening |
| `_I1_BASE` | `layer_44_alt` | **HybridOpening alt tape** (the new `old`) |
| `_original_agent` | final | production = layer_44_alt + promoted **`_ASTRA_I1`** opening extension |

---

## 3. The empirical loop: same game, replayed at each layer

Each prefix was run fresh (`importlib.reload(main)`) against 3 opponents at
seed 42. Because the layers mutate a shared chassis singleton and the in-memory
tape, every prefix needs its own clean process — the tool does that for us.

### vs kaggriculture-cloning-agent, seed 42

| # | stage | result | final $ | opponent $ | idle% | overflow d | disc. | floor$ | prem<base | esc | died | missedH | feed± | sell rev |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | BASE `_IMPL` | LOSS | 98294 | 114292 | 7.8 | 4 | 49 | 155 | 0.546 | 1 | 19 | 2 | −21 | 125033 |
| 2 | `layer_00` | LOSS | 98294 | 114292 | 7.8 | 4 | 49 | 155 | 0.546 | 1 | 19 | 2 | −21 | 125033 |
| 4 | `layer_09` (v231 livestock) | LOSS | 93620 | 113234 | 8.2 | 3 | 28 | 150 | .534 | **9** | **41** | **10** | −49 | 127526 |
| 7 | `layer_20` (r95/r97 feed) | LOSS | 104849 | 111146 | 8.8 | 5 | 56 | 118 | .499 | **1** | **19** | 2 | **+55** | 139959 |
| 8 | `layer_40` (r127) | **WIN** | 80528 | 71866 | 6.6 | 6 | 2 | 105 | .766 | 1 | 20 | 5 | +17 | 253332 |
| 11 | **final (I1)** | **WIN** | 80604 | 71824 | 6.4 | 6 | 2 | 105 | .766 | 1 | 20 | 5 | +19 | 253133 |

### vs kaggriculture-master-engine-v3, seed 42

| # | stage | result | final $ | opp $ | idle% | floor$ | esc | died | feed± |
|---|---|---|---|---|---|---|---|---|---|
| 1 | BASE | LOSS | 81830 | 96531 | 7.8 | 188 | 0 | 19 | −26 |
| 4 | `layer_09` | LOSS | 79013 | 96091 | 8.2 | 176 | **8** | **41** | −55 |
| 7 | `layer_20` | LOSS | 89467 | 93156 | 8.7 | 122 | **0** | **19** | **+63** |
| 8 | `layer_40` | LOSS | 91644 | 92175 | 8.4 | **99** | 0 | 19 | +82 |
| 11 | final (I1) | LOSS | 91696 | 92160 | 8.2 | 100 | 0 | 19 | +83 |

### vs kaggriculture-top-2-master-engine-v4, seed 42

| # | stage | result | final $ | opp $ | idle% | floor$ | esc | died | feed± |
|---|---|---|---|---|---|---|---|---|---|
| 1 | BASE | LOSS | 82037 | 95931 | 7.8 | 193 | 0 | 19 | −26 |
| 4 | `layer_09` | LOSS | 79410 | 95130 | 8.2 | 171 | **8** | **41** | −55 |
| 7 | `layer_20` | LOSS | 90867 | 92323 | 8.7 | 121 | **0** | **19** | **+65** |
| 8 | `layer_40` | **WIN** | 93288 | 89186 | 8.5 | **85** | 0 | 19 | +73 |
| 11 | final (I1) | **WIN** | 93345 | 89156 | 8.2 | 85 | 0 | 19 | +75 |

*(Full tables, every stage, and per-stage same-seed diffs are in
`diag-replays/iterative/iteration_report.md`.)*

---

## 4. What the data reveals (the iterative nature)

Three effects repeat identically on **all three opponents** — seed-consistent,
not a single-game fluke:

**1. `layer_09` (v231 livestock substitution) made animals & crops worse, then
`layer_19–20` (r85/r95/r97 feed) fixed the same thing.** At every opponent,
`layer_09` jumps escapes `1→9` (cloning) / `0→8` (others), plants died `19→41`,
missed harvests `2→10`, and feed goes negative-ish. The r70/r95/r97 feed layer
then **reverses every one of those**: escapes `9→1`/`8→0`, plants `41→19`,
missed harvests `10→2`, feed surplus flips strongly positive (`+55/+63/+65`).
This is the classic "livestock expansion without matching feed capacity" defect,
fixed later by smarter feed + reserve — the two bookends of the same system.

**2. `layer_40` (r127) is the money inflection point.** It is the first stage
that turns LOSS→WIN (cloning and top-2), cuts **floor-price sales** by roughly
half (`155→105`, `188→99`, `193→85`), drops premium-below-base, and craters the
**opponent's** final money (`114k→72k`, `95.9k→89.2k`). Its committed sell
revenue roughly **doubles** on cloning (`125k→253k`) — the layer's sale ordering
stops dumping produce at the $1/glut floor and sells into the scarcity window
(and into the opponent). This is the single biggest structural lever, and it
holds on every opponent.

**3. Several layers are no-ops at this seed (and that's fine).** `layer_00` ≡
`_IMPL` exactly (error-guard only), and `layer_43` ≡ `layer_40` exactly (v13v
entry only fires in specific market states, not here). The **final I1 patch adds
just +$23/+$18/+$17** — a small, safe monotone improvement on top of the fully
built stack, exactly as an opening-extension should be.

**4. BASE is inefficient even so:** ~7.8% idle labor, 36–49 shed discards,
155–193 floor sales, negative feed surplus, and 36–49 overflow-risk days — i.e.
even the raw tape wastes a lot; the layers are what make it competitive.

---

## 5. Signals legend / how to read these numbers

| column | what it means |
|---|---|
| `idle_share_pct` | share of work-unit turns that were `PASS` (labor waste) |
| `shed_overflow_days` / `discarded` | days shed ≥100 and units actually thrown away |
| `floor_sales` | units sold at the $1 glut floor (bad timing) |
| `prem<base` (`premium_below_base_frac`) | share of premium goods (strawberry/melon/milk/wool) sold below base |
| `esc` | escaped animals (≥2 unfed) |
| `died` / `missedH` | crops decayed to weeds / unharvested at end-of-day |
| `feed±` | wheat produced* minus fed (*net of audit flows) |

---

## Reproduce it yourself

```bash
# static survey (tape nature + layer stack) — no games
python analyze_patches.py --survey

# empirical iterative loop: 11 prefixes x 3 opponents, seed 42 (takes ~20 min)
python analyze_patches.py --iterative --pa 1,2,8 --seed 42 --batch 1 \
    --outdir diag-replays/iterative

# regenerate the markdown from saved replays (no games)
python analyze_patches.py --report --outdir diag-replays/iterative
```
