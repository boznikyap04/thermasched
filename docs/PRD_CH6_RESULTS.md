# PRD: Chapter 6 results on the site

Follow-up to `PRD.md` §9 (scenarios S1–S4, which the thesis numbers 6.1–6.4). It covers four
requests from the thesis group:

1. Label the existing runs with their Chapter 6 names.
2. Show every Chapter 6 run's results in one downloadable table.
3. Confirm the reference run for the cooling experiment (6.2).
4. Add the 6.4 test where temperature does not guide server choice.

Facts below were checked on 2026-10-21 against the 1.0.1 runs in `results/thesis10/`.

---

## 1. Background: what the current runs show

### 1.1 Run inventory (scenario `thesis10`, release 1.0.1)

| Thesis label (requested) | Run folder | Switches |
|---|---|---|
| 6.1 Base | `least_loaded_base18_free_optimize` | none |
| 6.1 Regrouped zones | `least_loaded_base18_free_optimize_zones1111222222` | `zone_map 1,1,1,1,2,2,2,2,2,2` |
| 6.1 Same-zone moves only | `least_loaded_base18_same_zone_optimize` | `reassignment same_zone` |
| 6.2 CRAC changed, cold plates fixed | `least_loaded_base18_free_optimize_cp_cpfixed` | `cold_plates`, `cp_mode fixed` |
| 6.2 Cold plates changed, CRAC fixed | `least_loaded_base18_free_fixed18_cp` | `cold_plates`, `supply_temp_mode fixed` (18 °C) |
| 6.3 Base 10 °C safety margin | `least_loaded_base18_free_optimize` (same run as 6.1 Base) | none (H_min = 10 °C) |
| 6.3 Low 5 °C safety margin | `least_loaded_base18_free_optimize_hmin5` | `H_min 5` |
| 6.3 High 15 °C safety margin | `least_loaded_base18_free_optimize_hmin15` | `H_min 15` |
| 6.4 Reassignment allowed | `least_loaded_base18_free_optimize` (same run as 6.1 Base) | none |
| 6.4 No reassignment | `least_loaded_base18_none_optimize` | `reassignment none` |
| 6.4 Flat carbon intensity | `least_loaded_base18_free_optimize_ciflat_tl1800` | `ci_flat`, time limit 1800 s |

The base run carries three labels. Runs under `archive-*` and the other scenarios
(`consolidated6`, `thesis10_tight`, `_swing`, `_warm`) get no thesis label.

### 1.2 Six of the runs have identical results

The optimized schedules of 6.1 Base, Regrouped zones, Same-zone moves, Low 5 °C, High 15 °C
and No reassignment are byte-identical (same `optimized/schedule.csv`): 31.017 kg CO₂,
50.04 kWh, hottest server 73.3 °C. No run moved a single workload (`n_reassigned = 0`).

What's behind it:

- **6.3 is a real result.** The CRAC sits at 27 °C, the top of its range, in every zone and
  period. The hottest server (73.3 °C) stays below even the 15 °C margin's cap (75 °C), so no
  margin from 5 to 15 °C binds and none of them changes the schedule.
- **6.1 and 6.4 may be a solver artifact.** A free-reassignment run first solves the
  no-reassignment model (20% of the 600 s limit), then tries to improve on it with moves. The
  no-reassignment model solves to optimality. The free runs stop at the time limit with a 26%
  MIP gap, without improving on it. Moves could save something: servers 8–10 average about 14%
  less IT energy per unit of work than servers 1–4 (`W_per_MHz`). So "reassignment changes
  nothing" is not yet established.
- **The time limits differ.** The flat-carbon run had 1800 s; every other run had 600 s.
  Within 6.4, that means one test gets three times the solve time of the others.

The table in R2 will make this visible: those rows will match. See decision D1.

### 1.3 The cooling runs (6.2)

- The base run has cold plates **off** (`cold_plates = False`, zero plates per server).
- Both cooling tests have cold plates **on**: one plate on each of servers 8, 9 and 10 (the
  servers with `CT_s = 1`).
- Their baselines are identical: same schedule, same zone data, 33.635 kg CO₂. Each uses the
  least-loaded schedule, CRAC fixed at 18 °C, and cold plates fixed at 0.30 L/min and 20 °C.
- That baseline cannot serve as the 6.2 reference. It is the heuristic baseline:
  placement, timing and both cooling systems are all held fixed. Comparing a test with it mixes
  the scheduling gain with the cooling gain.
- **No 1.0.1 run has both cooling systems on and optimized.** The pre-1.0 run
  `archive-thesis10/least_loaded_base18_free_optimize_cp` was made on an older model and is not
  comparable.
- **Airflow is not modelled.** There is no fan-power equation (`airflow_modelled = false`;
  `--fan-power` stops with "not defined yet"). In both tests, "CRAC changed" means only the
  supply air temperature, optimized per zone and period within 18–27 °C.
- **Cold-plate pump energy is about 0.07 Wh per day.** That is what the rated 0.657 mW per
  plate gives. In kWh it shows as 0.000.

