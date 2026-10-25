# Changelog

Each release of ThermaSched: the cleaning notebook (`data_prep.ipynb`), the solver and batch
notebooks (`solver.ipynb`, `batch.ipynb`) and the site. The notebooks print their release when
they run, every scenario and run records it, and the site shows it in the sidebar and on each
run.

**Re-run** says what to do after replacing the notebooks with a new release:

- **Nothing:** only the site or the documentation changed. Existing runs stay valid.
- **Solver:** the model changed. Solve again the runs you want to compare with new ones; runs
  from the earlier release still open on the site, marked with their release.
- **Cleaning, then solver:** the scenarios changed. Run the cleaning notebook again (its
  section 4 shows which scenarios differ from before), then solve again. The site warns when
  a run was solved on a different scenario build than the one it holds.

## Unreleased

**Re-run:** solver. The notebooks now re-plan per tick by default, which gives other
schedules than the whole-day plan; the whole-day model itself is unchanged.

- The plan going forward is [`docs/PLAN.md`](docs/PLAN.md): per-tick re-planning replaces the
  whole-day solve. Until its runs are in, `results/` is empty: the whole-day runs moved to
  `archive/results_2026-10-25_whole_day/`, the staged 1.2.1 runs (solved on 516 GB servers,
  invalid) to `archive/runs_staging_516GB_invalid/`, and the 1.0.0 run logs to
  `archive/logs_1.0.0/`.
- **Per-tick re-planning** (`--per-tick`, in the notebooks `per_tick=True`, their new default):
  the optimizer re-plans at every 5-minute period with only the workloads that have arrived,
  keeps that period's decisions and moves on, carrying the running workloads, the server
  temperatures and the supply-ramp history from tick to tick. Each tick has its own time limit
  (`--tick-time-limit`, 60 s); the run saves its state after every tick and resumes when run
  again; a tick with no valid schedule stops the run and names the limit. The whole-day plan
  stays available with the switch off.
- The site shows only the four Chapter 6 scenarios. The sidebar lists the pages: the
  Chapter 6 *Overview* (which test has a run in each configuration, and every result in one
  CSV), one page per scenario, 6.1 to 6.4, and *Output files*.
- On each scenario page, pick **10 servers**, **6 servers** or **2 servers** at the top, or
  *Across configurations*. The choice stays the same from page to page and is kept in the
  link (`?config=servers6`). A page shows what its scenario measures: the Base next to each
  test, a chart, per-server figures (utilization, temperature, headroom, DPF) and, for 6.1
  and 6.4, every workload's original and new server and zone.
- *Output files* shows every CSV a run wrote, as it is, with a download for each: pick the
  configuration, the run (named by its test) and the file.
- *Test charts › Charts and key results* brings back the run's charts and key results, for one
  test at a time: pick the configuration, the scenario and the test. Key results (carbon,
  energy, hottest server, lowest headroom, missed deadlines, workloads moved) show their change
  against the Base of the scenario; the solver's outcome, the settings and the self-checks
  follow. The charts of *Servers*, *Cooling*, *Energy and carbon* and *Workloads* (Gantt) draw
  the Base's optimized schedule dashed. The heuristic baseline is no longer drawn.
- When a test ends with the same optimized schedule as its Base (every workload on the same
  server, starting in the same period), the scenario page and *Test charts* say so, so equal
  figures don't look like a mistake.
- 2 servers is one configuration: two mid servers (`results/servers2/`). 6.2 does not apply
  to it (no server with a cold plate).
- A run is matched to its test by its settings, so runs from the batch notebook show under
  their test whatever their folder name.
- Removed from the site: the run picker, the nine Chapter 5 *Tables* (*Output files* has the
  same data), *Inputs*, *Upload results* and *New run*. *Run summary* and the Chapter 5
  *Charts* are now *Test charts*. The *Validation* page is kept in the code but not
  shown. To put a run on the site, send its zip (the notebooks write one) to the project owner.
- The runs kept on the site have short names: `results/servers10/base`, `s1_t1_zones`,
  `s2_t1_crac`, ... and `results/servers6/`. Their `summary.json` still records the name they
  were solved under. The 10-server runs are the 1800 s solves of `thesis10`; 6.4 Test 3b
  (deeper carbon swing) is the 600 s `thesis10_swing` run, and the two 6-server runs are the
  600 s `consolidated6` runs. The five validation runs are `results/servers10/v_*`.
- Every other run (the 600 s solves replaced at 1800 s, `thesis10_tight`, `_warm`, the other
  `_swing` run and the earlier `archive-*` folders) moved to `archive/results_2026-10-25/`.
- New scenarios, built by the cleaning notebook: `servers2` (two 2.4 GHz servers, one per
  zone, no cold plate, 123 workloads: drawn until peak demand is 60% of the fleet, as for
  every scenario), and `consolidated6_swing` and `servers2_swing`, the 6- and 2-server
  fleets with the carbon swing of `thesis10_swing`, for 6.4 Test 3b. The other scenarios are
  unchanged.
- The missing Chapter 6 runs, 6.3 Test 1 on 10 servers, the other 11 tests on 6 servers and
  the 10 tests on 2 servers, are solved with a 600 s time limit. The 10-server runs solved
  at 1800 s are solved again at 600 s, so every Chapter 6 run has the same limit; the 1800 s
  runs move to `archive/`.

## 1.2.1 (2026-10-22)

**Re-run:** nothing. Only the site changed.

- Fix: after the 1.2.0 update the site stopped with `AttributeError: module 'dashboard.state'
  has no attribute 'run_statuses'`. Community Cloud pulls a new release into the running app,
  which kept the previous release's code loaded next to the new page script. The site now
  reloads its own code whenever it changes on disk, so an update no longer needs a reboot.

