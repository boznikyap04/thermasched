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
- **10 servers** (Actions runs 40754754068, 40754820788, 40754837540, 40754856946): 26 runs,
  11 finished, 12 stuck, 3 crashed. All twelve stuck runs found no schedule for the tick
  within the 60 s cap.
  - Light day (`servers10_light`): 9 finished; stuck: the Base, 6.2 Test 2 and 6.3 Test 1
    (all at tick 125); crashed: 6.4 Test 3a (tick 112).
  - Normal day (`servers10`): 6.4 Test 1 and 6.4 Test 2 finished; stuck: the Base (tick 131),
    6.1 Test 1 (131), 6.1 Test 2 (71), 6.2 Base (55), 6.2 Test 1 (55), 6.3 Test 1 (71),
    6.3 Test 2 (55), 6.3 Test 3 (55), 6.4 Test 3b (144); crashed: 6.2 Test 2 (tick 107) and
    6.4 Test 3a (tick 58).
  - The three crashed runs have no folder here. The solver process died with a segmentation
    fault (exit code 139) on the GitHub runner; resumed from their checkpoints (Actions runs
    40821776650 and 40821779530) they crashed again at the same tick, which solves on macOS,
    so the fault is in HiGHS 1.15.1 on the Linux runner, not in the model.
- **10 servers, heavy day:** not run in this release.
