# Plan: per-tick re-planning

The basis for the work from 2026-10-25 on. It records what was decided, why, and what is
left to do. Where it differs from `PRD.md` or `PRD_CH6_RESULTS.md`, this file wins.

**Status (2026-10-25):** decided; work item 1 done (the 64 GB `servers6` scenarios). Nothing is built, nothing is solved, and
nothing is deployed until the project owner says go. The deployed site stays as it is
(release 1.2.1) until the per-tick results replace it.

---

## 1. Why the plan changed

Until now the optimizer has made **one plan for the whole day**: a single MILP over all 288
five-minute periods, solved once, with every workload's arrival and the carbon intensity of
every period known in advance (perfect foresight). This was checked on `small`:

- one HiGHS solve per optimization (9,265 columns, 10,039 rows, solved to optimality);
- lowering carbon intensity only after period 72 changed the start of 34 workloads that had
  started before period 72. A scheduler working in real time could not do that.

The thesis describes something else. Ch. I §1.3 and Ch. IV call the model a "rolling
multi-period horizon", re-solved at each scheduling interval with carried-over state, and the
T⁰ table note says the initial temperature is "updated for each run". The assumptions say the
same (numbering of `PROJECT_CONTEXT.md` §1.4):

- **5.** scheduling, assignment, server states and cooling decisions are updated each interval;
- **6.** the end-of-interval state (running workloads, thermal conditions, queued workloads)
  carries forward as the next interval's initial state;
- **10.** the grid emission factor is time-varying and known for every interval.

How often to re-solve, over what window and what carries over was never specified
(`PROJECT_CONTEXT.md` §7, E5). This plan fills that gap.

## 2. The method: per-tick re-planning, option 2A

At every tick (one 5-minute period) *t*:

1. **What the model sees.** Workloads that have arrived and not yet started; workloads
   already running, with their server and start fixed; each server's temperature at the end
   of the previous tick; the recent supply-air temperatures; the carbon intensity of every
   remaining period.
2. **What it does not see.** Workloads that arrive after *t*.
3. **Lookahead.** From *t* to the end of the planning horizon, using the known carbon
   intensity of every remaining period (assumption 10). Planning only up to the latest
   deadline among the waiting workloads gives the same decisions, because nothing known can
   run after it; it may be used as a speed-up only.
4. **What it keeps.** Only the decisions for period *t*: which workloads start now, on which
   server, the supply-air temperature of each zone and the cold-plate settings. The rest of
   the plan is discarded.
5. **Next tick.** Time moves to *t* + 1, new arrivals join, and the model solves again.

The kept decisions of all 288 ticks form the day's schedule, which the independent
evaluator scores exactly as it scores any schedule today.

| Setting | Decision |
|---|---|
| How often it re-plans | every tick (5 min); hourly re-planning is not used |
| Future workloads | unknown until they arrive |
| Carbon intensity | the true curve, known for every period (choice A); no forecast error |
| A tick with no valid schedule | the run stops and reports which limit caused it; every limit stays hard, no fallback |
| The whole-day solve | not used for results, not even as a benchmark; the same MILP is the solver inside each tick |
| Baseline | unchanged: the greedy arrival-order rule, which also has no foresight |

**Accepted consequences.**

- With no whole-day benchmark, the thesis cannot state how close per-tick gets to the best
  possible schedule.
- A run that gets stuck at a tick has no result. Heavy days are the most likely to.
- Per-tick is slower than one solve: 288 solves in sequence per run.
- The comparison with the baseline is like for like: neither knows future workloads.

## 3. First batch: 18 runs

