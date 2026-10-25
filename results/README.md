# Results

Solver outputs, one folder per run: `results/<configuration>/<test id>/summary.json`, with
`baseline/` and `optimized/` next to it. The site reads every run under this folder.

Per-tick runs only (see [`docs/PLAN.md`](../docs/PLAN.md)). The whole-day results of earlier
releases are in `archive/results_2026-10-25_whole_day/`.

- **First batch (2026-10-26):** 6.1 and 6.2 on six servers, light / normal / heavy day,
  18 runs, solved on GitHub Actions (workflow run 40219903101) with a 60 s cap per tick.
- **Second batch:** 6.3 and 6.4, 21 runs (workflow run 40222465947). 6.4 Test 3b runs on the
  day's `_swing` scenario and is filed here under the day's folder.
