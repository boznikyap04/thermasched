# Data Preparation Report

**Project:** Python translation of the optimization model in *"An Integrated Optimization
Model for Thermal-Aware Workload Scheduling and Air-Liquid Cooling Control in
Heterogeneous Data Centers"*.
**Date of work:** 2026-10-09; missing-data fixes and notebook 2026-10-10 (section 10)
**Scope of this report:** profiling the two raw datasets, cleaning them to fit the
theoretical model, and building ready-to-solve scenario instances.

**Not in scope, and not done:** the optimization model itself. No objective, variable,
or constraint has been coded and nothing has been solved. Every number below describes
the input data or a simple reference schedule, not a model result.

Equation numbers such as "Eq. (17)" refer to `thesisb.pdf`. Labels such as "A1" or "B9"
refer to the open questions in `PROJECT_CONTEXT.md`, section 7.

---

## 1. Summary

- Both raw datasets were profiled in full (2.7 million UniMelb rows, 15.4 million UFCG
  usage rows). The earlier project notes were based on a partial skim.
- One notebook, `data_prep.ipynb`, cleans both datasets and builds the scenarios. It is
  the project's only cleaning code. Run it top to bottom, or without opening it:
  `uv run jupyter-execute --inplace notebooks/data_prep.ipynb`. It runs in under a minute.
- **Servers:** 45 of 81 UniMelb servers have a usable power curve and thermal response.
- **Workloads:** 502 of 2,800 UFCG virtual machines qualify as finite workloads.
- Three scenario instances were generated: `base` (tuned to make the model's trade-offs
  visible), `thesis10` (the ten-server fleet the thesis text implies), and `small` (for
  solver debugging).
- Several questions the thesis leaves open had to be decided to make the data fit. All
  are listed in section 5, and all are single values in
  the Settings cell of `notebooks/data_prep.ipynb`.
- Two findings matter for what the model will be able to show (section 8): idle power
  is 82% of baseline IT energy, and the thesis still has no temperature equation.

---

## 2. Starting point

| Item | State before this work |
|---|---|
| `data/raw/UniMelb.csv` (613 MB) | Raw. Named by the thesis as the server dataset |
| `data/raw/UFCG/*.csv` (about 8 GB, 7 files) | Raw. Chosen by the project owner as the workload dataset, replacing Bitbrains |
| `old_notebook.ipynb` | Colab data preparation built around Bitbrains; no optimization code |
| `PROJECT_CONTEXT.md` | Full model specification and a list of open questions; datasets only skimmed |

The request was made in two steps: first a cleaning plan, then to make the alignment
decisions that make most sense and configure the setup so the model's effect is as
visible as possible.

---

## 3. What the data profiling found

### 3.1 UniMelb (servers)

2,748,525 rows, 81 servers, 10-minute records from 2018-10-09 to 2019-06-20.

| Finding | Size | Consequence for the model |
|---|---|---|
| `CPU_cores` changes from 64 to 128 on 2019-03-15 for every server, after about 24 hours where the field is null | 41% of rows are at 128 | Core count is not constant. Mean `CPU_Load` falls from 15.8 to 2.6 across the change and per-server idle power shifts by a median of 9 W |
| `CPU_Load` is on a 0 to 100 scale | 92 rows are at or below 0.01; 982,101 are at or below 1 | The 0.01 threshold in Eq. (17) has to be applied as 1.0 |
| Load never exceeds 68% (99th percentile 54%) | all servers | $P^{max}_s$ from Eq. (19) is power at partial load. Fitted full-load power is far higher (section 4.1) |
| Weak or negative power-to-load relationship | 14 servers never exceed 20% load; several have negative correlation | Eq. (20) is not meaningful for these servers |
| 486 apparent duplicate timestamps | 81 servers × 6 slots, 2019-04-07 02:00 to 02:50 | The repeated hour at the end of daylight saving. The values differ, so these are not true duplicates |
| Gaps | about 4 days from 2018-12-14 on roughly 40 servers; 21 hours on 2019-02-26 on all 81 | Lowers completeness; no effect on static parameters |
| `Inlet_Temperature` = 4.0 together with fan speed 280 | 140,255 rows on 9 servers | A failed-sensor reading, not a real temperature |
| Five servers (rcc196 to rcc200) start on 2019-02-01 | idle about 210 W against about 157 W elsewhere; no inlet data | A different hardware group |
| `Ram` is 64.45 to 64.49 with no documented unit | all rows | Resolved in section 5 |

