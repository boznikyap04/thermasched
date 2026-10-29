# Results

Solver outputs, one folder per run: `results/<configuration>/<test id>/summary.json`, with
`baseline/` and `optimized/` next to it. The site reads every run under this folder.

Per-tick runs, R840 + C6320 fleet, solved on GitHub Actions with a 60 s cap per tick.
6.4 Test 3b runs on the day's `_swing` scenario and is filed under the day's folder. The
whole-day results of earlier releases are in `archive/results_2026-10-25_whole_day/`.

**6 servers: re-run with cold plates on** (Actions run 40898903689, commit e4ffe45, after
release 1.4.0): all 36 runs, light, normal and heavy, with cold plates on in every test, each
tick's warm start filled by the baseline rule, a tick with no schedule at the 60 s cap solved
again up to 300 s in all, and each tick's solution polished. Their `summary.json` says
`thermasched_version` 1.4.0 although the solver changed after 1.4.0 (a relabel or version
bump is due at the next release). 35 finished and 1 is stuck; every check passed.

- Light day (`servers6_light`): 12 finished, 0-1 ticks at the cap, no tick extended.
  Carbon −13.0 to −13.4 % against the baseline (6.2 Test 2, CRAC fixed: −1.3 %; 6.4 Test 1,
  no moves: −12.2 %).
- Normal day (`servers6`): 12 finished, 0-37 ticks at the cap, 2 ticks extended (6.4 Test 2).
  Carbon −13.4 to −14.5 % (6.2 Test 2: −2.0 %; 6.4 Test 1: −12.2 %).
- Heavy day (`servers6_heavy`): 11 finished, 0-43 ticks at the cap, 14 ticks extended
  (6.1 Test 2: 3, 6.4 Test 2: 9, 6.4 Test 3a: 2); carbon −12.8 to −13.6 % (6.2 Test 2:
  −1.6 %; 6.4 Test 1: −12.2 %). 6.3 Test 1 (H_min 19 °C) is stuck at tick 122: no schedule
  within the 60 s cap, nor in 300 s in all (5 earlier ticks were extended and solved).
  6.4 Test 1, which had no valid schedule at tick 68 in 1.4.0 with cold plates off, now
  finishes the day.
- A few ticks stopped at the cap with almost no bound, so their gap is meaningless (the
  schedule is valid and its carbon checked): 6.2 Test 2 on the normal day (4 ticks, gap up to
  22,579 %) and heavy day (tick 55, 333,771 %), light day (tick 120, 12 %); 6.4 Test 3a,
  normal (tick 119, 20 %) and heavy (22 %).

**Stuck runs are results.** A per-tick run stops at the first tick it cannot plan and keeps
`summary.json` (`per_tick.stuck` names the tick and the limit), `ticks.csv` and
`partial_schedule.csv` (the workloads started before that tick), with no `optimized/` folder.
They are reported as they are, not re-run.

**10 servers: release 1.4.0, waiting for the re-run.** Solved with the code of 1.4.0 before
its version number was set, so their `summary.json` says 1.4.0 with `relabelled_from: 1.3.0`
in its provenance. Only the Base and 6.2 count: of these runs, only the 6.2 runs had cold
plates on. Each day's 6.2 Base, with every other switch at its default, is that day's Base
(its folder `s2_base` was renamed `base`, `renamed_from` in its provenance); 6.2 Tests 1 and
2 stand. The other folders (6.1 Tests 1-2, 6.3, 6.4) hold runs with cold plates off until
they are re-run; the site shows those tests as not run yet. The counts below are of the
1.4.0 batch as it was solved, before the rename. The 1.4.0 6-server batch (Actions run
40693621559: 39 runs, 20 finished, 19 stuck) is replaced by the re-run above.

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
