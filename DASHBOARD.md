# Viewing results in the dashboard

The dashboard shows every model run saved under `results/`, plus any zipped runs you
upload in the browser (*Upload results* page). It only reads files, except on the
optional *New run* page, which can start a run.

## 1. Start the dashboard

From the repository root (after `uv sync`, see `README.md`):

```sh
uv run streamlit run dashboard/app.py
```

The dashboard opens in your browser at <http://localhost:8501>. Press `Ctrl+C` in the
terminal to stop it.

## 2. Put results in the right folder

The dashboard finds a run only when its `summary.json` is at this location:

```
results/
└── <scenario>/                 small, base or thesis10
    └── <run-name>/             any name; shown in the sidebar
        ├── summary.json        required
        ├── comparison_period.csv
        ├── baseline/
        │   ├── schedule.csv, period.csv, server_period.csv, zone_period.csv
        │   └── compliance_servers.csv, compliance_zones.csv, compliance_workloads.csv
        └── optimized/          same files as baseline/ (missing if there was no optimized schedule)
```

**If you ran the model yourself**, you don't need to do anything.
`uv run python -m scheduler.run ...` (and the *New run* page) writes this structure for
you.

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
  `results/base/my_run/my_run/summary.json`. Move the inner folder up a level.
- **No scenario folder.** Putting the run directly in `results/my_run/` doesn't work.
  It must be inside a scenario folder.
- **Scenario missing from `scenarios/`.** The dashboard reads the server names and the
  clock times from `scenarios/<scenario>/`. If a run comes from a custom scenario,
  copy that scenario's folder into `scenarios/` as well. Otherwise servers show as
  "server 1, 2, ..." and the times may be wrong.

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

To set old results aside without deleting them, move them into a dated folder, keeping
the same `<scenario>/<run-name>/` structure:

```
results_archive/2026-10-13/base/least_loaded_base18_free_optimize/summary.json
```

To view any folder with that structure, point the dashboard at it:

```sh
# macOS / Linux
THERMASCHED_RESULTS_DIR=results_archive/2026-10-13 uv run streamlit run dashboard/app.py
```

```powershell
# Windows PowerShell
$env:THERMASCHED_RESULTS_DIR = "results_archive/2026-10-13"
uv run streamlit run dashboard/app.py
```

If the scenarios are stored somewhere other than `scenarios/`, set
`THERMASCHED_SCENARIOS_DIR` the same way.

## Troubleshooting

| Problem | Fix |
|---|---|
| "No runs found" | Check the folder structure in step 2, then press **Reload results**. Or upload a zip on *Upload results* |
| "No `summary.json` found" after uploading | Zip the run folder itself (the one with `summary.json`), not a folder of loose CSVs |
| A new or copied run doesn't appear | Press **Reload results**. The dashboard caches what it has read |
| Servers show as "server 1, 2, ..." | Add the run's scenario folder to `scenarios/` |
| Optimized charts are empty | The run had no optimized schedule (infeasible, no solution, or `--baseline-only`). The Overview page explains why |
| Port 8501 already in use | Another dashboard is running. Stop it, or add `--server.port 8502` to the command |