### 3.2 UFCG (workloads)

15,397,129 usage rows, 2,800 virtual machines, 5-minute snapshots from 2024-05-23 to
2025-05-17. In OpenStack a "server" is a virtual machine, so a UFCG `server_id` is a
workload in the model, not a server.

| Finding | Size | Consequence |
|---|---|---|
| CPU usage is the text `NA` | 3.45 million rows (22%) | Host-level: 26 of 102 hosts never report CPU or RAM usage (their hypervisors were not monitored), and they account for 3.14 million of the `NA` rows. Other hosts are about 0.4% `NA`. A VM on an unmonitored host has unknown work content, not zero |
| `amphora` flavor (load-balancer appliances) | 1,606 VMs (57%); most live under an hour | Infrastructure churn, not user workloads |
| Timestamps differ by a few seconds between snapshots and between files | 1,460 doubled rows once snapped to a 5-minute grid | Files must be joined on the 5-minute slot |
| Collection outages | 12 longer than 10 minutes; the longest is 38.7 hours on 2024-09-14 | Must not be read as a VM ending |
| VMs alive at the start or end of the trace | 118 and 162 | Arrival time or total work is unknown |
| Resized VMs | 19 | CPU demand must be constant per workload |
| One flavor has `ram` = 4 | 2 VMs | Data error |
| Typical CPU use | median 2.7% of the requested vCPUs among cleaned workloads | Requested capacity far exceeds work actually done |

**Correction to an earlier figure.** The cleaning plan reported 35 migrated VMs. That
count treated the text `NA` in the host column as if it were a host. Only 17 VMs truly
ran on two hosts; 6 of them were still present when that filter was applied.

Four UFCG files (`servers_ownerships`, `user_projects`, `projects_quota`,
`projects_quota_allocated`, about 6.7 GB) feed no model parameter and are not read.

---

## 4. Cleaning as implemented

### 4.1 Servers: `data_prep.ipynb` part 1 → `data/clean/servers.csv`

| Step | Before | After |
|---|---|---|
| Keep the 64-core period (before 2019-03-14 11:40) | 2,748,525 rows | 1,621,427 rows |
| Drop duplicate (server, time) | 1,621,427 | 1,621,427 |
| Drop rows missing `CPU_Load` or `Power` | 1,621,427 | 1,621,427 |
| Set failed-sensor inlet readings to missing | 53,165 values nulled | |
| Servers passing all gates | 81 servers | **45 servers** |

Keeping only the 64-core period removes the core-count change, the null block before
it, and the daylight-saving hour in one step, which is why the next two steps remove
nothing.

**Gates.** A server is eligible if it is at least 90% complete over the kept window,
reaches at least 30% CPU load, has a power-to-load correlation of at least 0.8, has at
least 30 near-idle records, and has a valid thermal fit. Of the 36 that fail (a server
can fail more than one): 25 on peak load, 16 on correlation, 13 on completeness, 6 with
no thermal fit, 2 on idle records.

**Parameters derived per server**

| Parameter | Rule | Range across the 45 eligible servers (min / median / max) |
|---|---|---|
| $P^{idle}_s$ | Eq. (17)-(18): mean power where `CPU_Load` ≤ 1 | 90.9 / 155.2 / 171.7 W |
| $P^{max}_s$ | Eq. (19): highest observed power | 288.1 / 358.8 / 393.2 W |
| Fitted power at 100% load | linear fit of power on load, kept as a sensitivity column | 454 / 589 / 767 W |
| $T^0_s$ | Eq. (30): higher of the two CPU temperatures at the first kept record | 32.1 / 63.0 / 76.6 °C |
| $N^{cores}_s$, $C_s$ | 64 | constant |
| $M_s$ | `Ram` × 8 GB | 528,286 MB (about 516 GB) |

**No resampling from 10 to 5 minutes was needed.** UniMelb supplies only static
per-server parameters; the solver never sees a UniMelb time series. This settles open
question E4.

**Thermal response (an addition, not from the thesis).** The thesis has no equation
for server temperature (A1). To give the model something data-based to use, each
server was fitted with a first-order response from consecutive 10-minute records:

- steady state: $T_{cpu} = T_{inlet} + a + R \cdot P$
- per period: $T_t = \alpha\,T_{t-1} + (1-\alpha)\cdot\text{steady state}$

