"""tools — the Kaggriculture diagnostic toolkit.

  * ``tools.diagnose``  the harness: run the agent, write replays + CSVs,
                        re-diagnose saved replays, render the graph dashboards.
  * ``tools.labour``    wasted turns: movement, idle, missed work, op patterns.
  * ``tools.market``    selling, pricing, demand, discards.
  * ``tools.report``    ours-vs-DSM behavioural map, per-day gap, arm diffs.
  * ``tools.gates``     acceptance gates and paired balance sheets.

Everything under ``tools/`` is read-only analysis: it reads replay JSONs, the
per-day CSVs and ``games.csv``, and prints (or writes) reports. Repo root must be
importable — ``tools.diagnose.config`` puts it on ``sys.path``, and the `Makefile`
and docs use ``PYTHONPATH=.``. See ``tools/readme.md``.
"""
