# Dashboard: viewing results

The dashboard shows every model run saved under `results/`, plus any zipped runs you
upload in the browser (*Upload results* page). It only reads files, except on the
optional *New run* page, which can start a run.

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
└── <folder>/                   servers10, servers6, servers2_<pair>, or a scenario name
    └── <run-name>/             any name; the site names a Chapter 6 run by its test
        ├── summary.json        required
        ├── comparison_period.csv
        ├── baseline/
        │   ├── schedule.csv, period.csv, server_period.csv, zone_period.csv
        │   └── compliance_servers.csv, compliance_zones.csv, compliance_workloads.csv
        └── optimized/          same files as baseline/ (missing if there was no optimized schedule)
```

**If you ran the model yourself**, you don't need to do anything.
`uv run python -m scheduler.run ...` (see the [solver guide](../scheduler/README.md)) and the
*New run* page write this structure for you.

**If you got results from someone else** (for example a zip of a run made on another
laptop), the easiest way is to open the **Upload results** page and drop the zip there
(see [Share runs as zip files](#share-runs-as-zip-files) below). To keep the run
permanently instead:

1. Find the folder that contains `summary.json`. That is the run folder.
2. Check which scenario it belongs to: its parent folder name, or `"scenario": {"name": ...}`
   at the top of `summary.json`.
3. Copy the whole run folder into `results/<scenario>/`, so that you end up with
   `results/<scenario>/<run-name>/summary.json`. Don't move files out of `baseline/` or
   `optimized/`, and don't rename them.
4. If a run already has the same name, rename the incoming run folder (for example add
   your initials) to keep both. The dashboard shows the folder name as the run name.
5. In the dashboard, press **Reload results** in the sidebar.

**Common mistakes**

- **Extra folder level.** Unzipping often adds one, for example
  `results/consolidated6/my_run/my_run/summary.json`. Move the inner folder up a level.
- **No scenario folder.** Putting the run directly in `results/my_run/` doesn't work.
  It must be inside a scenario folder.
- **Scenario missing from `scenarios/`.** The dashboard reads the server names and the
  clock times from `scenarios/<scenario>/`, else from `servers.csv` and `carbon.csv` in
  `results/<scenario>/`, next to the run folders (where an unzipped run zip puts them). If
  neither has them, servers show as "server 1, 2, ..." and the clock starts at 00:00.

**Sending your results to someone**: pick the run in the sidebar and press
**Download run (.zip)**, or use **Download these runs (.zip)** on the Chapter 6 *Overview* for
every run of the Chapter 6 table. The zip opens on the other person's *Upload results* page,
or can be unzipped directly into `results/`.

### Share runs as zip files

The *Upload results* page (sidebar › *Files*) opens zipped run folders without copying
anything into `results/`. This is meant for people who don't run the model themselves:

1. You run the model, then press **Download run (.zip)** in the sidebar (or zip the run
   folder yourself: right-click › *Compress* on a Mac, *Send to › Compressed (zipped)
   folder* on Windows).
2. You send the zip. They open the dashboard, go to **Upload results** and drop it in.
   Several zips at once, or one zip with many runs, both work.
3. The run is selected in the sidebar (marked 📤) and every page works as usual,
   including the Chapter 6 pages, where an uploaded run takes the place of an older run with
   the same settings.

Good to know:

- Uploads belong to that browser tab only. Other people using the same dashboard don't
  see them, and they are gone when the tab is closed or reloaded.
- Uploading a run again replaces the earlier upload, so a revised run can just be
  re-uploaded. If a run with the same name already exists in `results/`, the upload is
  shown as `<run> (uploaded)` instead of replacing it.
- The zips made by the download buttons include the scenario's `servers.csv` and
  `carbon.csv`, so server names and clock times show correctly even when the other
  dashboard doesn't have that scenario.
- The upload limit is 200 MB per file (a run is about 1 MB). Raise it with
  `--server.maxUploadSize` if needed.

## 3. Use the dashboard

In the sidebar, pick a **Configuration** (2, 6 or 10 servers; for 2 servers, also the
**Server pair**) and then a **Run**. Every configuration goes through the tests of the four
Chapter 6 scenarios (the list is in `scheduler/experiments.py`). A run is matched to its test
by its settings, not its folder name, so a run made in the batch notebook or uploaded here is
named by its test too, for example *6.1 · Test 1 · Same-type servers regrouped into one zone*.
After the tests, the run picker lists the configuration's other runs: the validation runs
(`v_…`) and older solves of a test. *Other* appears when there are runs of another scenario.
A badge shows the solver status in plain words: green for *Proven best*, orange for *Stopped
at time limit* (with its gap), red for *No valid schedule* or *Stopped, no schedule found*.

| Page | What it shows |
|---|---|
| **Chapter 6 › Overview** | which test has a run in each configuration (✅ proven best, ⏱ stopped at the time limit with its gap, · not run yet, n/a not applicable), and every result of every configuration in one table, downloadable as CSV |
| **Chapter 6 › 6.1 to 6.4** | one page per scenario, with its question and goal. *This configuration*: the Base next to each test, one row per measure the scenario asks for (with the change against the Base on request), a chart, per-server figures (utilization, temperature, headroom, DPF, periods slowed) and, for 6.1 and 6.4, every workload's original and new server and zone. *Across configurations*: one measure for every configuration and test, as a table and a chart. Everything downloads as CSV |
| **This run › Run summary** | run settings, what made the run (release, notebook or command line, date, scenario build), the solver status and gap, the headline numbers optimized vs baseline (carbon, energy by component, hottest server, lowest headroom, missed deadlines, workloads moved) and the self-checks. Without a solution, the infeasibility diagnosis. A warning shows if the run was solved on a different build of the scenario than this dashboard holds |
| **This run › Charts** | the graphs of Chapter 5, one section at a time. *Servers*: CPU utilization, predicted temperature, thermal headroom, effective processing capability and IT power, one line per server, then throttling (DPF) and a temperature heatmap. *Cooling*: CRAC supply-air temperature and CRAC energy per zone, and the cold plates' coolant temperature and flow. *Energy and carbon*: energy by component and carbon per period. *Workloads*: the Gantt chart. The optimized schedule is shown; *Compare with baseline* adds the baseline, dashed |
| **This run › Tables** | the tables of Chapter 5, one at a time, each downloadable as CSV: workload schedule, deadlines and waiting, reassignment, server CPU and memory, temperature and headroom, cooling limits, work completion, energy breakdown and carbon per period |
| **More › Validation** | *Model checks*: small, controlled checks of the model (moves, reassignment, the CRAC supply temperature, speed, server A vs B, slowdown, cold plates, server power), each downloadable as CSV; it reads `results/validation/<scenario>/`. *Relationships*: the literature checks of the output plan (for example utilization against IT power, IT power against temperature, headroom against DPF), drawn from the run picked in the sidebar |
| **More › Inputs** | the inputs of a scenario: servers, workloads, carbon intensity per period and the model's parameters, each downloadable as CSV |

Most charts are interactive. Hover for values, drag to zoom, and double-click to reset.
The browser URL includes the selected run (`?run=<folder>/<run-name>`, for example
`?run=servers10/s2_base`), so you can share a link to it.

**New run (optional):** turn on *Enable New run page* in the sidebar to start a run from
the browser. It writes to `results/` like the command line does. Only one run can solve
at a time, and the page lets you overwrite a run with the same name only if you tick the
confirmation box.

## 4. Keep old results or view another folder

**On the site, next to the current runs:** rename the scenario folder under `results/` to
`archive-<scenario>`, for example `results/archive-thesis10/`. Its runs are listed as their
own scenario, after the current ones, and compared only with each other; the sidebar marks
them as archived. They keep reading server names and clock times from the scenario named in
their `summary.json`. The runs made before release 1.0.0 are kept this way.

**Off the site:** to set old results aside without deleting them, move them into a dated folder under
`archive/`, keeping the same `<scenario>/<run-name>/` structure. The runs taken off the site
when the Chapter 6 runs were renamed are in `archive/results_2026-10-25/`:

```
archive/results_2026-10-13/base/least_loaded_base18_free_optimize/summary.json
```

To view any folder with that structure, point the dashboard at it:

```sh
# macOS / Linux
THERMASCHED_RESULTS_DIR=archive/results_2026-10-13 uv run streamlit run dashboard/app.py
```

```powershell
# Windows PowerShell
$env:THERMASCHED_RESULTS_DIR = "archive/results_2026-10-13"
uv run streamlit run dashboard/app.py
```

If the scenarios are stored somewhere other than `scenarios/`, set
`THERMASCHED_SCENARIOS_DIR` the same way.

## 5. Deploy on Streamlit Community Cloud

The deployed dashboard shows the runs committed to `results/`, plus any zip a visitor
uploads (for that browser session only).

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

Without the solver installed, the *New run* page is not offered: runs are made with the
notebook or the command line, not on the shared server.

The repository is private, so the app is private too: only you see it until you invite
viewers by email (*Share* at the top right of the app, or *App settings › Sharing*). A
Community Cloud account can have only one private app at a time.

**Add a run for good** (the thesis group sends you zips for this; they can't commit):

1. Get the zip: `solver.ipynb` writes `exports/<scenario>__<run>.zip`, `batch.ipynb` writes
   `exports/batch.zip`; for a command-line run, use the *Download run (.zip)* button in the
   local dashboard.
2. Unzip it into the repository's `results/` folder, so that you get
   `results/<scenario>/<run>/summary.json`, plus `results/<scenario>/servers.csv` and
   `carbon.csv`.
3. Open it on the local dashboard. If the Overview page warns that it was solved on a
   different scenario build, it isn't comparable with the other runs of that scenario: ask
   which settings or data were used before adding it.
4. Commit and push `main`, then `git push origin main:release`. Community Cloud redeploys the
   app with the new run within a few minutes.

**Show a run for a while:** drop the zip on the deployed dashboard's *Upload results* page.
Nothing is committed and only that browser tab sees it.

## Troubleshooting

| Problem | Fix |
|---|---|
| "No runs found" | Check the folder structure in step 2, then press **Reload results**. Or upload a zip on *Upload results* |
| "No `summary.json` found" after uploading | Zip the run folder itself (the one with `summary.json`), not a folder of loose CSVs |
| A new or copied run doesn't appear | Press **Reload results**. The dashboard caches what it has read |
| Servers show as "server 1, 2, ..." | Add the run's scenario folder to `scenarios/` |
| Optimized charts are empty | The run had no optimized schedule (infeasible, no solution, or `--baseline-only`). The Overview page explains why |
| Port 8501 already in use | Another dashboard is running. Stop it, or add `--server.port 8502` to the command |
| No *Enable New run page* toggle | The solver (`highspy`) is not installed, as on Community Cloud. Run `uv sync` for a local dashboard that can solve |