### 1.4 The 6.4 test that ignores temperature

The model cannot do this yet. No switch exists (`PRD.md` §10.3 and gap G12 list it as open).
Server temperature is built into the one model that chooses servers: the temperature
recursion (C9), the safety cap (C10) and throttling (C12). Turning those off would also turn
off the safety limits, which this test must keep. Release 1.1.0 adds it (R4, D2).

## 2. Goals and non-goals

**Goals**
- The site shows each Chapter 6 run under its thesis label, and its original run name stays
  visible.
- One table puts every metric from R2 side by side for all Chapter 6 runs, and downloads as a
  CSV.
- 6.2 has a reference run that differs from each test in exactly one thing.
- 6.4 has a test where temperature plays no part in choosing servers but the safety limits
  still hold.

**Non-goals**
- Modelling CRAC airflow or fan power (see D3).
- Renaming or moving run folders. Labels are display only.
- Changing the other experiment scenarios (`consolidated6`, `thesis10_*`).

## 3. Requirements

### R1. Thesis labels on the site

1. Define the Chapter 6 runs once, in `dashboard/data.py`. Each entry has a section, a label,
   the scenario, and the switches that differ from the defaults (the table in §1.1, plus the
   new runs from R3 and R4).
2. Match runs to labels **by settings, not by folder name**. A run matches when its scenario
   and every switch equal the entry's, and all other switches are at their defaults. The time
   limit and MIP gap are not part of the match. Runs made by the batch notebook (`nb_…`
   folders) and runs uploaded on the site then pick up their labels without extra work.
3. A run can match several labels. The base run matches 6.1 Base, 6.3 Base 10 °C and 6.4
   Reassignment allowed.
4. Where a run is listed or picked (sidebar run picker, Compare runs, Overview header), show
   the label first and the original run name after it, for example
   `6.1 Regrouped zones · least_loaded_base18_free_optimize_zones1111222222`. Runs without a
   label show their name as today.
5. When several runs match one label, take the newest by `provenance.created_utc`. The others
   still appear in the run picker with the label and their own run names.