| Coefficient | min / median / max |
|---|---|
| $R$ (°C per watt) | 0.115 / 0.148 / 0.219 |
| $a$ (°C) | -10.1 / 8.5 / 20.3 |
| $\alpha$ at 5 minutes | 0.659 / 0.924 / 0.980 |
| Steady-state error (RMSE) | 1.5 / 2.6 / 4.9 °C |

The inlet coefficient is fixed at 1. A first attempt fitted it freely and got negative
values on many servers, because inlet temperature barely varies in the data.

### 4.2 Workloads: `data_prep.ipynb` part 2 → `data/clean/workloads.csv`, `workload_usage.parquet`

A workload is defined as **one VM whose whole life lies inside the trace**.

| Step | Before | After |
|---|---|---|
| Snap to 5-minute slots, merge doubles | 15,397,129 rows | 15,395,669 rows |
| Usage reported as `NA` (kept as missing) | 15,395,669 | 11,942,874 with usage |
| Has a flavor record | 2,800 VMs | 2,799 |
| Drop `amphora` | 2,799 | 1,193 |
| Drop the flavor with implausible memory | 1,193 | 1,191 |
| Drop resized VMs | 1,191 | 1,172 |
| Drop migrated VMs | 1,172 | 1,166 |
| Drop VMs alive at trace start | 1,166 | 1,054 |
| Drop VMs alive at trace end | 1,054 | 944 |
| At least 3 snapshots | 944 | 785 |
| Drop VMs on unmonitored hosts | 785 | 545 |
| Has any usage reading | 545 | 527 |
| Usage coverage at least 90% | 527 | **502** |

Each slot of a kept VM's life is one of: observed; a gap of up to 3 slots, filled by
linear interpolation (989 slots); a collector outage, filled with the VM's own mean
usage (29,543 slots on 108 VMs); or a longer gap while the collector was up, left out of
the work window (12,628 slots). Coverage is measured only over slots when the collector
was running, so an outage does not count against a VM. Usage is clipped to 100% per
vCPU. The kind of each slot is in the `fill` column of `workload_usage.parquet`.

VMs on unmonitored hosts can instead be kept with imputed usage. This is the
`impute_unmonitored` switch in the Settings cell of `notebooks/data_prep.ipynb`, off by default. When it is on, each such
VM takes the mean usage of a measured VM of the same flavor and similar lifetime, and is
flagged `usage_imputed`. It recovers 239 workloads, 99 of them inside the scenario
runtime limits. `base` then reaches its 60% load target with 330 workloads, 96 of them
imputed.

**Parameters derived per workload**

| Parameter | Rule |
|---|---|
| $C^{req}_i$ | vCPUs of the VM's flavor |
| $M^{req}_i$ | memory of the flavor, MB |
| $A_i$ | first slot the VM is seen; time of day kept (Campina Grande, UTC-3) |
| $T^W_i$ | all observed or short-gap-filled slots of the VM's life |
| $U^{CPU}_{it}$ | usage ÷ 100 × 2,400 MHz |
| $W_i$ | Eq. (14) |
| $ET^{base}_i$ | $W_i / (C^{req}_i \cdot f_{ref})$, rounded up to whole periods |

**The resulting catalogue of 502 workloads**

| Flavor | vCPUs | Count |
|---|---|---|
| general.medium | 2 | 199 |
| general.large | 4 | 151 |
| general.small | 1 | 122 |
| general.xlarge | 8 | 23 |
| reservations | 1 to 16 | 7 |

Baseline execution time is very uneven: the median is 13 periods (about an hour), 131
workloads need fewer than 3 periods, and 99 need more than a full day.

---

## 5. Alignment decisions

Each is one value in the Settings cell of `notebooks/data_prep.ipynb`. None comes from the thesis; they are
project decisions and are also recorded in `PROJECT_CONTEXT.md`, section 10.

