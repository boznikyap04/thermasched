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

## 1.5.0 (2026-10-30)

**Re-run:** solver. Runs of 1.4.0 with cold plates off are no longer any test's run, and the
per-tick solver changed, so solve again the runs you want to compare with those of 1.5.0.

- **Cold plates are on in every run.** The C6320s carry their cold plate in every test, not
  only in 6.2; until now the Base and every test of 6.1, 6.3 and 6.4 ran with cold plates off,
  so the C6320s were cooled by the CRAC alone. `--cold-plates` is on by default and
  `--no-cold-plates` turns it off; a run with cold plates off gets `_nocp` in its default name.
- **6.2's Base is the shared Base.** With cold plates on everywhere, 6.2 Base (both cooling
  systems optimized) is the same run as the Base, so `s2_base` is gone and a fleet has 36
  runs instead of 39.
- **Every tick starts from a complete set of placements.** A tick's solve starts from the
  previous tick's plan; the workloads that arrived since were left open in it, and on the
  busiest ticks HiGHS could not complete it within 60 s (one 6-server heavy tick needed
  138 s), so the run stopped there. They are now placed by the baseline rule first (arrival
  order, earliest start with room, least loaded server first), and HiGHS chooses the cooling
  for the placements. This uses only arrived workloads, so re-planning still has no
  foresight, and the solver may change any of it. `ticks.csv` gains `warm_start_filled`. Each tick's solution is then polished: with every decision held, the
  continuous values (CRAC heat, coolant temperature) are solved again to their cheapest, so a
  start HiGHS keeps within the gap carries no slack and the solver's carbon still equals the
  evaluator's.
- **A tick with no schedule gets more time.** A tick that has no schedule at the 60 s tick
  limit is solved again, up to 300 s in all (`--tick-no-schedule-limit`); only after that is
  the run stuck. Ticks that have a schedule still stop at 60 s. `ticks.csv` gains `extended`,
  and `summary.json` `per_tick` gains `tick_no_schedule_limit_s` and `n_ticks_extended`.
- **All runs are re-run** with these two changes and cold plates on: 36 per fleet, light,
  normal and heavy. The 6-server runs are in this release; the 10-server runs (the heavy day
  included) follow.
- **10-server results until their re-run:** each day's 1.4.0 6.2 Base run (cold plates on,
  every other switch at its default) is now its Base (`s2_base` renamed `base`); 6.2 Tests 1
  and 2 stand. The runs of 6.1 Tests 1-2, 6.3 and 6.4 had cold plates off, so the site shows
  those tests as not run yet (`results/README.md`).
- **6 servers re-run:** all 36 runs (light, normal, heavy) are re-solved with these changes
  and replace their 1.4.0 runs: 35 finish the day, and 6.3 Test 1 on the heavy day is stuck
  at tick 122 (no schedule within the cap). Every heavy-day run but that one now finishes,
  where all of them were stuck in 1.4.0. They were solved with the code of 1.5.0 before its
  version number was set, so their `summary.json` says 1.5.0 with `relabelled_from: 1.4.0`.
- The slowdown validation check picks a server without a cold plate (an R840), since a plate
  keeps its server below the throttling temperature.

## 1.4.0 (2026-10-29)

**Re-run:** cleaning, then solver. The fleet is new (two server models, new hosts, new tiers),
so the cleaned data, every scenario and every result change. Run the cleaning notebook again
(it needs the second UniMelb file, `UniMelb_C6320.csv`), then solve again; runs of 1.3.0 do not
compare with runs of 1.4.0.

- **New fleet: two server models.** Slow servers are Dell PowerEdge R840 at 2.1 GHz, mid
  servers R840 at 2.4 GHz, both cooled by the CRAC; fast servers are Dell PowerEdge C6320 at
  2.6 GHz (was an R840 at 3.0 GHz), which carry the cold plates and are also cooled by the
  CRAC. The frequencies are assumptions taken from SPEC CPU results for these models (Xeon
  Gold 6130 and Gold 6148 for the R840, Xeon E5-2690 v4 for the C6320); the UniMelb data does
  not name the processors. `servers.csv` gains `model` and `cpu` columns, and each scenario's
  `params.json` lists the assumptions under `assumed_not_from_data`.