6. Never label `archive-*` runs.
7. Use the same labels for `RUNS` in the batch notebook (it currently says "S1/S4 base", "S1 T1
   regrouped zones" and so on).

### R2. Chapter 6 results table

A new page, **Chapter 6 results**, placed next to Compare runs. It has one row per label, in
section order 6.1 → 6.4. The base run appears in each section where it is labelled, so every
test sits right below its reference. Every value comes from the run's **optimized** result.

| Column | Unit | Source |
|---|---|---|
| Section, Label | — | R1 |
| Run (original name), Release | — | folder name, `provenance.thermasched_version` |
| Average waiting time | min | mean of `wait` over placed workloads in `optimized/schedule.csv`, × Δt (5 min) |
| Longest waiting time | min | max of `wait`, × Δt |
| Average time from arrival to completion | min | mean of `finish − arrival`, × Δt |
| Longest time from arrival to completion | min | max of `finish − arrival`, × Δt |
| CRAC electricity, Zone 1 | kWh | `optimized.totals.E_crac_by_zone_kWh[0]` |
| CRAC electricity, Zone 2 | kWh | `optimized.totals.E_crac_by_zone_kWh[1]` |
| IT electricity | kWh | `E_IT_kWh` |
| Cold-plate pump electricity | **Wh** | `E_cp_kWh` × 1000 (kWh would round to zero, §1.3) |
| Total electricity | kWh | `E_total_kWh` |
| Total carbon emissions | kg CO₂ | `carbon_kg` |
| Average server temperature | °C | `mean_T_C` (all servers, all periods) |
| Highest server temperature | °C | `hottest_T_C` |
| Workloads moved to another server | count | `n_reassigned` |
| Workloads moved to another zone | count | `n_cross_zone` |
| Missed deadlines | count | `n_late` |
| Missed deadlines | % | `n_late / n_workloads` × 100 |
| Servers slowed by temperature | count | `n_throttled_servers` (DPF < 1 in at least one period) |
| Solver status, MIP gap, time limit | — | `solver.status`, `solver.mip_gap`, `settings.time_limit_s` |

1. Compute the waiting and arrival-to-completion columns on the site from `schedule.csv`.
   That way the existing 1.0.1 runs work without being solved again. First confirm that
   `finish − arrival` equals $CT_i − A_i$ under the evaluator's period convention. In the base
   run, the averages are 71 min wait and 230 min arrival to completion.
2. Leave out unplaced workloads from the time columns and show their count in a caption.
3. A label with no matching run shows an empty row marked "not run yet". The new runs from
   R3 and R4 show up this way until they are made.
4. A run without an optimized schedule (infeasible, or no incumbent) shows its status and
   blank metrics.
5. Each column header carries its unit. Download as CSV (`chapter6_results.csv`), with the
   same headers and full-precision values.
6. Optional: a toggle that shows each test's change against its section's reference, in % and
   absolute terms.
7. Optional: an extra row per section for the heuristic baseline. Leave it off by default.

### R3. 6.2 reference run

1. New run: `thesis10` with `cold_plates` on and both cooling systems optimized. This is
   `--scenario thesis10 --cold-plates`, run name `least_loaded_base18_free_optimize_cp`.
2. Label: **6.2 Base, both cooling systems optimized**. The two tests then differ from it in
   one switch each (`cp_mode fixed` or `supply_temp_mode fixed`).
3. Add it to the batch notebook's `RUNS` and to the CLI runlist.
4. Change the 6.2 wording to remove airflow. In `PRD.md` §9 S2 T1 and the thesis text,
   "change CRAC temperature and airflow" becomes "change the CRAC supply air temperature
   (airflow is not modelled)" (D3).

### R4. 6.4 test where temperature does not guide server choice

The model needs a change. The rule, confirmed in D2: solve in **two passes**.

1. **Pass 1, choose servers without temperature.** Solve the model with the server
   temperature equations removed (C9, C10, C12; DPF = 1). It keeps capacity, deadlines,
   allowed delay, priority, reassignment rules and the carbon objective. Only the server
   chosen for each workload is kept.
2. **Pass 2, apply the safety limits.** Fix every workload to its pass-1 server. Solve the
   full model, with temperature, the safety cap, throttling and CRAC limits. Start times and
   cooling settings stay free.
3. If pass 2 is infeasible, record that as the result: the placement chosen without
   temperature cannot be run safely. Use the existing infeasibility diagnosis to name the
   binding limits. Don't fall back to anything else.
4. The new switch is `placement = "thermal_aware"` (the default) or `"thermal_blind"`. On the
   CLI it is `--thermal-blind`, and the run-name suffix is `tblind`. Record it in
   `summary.json` settings, and add a model note that names the two passes.
5. The time limit is split across the two passes. The total stays equal to the run's limit.
6. Tests: on `small`, pass 2 keeps pass 1's servers, every safety limit holds under the
   evaluator, and the default placement gives the same results as before the change.
7. Label: **6.4 Temperature ignored when choosing servers**. Add it to the batch notebook's
   `RUNS` and to the runlist.

### R5. Release

1. R1, R2 and the R3 run don't change the model. R4 does. Ship them together as
   **1.1.0**, with a CHANGELOG entry. Re-run: **solver**. Only the two new runs (6.2 Base and
   the 6.4 temperature-ignored test) are new to the model, and the 1.0.1 runs stay valid.
   Because of D1, every `thesis10` Chapter 6 run is solved again with a 1800 s limit, into new
   `_tl1800` folders (`logs/runs/v1.1.0/runlist.txt`). The flat-carbon run already had 1800 s
   and is not re-run. The old 600 s runs stay in `results/`.
2. Sync the notebooks (`tools/sync_notebooks.py`). The notebooks must stay standalone, with no
   mention of repository files, the CLI or flags.
3. Commit the new runs under `results/thesis10/`, then deploy through the `release` branch as
   usual.

## 4. Decisions

Decided on 2026-10-21.

| # | Question | Decision |
|---|---|---|
| D1 | Solve the 6.1 and 6.4 runs again with a longer time limit before the numbers go into the thesis? No run moves a workload, and the free runs stop at a 26% gap (§1.2). | Yes. Every `thesis10` Chapter 6 run is solved with the same 1800 s limit, which the flat-carbon run already used. That settles whether "reassignment changes nothing" is real, and it makes the 6.4 rows comparable. 10 runs of up to 30 min each, about 4.5 h (the no-reassignment run takes seconds). |
| D2 | Is the two-pass rule in R4 the intended meaning of "temperature does not guide which server receives a waiting workload"? | Yes. It keeps the safety limits and changes only how servers are chosen. Done: `placement = "thermal_blind"`, `--thermal-blind`. |
| D3 | Model airflow, or remove it from 6.2? | Remove it. Airflow is not modelled and there is no fan-power equation. 6.2 changes only the CRAC supply air temperature. |
| D4 | Is "6.2 Base, both cooling systems optimized" the right label for the new reference? | Yes. The reference is `thesis10` with cold plates on and both cooling systems optimized. |

## 5. Acceptance criteria

- Every run in §1.1 shows its thesis label and original run name on the site. The base run
  shows all three of its labels. `archive-*` runs show none.
- A Chapter 6 run made in the batch notebook or uploaded on the site gets its label without a
  code change.
- The Chapter 6 results page shows every column of R2 for every label, in section order. Its
  CSV opens in Excel with units in the headers. For the base run, the values match
  `summary.json`, and the wait and completion figures match a hand calculation from
  `schedule.csv`.
- The 6.2 reference run exists under `results/thesis10/`, is labelled, and differs from each
  cooling test in one switch only.
- The 6.4 temperature-ignored run exists. Its servers match pass 1,
  and it passes every safety check, or it reports which limits make it infeasible.
- No 6.2 text on the site or in the docs mentions airflow as a decision.
- `uv run pytest` passes, including the notebook sync and standalone checks.