| # | Question | Decision | Basis |
|---|---|---|---|
| 1 | How work is delivered, Eq. (39) (B9) | A workload is served by its own requested cores, not the whole server | As printed, the median workload would finish in half a period |
| 2 | UniMelb core count | 64, 64-core period only | Section 3.1 |
| 3 | Unit of `Ram` | 8 GB per unit, so about 516 GB per server | 64.488 × 8 × 75 hosts = 38,692 GB, the fleet total in the dataset's paper (Ilager et al., Table III) |
| 4 | Capacity unit for $C_s$ and $C^{req}_i$ | cores; one vCPU occupies one core | Keeps Eq. (12), (15), (16) on one scale |
| 5 | Unit of work (A10) | one vCPU at 100% = 2,400 MHz | UFCG reports percent, not MHz; 2,400 is the middle of the thesis's three frequencies |
| 6 | Eq. (22) (B2) | treated as an equality | The text describes a subtraction |
| 7 | Which servers get which frequency (E2) | highest frequency to the highest $P^{max}_s$ | Faster machines drawing more power is the physically plausible pairing |
| 8 | Cold plates, $CT_s$ (E1) | on the 3.0 GHz servers | Ch. I: high-capability servers use cold plates |
| 9 | Zones | 2, servers alternated by rank so each zone has every frequency tier | Needed for the zoning subproblem |
| 10 | Time-sensitive flag, $RT_i$ | about 30% of workloads, by a seeded hash of each workload's UFCG VM id | Not in any dataset. Keyed per workload so the flag does not change when other workloads enter or leave the catalogue |
| 11 | Deadlines, $D_i$ | time-sensitive: 25% slack; delay-tolerant: 2 × baseline time, clamped to 2 to 8 hours | Leaves room for throttling and for moving work across the carbon profile |
| 12 | Carbon intensity, $CI_t$ (D4) | 621.73 g/kWh mean with a ±25% daily shape (midday dip, evening peak) | A flat annual value gives time-shifting no carbon benefit |
| 13 | Usage during collector outages | the VM's own mean usage | The VM was alive but unobserved. Skipping these slots undercounted $W_i$ |
| 14 | VMs on unmonitored hosts | dropped by default; same-flavor hot-deck imputation behind a switch | No usage was ever recorded for them. Imputed work is borrowed, not measured |

Two consequences worth knowing:

- With decision 3, memory never binds (8 GB per core against 2 GB per vCPU in the
  common flavors). CPU is the binding resource.
- With decision 4, the mapping is conservative. UniMelb hosts themselves ran up to
  1.58 vCPUs per core.

---

## 6. Scenarios

Built by `data_prep.ipynb` part 3 into `scenarios/<name>/`. Arrivals across the whole
year are pooled into one day, keeping each workload's time of day, because cleaned
workloads arrive at only about 1.4 per day. Workloads are drawn in seeded random order
until peak requested vCPUs reach 60% of fleet cores or the catalogue runs out. In all
three scenarios the catalogue ran out first.

| | `base` | `thesis10` | `small` |
|---|---|---|---|
| Purpose | visible trade-offs | fleet as the thesis text implies | solver debugging |
| Servers (2.1 / 2.4 / 3.0 GHz) | 6 (2 / 2 / 2) | 10 (4 / 3 / 3) | 3 (1 / 1 / 1) |
| Workloads | 238 | 238 | 99 |
| Time-sensitive workloads | 71 | 71 | 32 |
| Horizon | 288 periods (24 h from 06:00) | 288 periods | 96 periods (12:00 to 20:00) |
| Fleet cores | 384 | 640 | 192 |
| Peak requested vCPUs | 168 | 168 | 66 |
| Peak demand, share of fleet | 44% | 26% | 34% |
| Peak demand, share of fastest tier | 131% | 88% | 103% |
| Servers capped below full load at 18 °C inlet | 2 | 5 | 1 |
| Servers capped below full load at 27 °C inlet | 6 | 10 | 3 |
| Assignment binaries inside time windows | 91,812 | 153,020 | 6,762 |
| Carbon intensity range (g/kWh) | 489 to 777 | 489 to 777 | 489 to 777 |

Only workloads with a baseline execution time of 3 to 144 periods are admitted (240 of
the 502). Below 3 periods a VM did almost no work in its whole life; above 144 it
cannot finish with slack inside a day.

### 6.1 Why `base` uses six servers

The thesis text beside Eq. (15) implies ten servers. With this workload set, ten
64-core servers would peak at 26% load, and demand would not even fill the fastest
tier. Six servers put peak demand at 44% of the fleet and 131% of the fastest tier, so
work must spill onto less efficient machines. The ten-server fleet is kept as
`thesis10` for comparison.

### 6.2 The `base` fleet

