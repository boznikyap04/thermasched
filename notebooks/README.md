# Notebooks

| Notebook | What it does |
|---|---|
| `data_prep.ipynb` | the cleaning notebook: raw datasets → cleaned tables and scenarios (this guide, sections 1-4) |
| `solver.ipynb` | builds a scenario with your settings (optional), then runs the solver step by step, the same code as `python -m scheduler.run` (see [Solver notebook](#solver-notebook)) |
| `batch.ipynb` | solves a list of runs unattended, preset to the thesis scenarios, and zips them for the site (see [Batch notebook](#batch-notebook)) |

All three notebooks are self-contained: each runs on its own, in the repository or on Google
Colab, with only its data folder. They are what the thesis group gets, with the link to the
site (see [Delivery](../README.md#delivery-to-the-thesis-group)), so none of them points to a
file of the repository or to the command line; `uv run pytest` checks that. Open any of them
in VS Code with the `.venv` kernel, in Jupyter Lab as described in [step 2](#2-run-it), or on
Colab as described in [Google Colab](#google-colab).

Each notebook prints its release (`scheduler/version.py`) when it runs, and every scenario and
run it writes records it.

## Google Colab

Put one project folder on Google Drive, by default `My Drive/thermasched/` (set
`COLAB_DRIVE_FOLDER` in the first code cell of each notebook if it has another name):

```
My Drive/thermasched/
├── data/
│   ├── raw/          UniMelb.csv and UFCG/ (only for data_prep.ipynb, see step 1 below)
│   └── clean/        written by data_prep.ipynb, or copied from the repository
├── scenarios/        written by data_prep.ipynb, or copied from the repository
├── results/          written by solver.ipynb and batch.ipynb
└── exports/          written by solver.ipynb (one zip per run) and batch.ipynb (one zip per list), for the site
```

To only run the solver, copy `scenarios/` and `data/clean/` from the repository into that
folder; the raw data is not needed. Then upload the notebook to Colab (*File › Upload
notebook*) and press *Runtime › Run all*. Colab asks for permission to mount Drive. DuckDB
(cleaning) and HiGHS (solver) are installed on the first run if they are missing; the
other packages come with Colab.

### Where the notebooks' code comes from

The notebooks carry copies of the repository's code, so that they need nothing else:
`data_prep.ipynb` holds `scheduler/build.py` (part 3, the scenario rules) and a release cell
with the version and the fingerprint of every scenario in `scenarios/` (section 4 compares
what it wrote with them); `solver.ipynb` and `batch.ipynb` hold the `scheduler` package and
the parts of `dashboard/` they need (section 0). These cells are generated: edit the files in
the repository, then run

```sh
uv run python tools/sync_notebooks.py
```

`uv run pytest` fails while a notebook is out of date, so a copy cannot silently differ
from the package. After changing how scenarios are built, run `data_prep.ipynb` and then the
sync again, so that the reference fingerprints are those of the new scenarios.

# Cleaning notebook: preparing the data

`data_prep.ipynb` turns the two raw datasets into the cleaned tables in `data/clean/` and
the ready-to-solve scenarios in `scenarios/`:

- **UniMelb** (physical server telemetry) supplies the server parameters: idle and peak
  power, cores, RAM and the fitted thermal response.
- **UFCG** (an OpenStack virtual-machine trace) supplies the workloads: arrival, CPU and
  RAM requests, and work content.

Every cleaning step prints how many rows, servers or VMs it removed, and the same counts
are saved to a cleaning log, so every figure in the thesis can be traced back to a step.
The reasoning behind each step is in the notebook itself and in
[`docs/DATA_PREP_REPORT.md`](../docs/DATA_PREP_REPORT.md).

**You only need this notebook to change the data or the shipped scenarios.** The cleaned
tables and the scenarios it produces are already in the repository, so running the solver
or the dashboard does not need it. To try a scenario with other settings, build it in
[`solver.ipynb`](#solver-notebook) instead: that uses the cleaned tables, not the raw data.

## 1. Get the raw data

The raw files are too large for GitHub (about 8 GB), so they are not in the repository.
Ask the project owner for a copy and place them like this (folder and file names must
match exactly):

```
data/raw/
├── UniMelb.csv              613 MB
└── UFCG/
    ├── servers_usage.csv    1.94 GB
    ├── servers_specs.csv    1.50 GB
    └── flavors.csv          1.5 kB
```

Only these four files (about 4 GB) are read, so share only these. The other UFCG files (`servers_ownerships.csv`,
`user_projects.csv`, `projects_quota*.csv`) can be left in `UFCG/` or skipped. Everything
inside `data/raw/` is ignored by git, so it is never uploaded by accident.

## 2. Run it

Install the environment first (`uv sync` from the repository root, see the
[main README](../README.md#setup)). Then pick one:

- **VS Code:** open `notebooks/data_prep.ipynb`, choose the `.venv` interpreter as the
  kernel (top right), and press **Run All**.
- **Jupyter Lab:** `uv run --with jupyterlab jupyter lab notebooks/data_prep.ipynb`, then
  *Run › Run All Cells*.
- **Command line, no editor:** `uv run jupyter-execute --inplace notebooks/data_prep.ipynb`.
  This runs every cell and saves the outputs into the notebook.

Always run every cell from top to bottom; later cells use results of earlier ones. A
full run takes from a few seconds to about a minute on a laptop. DuckDB is capped at
9 GB of memory; on a smaller machine, lower `memory_limit` in `connect()` (second code
cell).

The notebook finds the repository root on its own when started from the repository or
from `notebooks/`, and on Colab uses the Drive folder (see [Google Colab](#google-colab)).
If the data is somewhere else, set `ROOT` in the first code cell to the folder that
contains `data/raw/`.

## 3. Change a setting

Every threshold and modelling choice is a named value in the first code cell
(**Settings**), with the reason beside it. To test a different choice, change the value
and run all cells again. The main groups:

| Group | Examples | Affects |
|---|---|---|
| `cfg["paths"]` | where the raw files are, where outputs go | file locations only |
| `cfg["servers"]` | core-count regime, failed-sensor values, eligibility gates | `data/clean/servers.csv` |
| `cfg["workloads"]` | slot length, dropped flavors, coverage and gap-filling limits, `impute_unmonitored` | `data/clean/workloads.csv`, `workload_usage.parquet` |
| `servers10`, `fleets`, `levels` and `cfg["scenario"]` | the reference settings (fleet, horizon, load target, deadline slack, carbon intensity), then each scenario's changes to them | `scenarios/servers6_light`, `servers6`, `servers6_heavy` and `small` |
| `cfg["scenario_constants"]` | constants changed for one scenario only (none as shipped) | that scenario's `params.json` |
| `cfg["constants"]`, `cfg["cold_plate"]` | thesis constants, cold-plate resistance table | each scenario's `params.json` |

## 4. What it writes

| Part | Reads | Writes |
|---|---|---|
| 1. Servers | `data/raw/UniMelb.csv` (R840), `data/raw/UniMelb_C6320.csv` (C6320) | `data/clean/servers.csv`, `cleaning_log_servers.csv` |
| 2. Workloads | `data/raw/UFCG/servers_usage.csv`, `servers_specs.csv`, `flavors.csv` | `data/clean/workloads.csv`, `workload_usage.parquet`, `cleaning_log_workloads.csv` |
| 3. Model inputs | the two cleaned tables | `scenarios/servers6_light/`, `servers6/`, `servers6_heavy/` and `small/`, by the rules in `scheduler/build.py` |
| 4. Checks | all outputs | nothing; every assertion must pass |

Every scenario is the reference settings (`servers10`, the ten-server data center the
thesis describes) with some values changed, recorded under `variant_of` in its
`params.json`: `servers6` has six servers, and its light and heavy days a lower or higher
load target. The 10- and 2-server fleets are one line each in `fleets`, added when they are
run. Section 3 of the notebook has a table of what each one
changes and which question it answers. Section 5 describes every output column. Each scenario folder gets
`servers.csv`, `workloads.csv`, `carbon.csv`, `baseline_schedule.csv` and `params.json`.
`scenarios/small_running/` is made from `small` rather than from the cleaned tables: five
workloads already running at the start and server 3 down for an hour, written to an extra
`availability.csv` (`cfg["running_variants"]`; see the
[solver guide](../scheduler/README.md#2-scenarios)).

Section 4 ends with a fingerprint of each scenario next to the one in the release. With the
settings unchanged and the same raw files, every scenario is **same**. Each raw file's size is
also compared with the reference copy at the start.

**Re-running overwrites those files.** With the settings unchanged, the outputs match
the ones in the repository (a few values in `data/clean/workloads.csv` can differ in the
last decimal place, from DuckDB's parallel sums; the scenarios come out identical). If
you change a setting:

- the existing runs in `results/` were solved on the old scenarios, so re-run the solver
  before comparing;
- `uv run pytest` checks some numbers of the current scenarios and will report the
  change. To experiment without touching the shared scenarios, change
  `cfg["paths"]["scenarios"]` (and `"clean"`) to a new folder first.

## Troubleshooting

| Problem | Fix |
|---|---|
| `FileNotFoundError: raw data not found` | The message lists the missing files. Check the layout in step 1, or set `ROOT` |
| `ModuleNotFoundError: duckdb` | The kernel is not the project's `.venv`. Select it in VS Code, or run `uv sync` |
| Out of memory / very slow | Lower `memory_limit` and `threads` in `connect()` |
| An assertion fails in part 4 | A setting produced inconsistent inputs (for example a deadline past the horizon). The message says which check |

# Solver notebook

`solver.ipynb` runs one baseline-vs-optimized comparison in steps: load the scenario, build
the baseline, solve the MILP, score both schedules with the evaluator, run the checks, and
compare them in tables and charts. It carries a copy of the `scheduler` package (section 0,
see [above](#where-the-notebooks-code-comes-from)), so it gives the same numbers as
`uv run python -m scheduler.run` with the same switches. It needs `scenarios/` (and
`data/clean/` to build scenarios), not the raw data. On Colab, see
[Google Colab](#google-colab).

- **Scenario:** the first code cell starts with `SCENARIO`, the folder to solve; it is
  `servers6`, the six-server fleet on a normal day, by default. To build a new experiment first, set `SCENARIO`
  to a new name and `BUILD_FROM` to an existing scenario (normally `"servers6"`), then uncomment and edit values in `SCENARIO_CHANGES`, `CONSTANT_CHANGES` and
  `COLD_PLATE_CHANGES`. Every key is listed there with what it does. Section 1 writes
  `scenarios/<SCENARIO>/` and shows what changed and the new scenario's figures beside the
  starting one's (size, load, thermal caps, baseline carbon). Running again rebuilds it. The
  shipped scenarios are never overwritten, and `small_running` cannot be a starting point.
  The command line and the dashboard can use a built scenario like any other.
- **Settings:** the same cell then holds `RUN`, every switch of a run (the fields of
  `RunSettings`, with the same names as the
  [command-line options](../scheduler/README.md#3-run-options)), plus a few notebook options.
  Change them and run all cells again.
- **Run time:** the settings are the command-line defaults, so the solve runs for the full
  10-minute time limit (on `servers6` as on `small`). With `reassignment="none"`, a run takes a few seconds.
- **Output:** the run is written to `results/<scenario>/nb_<run name>/`, in the same layout as
  a command-line run, and the local dashboard shows it. The name holds every switch that
  differs from its default, so a sweep over one switch (for example `H_min_C`) gives one
  folder per value. The `nb_` prefix keeps it from overwriting a command-line run. Set
  `WRITE_RESULTS = False` to write nothing.
- **Zip for the dashboard:** the run is also zipped to `exports/<scenario>__<run name>.zip`,
  together with its scenario's `servers.csv` and `carbon.csv` (on Colab the zip is also
  downloaded; `DOWNLOAD_ZIP = False` turns that off). To put it on the deployed site, the
  group sends the zip to the project owner, who adds it (see
  [Adding a run the group sent](../README.md#releasing-an-update)).
- **Checks:** the last cell fails if any check failed, as the command line exits with an
  error.
- **Validation checks:** section 8 runs the model checks on
  `VALIDATION_SCENARIO` (`servers6`) when `RUN_VALIDATION = True`, the default. They take about a
  minute, write `results/validation/<scenario>/`, and fail the cell if a check fails. The same
  tables come from `uv run python -m scheduler.validate --scenario servers6`.
- **Command line, no editor:** `uv run jupyter-execute --inplace notebooks/solver.ipynb`.
- **Release:** the first lines printed name the release. The run records it, with a
  fingerprint of its scenario, in `summary.json` (`provenance`), and the site shows both.

# Batch notebook

`batch.ipynb` solves a list of runs one after another with the same code as `solver.ipynb`,
and zips every run of the list for the site. It is meant for producing a set of results
unattended, on Colab or a laptop.

- **The list:** `RUNS` in the first code cell, one entry per run: a label and the switches that
  differ from their defaults (the fields of `RunSettings`, as in `solver.ipynb`). It comes set
  to the first set of thesis runs: the six tests of 6.1 and 6.2 (the switches of
  [section 5 of the solver guide](../scheduler/README.md#5-thesis-scenarios-ch-6)) on
  `servers6_light`, `servers6` and `servers6_heavy`, labelled as on the site, each with a
  1800 s time limit: 18 runs and up to nine hours.
  `DEFAULTS` applies switches to every run, for example a longer time limit.
- **Plan first:** section 1 validates every entry, checks that its scenario exists and that no
  two entries are the same run, and prints the plan with an upper bound on the time, before
  anything is solved.
- **Resuming:** each run is written as soon as it finishes. Running the notebook again skips
  the runs already in `results/` from the same release and scenario build (`SKIP_DONE`), so
  after a Colab disconnect it picks up where it stopped. A run from another release or
  scenario build is solved again.
- **Errors:** a run that fails is reported and the list goes on; the last cell fails if any run
  had an error or a failed check.
- **Output:** `results/<scenario>/nb_<run name>/` per run, named as in `solver.ipynb`, and
  `exports/<ZIP_NAME>.zip` (`batch.zip`) with every run of the list, downloaded on Colab.
