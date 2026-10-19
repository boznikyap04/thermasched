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
└── <scenario>/                 thesis10 (main), or an experiment: consolidated6, thesis10_tight, ...
    └── <run-name>/             any name; shown in the sidebar
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
**Download run (.zip)**, or use **Download all these runs (.zip)** on *Compare runs* for
every run of a scenario. The zip opens on the other person's *Upload results* page, or
can be unzipped directly into `results/`.

### Share runs as zip files

The *Upload results* page (sidebar › *Files*) opens zipped run folders without copying
anything into `results/`. This is meant for people who don't run the model themselves:

1. You run the model, then press **Download run (.zip)** in the sidebar (or zip the run
   folder yourself: right-click › *Compress* on a Mac, *Send to › Compressed (zipped)
   folder* on Windows).
2. You send the zip. They open the dashboard, go to **Upload results** and drop it in.
   Several zips at once, or one zip with many runs, both work.
3. The run is selected in the sidebar (marked 📤) and every page works as usual,
   including *Compare runs* next to the runs in `results/`.

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

In the sidebar, pick a **Scenario** and then a **Run**. A badge shows the solver status:
green for optimal, orange for time limit reached, red for infeasible or no solution.

| Page | What it shows |
|---|---|
| **Overview** | run settings, key results (carbon, energy, temperatures, late workloads) for optimized vs baseline, solver status and gap, self-checks, and the infeasibility diagnosis if there is no solution |
| **Energy & Carbon** | carbon per period against grid carbon intensity, energy by component, cumulative carbon saved, and where the savings came from |
| **Thermal** | temperature heatmap; per server over time: temperature, headroom (with H_min), CPU utilization, IT power and effective processing capability (PC_eff); throttling (DPF) |
| **Cooling** | CRAC supply temperature and cooling load per zone, plus the supply range, ramp and capacity limits. With cold plates: coolant temperature next to the zone's supply air, coolant flow, and the cold-plate limits table. Cold-plate pump energy is on Energy & Carbon |
| **Schedule** | Gantt chart of workloads per server for both schedules. You can filter by type or server, or show only reassigned workloads. The list of moved workloads can be downloaded as CSV |
| **Compliance** | every limit per server, zone, cold plate and workload, plus the reassignment table (original and final zone, cross-zone moves, reason). Red cells break a limit |
| **Compare runs** | every run of one scenario side by side: carbon saved and settings. The table can be downloaded as CSV |

Most charts are interactive. Hover for values, drag to zoom, and double-click to reset.
The browser URL includes the selected run (`?run=<scenario>/<run-name>`), so you can
share a link to it.

**New run (optional):** turn on *Enable New run page* in the sidebar to start a run from
the browser. It writes to `results/` like the command line does. Only one run can solve
at a time, and the page lets you overwrite a run with the same name only if you tick the
confirmation box.

## 4. Keep old results or view another folder

To set old results aside without deleting them, move them into a dated folder under
`archive/`, keeping the same `<scenario>/<run-name>/` structure:

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
2. Repository `boznikyap04/thermasched`, branch `main`, main file path `dashboard/app.py`.
3. Under *Advanced settings*, keep Python 3.12 (the default) or later, then *Save*.
4. Deploy. Community Cloud installs `dashboard/requirements.txt` (it looks next to
   `app.py` before the repository root, so the root `uv.lock` is not used): Streamlit,
   pandas, plotly and numpy only. The theme comes from `.streamlit/config.toml`.

Without the solver installed, the *New run* page is not offered: runs are made with the
notebook or the command line, not on the shared server.

The repository is private, so the app is private too: only you see it until you invite
viewers by email (*Share* at the top right of the app, or *App settings › Sharing*). A
Community Cloud account can have only one private app at a time.

**Add a run for good:**

1. Make the run: `solver.ipynb` (locally or on Colab) writes
   `exports/<scenario>__<run>.zip`; for a command-line run, use the *Download run (.zip)*
   button in the local dashboard.
2. Unzip it into the repository's `results/` folder, so that you get
   `results/<scenario>/<run>/summary.json`, plus `results/<scenario>/servers.csv` and
   `carbon.csv`.
3. Commit and push. Community Cloud redeploys the app with the new run within a few minutes.

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
