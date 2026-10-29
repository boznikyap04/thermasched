# Results

Solver outputs, one folder per run: `results/<configuration>/<test id>/summary.json`, with
`baseline/` and `optimized/` next to it. The site reads every run under this folder.

Per-tick runs of release 1.4.0 (R840 + C6320 fleet), solved on GitHub Actions with a 60 s cap
per tick. 6.4 Test 3b runs on the day's `_swing` scenario and is filed under the day's folder.
The runs were solved with the code of 1.4.0 before its version number was set, so their
`summary.json` says 1.4.0 with `relabelled_from: 1.3.0` in its provenance. The whole-day
results of earlier releases are in `archive/results_2026-10-25_whole_day/`.

**Stuck runs are results.** A per-tick run stops at the first tick it cannot plan and keeps
`summary.json` (`per_tick.stuck` names the tick and the limit), `ticks.csv` and
`partial_schedule.csv` (the workloads started before that tick), with no `optimized/` folder.
They are reported as they are, not re-run.

- **6 servers** (Actions run 40693621559): 39 runs, 20 finished and 19 stuck.
  - Light day (`servers6_light`): 12 finished; 6.4 Test 3a stuck at tick 128.
  - Normal day (`servers6`): 8 finished; stuck: 6.1 Test 1 (tick 169), 6.2 Base (138),
    6.3 Test 3 (111), 6.4 Test 3a (112), 6.4 Test 3b (111).
  - Heavy day (`servers6_heavy`): all 13 stuck, at ticks 52 to 152. Twelve found no schedule
    for the tick within the 60 s cap (a schedule may exist); 6.4 Test 1 (no moves) has no valid
    schedule at tick 68: without moves, the waiting workloads cannot meet their deadlines on
    the capacity left (relaxing deadlines or server capacity alone gives a schedule).
- **10 servers**, light and normal day: **[ORCHESTRATOR: fill in when the 26 runs are
  installed: Actions run ids, finished / stuck per day, stuck ticks and limits.]** Until then
  `servers10/` and `servers10_light/` hold the 1.3.0 runs on the old fleet.
- **10 servers, heavy day:** not run in this release.
