"""tools.phases — phased structural development: find the ROOT, not the symptom.

`phase_map` runs the agent in-memory against the public field, truncated at a phase
boundary, and reports the phase's structural metrics against the #1's, then walks a
causal DAG over them to separate root causes from downstream casualties. `--days 0-10`
scopes it to a custom window and `--dag phase1` prints the opening subgraph.

`state_value` prices the state at the phase boundary (cash + shed, plus a model for
crops and herd) and continues the game from there under a frozen policy, so the d5
position gets a low-variance dollar value instead of being judged on the season bank.

`shadow_prices` measures the marginal value of one more unit of each resource by paired
finite difference on `SCRATCH_PARAMS`, reporting the phase objective beside the season
objective so a "paper" improvement is visible as a sign disagreement.

Data lives in `dag.py` (metric registry, the #1's per-day reference and his invariant
d5 state, and the edges).
"""