| s | Server | Zone | Frequency | Cold plate | $P^{idle}$ (W) | $P^{max}$ (W) | Max load at 18 °C / 27 °C inlet |
|---|---|---|---|---|---|---|---|
| 1 | qh2-rcc188 | 1 | 2.1 GHz | no | 144.2 | 312.0 | 100% / 74% |
| 2 | qh2-rcc158 | 2 | 2.1 GHz | no | 158.7 | 352.3 | 100% / 76% |
| 3 | qh2-rcc159 | 1 | 2.4 GHz | no | 158.7 | 360.0 | 100% / 68% |
| 4 | qh2-rcc181 | 2 | 2.4 GHz | no | 152.9 | 361.9 | 95% / 63% |
| 5 | qh2-rcc133 | 1 | 3.0 GHz | yes | 152.8 | 368.0 | 100% / 80% |
| 6 | qh2-rcc138 | 2 | 3.0 GHz | yes | 126.6 | 368.0 | 93% / 61% |

"Max load" is the highest steady utilization that keeps the server at or under 80 °C
(the 90 °C limit less the 10 °C headroom), using the fitted thermal response and
ignoring cold plates. Servers were picked from the 45 eligible at evenly spaced points
across the range of dynamic power, which avoids the extremes.

### 6.3 Reference schedule

Each scenario includes a thermally unaware baseline: every workload starts at arrival
on the least-loaded server with room. It supplies the existing assignment $X^0_{is}$
and a figure to compare the model against.

| | `base` | `thesis10` | `small` |
|---|---|---|---|
| IT energy (kWh) | 26.27 | 42.27 | 4.45 |
| IT carbon (kg CO₂) | 16.33 | 26.29 | 2.82 |
| Workloads late or unplaced | 0 | 0 | 0 |

These cover server energy only, by Eq. (16), (20), (3), and (6). Cooling energy is not
included, and the baseline ignores temperature entirely.

---

## 7. What was produced

| Path | Contents |
|---|---|
| `pyproject.toml` | Dependencies (DuckDB, NumPy), run through `uv` |
| `notebooks/data_prep.ipynb` | The cleaning and scenario pipeline, step by step, with outputs and checks. Its first code cell holds every decision and scenario setting, commented |
| `archive/notebooks/before_after_missing_data_fixes.ipynb` | Compares outputs before and after the 2026-10-10 fixes (section 10) |
| `archive/data_2026-10-09_before_missing_data_fixes/` | Cleaned tables and scenarios as they were before those fixes |
| `data/clean/servers.csv` | All 81 servers with parameters and an `eligible` flag |
| `data/clean/workloads.csv` | The 502 workloads |
| `data/clean/workload_usage.parquet` | $U^{CPU}_{it}$ for every workload and slot, with how each slot was filled |
| `data/clean/cleaning_log_*.csv` | Before and after counts for every cleaning step |
| `scenarios/<name>/servers.csv` | Chosen servers with zone, frequency, cold plate, thermal fit |
| `scenarios/<name>/workloads.csv` | $A_i$, $D_i$, $AD_i$, $ET^{base}_i$, $RT_i$, $B_i$, $X^0$, $C^{req}_i$, $M^{req}_i$, $W_i$ |
| `scenarios/<name>/carbon.csv` | $CI_t$ per period |
| `scenarios/<name>/baseline_schedule.csv` | The reference schedule |
| `scenarios/<name>/params.json` | Settings, thesis constants as printed, conventions, diagnostics |
| `docs/PROJECT_CONTEXT.md`, section 10 | The decisions in section 5, added to the project notes |

To re-run: open `notebooks/data_prep.ipynb` and run all cells, or
`uv run jupyter-execute --inplace notebooks/data_prep.ipynb`. Raw data files were not modified.
The original Python package `dataprep/` was retired on 2026-10-10; the notebook
replaces it and writes identical files.

**Checks run on the outputs.** For all three scenarios: arrival + baseline time + slack
equals the deadline and stays inside the horizon; every workload has a baseline server;
no workload ID repeats; baseline execution time matches the work rule. All passed.
The same checks, plus Eq. (14) against the stored usage series, run as assertions at the
end of `data_prep.ipynb`. There are no other automated tests in the repository.

---

## 8. Limitations and open items

**Affecting what the model can show**

1. **Idle power is 82% of baseline IT energy in `base`.** The model has no server
   on/off variable, so idle draw is paid whatever the schedule is. Scheduling can only
   move the remaining 18% plus cooling energy. Expect small percentage changes in the
   objective unless a power-off decision is added to the model.