## 1.2.0 (2026-10-22)

**Re-run:** nothing. The model is unchanged, so runs made with 1.0.0 to 1.1.0 stay valid. The
five new validation runs of `thesis10` are on the site, and the batch notebook lists them if
you want to make them yourself.

- New site page, **Validation**: small, controlled checks of the model, each answering a
  question of the thesis group, with tables you can download. It covers server power at 0, 50
  and 100 % CPU use, server speed and run length (with the examples qh2-rcc165 and qh2-rcc183),
  the same workload on server A or B with idle electricity, moves where a move is needed or
  helps, the CRAC supply temperature at several safety margins, slowdown from heat, the cold
  plates, and how complete each solver result is. It also has the `thesis10` workload table
  for Section 5.2.2: requested CPU cores (vCPU), RAM (GB), arrival, deadline, runtime and
  allowed delay.
- Solver notebook, new section 8: the same checks, made from your own folder
  (`RUN_VALIDATION`). Their tables go to `results/validation/<scenario>/`.
- The solver status is in plain words everywhere: *Proven best*, *Stopped at time limit*
  (with its gap), *No valid schedule (proven)*. The run picker shows it after each run's name.
  The Chapter 6 table gained a *Solve time (s)* column.
- Why no run moves a workload: each run that allows moves starts from the no-move schedule,
  which is proven best, and finds no better one in 30 minutes. It is not proven that none
  exists. With the CRAC fixed at 27 °C (the value every optimized run picks), it is the same:
  stopped at the time limit with no move, gap 1.57 % (moves anywhere) and 1.41 % (same-zone
  moves, down from 26 %). The solver's bound limits what moves could save to about 0.49 kg
  CO2. In the controlled cases, the model moves workloads when a move is needed or helps.
- The CRAC supply temperature is chosen by the solver. It stays at 27 °C, the top of its range
  and the setting with the highest COP, until a server would pass its cap. With H_min = 19 °C
  the solver lowers zone 2 to 18 °C, then 23 °C, at the start of the day. With 20 °C, no
  valid schedule exists.
- Airflow is not modelled, as decided with the thesis group. Fan power stays at zero.
- Batch notebook: five validation runs of `thesis10`: moves (free, same zone, none) with the
  CRAC fixed at 27 °C, and no moves at H_min 18 °C and 19 °C.

## 1.1.0 (2026-10-21)

**Re-run:** solver, but only for the two new runs (6.2 Base and 6.4 Temperature ignored when
choosing servers). Runs made with 1.0.0 and 1.0.1 stay valid: the model only gained a switch,
and its default gives the same results as before. The Chapter 6 runs of `thesis10` have all
been solved again with a 1800 s time limit, the one the flat-carbon run already had, and are on
the site. The earlier 600 s runs stay there too.

- The site shows each Chapter 6 run under its thesis label (for example `6.1 Regrouped
  zones`), with its original run name after it. A run gets its label from its settings, not
  its name, so runs made in the batch notebook or uploaded on the site are labelled too. The
  base run carries three labels: 6.1 Base, 6.3 Base 10 °C safety margin and 6.4 Reassignment
  allowed.
- New page, Chapter 6 results: one row per Chapter 6 run, in section order, with waiting and
  completion times, electricity per source, carbon, temperatures, moved workloads and missed
  deadlines. It downloads as a CSV, with the units in the column headers.
- New 6.2 reference run, **6.2 Base, both cooling systems optimized**: `thesis10` with cold
  plates on, and both the CRAC and the cold plates optimized. Each 6.2 test differs from it in
  one setting. 6.2 changes the CRAC supply air temperature only; airflow is not modelled.
- New setting `placement`, for **6.4 Temperature ignored when choosing servers**. With
  `"thermal_blind"`, a run is solved twice. The first time, server temperature is left out, and
  only the server chosen for each workload is kept. The second time, each workload stays on
  that server, and start times and cooling are solved with every temperature limit. If no
  schedule on those servers stays within the limits, the run says so and names the limits
  that cannot be met. The default, `"thermal_aware"`, works as before.
- Batch notebook: the preset runs carry the Chapter 6 labels, include the two new runs, and
  give every `thesis10` Chapter 6 run a 1800 s time limit.

## 1.0.1 (2026-10-19)

**Re-run:** nothing. Runs made with 1.0.0 stay valid: the scenarios and the model are unchanged.

- The site lists the runs made before release 1.0.0 as `archive-<scenario>` (for example
  `archive-thesis10`), after the current scenarios, so they are never compared with new runs.
- A zip of an archived run holds it under its real scenario name.

## 1.0.0 (2026-10-19)

First release to the thesis group.

**Re-run:** everything, from the raw data: the cleaning notebook, then the solver or batch
notebook.

- Cleaning notebook: builds the main scenario `thesis10`, the experiments `consolidated6`,
  `thesis10_tight`, `thesis10_swing`, `thesis10_warm`, the test scenario `small`, and
  `small_running` (`small` with running workloads and a server outage). It checks the raw file
  sizes and compares every scenario it writes with the reference scenarios of the release.
- Solver notebook: one run, step by step, with a scenario of your own if wanted.
- Batch notebook: a list of runs, unattended, preset to the thesis scenarios; resumes after a
  disconnect and writes one zip for the site.
- Every run records the release, where it was made, and a fingerprint of its scenario. Run
  names hold every switch that differs from its default, so a sweep (for example over
  `H_min_C`) never overwrites its own runs.