Six servers (2 slow, 2 mid, 2 fast) with 64 GB per server, on the light, normal and heavy day
(peak demand 30 / 60 / 85 % of the fleet's cores or memory, whichever fills first), sections
6.1 and 6.2.

| # | Section | Test | Light | Normal | Heavy |
|---|---|---|---|---|---|
| 1–3 | 6.1 | Base | ✓ | ✓ | ✓ |
| 4–6 | 6.1 | T1: same-type servers regrouped into one zone | ✓ | ✓ | ✓ |
| 7–9 | 6.1 | T2: moves only within the original zone | ✓ | ✓ | ✓ |
| 10–12 | 6.2 | Base: both cooling systems optimized | ✓ | ✓ | ✓ |
| 13–15 | 6.2 | T1: CRAC changed, cold plates fixed | ✓ | ✓ | ✓ |
| 16–18 | 6.2 | T2: cold plates changed, CRAC fixed | ✓ | ✓ | ✓ |

**Not in this batch:** the 10- and 2-server fleets, sections 6.3 and 6.4, and the validation
runs. They follow once the first batch works.

## 4. Where it runs: GitHub Actions

The repository is public, so GitHub-hosted runners are free: up to 20 jobs at once, 4 cores
and 16 GB per machine, 6 hours per job. The 18 runs go as 18 parallel jobs, so the batch
takes about as long as its slowest run. Each job uploads its run folder; the folders are
downloaded as a zip and unzipped into `results/`.

- **Time estimate (not measured):** 25–100 minutes per run, heavy days slowest; about 1–2 h
  for the batch.
- **Safety nets:** the per-tick mode saves its state after every tick, so a job stopped at
  6 hours can resume; one heavy run is timed first to set the per-tick solve-time cap.
- **Visibility:** workflow logs and run artifacts of a public repository are public. The
  results are meant for the public site anyway; the thesis PDFs are never in the repository.

## 5. Work items, in order

1. **Rebuild the 6-server scenarios with 64 GB per server** (`servers6_light`, `servers6`,
   `servers6_heavy`): memory 66,036 MB per server, the draw stops at the target share of
   cores or memory, the baseline rules check memory. Commit them; the runners see only what
   is in the repository. Only these three are rebuilt; the 10- and 2-server fleets wait until
   they are run.
   **Done (2026-10-25).** `data/clean/` rebuilt at 64 GB; `servers6_light`, `servers6`,
   `servers6_heavy` have 45 / 132 / 210 workloads, peak memory 33.6 / 60.5 / 86.3 % and peak
   cores 16.9 / 30.5 / 43.5 % of the fleet, and a baseline with 0 late and 0 unplaced, within
   every server's cores and 66,036 MB. `small` and `small_running` are rebuilt the same way
   (79 workloads; 5 running at the start). The old 516 GB scenarios moved to
   `archive/scenarios_516GB/`; the build test covers the new ones. The data-prep notebook
   builds only these scenarios; the solver notebook starts on `servers6`, and the batch
   notebook's list is the 18 runs of §3 (whole-day until the per-tick switch exists).
2. **Build the per-tick mode** (estimate 2–4 days):
   - the loop over ticks: build the window's problem, solve, keep period *t*, advance;
   - only arrived, not-yet-started workloads are free; arrival, deadline and allowed delay are
     measured from the window's start;
   - running workloads keep their server (Eq. 29, supported) **and their start**, and only
     their remaining work counts (work credit, Eq. 38–39); today a running workload's start
     can still move;
   - starting temperatures T⁰ from the previous tick (Eq. 30, supported);
   - recent supply-air temperatures as fixed history, so the ramp limits (Eq. 35–36, 15 min
     and 1 h) hold across ticks;
   - priority (Eq. 56–57) with started workloads fixed;
   - a per-tick solve-time cap, and the state saved after every tick so a run can resume;
   - a run switch for the mode, its log per tick (status, solve time) in the run folder, and
     the copies in the solver and batch notebooks (`tools/sync_notebooks.py`).
   - tests on `small`: the evaluator accepts every per-tick schedule; no workload starts
     before it arrives and no started workload moves; a run resumed from its checkpoint gives
     the same schedule as an unbroken run; a stuck tick stops and names the limit.
3. **Time one heavy-day run** on this machine (6.1 Base, `servers6_heavy`) and set the
   per-tick cap from it with margin; the first Actions job confirms it on the 4-core runner.
4. **Add the GitHub Actions workflow** for the 18 jobs: a matrix of 18, resume from the
   checkpoint, upload each run folder. It starts on a push to a dedicated runs branch, so
   `main` and `release` are not touched.
5. **Push and start it.** This is the first step that publishes anything, and it needs the
   project owner's go.
6. **Put the results into `results/`** and check them on the local site.
7. **Release** with the per-tick results (version, changelog, notebooks), which replaces the
   whole-day results on the deployed site.

### Who does what

One thread per phase; this planning thread ("Plan Next Steps") coordinates and keeps this
file current.

| Thread | Work items | Starts from | Can run alongside |
|---|---|---|---|
| A: 64 GB servers6 scenarios | 1 | `refactor-10_25` | B, D |
| B: per-tick mode | 2 | `refactor-10_25`, own worktree and branch | A, D |
| D: Actions workflow | 4 | `refactor-10_25`, own worktree and branch | A, B |
| planning thread | 3, 6, 7 and merging A, B, D back | after A and B | none |

B and D both touch the run entry point (`scheduler/run.py`): D codes against the run switch
and checkpoint layout fixed at the start of B, and is merged after B. Step 5 (push) needs a
separate go.

## 6. Open items

- The per-tick solve-time cap (after the timing run).
- When to add the 10- and 2-server fleets, 6.3 and 6.4, and the validation runs.
- The tests that read whole-day runs (`tests/test_validate.py`) now skip; they need per-tick
  runs or a rewrite.

## 7. Where things moved (2026-10-25)

| From | To | Why |
|---|---|---|
| `results/servers10/`, `results/servers6/`, `results/validation/` | `archive/results_2026-10-25_whole_day/` | whole-day results, set aside for the per-tick runs |
| `runs_staging/` | `archive/runs_staging_516GB_invalid/` | runs on 516 GB servers; invalid since the memory is 64 GB |
| top-level `logs/runs/*.log`, `runlist.txt`, `runlist_rest.txt` | `archive/logs_1.0.0/` | logs of the 1.0.0 runs; `logs/runs/` keeps one folder per release |

`results/` is empty until the per-tick runs come in. The deployed site still shows the 1.2.1
results from the `release` branch.

## 8. Decision log

All on 2026-10-25.

| Decision | Choice |
|---|---|
| Re-planning frequency | every tick (option 2); hourly (option 1) dropped |
| Carbon knowledge | the true curve (choice A); forecast error (choice B) dropped |
| A stuck tick | fail and report |
| Whole-day solve | dropped from the results, including as a benchmark |
| Lookahead | to the end of the planning horizon (assumption 10) |
| First batch | 6 servers × light/normal/heavy × 6.1 and 6.2 = 18 runs |
| Validation runs | left out for now |
| Where to run | GitHub Actions |
| Per-tick cap | set after timing one heavy run |
| Deployed site | unchanged until the per-tick release |
| Whole-day results and staged 516 GB runs | moved to `archive/` |
| Scenarios to rebuild now | the three 6-server ones only |
| How the work is split | one thread per phase (A, B, D); this planning thread coordinates |
| Where to time the cap | this machine first, confirmed by the first Actions job |
| Start | not yet: nothing starts until the owner says go |