- **C6320 data from UniMelb's second dataset** (D2, same Zenodo record, 64 C6320 hosts,
  February to June 2019), cleaned like the R840 data. A C6320 has 80 cores (its hardware
  threads before the cloud doubled its vCPU slots in March 2019, the rule that gives the R840
  its 64) and 193 GB of memory (measured). D2 has no inlet sensor, so each C6320 uses the R840
  room's measured inlet at the same time (mean over the R840 hosts with a valid reading:
  18.8 °C, SD 0.6), an assumption. `qh2-rcc263` and `qh2-rcc264` (another configuration:
  258 GB, 48 / 96 slots) and `qh2-rcc248` (rcc263's power and thermal profile) are left out,
  and C6320 records with more than 160 slots (the doubled slots) are dropped, as for the R840.
  45 R840 and 43 C6320 hosts pass the gates.
- **Hosts drawn by seed.** The servers of each model are drawn from that model's eligible hosts
  with a fixed seed, without regard to power, no host twice in a fleet (the power ranking is
  gone).
- **10 servers are 3 slow / 4 mid / 3 fast** (was 4 / 3 / 3); 6 servers stay 2 / 2 / 2. The
  6.1 Test 1 zone map of 10 servers is (1, 1, 1, 2, …): the slow tier in zone 1.
- **Bigger days.** The light / normal / heavy rule is unchanged (30 / 60 / 85 % of the fleet's
  cores or memory, whichever fills first; memory still fills first), but the fleet has more
  memory, so the days draw more workloads: 6 servers 91 / 257 / 370, 10 servers 199 / 414 / 604
  (with 0 / 77 / 267 repeats of catalogue workloads). The 12 scenarios and `small` /
  `small_running` are rebuilt.
- **Per-tick only.** Every result is re-planned per tick (60 s per tick); the whole-day solver
  is no longer used for results, and `small_running` is tested per tick.
- **Results.** The 6-server fleet: 39 runs, every test of 6.1 to 6.4 on the light, normal and
  heavy day. 20 finished: 12 on the light day, 8 on the normal day. 19 got stuck at a tick and
  are kept as they are, not re-run: a stuck run stops at the first tick it cannot plan, keeps
  its summary, `ticks.csv` and `partial_schedule.csv` (the workloads started before that tick),
  and has no full-day schedule. On the light day 6.4 Test 3a got stuck (tick 128); on the
  normal day 6.1 Test 1 (tick 169), 6.2 Base (138), 6.3 Test 3 (111), 6.4 Test 3a (112) and
  6.4 Test 3b (111); on the heavy day all 13, at ticks 52 to 152. Eighteen of them found no
  schedule for the tick within the 60 s cap, so a schedule may exist (a checked heavy-day tick
  does have one, which takes longer than 60 s to find); 6.4 Test 1 (no moves) on the heavy day
  has no valid schedule at tick 68: with no moves allowed, the deadlines and the servers'
  capacity cannot both be met (relaxing either alone gives a schedule).
  The 10-server fleet, light and normal day: 26 runs, 11 finished, 12 stuck and 3 crashed.
  On the light day 9 finished; the Base, 6.2 Test 2 and 6.3 Test 1 got stuck at tick 125. On
  the normal day 6.4 Test 1 and 6.4 Test 2 finished; the Base and 6.1 Test 1 got stuck at tick
  131, 6.1 Test 2 and 6.3 Test 1 at 71, 6.2 Base, 6.2 Test 1, 6.3 Test 2 and 6.3 Test 3 at 55,
  6.4 Test 3b at 144; all twelve found no schedule within the 60 s cap. Three runs have no
  result: the solver process crashed (segmentation fault) on the GitHub runner at tick 107 of
  6.2 Test 2 (normal day) and at ticks 58 and 112 of 6.4 Test 3a (normal and light day).
  Resumed from their checkpoints, they crashed again at the same tick, while the same tick
  solves on macOS, so the crash is in HiGHS on the Linux runner, not in the model; the site
  lists these three as not run yet. The 10-server heavy day is not run in
  this release. The runs were solved with the code of this release before its version number
  was set, so their `summary.json` was relabelled 1.4.0 and keeps `relabelled_from: 1.3.0`.
  The 1.3.0 results (old fleet) are no longer on the site.
- **Stuck runs on the site.** The overview grid shows a stuck run as *stuck at tick N*, with no
  schedule within the cap or no valid schedule, and a note lists the stuck runs and why; the
  results table and its CSV gain *Stuck at tick* and *Why it got stuck*. The scenario pages
  name each stuck test with its tick and leave it out of the chart and the per-server and
  workload tables. *Test charts* says at which tick (and local time) the run stopped, why, how
  many workloads were waiting and running, what it keeps, and charts the solve time of every
  tick up to the stuck one (in its own colour), with the limits that cause it when no valid
  schedule exists. *Output files* opens a stuck run on its `partial_schedule.csv`. A
  configuration with no run at all says *not run in this release*.
- The site names the server model in its captions and per-server tables, and reads each
  tier's clock from the release instead of a fixed 3000 MHz.

## 1.3.0 (2026-10-26)

**Re-run:** cleaning, then solver. The cleaned data and the scenarios are rebuilt with 64 GB
per server, and the notebooks now re-plan per tick by default, which gives other schedules
than the whole-day plan; the whole-day model itself is unchanged.

- **Per-tick re-planning** (`--per-tick`, in the notebooks `per_tick=True`, their new default):
  the optimizer re-plans at every 5-minute period with only the workloads that have arrived,
  keeps that period's decisions and moves on, carrying the running workloads, the server
  temperatures and the supply-ramp history from tick to tick. Each tick has its own time limit
  (`--tick-time-limit`, 60 s); the run saves its state after every tick and resumes when run
  again; a tick with no valid schedule stops the run and names the limit. The whole-day plan
  stays available with the switch off. The plan behind it is [`docs/PLAN.md`](docs/PLAN.md).
- **64 GB per server.** Each UniMelb host has 64 GB of memory, not 516 GB: `data/clean/` and
  the scenarios are rebuilt with 66,036 MB per server. Workloads on hosts that never report
  usage are kept, with borrowed usage (`usage_imputed`), so the catalogue has 741 workloads;
  the draw stops at the target share of the fleet's cores or memory, whichever fills first,
  and both baseline rules check memory as well as cores.
- **Scenarios.** `scenarios/` holds the six-server fleet on a light, normal and heavy day,
  `servers6_light`, `servers6` and `servers6_heavy` (45, 132 and 210 workloads; peak memory
  34, 60 and 86 % of the fleet), their `_swing` twins with a deeper daily carbon swing (the
  same workloads, amplitude 0.50) for 6.4 Test 3b, and `small` and `small_running`, rebuilt.
  The baseline has no late or unplaced workload in any of them. The 10- and 2-server fleets
  are added when they are run. The earlier 516 GB scenarios (`thesis10`, `thesis10_tight`,
  `_swing`, `_warm`, `consolidated6`, `consolidated6_swing`, `servers2`, `servers2_swing`)
  moved to `archive/scenarios_516GB/`.
- **Results.** `results/` holds the 39 per-tick runs of the six-server fleet: every test of
  6.1 to 6.4 on the light, normal and heavy day, solved on GitHub Actions with a 60 s cap per
  tick. Every run finished with no broken limit and no missed deadline. 6.4 Test 3b ran on
  each day's `_swing` scenario and is filed under the day's folder. The runs were solved with
  the code of this release before its version number was set, so their `summary.json` was
  relabelled 1.3.0 and keeps the original label as `relabelled_from: 1.2.1`, next to the
  commit that solved it. The whole-day runs of 1.2.x moved to
  `archive/results_2026-10-25_whole_day/`, the staged runs on 516 GB servers (invalid) to
  `archive/runs_staging_516GB_invalid/`, and the 1.0.0 run logs to `archive/logs_1.0.0/`.
- The solver notebook starts on `servers6`, and the batch notebook's list is the 39 runs.
- The site shows only the four Chapter 6 scenarios. The sidebar lists the pages: the
  Chapter 6 *Overview* (which test has a run in each configuration, and every result in one
  CSV), one page per scenario, 6.1 to 6.4, and *Output files*.
- On each scenario page, pick **10 servers**, **6 servers** or **2 servers** at the top, or
  *Across configurations*; a first visit opens on the first fleet with runs. The choice
  stays the same from page to page and is kept in the link (`?config=servers6`). A page shows what its scenario measures: the Base next to each
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
- 2 servers is one configuration: two mid servers. 6.2 does not apply to it (no server with
  a cold plate).
- A run is matched to its test by its settings, so runs from the batch notebook show under
  their test whatever their folder name.
- Removed from the site: the run picker, the nine Chapter 5 *Tables* (*Output files* has the
  same data), *Inputs*, *Upload results* and *New run*. *Run summary* and the Chapter 5
  *Charts* are now *Test charts*. The *Validation* page is kept in the code but not
  shown. To put a run on the site, send its zip (the notebooks write one) to the project owner.
- **Per-tick runs on the site.** The solver outcome of a per-tick run reads *Every tick
  solved*, or how many ticks stopped at the cap with the worst tick's MIP gap, instead of
  *proven best* or a whole-day gap. Its test page shows the solve time, the worst tick's gap
  and the ticks at the cap, with a chart of every tick's solve time; the tables show the
  per-tick cap instead of the whole-day time limit.

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
