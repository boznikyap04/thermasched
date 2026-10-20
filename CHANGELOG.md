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
