# Solver: running the model

The solver lives in this folder (`scheduler/`, a Python package). Each run builds a
**baseline** schedule, solves the **optimized** MILP with HiGHS, scores both with the same
evaluator and writes the comparison to `results/`. Run every command from the
repository root, after `uv sync` (see the [main README](../README.md#setup)).

| File | What it does |
|---|---|
| `run.py` | command line: loads a scenario, runs baseline and optimizer, writes the results |
| `io.py` | reads `scenarios/<name>/` and applies the command-line overrides |
| `build.py` | writes a scenario folder from the cleaned tables in `data/clean/` (used by both notebooks) |
| `baseline.py` | the baseline scheduling rules (`least_loaded`, `fastest_first`, `random`) |
| `optimize.py` | builds and solves the MILP; diagnoses infeasibility |
| `evaluate.py` | scores any schedule (carbon, energy, temperatures, every limit) |
| `report.py` | writes `summary.json`, the per-period tables and the compliance tables |
| `types.py` | shared data types, constants and run settings |

Both notebooks carry generated copies of this package (`solver.ipynb` all of it,
`data_prep.ipynb` `build.py`), so that they run on Colab without the repository. After
changing a file here, run `uv run python tools/sync_notebooks.py`; `uv run pytest` fails
until you do.

## 1. Run the model

```sh
uv run python -m scheduler.run --scenario small
```

The run prints a summary and a list of checks, then writes its outputs to
`results/<scenario>/<run-name>/`. If you don't pass `--run-name`, the name is built from
the switches, for example `least_loaded_base18_free_optimize`, with a suffix for every other
switch that differs from its default (`_hmin15`, `_tblind`, `_tl180`, `_gap0.01`, `_seed3` for the
random rule, cold-plate values), so runs with different switches never share a folder. A
run with the same name overwrites the old one.

Some common runs:

```sh
# fast run: workloads stay on their baseline server, only timing and cooling change
uv run python -m scheduler.run --scenario servers6 --reassignment none

# full model on the six-server normal day, 10-minute time limit (the default)
uv run python -m scheduler.run --scenario servers6

# with cold plates on every server, and a custom output folder
uv run python -m scheduler.run --scenario servers6 --cold-plate-count 1 --run-name cp1

# baseline only, no optimization
uv run python -m scheduler.run --scenario servers6 --baseline-only
```

To run the same steps one at a time, with tables and charts in between, open
[`notebooks/solver.ipynb`](../notebooks/solver.ipynb) (see the
[notebook guide](../notebooks/README.md#solver-notebook)). It calls the same code, so the
numbers match a command-line run with the same switches.

To view results, run `uv run streamlit run dashboard/app.py`. See the
[dashboard guide](../dashboard/README.md) for how to use the dashboard, where to put result
folders, and how to start a run from the browser.

## 2. Scenarios

| Scenario | Servers | Workloads | Horizon | Use |
|---|---|---|---|---|
| `servers6_light` | 6 (2/2/2 by speed) | 45 | 288 periods (24 h from 06:00) | light day: workloads drawn until peak demand is 30% of the fleet's cores or memory (34% of memory, 17% of cores) |
| `servers6` | 6 (2/2/2) | 132 | 288 periods | normal day: peak demand 60% (61% of memory, 31% of cores) |
| `servers6_heavy` | 6 (2/2/2) | 210 | 288 periods | heavy day: peak demand 85% (86% of memory, 44% of cores) |
| `small` | 3 | 79 | 96 periods (8 h, 12:00-20:00) | quick tests, debugging |
| `small_running` | 3 | same as `small` | 96 periods | `small` with 5 workloads already running (B_i = 1) and server 3 down 15:00-16:00 (`availability.csv`), to exercise Eq. (11) and (29) |

Every server has 64 GB of memory (66,036 MB). Almost every workload asks for 2 GB per vCPU,
so memory fills first and sets the load level. All scenarios are built by
`notebooks/data_prep.ipynb` from one set of reference settings (`servers10`, the ten-server
fleet of the thesis text), each with some values changed, recorded under `variant_of` in
`params.json`. The notebook makes `small_running` from `small`
(`build.build_running_variant`) and records it under `derived_from`. The 10- and 2-server
fleets (`servers10*`, `servers2*`) are added when they are run. The earlier scenarios
(`thesis10`, `consolidated6`, `servers2` and their variants) had 516 GB per server and are in
`archive/scenarios_516GB/`.

One period is 5 minutes. Scenarios built in `notebooks/solver.ipynb` (see
[Changing the inputs](#6-changing-the-inputs)) are folders here too, and run the same way.

## 3. Run options

| Option | Default | What it does |
|---|---|---|
| `--scenario` | `small` | folder under `scenarios/` |
| `--run-name` | built from the switches | output folder under `results/<scenario>/` |
| `--baseline-rule` | `least_loaded` | `least_loaded`, `fastest_first` or `random` (uses `--seed`) |
| `--baseline-supply-temp` | `18` | the baseline's fixed CRAC supply air temperature, °C |
| `--reassignment` | `free` | where the optimizer may move workloads: `free` (any server), `same_zone`, or `none` (baseline server) |
| `--thermal-blind` | off | `placement = "thermal_blind"`: choose servers with server temperature left out, then solve start times and cooling on those servers with every thermal limit (two passes, the time limit split between them), for S4 T2 |
| `--supply-temp-mode` | `optimize` | `optimize` picks a supply temperature per zone and period; `fixed` holds it at `--fixed-supply-temp` (default: the baseline's) |
| `--h-min` | `10` (from scenario) | minimum thermal headroom, °C. The server temperature cap is 90 − H_min |
| `--time-limit` | `600` | solver time limit, seconds |
| `--mip-gap` | `0.001` | relative MIP gap at which the solver stops |
| `--cold-plates` | off | model cold plates, using `n_cold_plates` per server from `servers.csv` |
| `--cold-plate-count N` | — | put N cold plates on every server (turns on `--cold-plates`) |
| `--baseline-cp-flow` / `--baseline-cp-coolant` | `0.30` L/min / `20` °C | the baseline's fixed cold-plate settings |
| `--cp-mode` | `optimize` | `fixed` holds the optimized run's cold plates at `--fixed-cp-flow` / `--fixed-cp-coolant` (default: the baseline's), for S2 T2 |
| `--no-priority` | off | drop the priority rules, Eq. (56)-(57) (see below) |
| `--zone-map 1,1,1,2,2,2` | `servers.csv` | zone of each server in order, for S1 T1 (regrouped zones) |
| `--carbon-file PATH` | `carbon.csv` | another carbon-intensity profile (columns `t`, `CI_t_g_per_kWh`), for S4 T3 |
| `--ci-flat` | off | carbon intensity held at the scenario's mean, for S4 T3 |
| `--baseline-only` | off | skip the optimized run |
| `--no-warm-start` | off | don't give the solver a starting schedule |
| `--solver-log` | off | print the HiGHS log |
| `--diagnosis-time-limit` | `120` | seconds per relaxed re-solve when the model is infeasible |

Run `uv run python -m scheduler.run --help` for the full list.

## 4. Outputs

Each run folder contains:

- `summary.json`: settings, totals (carbon, IT/CRAC/cold-plate energy, waits,
  temperatures), the baseline-vs-optimized comparison, solver status and gap, and checks.
  Its `provenance` block says what made the run: the release (`scheduler/version.py`), the
  layout version of the file (`schema_version`), where it was made (command line, notebook,
  batch notebook, dashboard), when, the git commit for a run made in the repository, the
  HiGHS version, and the **scenario fingerprint**, a hash of the scenario's input files
  (`build.scenario_fingerprint`). Runs of one scenario are comparable only when their
  fingerprints are equal; the dashboard warns when they are not.
- `comparison_period.csv`: baseline and optimized values side by side for each period.
- `baseline/` and `optimized/`: `schedule.csv`, per-period tables (`period.csv`,
  `server_period.csv`, `zone_period.csv`) and compliance tables (`compliance_servers.csv`,
  `compliance_zones.csv`, `compliance_cold_plates.csv`, `compliance_workloads.csv`).
- `optimized/reassignment.csv`: per workload, the original and final server and zone,
  whether it moved, whether the move crossed zones, and a reason. The reason is a reading
  of the scored schedule (original server full, faster server, less IT energy, cooler
  server, zone with higher COP); the solver itself only minimises carbon.

## 5. Thesis scenarios (Ch. 6)

The thesis scenarios are run switches, applied to the six-server fleet on each load level
(`--scenario servers6_light`, `servers6`, `servers6_heavy`).

| Scenario | Command switches |
|---|---|
| S1 base / T1 / T2 | default / `--zone-map 1,1,2,2,2,2` (the 2.1 GHz tier in zone 1, the faster tiers in zone 2) / `--reassignment same_zone` |
| S2 base / T1 / T2 | `--cold-plates` (both optimized) / `--cold-plates --cp-mode fixed` (CRAC optimized) / `--cold-plates --supply-temp-mode fixed` (cold plates optimized). Airflow is not modelled |
| S3 | `--h-min <value>` |
| S4 base / T1 / T2 / T3 | default / `--reassignment none` / `--thermal-blind` / `--ci-flat` or `--carbon-file <csv>` |

Since 1.1.0 every Chapter 6 run is solved with `--time-limit 1800`
(`logs/runs/v1.1.0/runlist.txt`). With `--thermal-blind`, if no schedule on the servers chosen
in the first pass meets the thermal limits, the run is infeasible and the diagnosis names the
limits; there is no fallback.

The command exits with code 1 if any check fails, for example if the optimized schedule
breaks a limit when the evaluator re-checks it.

## 6. Changing the inputs

- **Solver and run settings:** the command-line options above.
- **Per-server and per-workload values:** edit the CSVs in `scenarios/<name>/`
  (`servers.csv`, `workloads.csv`, `carbon.csv`). `n_cold_plates` in `servers.csv` is
  meant to be edited by hand. If you change workloads or servers, the
  `least_loaded_reproduces_baseline_schedule_csv` check will fail, because
  `baseline_schedule.csv` no longer matches. To keep it passing, copy the scenario to a new
  folder and regenerate it.
- **A new scenario from an existing one:** in `notebooks/solver.ipynb`, set `SCENARIO` to a new
  name and `BUILD_FROM` to the scenario to start from (normally `servers6`), and put the values to change in
  `SCENARIO_CHANGES` (fleet size, speed split, horizon, load target, deadlines, carbon
  intensity), `CONSTANT_CHANGES` (the thesis constants) or `COLD_PLATE_CHANGES`. The notebook
  writes `scenarios/<name>/` with its own `baseline_schedule.csv`, so every check passes, and
  records the changes under `built_from` in `params.json`. It reads only `data/clean/`, so it
  does not need the raw data. The shipped scenarios are never overwritten. In code:
  `scheduler.build.derive_scenario(name, start_from, settings, constants, cold_plate)`.
- **Constants and scenario construction of the shipped scenarios:** edit the Settings cell of
  `notebooks/data_prep.ipynb` (fleet size, speed split, horizon, deadlines, carbon
  intensity, model constants, cold-plate table), then re-run the notebook. This needs the
  raw datasets in `data/raw/`, which are not in the repository because of their size. See
  the [cleaning notebook guide](../notebooks/README.md).

## 7. Run many scenarios in a row

`logs/runs/v<release>/runlist.txt` lists the switches of a release's runs, one run per line,
and `logs/runs/v<release>/*.log` holds what each run printed (the 1.0.0 logs are in
`archive/logs_1.0.0/`). To repeat a list (macOS / Linux):

```sh
while read -r args; do uv run python -m scheduler.run $args < /dev/null; done < logs/runs/v1.1.0/runlist.txt
```

Keep the printed output of a long run with `... | tee logs/runs/v<release>/<name>.log`.

## 7b. Validation checks

```sh
uv run python -m scheduler.validate --scenario servers6
```

runs the checks of `scheduler/validate.py` and writes their tables to
`results/validation/<scenario>/` (CSV, plus `validation.json`). Section 8 of the solver
notebook makes the same tables. The site does not show them (its Validation page,
`dashboard/views/validation.py`, is kept off it). The checks that solve
build small scenarios from the scenario's own servers and constants. The checks that read runs
(cold plates, the warm-scenario slowdown, solver completeness) are skipped if their run folders
are missing. Run it again after adding runs to `results/<scenario>/`, so the solver table lists
them. It exits with 1 if a check fails.

## 8. Current caveats

**Solving**

The figures in these points come from the whole-day runs on the earlier 516 GB scenarios
(`thesis10`, `consolidated6`; now in `archive/scenarios_516GB/`).

- **Most full-model runs stop at the time limit, not at the optimum.** On `consolidated6`
  and `thesis10` with `--reassignment free` or `same_zone`, the solver stops at 600 s with a
  gap of about 1-4%. The worst case so far is 26% on `thesis10 free` at 600 s (1.6% at
  1800 s). Treat these results as good valid schedules with a proven bound, not as optima.
  Report the gap from `summary.json`; the validation table `solver.csv` lists every run's
  status, gap and the most a better schedule could still save.
- **On the large scenarios the solver often doesn't improve on its starting schedule.**
  With `free` or `same_zone`, the model is first solved with workloads fixed to their
  servers, and that schedule is used as the start. On `consolidated6` and `thesis10` with
  `--supply-temp-mode optimize`, several runs stop at the time limit still on that start:
  the carbon is the same as `--reassignment none`, and no workload moves. On `thesis10` this
  holds at 1800 s too, also with the supply fixed at 27 °C (`free` 1.57%, `same_zone` 1.41%):
  moves could save at most about 0.49 kg there. When the solver
  does get further, moving workloads helps: `small` moves 67 workloads, and `consolidated6` with
  `--h-min 15` moves 197 and solves to optimality.
- **Results that stop at the time limit can be non-monotone.** For example, `consolidated6` with
  `--h-min 15` (a tighter limit) produced less carbon than `--h-min 5`, which stopped at
  the time limit. Compare scenarios only between runs that are optimal or have small
  gaps, or raise `--time-limit`.
- **`--reassignment none` solves in seconds** and to optimality. Use it for quick
  comparisons.
- **No fallback when there is no valid schedule.** Every limit is a hard constraint. If
  the model is infeasible, the run says so and re-solves with each group of limits relaxed
  in turn (deadlines, thermal cap, capacity, cooling capacity, priority) to show which group
  causes it (see `results/archive-small/infeasible_demo_hmin20`). If the solver finds no schedule within
  the time limit, the status is `no_solution`, which does not prove infeasibility (see
  `results/archive-small/fastest_first_base27_free_optimize`).
- **The baseline is not guaranteed to be valid.** A baseline with a warm supply
  temperature (for example 27 °C) can exceed the thermal cap. `summary.json` lists its
  violations.

**Model simplifications**

- The supply air temperature is chosen in whole degrees (18-27 °C), so the COP comes
  from a lookup table. CRAC power is Q / COP. The printed Eq. (46) multiplies by COP
  instead.
- DVFS slowdown uses only the linear part of Eq. (37), which is valid below
  T_throttle = 100 °C.
- **Priority, Eq. (56)-(57)** is on by default. The thesis prints no link between O_ij
  and the schedule, so the model uses this one: if two workloads share a server and the
  lower-priority one starts while the higher-priority one is waiting, that is an
  inversion and is not allowed. Time-sensitive goes before delay-tolerant; same type and
  deadline go first-come first-served. Earliest-deadline-first within a type is not in
  the equations and is not modelled. The evaluator counts inversions in every run;
  `--no-priority` makes them allowed.
- **Server availability, Eq. (11)** comes from an optional `availability.csv` (`s, t, AV`);
  unlisted server-periods are available. An unavailable server takes no work but stays on
  at idle power. Running workloads (B_i = 1) keep their server, Eq. (29), but may still
  be shifted in time.
- **Not modelled:** fan power and airflow (`--fan-power` exits with "not defined yet"; decided
  with the thesis group on 2026-10-22) and turning servers on and off (every server stays on
  and draws idle power, so a move changes only the power a workload adds above idle).
- **Cold-plate settings carry almost no cost.** Pump power is under about 1 mW per plate,
  and no equation charges energy for chilling the water. The optimizer therefore uses
  whichever flow and coolant settings remove the most heat. Where the 0.3 kW plate limit
  binds, the reported flow and coolant values are arbitrary. Don't interpret them as
  control decisions yet.

**Data assumptions**

- The server temperature model (a_s, R_s, α_s) is fitted from the UniMelb data. It is not
  part of the thesis formulation.
- Deadlines, time-sensitive flags, zones, cold-plate placement, which servers get which
  speed, and the **daily shape of carbon intensity** are generated by rule. No dataset
  supplies them. The carbon intensity uses the Philippines 2024 annual mean with a
  synthetic ±25% daily curve. Each scenario's `params.json` lists these values under
  `assumed_not_from_data`.
- Workloads on the 26 UFCG hosts that never report usage are dropped (imputation can be
  turned on in the notebook's Settings cell).

[`docs/PROJECT_CONTEXT.md`](../docs/PROJECT_CONTEXT.md) has the full specification and the
reasons for each decision.
