# Dashboard: viewing results

The dashboard (the "site") shows the four Chapter 6 scenarios, 6.1 to 6.4, for 10, 6 and 2
servers, each on a light, normal and heavy day (peak demand at 30, 60 and 85 % of the fleet's
cores or memory, whichever fills first), from the runs saved under `results/`: the scenario pages, the charts
and key results of each test against its Base, and every CSV those runs wrote. It only reads
files.

## 1. Start the dashboard

From the repository root (after `uv sync`, see the [main README](../README.md#setup)):

```sh
uv run streamlit run dashboard/app.py
```

The dashboard opens in your browser at <http://localhost:8501>. Press `Ctrl+C` in the
terminal to stop it.

## 2. Put results in the right folder

The dashboard finds a run only when its `summary.json` is at this location:

```
results/
└── <folder>/                   the scenario's name: servers10, servers10_light,
                                servers10_heavy, servers6, ..., servers2_heavy
    └── <run-name>/             any name; the site names a Chapter 6 run by its test
        ├── summary.json        required
        ├── comparison_period.csv
        ├── baseline/
        │   ├── schedule.csv, period.csv, server_period.csv, zone_period.csv
        │   └── compliance_servers.csv, compliance_zones.csv, compliance_workloads.csv, ...
        └── optimized/          same files as baseline/, and reassignment.csv
                                (missing if there was no optimized schedule)
```

A run shows on the site when it was solved on one of the configurations' scenarios: the normal
day of 10 servers is `servers10` (earlier `thesis10`), its light and heavy days
`servers10_light` and `servers10_heavy`, and each has a `_swing` twin for 6.4 Test 3b; the
same for `servers6` (earlier `consolidated6`) and `servers2` (two mid servers). The list is in
`scheduler/experiments.py`. Only the `servers6` scenarios are in `scenarios/` for now; the
others are added when they are run. A run
is matched to its test by its settings, not its folder name, so a run made in the batch
notebook shows under its test too.

**If you ran the model yourself**, you don't need to do anything.
`uv run python -m scheduler.run ...` (see the [solver guide](../scheduler/README.md)) and the
notebooks write this structure for you.

**If you got a zip from the thesis group** (the notebooks write one to `exports/`):

1. Unzip it into `results/`. You get `results/<scenario>/<run>/summary.json`, plus the
   scenario's `servers.csv` and `carbon.csv` next to the run folders.
2. Restart the dashboard, or reload the page.
3. Optionally move the run to `results/<configuration>/<test id>/` to match the others, for
   example `results/servers10_heavy/s3_t1_hmin_high/`. The test ids are in
   `scheduler/experiments.py`.

**Common mistakes**

- **Extra folder level.** Unzipping often adds one, for example
  `results/servers6/my_run/my_run/summary.json`. Move the inner folder up a level.
- **No scenario folder.** Putting the run directly in `results/my_run/` doesn't work.
  It must be inside a folder.
- **Scenario missing from `scenarios/`.** The dashboard reads the server names and the
  clock times from `scenarios/<scenario>/`, else from `servers.csv` and `carbon.csv` in
  `results/<scenario>/`, next to the run folders (where an unzipped run zip puts them). If
  neither has them, servers show as "server 1, 2, ..." and the clock starts at 00:00.

## 3. Use the dashboard

The sidebar lists the pages. On every page but the Overview, pick the configuration at the
top: **10 servers**, **6 servers** or **2 servers**. The choice stays the same when you go to
another page, and the browser URL keeps it (`?config=servers6`), so a link opens the same
view. *Test charts* keeps its scenario, test and topic the same way
(`?section=6.4&test=Test+3b&topic=Workloads`).

| Page | What it shows |
|---|---|
| **Chapter 6 › Overview** | which test has a run in each configuration (✅ proven best, ⏱ stopped at the time limit with its gap, · not run yet, n/a not applicable), and every result of every configuration in one table, downloadable as CSV |
| **Chapter 6 › 6.1 to 6.4** | one page per scenario, with its question and goal. For a configuration: the Base next to each test, one row per measure the scenario asks for (with the change against the Base on request), a chart, per-server figures (utilization, temperature, headroom, DPF, periods slowed) and, for 6.1 and 6.4, every workload's original and new server and zone. *Across configurations*: one measure for every configuration and test, as a table and a chart. Everything downloads as CSV |
| **Test charts › Charts and key results** | one test of one configuration: pick the scenario, then the test (Base, Test 1, ...). It shows the run's settings, its key results (carbon, energy, hottest server, lowest headroom, missed deadlines, workloads moved) with their change against the Base of its scenario, the solver's outcome and the run's self-checks. Then one topic at a time: **Servers** (utilization, temperature, headroom, effective capability, IT power and DPF per server, and a temperature heatmap), **Cooling** (CRAC supply temperature and energy per zone; coolant and flow of the cold plates in 6.2), **Energy and carbon** (energy by component, carbon and carbon intensity per period) and **Workloads** (a Gantt chart with filters). The Base's optimized schedule is drawn dashed; switch it off with *Base dashed*. When a test has the same schedule as the Base, the page says so |
| **Outputs › Output files** | every CSV of a run, as the run wrote it: pick the configuration, the run (named by its test; the validation runs `v_…` and older solves of a test come after) and the file. Each file downloads as it is. A warning shows if the run was solved on a different build of its scenario than the one in `scenarios/` |

6.2 needs a server with a cold plate (a fast, 3000 MHz server), so it does not apply to
2 servers. When several runs match one test, the newest is used.

Every comparison is with the Base test of the same scenario and configuration: 6.2 compares
with its own Base (both cooling systems optimized), 6.1, 6.3 and 6.4 with the shared Base. The
heuristic baseline schedule each run also writes (`baseline/`) is on *Output files* only.
Many tests end with the same optimized schedule as the Base (most runs stop at their time
limit), so their charts look the same; the scenario page and *Test charts* say when that
happens.

Most charts are interactive. Hover for values, drag to zoom, and double-click to reset.

The model checks of `results/validation/` (`dashboard/views/validation.py`) are kept off the
site. To show them again, add their page to the list in `dashboard/app.py`.

## 4. View another folder

To set old results aside without deleting them, move them into a dated folder under
`archive/`, keeping the same `<folder>/<run-name>/` structure. The runs taken off the site
when the Chapter 6 runs were renamed are in `archive/results_2026-10-25/`, and the whole-day
runs set aside for per-tick re-planning ([`docs/PLAN.md`](../docs/PLAN.md)) in
`archive/results_2026-10-25_whole_day/`.

To view any folder with that structure, point the dashboard at it:

```sh
# macOS / Linux
THERMASCHED_RESULTS_DIR=archive/results_2026-10-25 uv run streamlit run dashboard/app.py
```

```powershell
# Windows PowerShell
$env:THERMASCHED_RESULTS_DIR = "archive/results_2026-10-25"
uv run streamlit run dashboard/app.py
```

Only runs of the configurations' scenarios show (see section 2). If the scenarios are stored
somewhere other than `scenarios/`, set `THERMASCHED_SCENARIOS_DIR` the same way.

## 5. Deploy on Streamlit Community Cloud

The deployed dashboard shows the runs committed to `results/`.

**Set up once** (at <https://share.streamlit.io>, signed in with the GitHub account that
owns the repository):

1. *Create app* › *Yup, I have an app*.
2. Repository `boznikyap04/thermasched`, branch **`release`**, main file path
   `dashboard/app.py`. The site follows the release branch, not `main`, so work in progress
   never reaches the thesis group (see
   [Releasing an update](../README.md#releasing-an-update)). If the app already runs from
   `main` and its settings don't offer a branch change, delete it and deploy it again from
   `release`.
3. Under *Advanced settings*, keep Python 3.12 (the default) or later, then *Save*.
4. Deploy. Community Cloud installs `dashboard/requirements.txt` (it looks next to
   `app.py` before the repository root, so the root `uv.lock` is not used): Streamlit,
   pandas, plotly and numpy only. The theme comes from `.streamlit/config.toml`.

The repository is private, so the app is private too: only you see it until you invite
viewers by email (*Share* at the top right of the app, or *App settings › Sharing*). A
Community Cloud account can have only one private app at a time.

**Add a run for good** (the thesis group sends you zips for this; they can't commit):

1. Get the zip: `solver.ipynb` writes `exports/<scenario>__<run>.zip`, `batch.ipynb` writes
   `exports/batch.zip`.
2. Unzip it into the repository's `results/` folder (section 2).
3. Open it on the local dashboard's *Output files* page. If it warns that the run was solved
   on a different scenario build, it isn't comparable with the other runs of that scenario:
   ask which settings or data were used before adding it.
4. Commit and push `main`, then `git push origin main:release`. Community Cloud redeploys the
   app with the new run within a few minutes.

## Troubleshooting

| Problem | Fix |
|---|---|
| A test shows "not run yet" | Check the folder structure in section 2 and that the run's scenario is one of the configurations', then reload the page. The dashboard caches what it has read; a new run folder clears it |
| Servers show as "server 1, 2, ..." | Add the run's scenario folder to `scenarios/` |
| A test's figures show "–" | The run had no optimized schedule (infeasible or no solution). Its status is in the table |
| Port 8501 already in use | Another dashboard is running. Stop it, or add `--server.port 8502` to the command |
