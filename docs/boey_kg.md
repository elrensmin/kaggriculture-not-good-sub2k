# Knowledge graph — v1 (auto)

games: **120**

## Per-day state (medians)

| | d6 | d8 | d10 | d12 | d14 | d16 | d17 | d20 | d24 | d29 |
|---|---|---|---|---|---|---|---|---|---|---|
| animals | 8.5 | 13.0 | 17.0 | 18.0 | 19.0 | 19.0 | 19.0 |  |  |  |
| cow | 4.0 | 6.0 | 7.0 | 7.0 | 7.0 | 7.0 | 7.0 |  |  |  |
| sheep | 2.0 | 3.0 | 3.0 | 4.0 | 5.0 | 5.0 | 5.0 |  |  |  |
| goose | 1.0 | 2.0 | 3.0 | 5.0 | 5.0 | 5.0 | 5.0 |  |  |  |
| wheat_tiles | 1.0 | 7.0 | 17.0 | 24.0 | 24.0 | 22.0 | 21.5 |  |  |  |
| straw_tiles | 4.0 | 16.0 | 20.0 | 24.0 | 28.0 | 29.5 | 29.5 |  |  |  |
| planted | 16.0 | 35.0 | 53.0 | 55.0 | 56.0 | 55.0 | 56.0 |  |  |  |
| empty | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 1.0 | 0.0 |  |  |  |
| structs | 9.0 | 13.0 | 17.0 | 18.0 | 19.0 | 19.0 | 19.0 |  |  |  |
| quadrants | 1.0 | 2.0 | 3.0 | 3.0 | 3.0 | 3.0 | 3.0 |  |  |  |
| money | 99.5 | 111.0 | 504.0 | 14466.5 | 22163.5 | 30528.5 | 37729.0 |  |  |  |
| yarn | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 |  |  |  |

## Actions per day (medians)

| | d6 | d8 | d10 | d12 | d14 | d16 | d17 | d20 | d24 | d29 |
|---|---|---|---|---|---|---|---|---|---|---|
| build_coop | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 |  |  |  |
| build_pasture | 3.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 |  |  |  |
| buy_COW | 1.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 |  |  |  |
| buy_GOOSE | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 |  |  |  |
| buy_SHEEP | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 |  |  |  |
| buy_land | 1.0 | 1.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 |  |  |  |
| buy_wheat | 27.0 | 34.0 | 68.0 | 30.0 | 18.0 | 13.0 | 22.5 |  |  |  |
| fert | 0.0 | 0.0 | 0.5 | 6.0 | 6.0 | 8.0 | 8.0 |  |  |  |
| hire | 9.0 | 10.0 | 11.0 | 11.0 | 11.0 | 11.0 | 11.0 |  |  |  |
| plant_CARROT | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 |  |  |  |
| plant_MELON | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 |  |  |  |
| plant_STRAWBERRY | 8.0 | 1.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 |  |  |  |
| plant_TOMATO | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 |  |  |  |
| plant_WHEAT | 5.0 | 5.0 | 7.0 | 7.0 | 7.0 | 7.0 | 7.0 |  |  |  |

## Induced rules

- **wheat_tiles / (animals+1) → BUY_ANIMAL** (learned) — >= 0.8  
  support 1199, confidence 0.766, lag 0  
  F1 0.643, recall 0.554; median ratio on buy days 0.85, overall 0.93
- **YARN_STORE unlocked → SHEEP/GOOSE target** (learned) — YARN present -> more SHEEP  
  support 59, confidence None, lag 0  
  {'yarn_games': 59, 'no_yarn_games': 61, 'yarn': {'COW': 6, 'SHEEP': 10, 'GOOSE': 3}, 'no_yarn': {'COW': 8, 'SHEEP': 3, 'GOOSE': 5}}

## Herd gate, induced

- best separation: `wheat_tiles >= 0.8 * (animals+1)` (F1 0.643, precision 0.766, recall 0.554)
- buy-day support 1199/1440 game-days
- median ratio (wheat/(animals+1)): **0.93** overall, 0.85 on buy days

## Land buy days (medians)

`{6: 1, 7: 1, 8: 2, 9: 1.0, 10: 1, 11: 1.0, 12: 1.0, 17: 1}`

