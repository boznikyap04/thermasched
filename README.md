# ThermaSched

Thermal-aware workload scheduling and air-liquid cooling control for heterogeneous data
centers. Each run builds a **baseline** schedule, solves
the **optimized** MILP with HiGHS, scores both with the same evaluator and writes the
comparison to `results/`.

## Setup

Install [uv](https://docs.astral.sh/uv/getting-started/installation/), then from the
repository root:

```sh
uv sync          # creates .venv with Python >= 3.11 and every dependency
uv run pytest    # optional: checks that the install works
```

## Running the model

```sh
uv run python -m scheduler.run --scenario small
```

The run prints a summary and a list of checks, then writes its outputs to
`results/<scenario>/<run-name>/`. If you don't pass `--run-name`, the name is built from
the switches, for example `least_loaded_base18_free_optimize`. A run with the same name
overwrites the old one.

Some common runs:

```sh
# fast run: workloads stay on their baseline server, only timing and cooling change
uv run python -m scheduler.run --scenario base --reassignment none

# full model on the main scenario, 10-minute time limit (the default)
uv run python -m scheduler.run --scenario base

# with cold plates on every server, and a custom output folder
uv run python -m scheduler.run --scenario base --cold-plate-count 1 --run-name base_cp1

# baseline only, no optimization
uv run python -m scheduler.run --scenario base --baseline-only
```

To view results, run `uv run streamlit run dashboard/app.py`. See
[`DASHBOARD.md`](DASHBOARD.md) for how to use the dashboard, where to put result folders,
and how to start a run from the browser.

### Scenarios

| Scenario | Servers | Workloads | Horizon | Use |
|---|---|---|---|---|
| `small` | 3 | 99 | 96 periods (8 h, 12:00-20:00) | quick tests, debugging |
| `small_running` | 3 | same as `small` | 96 periods | `small` with 4 workloads already running (B_i = 1) and server 3 down 15:00-16:00 (`availability.csv`), to exercise Eq. (11) and (29) |
| `base` | 6 | 238 | 288 periods (24 h from 06:00) | main results |
| `thesis10` | 10 (4/3/3 by speed) | same workloads as `base` | 288 periods | the 10-server fleet from the thesis text |

One period is 5 minutes.

### Run options

| Option | Default | What it does |
|---|---|---|
| `--scenario` | `small` | folder under `scenarios/` |
| `--run-name` | built from the switches | output folder under `results/<scenario>/` |
| `--baseline-rule` | `least_loaded` | `least_loaded`, `fastest_first` or `random` (uses `--seed`) |
| `--baseline-supply-temp` | `18` | the baseline's fixed CRAC supply air temperature, °C |
| `--reassignment` | `free` | where the optimizer may move workloads: `free` (any server), `same_zone`, or `none` (baseline server) |
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

### Outputs

Each run folder contains:

- `summary.json`: settings, totals (carbon, IT/CRAC/cold-plate energy, waits,
  temperatures), the baseline-vs-optimized comparison, solver status and gap, and checks.
- `comparison_period.csv`: baseline and optimized values side by side for each period.
- `baseline/` and `optimized/`: `schedule.csv`, per-period tables (`period.csv`,
  `server_period.csv`, `zone_period.csv`) and compliance tables (`compliance_servers.csv`,
  `compliance_zones.csv`, `compliance_cold_plates.csv`, `compliance_workloads.csv`).
- `optimized/reassignment.csv`: per workload, the original and final server and zone,
  whether it moved, whether the move crossed zones, and a reason. The reason is a reading
  of the scored schedule (original server full, faster server, less IT energy, cooler
  server, zone with higher COP); the solver itself only minimises carbon.

### Thesis scenarios (Ch. 6)

| Scenario | Command switches |
|---|---|
| S1 base / T1 / T2 | default / `--zone-map 1,1,1,2,2,2` / `--reassignment same_zone` |
| S2 T1 / T2 | `--cold-plates --cp-mode fixed` (CRAC optimized) / `--cold-plates --supply-temp-mode fixed` (cold plates optimized). Airflow is not modelled |
| S3 | `--h-min <value>` |
| S4 base / T1 / T3 | default / `--reassignment none` / `--ci-flat` or `--carbon-file <csv>`. T2 (thermal-blind reassignment) is not defined yet |

The command exits with code 1 if any check fails, for example if the optimized schedule
breaks a limit when the evaluator re-checks it.

### Changing the inputs

- **Solver and run settings:** the command-line options above.
- **Per-server and per-workload values:** edit the CSVs in `scenarios/<name>/`
  (`servers.csv`, `workloads.csv`, `carbon.csv`). `n_cold_plates` in `servers.csv` is
  meant to be edited by hand. If you change workloads or servers, the
  `least_loaded_reproduces_baseline_schedule_csv` check will fail, because
  `baseline_schedule.csv` no longer matches. To keep it passing, copy the scenario to a new
  folder and regenerate it.
- **Constants and scenario construction:** edit `config.toml` (fleet size, speed split,
  horizon, deadlines, carbon intensity, model constants, cold-plate table), then re-run
  `data_prep.ipynb`. This needs the raw datasets `Data/UniMelb.csv` and `UFCG/*.csv`,
  which are not in the repository because of their size.

## Current caveats

**Solving**

- **Most full-model runs stop at the time limit, not at the optimum.** On `base` and
  `thesis10` with `--reassignment free` or `same_zone`, the solver stops at 600 s with a
  gap of about 1-4%. The worst case so far is 26% on `thesis10 free`. Treat these results
  as good valid schedules with a proven bound, not as optima. Report the gap from
  `summary.json`.
- **On the large scenarios the solver often doesn't improve on its starting schedule.**
  With `free` or `same_zone`, the model is first solved with workloads fixed to their
  servers, and that schedule is used as the start. On `base` and `thesis10` with
  `--supply-temp-mode optimize`, several runs stop at the time limit still on that start:
  the carbon is the same as `--reassignment none`, and no workload moves. When the solver
  does get further, moving workloads helps: `small` moves 67 workloads, and `base` with
  `--h-min 15` moves 197 and solves to optimality.
- **Results that stop at the time limit can be non-monotone.** For example, `base` with
  `--h-min 15` (a tighter limit) produced less carbon than `--h-min 5`, which stopped at
  the time limit. Compare scenarios only between runs that are optimal or have small
  gaps, or raise `--time-limit`.
- **`--reassignment none` solves in seconds** and to optimality. Use it for quick
  comparisons.
- **No fallback when there is no valid schedule.** Every limit is a hard constraint. If
  the model is infeasible, the run says so and re-solves with each group of limits relaxed
  in turn (deadlines, thermal cap, capacity, cooling capacity, priority) to show which group
  causes it (see `results/small/infeasible_demo_hmin20`). If the solver finds no schedule within
  the time limit, the status is `no_solution`, which does not prove infeasibility (see
  `results/small/fastest_first_base27_free_optimize`).
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
- **Not modelled:** fan power and airflow (`--fan-power` exits with "not defined yet") and
  turning servers on and off (every server stays on and draws idle power).
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
  turned on in `config.toml`).

`PROJECT_CONTEXT.md` has the full specification and the reasons for each decision.
