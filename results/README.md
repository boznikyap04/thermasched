# Results

Solver outputs, one folder per run: `results/<configuration>/<test id>/summary.json`, with
`baseline/` and `optimized/` next to it. The site reads every run under this folder.

Per-tick runs only (see [`docs/PLAN.md`](../docs/PLAN.md)). The whole-day results of earlier
releases are in `archive/results_2026-10-25_whole_day/`.

- **First batch (2026-10-26):** 6.1 and 6.2 on six servers, light / normal / heavy day,
  18 runs, solved on GitHub Actions (workflow run 40219903101) with a 60 s cap per tick.
- **Second batch:** 6.3 and 6.4, 21 runs (workflow run 40222465947). 6.4 Test 3b runs on the
  day's `_swing` scenario and is filed here under the day's folder.
- **Third batch (2026-10-26):** ten servers, light / normal / heavy day, 6.1–6.4, 39 runs
  (workflow run 40238528912, 60 s cap; run 40254057648 resumed one run that had crashed at
  tick 58). Four runs stuck at 60 s were re-run at a 120 s cap (run 40254014552): 6.4 Test 2
  and Test 3b on the heavy day finished; 6.4 Test 3a on the normal day (tick 55) and 6.3
  Test 3 on the heavy day (tick 111) got stuck again and are kept as stuck runs, with no
  optimized schedule. Each run's cap is `per_tick.tick_time_limit_s` in its summary.json.
