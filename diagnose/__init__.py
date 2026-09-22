"""diagnose — Kaggriculture diagnostic / A-B test harness (package).

This package replaces the former single-file ``diagnose.py``. It is split into
focused modules under :data:`diagnose`:

- ``config``      shared constants, engine tables, cross-module state
- ``agents``      public-agent loading + the old/new main.py pair
- ``games``       episode runner, market audit, replay persistence
- ``analysis``    replay -> frames/days -> per-game summaries
- ``render``      terminal board / day report printout
- ``report``      CSV writers, per-game table, narrative summaries
- ``runbook``     run-dir / seed / --pa bookkeeping
- ``paired``      same-seed A/B delta report + wins-not-money verdict
- ``parallel``    fork-based parallel game-batch execution
- ``batch``       serial run + old/new compare wrappers
- ``grid``        --grid param-space sweep over agent.py E1_PARAMS
- ``xray``        per-step patch() investigation
- ``plot``        matplotlib dashboards / GIFs / payback chart
- ``cli``         argparse entry point (``python -m diagnose``)

Imports below follow the module dependency order (each module only imports
from ones listed earlier, so there are no cycles). Public names are re-exported
so ``import diagnose; diagnose.game_summary(...)`` keeps working unchanged.
"""
from diagnose import config as config

from diagnose import agents
from diagnose import games
from diagnose import analysis
from diagnose import render
from diagnose import report
from diagnose import runbook
from diagnose import paired
from diagnose import parallel
from diagnose import batch
from diagnose import grid
from diagnose import xray
from diagnose import plot
from diagnose import cli as cli

# ---- re-export the public surface that callers used from the monolithic module
from diagnose.config import (
    EPISODE_STEPS,
    TURNS_PER_DAY,
    SHED_CAPACITY,
    TEST_SEAT,
    PUBLIC_AGENTS_DIR,
    REPLAY_ROOT,
    PUBLIC_AGENT_MAP,
    PRODUCTS,
    MARKET_PARAMS,
    SHOPS,
    CROPS,
    ANIMALS,
    PRICE_FLOOR,
    _SPIKEY_PRODUCTS,
    _SHOP_TITLE,
    _E1_DEFAULT,
    _E1_GUARDS,
)
from diagnose.agents import (
    _refresh_public_agent_map,
    public_agent_names,
    load_public_agent,
    load_old_agent,
    load_new_agent,
    load_old_and_new,
    _tape_module,
)
from diagnose.games import run_game, save_replay, load_replay, _NoOpContext, _MarketAudit
from diagnose.analysis import (
    build_frames,
    build_days,
    summarize,
    replay_to_record,
    replay_to_summary,
    game_summary,
    _day_columns,
    _game_columns,
    _agent_seat,
    _dist_to_shed,
    _near_shed_stats,
    _flatten,
)
from diagnose.render import render, render_map, render_legend, render_day
from diagnose.report import print_game_table, narrative_summary, write_run_csv
from diagnose.runbook import (
    _new_run_dir,
    _most_recent_run_dir,
    _parse_pa_arg,
    _make_seeds,
)
from diagnose.paired import ab_delta_report, _paired_verdict, _money_curve
from diagnose.parallel import (
    run_parallel_tasks,
    run_labeled_batch,
    _batch_exec_worker,
    _get_agent_pair,
)
from diagnose.batch import batch_run, compare_batch
from diagnose.grid import grid_search, _parse_param_space, _paired_deltas
from diagnose.xray import xray_game, xray_report, xray_batch, env_to_replay
from diagnose.plot import (
    plot_game,
    graph_batch,
    plot_board,
    plot_board_gif,
    plot_animal_care_payback,
)
from diagnose.cli import cli

__all__ = [
    "EPISODE_STEPS", "TURNS_PER_DAY", "SHED_CAPACITY", "TEST_SEAT",
    "PUBLIC_AGENTS_DIR", "REPLAY_ROOT", "PUBLIC_AGENT_MAP",
    "PRODUCTS", "MARKET_PARAMS", "SHOPS", "CROPS", "ANIMALS", "PRICE_FLOOR",
    "public_agent_names", "load_public_agent", "load_old_agent", "load_new_agent",
    "load_old_and_new",
    "run_game", "save_replay", "load_replay",
    "build_frames", "build_days", "summarize", "replay_to_record",
    "replay_to_summary", "game_summary",
    "render", "render_map", "render_legend", "render_day",
    "print_game_table", "narrative_summary", "write_run_csv",
    "ab_delta_report",
    "run_parallel_tasks", "run_labeled_batch",
    "batch_run", "compare_batch",
    "grid_search",
    "xray_game", "xray_report", "xray_batch", "env_to_replay",
    "plot_game", "graph_batch", "plot_board", "plot_board_gif",
    "plot_animal_care_payback",
    "cli",
]
