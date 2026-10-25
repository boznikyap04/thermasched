# Archive

Superseded material, kept for reference. Nothing in the current pipeline reads it.

| Path | What it is |
|---|---|
| `notebooks/old_notebook.ipynb` | The first, Colab-based data preparation (built around Bitbrains, since dropped). Described in `docs/PROJECT_CONTEXT.md` section 8 |
| `notebooks/before_after_missing_data_fixes.ipynb` | Compares the cleaned data and scenarios before and after the missing-data fixes of 2026-10-10 (`docs/DATA_PREP_REPORT.md` section 10) |
| `data_2026-10-09_before_missing_data_fixes/` | `data/clean/` and `scenarios/` as they were before those fixes |
| `results_2026-10-13/` | Solver runs from 2026-10-13, set aside when the runs now in `results/` were made |
| `results_2026-10-25/` | Every run taken off the site when the Chapter 6 runs were renamed (2026-10-25): the 600 s solves replaced by 1800 s ones, the experiment scenarios (`thesis10_tight`, `_warm`, `_swing`), and the earlier `archive-*` folders. The runs kept on the site moved to `results/servers10/` and `results/servers6/` under short names (since moved to `results_2026-10-25_whole_day/`); their `summary.json` still records the original run name |
| `results_2026-10-25_whole_day/` | The whole-day (perfect-foresight) runs that were in `results/` on 2026-10-25: `servers10/`, `servers6/` and `validation/`, made on 516 GB servers. Set aside when per-tick re-planning became the method (`docs/PLAN.md`) |
| `scenarios_516GB/` | The scenarios built with 516 GB per server, set aside on 2026-10-25 when they were rebuilt with 64 GB (`docs/PLAN.md` §5, item 1): `thesis10` (and `_tight`, `_swing`, `_warm`), `consolidated6` (and `_swing`), `servers2` (and `_swing`). The archived runs were solved on them. `tests/test_validate.py` still reads `thesis10`, the scenario the thesis group's worked examples were posed on |
| `runs_staging_516GB_invalid/` | The 1.2.1 Chapter 6 runs staged for the site, solved on scenarios with 516 GB per server. **Invalid:** the servers have 64 GB. Never on the site |
| `logs_1.0.0/` | Console output and run lists of the 1.0.0 runs, which were at the top of `logs/runs/` |

To view the archived runs in the dashboard, see
[View another folder](../dashboard/README.md#4-view-another-folder).
