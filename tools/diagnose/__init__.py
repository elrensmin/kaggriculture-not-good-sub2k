"""tools.diagnose — the Kaggriculture diagnostic harness.

Run it with ``python -m tools.diagnose`` (or ``make scratch``). It does exactly
three things: run the agent under test over a batch of public opponents in
parallel, re-diagnose saved replays (``--replay-dir``), and render the graph
dashboards (``--graph`` / ``--animals``).

The submodules are imported in dependency order (config -> games -> analysis ->
render/report -> parallel -> cli), so this package can be ``import``-ed without a
cycle and the common names below are re-exported for the analysis tools.

The agent under test is the ``src`` package — there is no route tape, no
``main.py`` chassis and no patch layer.
"""
from __future__ import annotations

# Submodules, in dependency order.
from . import config as config
from . import agents
from . import games
from . import analysis
from . import render
from . import report
from . import runbook
from . import plot
from . import parallel
from . import cli as cli

from .config import (
    ANIMALS,
    CROPS,
    MARKET_PARAMS,
    PRICE_FLOOR,
    PRODUCTS,
    SHOPS,
    EPISODE_STEPS,
    TURNS_PER_DAY,
    SHED_CAPACITY,
    TEST_SEAT,
    PUBLIC_AGENT_MAP,
    REPLAY_ROOT,
    _GATED_WASTE,
    _SHED_ACCESS,
    _SPIKEY_PRODUCTS,
    _SHOP_TITLE,
)
from .agents import (
    _refresh_public_agent_map,
    public_agent_names,
    load_public_agent,
    load_agent,
)
from .games import run_game, save_replay, load_replay, _NoOpContext, _MarketAudit
from .analysis import (
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
from .render import render, render_map, render_legend, render_day
from .report import print_game_table, write_run_csv
from .runbook import (
    _new_run_dir,
    _most_recent_run_dir,
    _parse_pa_arg,
    _make_seeds,
)
from .parallel import (
    run_parallel_tasks,
    run_labeled_batch,
    _batch_exec_worker,
    _get_agent,
)
from .plot import (
    graph_batch,
    plot_animal_care_payback,
)
from .cli import cli

__all__ = [
    "config", "agents", "games", "analysis", "render", "report", "runbook",
    "plot", "parallel", "cli",
    # config
    "ANIMALS", "CROPS", "MARKET_PARAMS", "PRICE_FLOOR", "PRODUCTS", "SHOPS",
    "EPISODE_STEPS", "TURNS_PER_DAY", "SHED_CAPACITY", "TEST_SEAT",
    "PUBLIC_AGENT_MAP", "REPLAY_ROOT", "_GATED_WASTE", "_SHED_ACCESS",
    "_SPIKEY_PRODUCTS", "_SHOP_TITLE",
    # agents
    "_refresh_public_agent_map", "public_agent_names", "load_public_agent",
    "load_agent",
    # games
    "run_game", "save_replay", "load_replay", "_NoOpContext", "_MarketAudit",
    # analysis
    "build_frames", "build_days", "summarize", "replay_to_record",
    "replay_to_summary", "game_summary", "_day_columns", "_game_columns",
    "_agent_seat", "_dist_to_shed", "_near_shed_stats", "_flatten",
    # render / report
    "render", "render_map", "render_legend", "render_day",
    "print_game_table", "write_run_csv",
    # runbook / parallel
    "_new_run_dir", "_most_recent_run_dir", "_parse_pa_arg", "_make_seeds",
    "run_parallel_tasks", "run_labeled_batch", "_batch_exec_worker", "_get_agent",
    # plot / cli
    "graph_batch", "plot_animal_care_payback", "cli",
]
