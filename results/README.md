# Results

Solver outputs, one folder per run: `results/<configuration>/<test id>/summary.json`, with
`baseline/` and `optimized/` next to it. The site reads every run under this folder.

Per-tick runs, R840 + C6320 fleet, solved on GitHub Actions with a 60 s cap per tick.
6.4 Test 3b runs on the day's `_swing` scenario and is filed under the day's folder. The
whole-day results of earlier releases are in `archive/results_2026-10-25_whole_day/`.

**6 servers: release 1.5.0, re-run with cold plates on** (Actions run 40898903689,
commit e4ffe45): all 36 runs, light, normal and heavy, with cold plates on in every test, each
tick's warm start filled by the baseline rule, a tick with no schedule at the 60 s cap solved
again up to 300 s in all, and each tick's solution polished. Their `summary.json` says
`thermasched_version` 1.5.0 with `relabelled_from: 1.4.0` in its provenance: they were solved
with the code of release 1.5.0 before its version number was set. 35 finished and 1 is stuck; every check passed.

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

**10 servers: release 1.5.0, re-run with cold plates on** (Actions run 41441956166, release
1.5.0 code): all 36 runs, light, normal and heavy, solved as the 6-server runs above. Their
`summary.json` says `thermasched_version` 1.5.0, with no relabel: the release's version was
already set. 31 finished and 5 are stuck, all on the heavy day; every check passed. No run
crashed: the HiGHS segmentation faults of the 1.4.0 batch did not come back.

- Light day (`servers10_light`): 12 finished, 0-6 ticks at the cap, no tick extended.
  Carbon −12.6 to −13.2 % against the baseline (6.2 Test 2, CRAC fixed: −0.9 %; 6.4 Test 1,
  no moves: −12.1 %).
- Normal day (`servers10`): 12 finished, 0-25 ticks at the cap, 5 ticks extended (6.1 Test 2:
  1, 6.2 Test 1: 1, 6.4 Test 3b: 3). Carbon −12.7 to −13.3 % (6.2 Test 2: −1.2 %; 6.4 Test 1:
  −12.3 %).
- Heavy day (`servers10_heavy`): 7 finished, 10-53 ticks at the cap, 15 ticks extended;
  carbon −12.1 to −13.3 % (6.2 Test 2: −1.2 %). Stuck:
  - with no schedule within the 60 s cap, nor in 300 s in all: 6.1 Test 1 (regrouped zones)
    at tick 119, 6.3 Test 3 (H_min 5 °C) at tick 139, 6.4 Test 2 (moves chosen without
    temperature) at tick 145 and 6.4 Test 3b (deeper carbon swing) at tick 119;
  - with no valid schedule: 6.4 Test 1 (no moves) at tick 71, where relaxing deadlines and
    allowed waiting, server capacity or priority alone gives a schedule.
- A few ticks stopped at the cap with almost no bound, so their gap is meaningless (the
  schedule is valid and its carbon checked): 6.2 Test 2 on the normal day (tick 96, gap
  2,448,986 %) and heavy day (ticks 84 and 87, up to 366,024 %).

The 1.4.0 10-server batch (Actions runs 40754754068, 40754820788, 40754837540, 40754856946:
26 runs, 11 finished, 12 stuck, 3 crashed, cold plates off outside 6.2, no heavy day) and the
1.4.0 6-server batch (Actions run 40693621559: 39 runs, 20 finished, 19 stuck) are replaced by
the re-runs above.