2. **The thesis still has no temperature equation** (A1 to A3). The fitted thermal
   response is offered for it, but adopting it is a modelling decision that has not
   been made. It also covers air cooling only; nothing in the data describes cold
   plates.
3. **$P^{max}_s$ understates full-load power.** It is observed at no more than 68%
   load. The fitted full-load value is about 64% higher at the median. Eq. (19) was
   kept as written.

**Assumptions to confirm**

4. **Carbon intensity.** The 621.73 g/kWh mean is the Philippines 2024 figure from the
   thesis's cited source, read through an automated summary of the page rather than
   checked by hand. The country is inferred from the university, not stated in the
   thesis. The daily shape is synthetic.
5. **`Ram` unit.** The 8 GB unit is inferred from a fleet total that matches to four
   digits; the paper does not state the unit conversion itself.
6. **Time-sensitive share and deadline rule** are invented for the scenario and have
   no empirical basis.
7. **Six servers instead of ten** in `base` departs from the thesis text.

**Data caveats**

8. **Pooled arrivals.** One simulated day combines VMs that arrived on different dates
   over a year. Time-of-day pattern is real; day-level concurrency is constructed.
9. **Different eras and sites.** Servers are from Melbourne in 2018-19 and workloads
   from Campina Grande in 2024-25. They are matched by position, not by calendar.
10. **Requested versus used capacity.** Utilization in the model follows requested
    vCPUs, while VMs used a median of 2.7% of them.

**Not yet done**

11. The optimization model, including the linearizations the thesis promises but does
    not contain (A5).
12. Solver tractability is untested. `base` has about 92,000 assignment binaries
    inside time windows; whether that solves in reasonable time is unknown.
13. Rolling-horizon state: every workload has $B_i = 0$ and every server is always
    available.

---

## 9. Sources

- Ilager, Ramamohanarao, Buyya, *Thermal Prediction for Efficient Energy Management of
  Clouds using Machine Learning*: https://ar5iv.labs.arxiv.org/html/2011.03649
- Our World in Data, carbon intensity of electricity:
  https://ourworldindata.org/grapher/carbon-intensity-electricity

---

## 10. Changes on 2026-10-10: missing usage data

The figures above are current. Model formulas are unchanged; only input values moved.

1. **Bug fixed: long gaps were filled at full load.** Usage was clipped with DuckDB's
   `least()`, which ignores NULLs. A gap too long to interpolate was therefore set to
   100% of every requested vCPU instead of being left out. Of the 13,110 slots
   previously reported as "short gaps filled", 12,633 were such gaps. This inflated $W_i$
   for 165 of the 502 workloads: for the median affected workload, 7% of its work was
   phantom, and in the worst case 98%.
2. **Collector outages now count toward $W_i$.** Slots when the collector was down for
   every VM were previously skipped, which undercounted work for VMs alive through an
   outage. They now take the VM's mean usage (29,543 slots on 108 VMs).
3. **The `NA` usage is described correctly.** It comes from 26 unmonitored hosts, not from
   gaps inside each VM's record. Their VMs are now removed by a named step (240 VMs) and
   can optionally be imputed (decision 14).

`before_after_missing_data_fixes.ipynb` shows the comparison in full. Net effect on
the 502 workloads: $W_i$ fell for 142 and rose for 93. 77 changed by more
than 10%, and total work fell 4%. Baseline execution time changed for 203 workloads,
and 240 instead of 244 fall inside the scenario limits. The scenario tables in section 6
reflect this.

**Time-sensitive flag made stable.** $RT_i$ used to be drawn from the same seeded
random sequence as the workload draw order, so a workload's flag depended on its
position in the shuffled catalogue. Any catalogue change reassigned it: after the fixes
above, 101 of the 232 workloads in `base` both before and after had switched flag, and
their deadlines moved with it. The flag is now a seeded hash of each workload's UFCG VM
id. Tested by turning imputation on, which adds 92 workloads to `base` and renumbers
478 workload ids: none of the 234 workloads in both builds changed flag. This one-time
change produced a new, equally random assignment (71 of 238 in `base`). The workload
set, peak load and reference energy are unchanged by it.

The notebook's Eq. (14) check now uses the exact rounding bound per slot. The previous
relative tolerance failed on 30 imputed workloads whose flat usage profiles round the
same way in every slot; all were within the bound.
