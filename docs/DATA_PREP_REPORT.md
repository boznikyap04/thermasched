# Data Preparation Report

**Project:** Python translation of the optimization model in *"An Integrated Optimization
Model for Thermal-Aware Workload Scheduling and Air-Liquid Cooling Control in
Heterogeneous Data Centers"*.
**Date of work:** 2026-10-09; missing-data fixes and notebook 2026-10-10 (section 10); second
UniMelb dataset (Dell C6320 servers) 2026-10-28 (sections 3.2, 4.2, 5)
**Scope of this report:** profiling the raw datasets (two UniMelb server datasets and the UFCG
workload trace), cleaning them to fit the
theoretical model, and building ready-to-solve scenario instances.

**Not in scope, and not done:** the optimization model itself. No objective, variable,
or constraint has been coded and nothing has been solved. Every number below describes
the input data or a simple reference schedule, not a model result.

Equation numbers such as "Eq. (17)" refer to `thesisb.pdf`. Labels such as "A1" or "B9"
refer to the open questions in `PROJECT_CONTEXT.md`, section 7.

---

## 1. Summary

- The raw datasets were profiled in full (2.7 million UniMelb R840 rows, 1.3 million
  UniMelb C6320 rows, 15.4 million UFCG usage rows). The earlier project notes were based on
  a partial skim.
- **Two server datasets.** UniMelb is published as two datasets of one cloud (Zenodo
  10.5281/zenodo.10069402): D1, 81 Dell PowerEdge **R840** hosts (`UniMelb.csv`), and D2, 64
  Dell PowerEdge **C6320** hosts (`UniMelb_C6320.csv`, added 2026-10-28). Each server model
  takes its power, temperature, cores and memory from its own dataset.
- One notebook, `data_prep.ipynb`, cleans both datasets and builds the scenarios. It is
  the project's only cleaning code. Run it top to bottom, or without opening it:
  `uv run jupyter-execute --inplace notebooks/data_prep.ipynb`. It runs in under a minute.
- **Servers:** 45 of 81 R840 servers and 44 of 64 C6320 servers have a usable power curve
  and thermal response.
- **D2 has no inlet temperature and no fan speeds.** Neither does any host, of either model,
  whose records start on 2019-02-01 (section 3.2). The C6320 inlet is taken from the R840
  room at the same timestamp, an assumption (decision 15).
- **Workloads:** 502 of 2,800 UFCG virtual machines qualify as finite workloads.
- The main scenario is `thesis10`, the ten-server fleet the thesis describes. Five
  experiments are built from it, each changing one aspect: `consolidated6` (the same work on six
  servers), `small` (for solver debugging), `thesis10_tight` (stricter deadlines),
  `thesis10_swing` (a deeper daily carbon swing) and `thesis10_warm` (a wider CRAC supply
  range).
- Several questions the thesis leaves open had to be decided to make the data fit. All
  are listed in section 5, and all are single values in
  the Settings cell of `notebooks/data_prep.ipynb`.
- Two findings matter for what the model will be able to show (section 8): idle power
  is 88% of baseline IT energy in `thesis10`, and the thesis still has no temperature
  equation.

---

## 2. Starting point

| Item | State before this work |
|---|---|
| `data/raw/UniMelb.csv` (613 MB) | Raw. Named by the thesis as the server dataset. Dataset D1 of the Zenodo record: Dell R840 servers |
| `data/raw/UniMelb_C6320.csv` (184 MB, added 2026-10-28) | Raw. Dataset D2 of the same record (`dataset2_combined.csv`): Dell C6320 servers |
| `data/raw/UFCG/*.csv` (about 8 GB, 7 files) | Raw. Chosen by the project owner as the workload dataset, replacing Bitbrains |
| `old_notebook.ipynb` | Colab data preparation built around Bitbrains; no optimization code |
| `PROJECT_CONTEXT.md` | Full model specification and a list of open questions; datasets only skimmed |

The request was made in two steps: first a cleaning plan, then to make the alignment
decisions that make most sense and configure the setup so the model's effect is as
visible as possible.

---

## 3. What the data profiling found

### 3.1 UniMelb D1: Dell R840 servers

2,748,525 rows, 81 servers (`qh2-rcc120` to `qh2-rcc200`), 10-minute records from 2018-10-09
to 2019-06-20.

| Finding | Size | Consequence for the model |
|---|---|---|
| `CPU_cores` changes from 64 to 128 on 2019-03-15 for every server, after about 24 hours where the field is null | 41% of rows are at 128 | Core count is not constant. Mean `CPU_Load` falls from 15.8 to 2.6 across the change and per-server idle power shifts by a median of 9 W |
| `CPU_Load` is on a 0 to 100 scale | 92 rows are at or below 0.01; 982,101 are at or below 1 | The 0.01 threshold in Eq. (17) has to be applied as 1.0 |
| Load never exceeds 68% (99th percentile 54%) | all servers | $P^{max}_s$ from Eq. (19) is power at partial load. Fitted full-load power is far higher (section 4.1) |
| Weak or negative power-to-load relationship | 14 servers never exceed 20% load; several have negative correlation | Eq. (20) is not meaningful for these servers |
| 486 apparent duplicate timestamps | 81 servers × 6 slots, 2019-04-07 02:00 to 02:50 | The repeated hour at the end of daylight saving. The values differ, so these are not true duplicates |
| Gaps | about 4 days from 2018-12-14 on roughly 40 servers; 21 hours on 2019-02-26 on all 81 | Lowers completeness; no effect on static parameters |
| `Inlet_Temperature` = 4.0 together with fan speed 280 | 140,255 rows on 9 servers | A failed-sensor reading, not a real temperature |
| Five servers (rcc196 to rcc200) start on 2019-02-01 | idle about 210 W against about 157 W elsewhere; no inlet and no fan readings at all | Ineligible anyway (26% complete). Same model and configuration as the other R840s (64 slots, 64.5 GB); the missing inlet follows when they joined the monitoring (section 3.2) |
| `Ram` is 64.45 to 64.49 with no documented unit | all rows | Resolved in section 5 |

### 3.2 UniMelb D2: Dell C6320 servers

1,281,024 rows, 64 servers (`qh2-rcc201` to `qh2-rcc264`), 10-minute records from 2019-02-01
to 2019-06-20. Columns as D1 except `Inlet_Temperature` and the four fan speeds, which D2
does not have. Host names never overlap with D1.

| Finding | Size | Consequence for the model |
|---|---|---|
| No inlet temperature, no fan speeds | all 64 hosts | The thermal fit $T_{cpu} = T_{inlet} + a + R \cdot P$ needs an inlet from elsewhere (decision 15) |
| `CPU_cores` counts vCPU slots: 80 in the first hosts' first three days, then 160; 320 on some hosts from 2019-03-15, each on its own date | 101,393 records (8%) above 160 | No single change date as in D1, so records at a doubled count are dropped one by one. On the four hosts with many low-load records at both counts, power at load ≤ 5% is 1 to 28 W higher at the doubled count |
| `CPU_cores` is missing | 202,576 records, all up to 2019-03-15 11:00 (about half of the records to that date) | Kept: no host had doubled yet |
| `Power` or `CPU_Load` missing | 148,640 records after the steps above | Dropped, as for D1 |
| Repeated daylight-saving hour on 2019-04-07 | 64 servers × 6 records (348 left after the slot-count step) | Removed by the duplicate step |
| Two hosts differ: `qh2-rcc263`, `qh2-rcc264` | 258 GB of memory and 48, later 96, slots (the other 62: 193 GB, 160 slots); rcc263 draws 286 to 374 W, rcc264 never reports power | Another configuration: kept in the table, not eligible (decision 16) |
| `qh2-rcc248` draws 286 to 390 W at up to 50% load, with CPUs at about 35 °C | 1 host | Unlike the other C6320s (about 390 W idle, 765 W peak, 78 °C at the median) and like rcc263. It passes every gate, so it is eligible; see section 8 |
| Power follows each host's own CPU load | median correlation 0.95 over the 44 eligible hosts | A per-host reading, not a shared chassis reading |

**The missing inlet follows the monitoring start, not the server model.** The 76 R840 hosts
recorded since October 2018 report inlet and fans. Every host whose records start on
2019-02-01 reports neither: all 64 C6320s and the five R840s `qh2-rcc196` to `qh2-rcc200`,
which are the same model and configuration as the R840s that do report inlet. The
collection set up in February 2019 most likely did not read those sensors. The notebook
prints the five R840 hosts in section 1.6.

### 3.3 UFCG (workloads)

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

Both server models go through the same steps and gates and are written to one table, 145
rows, with a `model` column (`R840` or `C6320`) and an `inlet_source` column (`measured`, or
`d1_room_mean` for the C6320s). The R840 steps come first; the C6320 steps follow below.

**R840 (D1)**

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
| $M_s$ | largest `Ram` × 1,024 MB (`Ram` is in GB) | 66,036 MB (64 GB) |

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

**C6320 (D2)**

| Step | Before | After |
|---|---|---|
| Drop records at a doubled slot count (`CPU_cores` above 160) | 1,281,024 rows | 1,179,631 rows |
| Drop duplicate (server, time) | 1,179,631 | 1,179,283 |
| Drop rows missing `CPU_Load` or `Power` | 1,179,283 | 1,030,643 |
| Inlet from the R840 room (decision 15) | 7,454 records at a timestamp with no R840 reading, left out of the thermal fit | |
| Servers passing all gates | 64 servers | **44 servers** |

The slot-count step is the C6320 form of the R840's 64-core cut: the cloud doubled the slots
on each C6320 host at its own date, so the cut is per record. Records with no count (all
before 2019-03-15 11:00) are kept.

**Gates.** The R840 gates and thresholds unchanged (90% complete, 30% peak load, correlation
0.8, 30 near-idle records, a valid thermal fit, here with the room inlet), with completeness
measured over D2's own period, 2019-02-01 to 2019-06-20, plus a configuration gate that
leaves out `qh2-rcc263` and `qh2-rcc264` (decision 16). Of the 20 that fail: 19 on
completeness, 6 on peak load, 4 on idle records, 3 on correlation, 2 with no thermal fit, 2
on configuration. Completeness is the main loss: `qh2-rcc201` to `rcc205` and `rcc207` hold
almost all the records at the doubled slot count, and the other failures on completeness have
long gaps in `Power` or `CPU_Load`.

**Parameters derived per server**

| Parameter | Rule | Range across the 44 eligible C6320s (min / median / max) | R840, for comparison (median) |
|---|---|---|---|
| $P^{idle}_s$ | as for the R840 | 286.0 / 390.8 / 392.4 W | 155.2 W |
| $P^{max}_s$ | as for the R840 | 390.0 / 767.4 / 806.0 W | 358.8 W |
| Fitted power at 100% load | as for the R840 | 393 / 1,023 / 1,351 W | 589 W |
| $T^0_s$ | as for the R840 | 36.0 / 53.8 / 60.5 °C | 63.0 °C |
| Peak load reached | | 31.8 / 58.1 / 86.3% | |
| $N^{cores}_s$, $C_s$ | 80 (decision 2) | constant | 64 |
| $M_s$ | median of the host's `Ram` × 1,024 MB | 197,972 MB (193 GB) | 66,036 MB |
| Mean inlet (room mean at the host's records) | decision 15 | 18.81 / 18.87 / 18.87 °C | 18.2 °C (measured) |

The minimum $P^{idle}$ and $P^{max}$ are both `qh2-rcc248` (section 3.2); without it the
eligible C6320s idle at 365 to 392 W.

| Thermal coefficient | C6320 min / median / max | R840 median |
|---|---|---|
| $R$ (°C per watt) | 0.030 / 0.079 / 0.109 | 0.148 |
| $a$ (°C) | -18.4 / 0.9 / 19.4 | 8.5 |
| $\alpha$ at 5 minutes | 0.907 / 0.964 / 0.995 | 0.924 |
| Steady-state error (RMSE) | 2.0 / 3.3 / 4.7 °C | 2.6 °C |

A C6320's temperature rises about half as much per watt as an R840's, over a power range
about twice as wide, and its fit is about 0.8 °C less accurate at the median, as expected
with an inlet that is the room's and not the server's own.

**The C6320 servers**

| Server | Eligible | Complete | Peak load (%) | Corr. | $P^{idle}$ (W) | $P^{max}$ (W) | Fit at 100% (W) | $R$ (°C/W) | RMSE (°C) | Gates failed |
|---|---|---|---|---|---|---|---|---|---|---|
| qh2-rcc201 | no | 0.26 | 61.0 | 0.82 | 390.3 | 743.2 | 1,314 | 0.072 | 3.10 | completeness |
| qh2-rcc202 | no | 0.26 | 33.1 | 0.86 | 390.3 | 629.6 | 1,107 | 0.768 | 6.20 | completeness |
| qh2-rcc203 | no | 0.26 | 53.4 | 0.99 | 390.4 | 625.7 | 1,147 | 0.090 | 4.53 | completeness |
| qh2-rcc204 | no | 0.21 | 31.0 | 0.83 |  | 603.2 | 1,803 | 0.057 | 1.58 | completeness, idle records |
| qh2-rcc205 | no | 0.24 | 27.1 | 0.95 | 390.7 | 573.3 | 1,736 | 0.045 | 3.51 | completeness, peak load |
| qh2-rcc206 | yes | 0.99 | 31.8 | 0.98 | 392.1 | 615.8 | 1,351 | 0.030 | 4.20 |  |
| qh2-rcc207 | no | 0.26 | 30.2 | 0.63 | 390.7 | 606.2 | 1,074 | 0.415 | 2.74 | completeness, correlation |
| qh2-rcc208 | no | 0.87 | 57.8 | 0.98 | 390.8 | 780.0 | 1,065 | 0.085 | 3.59 | completeness |
| qh2-rcc209 | yes | 0.99 | 44.9 | 0.96 | 390.7 | 646.1 | 945 | 0.061 | 3.25 |  |
| qh2-rcc210 | yes | 0.99 | 49.6 | 0.95 | 390.4 | 743.6 | 1,019 | 0.073 | 3.24 |  |
| qh2-rcc211 | yes | 0.98 | 50.2 | 0.98 | 390.8 | 796.0 | 1,111 | 0.099 | 4.12 |  |
| qh2-rcc212 | yes | 0.92 | 53.4 | 0.98 | 391.5 | 666.0 | 1,021 | 0.086 | 3.04 |  |
| qh2-rcc213 | yes | 0.99 | 57.3 | 0.92 | 391.5 | 760.1 | 1,024 | 0.078 | 2.89 |  |
| qh2-rcc214 | yes | 0.98 | 37.1 | 0.97 | 390.4 | 695.1 | 1,102 | 0.077 | 3.59 |  |
| qh2-rcc215 | yes | 0.94 | 49.2 | 0.97 | 388.8 | 724.1 | 952 | 0.108 | 4.52 |  |
| qh2-rcc216 | yes | 0.98 | 61.6 | 0.95 | 390.5 | 795.2 | 995 | 0.076 | 2.78 |  |
| qh2-rcc217 | yes | 0.97 | 49.1 | 0.98 | 390.4 | 767.4 | 1,064 | 0.087 | 4.67 |  |
| qh2-rcc218 | yes | 0.99 | 61.3 | 0.93 | 390.9 | 804.3 | 1,023 | 0.095 | 3.39 |  |
| qh2-rcc219 | yes | 0.99 | 69.5 | 0.92 | 390.5 | 790.4 | 986 | 0.079 | 3.11 |  |
| qh2-rcc220 | yes | 0.99 | 86.3 | 0.91 | 390.8 | 806.0 | 913 | 0.087 | 2.94 |  |
| qh2-rcc221 | yes | 0.99 | 61.5 | 0.94 | 390.8 | 760.1 | 1,032 | 0.078 | 3.32 |  |
| qh2-rcc222 | yes | 0.99 | 61.7 | 0.94 | 390.8 | 769.6 | 1,012 | 0.075 | 3.23 |  |
| qh2-rcc223 | yes | 0.99 | 60.7 | 0.96 | 391.1 | 790.4 | 1,076 | 0.091 | 3.36 |  |
| qh2-rcc224 | yes | 0.99 | 61.1 | 0.95 | 390.9 | 780.0 | 1,049 | 0.073 | 2.65 |  |
| qh2-rcc225 | yes | 0.99 | 62.1 | 0.95 | 391.5 | 806.0 | 1,040 | 0.065 | 3.47 |  |
| qh2-rcc226 | no | 0.21 | 7.1 | 0.60 | 392.2 | 468.0 | 1,489 | 1.357 | 5.67 | completeness, peak load, correlation, idle records |
| qh2-rcc227 | yes | 0.99 | 73.6 | 0.92 | 391.2 | 780.0 | 960 | 0.074 | 3.52 |  |
| qh2-rcc228 | yes | 0.99 | 49.8 | 0.97 | 392.2 | 754.4 | 1,089 | 0.072 | 3.41 |  |
| qh2-rcc229 | yes | 0.99 | 73.3 | 0.94 | 390.6 | 772.6 | 935 | 0.079 | 4.02 |  |
| qh2-rcc230 | yes | 0.99 | 46.0 | 0.95 | 390.4 | 684.2 | 1,027 | 0.096 | 3.37 |  |
| qh2-rcc231 | yes | 0.99 | 59.1 | 0.95 | 390.6 | 754.0 | 1,016 | 0.077 | 3.72 |  |
| qh2-rcc232 | yes | 0.99 | 49.2 | 0.96 | 390.8 | 780.0 | 1,033 | 0.083 | 3.49 |  |
| qh2-rcc233 | yes | 0.99 | 58.1 | 0.92 | 390.5 | 778.7 | 985 | 0.077 | 3.07 |  |
| qh2-rcc234 | yes | 0.99 | 48.7 | 0.96 | 391.0 | 670.4 | 1,163 | 0.079 | 3.09 |  |
| qh2-rcc235 | yes | 0.99 | 61.4 | 0.95 | 364.7 | 759.6 | 965 | 0.067 | 2.85 |  |
| qh2-rcc236 | yes | 0.91 | 62.1 | 0.97 | 390.4 | 747.9 | 1,014 | 0.109 | 3.54 |  |
| qh2-rcc237 | yes | 0.93 | 53.2 | 0.97 | 385.0 | 763.5 | 1,024 | 0.082 | 2.71 |  |
| qh2-rcc238 | yes | 0.99 | 57.7 | 0.95 | 390.9 | 740.1 | 1,078 | 0.085 | 3.41 |  |
| qh2-rcc239 | yes | 0.99 | 57.6 | 0.97 | 392.3 | 715.4 | 917 | 0.094 | 3.26 |  |
| qh2-rcc240 | no | 0.86 | 47.4 | 0.99 | 392.0 | 640.5 | 1,218 | 0.084 | 3.57 | completeness |
| qh2-rcc241 | no | 0.78 | 57.8 | 0.94 | 391.0 | 701.6 | 1,009 | 0.118 | 3.96 | completeness |
| qh2-rcc242 | no | 0.84 | 50.1 | 0.92 | 390.5 | 751.8 | 1,091 | 0.101 | 3.95 | completeness |
| qh2-rcc243 | yes | 0.99 | 62.0 | 0.94 | 390.6 | 751.8 | 1,015 | 0.069 | 3.06 |  |
| qh2-rcc244 | no | 0.76 | 19.6 | 0.96 | 390.9 | 523.0 | 1,084 | 0.041 | 4.41 | completeness, peak load |
| qh2-rcc245 | yes | 0.99 | 49.2 | 0.97 | 390.7 | 773.9 | 1,054 | 0.086 | 3.27 |  |
| qh2-rcc246 | yes | 0.99 | 69.3 | 0.97 | 390.5 | 746.6 | 947 | 0.053 | 4.58 |  |
| qh2-rcc247 | no | 0.73 | 49.4 | 0.97 | 388.0 | 742.3 | 1,158 | 0.077 | 3.57 | completeness |
| qh2-rcc248 | yes | 0.99 | 50.2 | 0.89 | 286.0 | 390.0 | 393 | 0.080 | 2.04 |  |
| qh2-rcc249 | yes | 0.99 | 53.0 | 0.97 | 391.7 | 755.3 | 1,084 | 0.079 | 3.48 |  |
| qh2-rcc250 | no | 0.79 | 57.1 | 0.99 | 371.1 | 734.5 | 994 | 0.079 | 3.22 | completeness |
| qh2-rcc251 | yes | 0.99 | 61.3 | 0.94 | 390.8 | 780.0 | 1,021 | 0.066 | 3.16 |  |
| qh2-rcc252 | yes | 0.97 | 49.1 | 0.96 | 373.0 | 761.4 | 1,079 | 0.084 | 4.34 |  |
| qh2-rcc253 | yes | 0.99 | 49.7 | 0.97 | 378.9 | 773.1 | 1,091 | 0.090 | 3.48 |  |
| qh2-rcc254 | yes | 0.97 | 49.9 | 0.98 | 391.0 | 780.4 | 1,075 | 0.081 | 2.54 |  |
| qh2-rcc255 | yes | 0.99 | 61.8 | 0.94 | 390.6 | 780.0 | 1,020 | 0.079 | 2.75 |  |
| qh2-rcc256 | no | 0.90 | 49.2 | 0.90 | 391.4 | 761.8 | 969 | 0.088 | 2.82 | completeness |
| qh2-rcc257 | no | 0.99 | 24.4 | 0.98 | 391.2 | 610.6 | 1,312 | 0.094 | 3.08 | peak load |
| qh2-rcc258 | no | 0.53 | 73.3 | 0.97 | 390.6 | 770.9 | 917 | 0.077 | 3.06 | completeness |
| qh2-rcc259 | yes | 0.99 | 61.8 | 0.94 | 391.0 | 785.6 | 984 | 0.077 | 2.25 |  |
| qh2-rcc260 | yes | 0.99 | 64.8 | 0.93 | 391.6 | 806.0 | 977 | 0.086 | 3.32 |  |
| qh2-rcc261 | yes | 0.99 | 61.5 | 0.96 | 392.4 | 806.0 | 1,046 | 0.088 | 3.43 |  |
| qh2-rcc262 | no | 0.88 | 37.8 | 0.97 | 368.0 | 702.0 | 1,146 | 0.093 | 3.63 | completeness |
| qh2-rcc263 | no | 0.02 | 17.1 | 0.96 |  | 374.0 | 725 |  |  | completeness, peak load, idle records, thermal fit, configuration |
| qh2-rcc264 | no | 0.00 |  |  |  |  |  |  |  | completeness, peak load, correlation, idle records, thermal fit, configuration |

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
runtime limits. `consolidated6` then reaches its 60% load target with 330 workloads, 96 of them
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
| 2 | UniMelb core count | R840: 64, 64-core period only. C6320: 80, records at a doubled slot count (above 160) dropped | Sections 3.1, 3.2. `CPU_cores` counts vCPU slots; 64 and 80 are the counts before the cloud doubled them (the first C6320 hosts show 80 for three days, then 160), read as hardware threads. Stated in the thesis as an assumption |
| 3 | Unit of `Ram` | GB: $M_s$ = 66,036 MB (64 GB) for an R840 (largest `Ram`), 197,972 MB (193 GB) for a C6320 (median `Ram`) | The R840 hosts have 64 GB (Ilager et al., UCC 2023) and their largest `Ram_Used` is 64.42. Revised from the 8 GB unit of 2026-10-09 |
| 4 | Capacity unit for $C_s$ and $C^{req}_i$ | cores; one vCPU occupies one core | Keeps Eq. (12), (15), (16) on one scale |
| 5 | Unit of work (A10) | one vCPU at 100% = 2,400 MHz | UFCG reports percent, not MHz; 2,400 is the middle of the thesis's three frequencies |
| 6 | Eq. (22) (B2) | treated as an equality | The text describes a subtraction |
| 7 | Which servers get which frequency (E2) | **From SPEC results for the server model's processor, not from power.** Each fleet is a table of server rows (model, frequency, zone, cold plate): R840 at 2.1 GHz (Xeon Gold 6130) and 2.4 GHz (Xeon Gold 6148), both SPEC CPU2017 results of 2018 Q2; C6320 at 2.6 GHz (Xeon E5-2690 v4, SPEC CPU2006, 2017 Q3). Ten servers: 3 / 4 / 3; six: 2 / 2 / 2. Each row's host is drawn by seed from the eligible hosts of its model, without regard to power | The thesis group's guide of 2026-10-28. UniMelb names no processor, and the 2.4 and 2.6 GHz processors do not match the datasets' slot counts, so the frequencies are stated in the thesis as assumptions taken from SPEC. Replaces the earlier rule (highest frequency to the highest $P^{max}_s$, tiers 2.1 / 2.4 / 3.0 GHz) |
| 8 | Cold plates, $CT_s$ (E1) | **on the C6320 servers** (2.6 GHz), which are also CRAC-cooled for the heat the plate does not remove | The group's guide: the C6320s are cooled by CRAC air plus a cold plate, the R840s by CRAC air only. Replaces "on the 3.0 GHz servers" |
| 9 | Zones | 2, set per server row of the fleet table, alternating 1, 2, 1, ... | Needed for the zoning subproblem; matches the group's fleet tables |
| 10 | Time-sensitive flag, $RT_i$ | about 30% of workloads, by a seeded hash of each workload's UFCG VM id | Not in any dataset. Keyed per workload so the flag does not change when other workloads enter or leave the catalogue |
| 11 | Deadlines, $D_i$ | time-sensitive: 25% slack; delay-tolerant: 2 × baseline time, clamped to 2 to 8 hours | Leaves room for throttling and for moving work across the carbon profile |
| 12 | Carbon intensity, $CI_t$ (D4) | 621.73 g/kWh mean with a ±25% daily shape (midday dip, evening peak) | A flat annual value gives time-shifting no carbon benefit |
| 13 | Usage during collector outages | the VM's own mean usage | The VM was alive but unobserved. Skipping these slots undercounted $W_i$ |
| 14 | VMs on unmonitored hosts | dropped by default; same-flavor hot-deck imputation behind a switch | No usage was ever recorded for them. Imputed work is borrowed, not measured |
| 15 | C6320 inlet temperature | **the R840 room's measured inlet at the same timestamp**: per 10-minute record, the mean over R840 hosts with a valid inlet (the 4.0 °C failed-sensor value excluded). Over D2's period it averages 18.84 °C, SD 0.62 (17.6 to 22.6 °C), from a median of 71 R840 hosts per record. Used for the C6320 thermal fits and the thermal-fit gate | D2 has no inlet (section 3.2). Assumes the C6320s draw the same room air as the R840s. Stated in the thesis as an assumption |
| 16 | `qh2-rcc263`, `qh2-rcc264` | kept in `servers.csv` with `eligible = 0` (configuration gate) | 258 GB, 48 then 96 slots and 286 to 374 W (rcc264 reports no power): another configuration than the other 62 C6320s |

Two consequences worth knowing:

- With decision 3, memory fills before cores: an R840 offers 1 GB per core and a C6320
  2.4 GB, against 2 GB per vCPU in the common flavors. Across the fleet, memory is the
  binding resource.
- With decision 4, the mapping is conservative. UniMelb hosts themselves ran up to
  1.58 vCPUs per core.

---

## 6. Scenarios

> **Out of date.** This section describes the scenarios of 2026-10-09 (`thesis10` and its
> experiments, tiers 2.1 / 2.4 / 3.0 GHz, servers picked by power). The scenarios are rebuilt
> from the fleet tables of decision 7; their figures are in each scenario's `params.json`.

Built by `data_prep.ipynb` part 3 into `scenarios/<name>/`. Arrivals across the whole
year are pooled into one day, keeping each workload's time of day, because cleaned
workloads arrive at only about 1.4 per day. Workloads are drawn in seeded random order
until peak requested vCPUs reach 60% of fleet cores or the catalogue runs out. In every
scenario the catalogue ran out first.

**`thesis10` is the main scenario**: the data center as the thesis describes it, ten
servers split 4 / 3 / 3 across 2.1 / 2.4 / 3.0 GHz (text beside Eq. 15). It is built
first, and its results are the main results. Every other scenario is an **experiment**:
thesis10 with one aspect changed, so its effect is read as the difference from thesis10.
Each experiment's `params.json` records what it changes under `variant_of`.

| Scenario | Changed from `thesis10` | Question it answers |
|---|---|---|
| `thesis10` | (main scenario) | |
| `consolidated6` | 6 servers (2 / 2 / 2) | What happens when the same work runs on a consolidated fleet? |
| `small` | 3 servers, 8 h from 12:00, shorter workloads and slack | None: solver checks and debugging |
| `thesis10_tight` | 50% time-sensitive; delay-tolerant slack 1 × $ET^{base}_i$ within 30 min to 2 h | How much of the saving depends on how long workloads may wait? |
| `thesis10_swing` | carbon-intensity daily swing ±50% of the mean, not ±25% | How much more is saved on a grid whose carbon intensity varies more over the day? |
| `thesis10_warm` | CRAC supply air up to 32 °C, not 27 °C | How much does a wider cooling envelope save? |

18 to 27 °C is the ASHRAE recommended supply range, and 32 °C is the top of its A1
allowable range and the zone air limit $T^{max}_z$. A flat carbon intensity and regrouped
cooling zones need no scenario of their own: they are run switches on thesis10
(`--ci-flat`, `--zone-map`).

| | `thesis10` | `consolidated6` | `small` | `thesis10_tight` | `thesis10_swing` | `thesis10_warm` |
|---|---|---|---|---|---|---|
| Servers (2.1 / 2.4 / 3.0 GHz) | 10 (4 / 3 / 3) | 6 (2 / 2 / 2) | 3 (1 / 1 / 1) | 10 (4 / 3 / 3) | 10 (4 / 3 / 3) | 10 (4 / 3 / 3) |
| Workloads | 238 | 238 | 99 | 238 | 238 | 238 |
| Time-sensitive workloads | 71 | 71 | 32 | 123 | 71 | 71 |
| Median slack, delay-tolerant (periods) | 24 | 24 | 14 | 14 | 24 | 24 |
| Horizon | 288 periods (24 h from 06:00) | 288 periods | 96 periods (12:00 to 20:00) | 288 periods | 288 periods | 288 periods |
| Fleet cores | 640 | 384 | 192 | 640 | 640 | 640 |
| Peak requested vCPUs | 168 | 168 | 66 | 168 | 168 | 168 |
| Peak demand, share of fleet | 26% | 44% | 34% | 26% | 26% | 26% |
| Peak demand, share of fastest tier | 88% | 131% | 103% | 88% | 88% | 88% |
| Servers capped below full load at 18 °C inlet | 5 | 2 | 1 | 5 | 5 | 5 |
| Servers capped below full load at the warmest inlet | 10 (27 °C) | 6 (27 °C) | 3 (27 °C) | 10 (27 °C) | 10 (27 °C) | 10 (32 °C) |
| Assignment binaries inside time windows | 153,020 | 91,812 | 6,762 | 103,480 | 153,020 | 153,020 |
| Carbon intensity range (g/kWh) | 489 to 777 | 489 to 777 | 489 to 777 | 489 to 777 | 356 to 933 | 489 to 777 |

Only workloads with a baseline execution time of 3 to 144 periods are admitted (240 of
the 502). Below 3 periods a VM did almost no work in its whole life; above 144 it
cannot finish with slack inside a day.

### 6.1 Why `consolidated6` is kept as an experiment

With this workload set, the ten servers of thesis10 peak at 26% load, and demand does not
even fill the fastest tier, so the model can keep most work on efficient servers. Six
servers put peak demand at 44% of the fleet and 131% of the fastest tier, so work must
spill onto less efficient machines, and each server runs closer to its thermal limit.
`consolidated6` shows how the results change when the same work runs on a consolidated
fleet. It was the first scenario built, under the name `consolidated6`; it was renamed on
2026-10-19 so that the name no longer suggests it is the main scenario. Older material in
`archive/` still uses the old name.

### 6.2 The `thesis10` fleet

| s | Server | Zone | Frequency | Cold plate | $P^{idle}$ (W) | $P^{max}$ (W) | Max load at 18 °C / 27 °C inlet |
|---|---|---|---|---|---|---|---|
| 1 | qh2-rcc165 | 1 | 2.1 GHz | no | 164.8 | 328.3 | 100% / 94% |
| 2 | qh2-rcc176 | 2 | 2.1 GHz | no | 158.3 | 344.0 | 100% / 92% |
| 3 | qh2-rcc158 | 1 | 2.1 GHz | no | 158.7 | 352.3 | 100% / 76% |
| 4 | qh2-rcc127 | 2 | 2.1 GHz | no | 151.9 | 358.0 | 88% / 61% |
| 5 | qh2-rcc132 | 1 | 2.4 GHz | no | 160.6 | 358.8 | 82% / 58% |
| 6 | qh2-rcc163 | 2 | 2.4 GHz | no | 155.2 | 360.0 | 93% / 70% |
| 7 | qh2-rcc150 | 1 | 2.4 GHz | no | 157.4 | 368.0 | 100% / 76% |
| 8 | qh2-rcc133 | 2 | 3.0 GHz | yes | 152.8 | 368.0 | 100% / 80% |
| 9 | qh2-rcc183 | 1 | 3.0 GHz | yes | 153.1 | 380.5 | 87% / 60% |
| 10 | qh2-rcc174 | 2 | 3.0 GHz | yes | 143.8 | 393.2 | 87% / 60% |

"Max load" is the highest steady utilization that keeps the server at or under 80 °C
(the 90 °C limit less the 10 °C headroom), using the fitted thermal response and
ignoring cold plates. Servers were picked from the 45 eligible at evenly spaced points
across the range of dynamic power, which avoids the extremes. The experiments with ten
servers use this fleet; `consolidated6` and `small` pick six and three servers by the same rule.

### 6.3 Reference schedule

Each scenario includes a thermally unaware baseline: every workload starts at arrival
on the least-loaded server with room. It supplies the existing assignment $X^0_{is}$
and a figure to compare the model against.

| | `thesis10` | `consolidated6` | `small` | `thesis10_tight` | `thesis10_swing` | `thesis10_warm` |
|---|---|---|---|---|---|---|
| IT energy (kWh) | 42.27 | 26.27 | 4.45 | 42.27 | 42.27 | 42.27 |
| IT carbon (kg CO₂) | 26.29 | 16.33 | 2.82 | 26.29 | 26.30 | 26.29 |
| Workloads late or unplaced | 0 | 0 | 0 | 0 | 0 | 0 |

These cover server energy only, by Eq. (16), (20), (3), and (6). Cooling energy is not
included, and the baseline ignores temperature entirely. The three thesis10 experiments
share thesis10's servers and workloads, so their reference schedules are the same; only
the deadlines, the carbon profile or the cooling range differ.

---

## 7. What was produced

| Path | Contents |
|---|---|
| `pyproject.toml` | Dependencies (DuckDB, NumPy), run through `uv` |
| `notebooks/data_prep.ipynb` | The cleaning and scenario pipeline, step by step, with outputs and checks. Its first code cell holds every decision and scenario setting, commented |
| `archive/notebooks/before_after_missing_data_fixes.ipynb` | Compares outputs before and after the 2026-10-10 fixes (section 10) |
| `archive/data_2026-10-09_before_missing_data_fixes/` | Cleaned tables and scenarios as they were before those fixes |
| `data/clean/servers.csv` | All 145 servers (81 R840, 64 C6320) with parameters, `model`, `inlet_source` and an `eligible` flag |
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

1. **Idle power is 88% of baseline IT energy in `thesis10`** (82% in `consolidated6`). The model
   has no server on/off variable, so idle draw is paid whatever the schedule is.
   Scheduling can only move the remaining 12% plus cooling energy. Expect small percentage changes in the
   objective unless a power-off decision is added to the model.
2. **The thesis still has no temperature equation** (A1 to A3). The fitted thermal
   response is offered for it, but adopting it is a modelling decision that has not
   been made. It also covers air cooling only; nothing in the data describes cold
   plates.
3. **$P^{max}_s$ understates full-load power.** It is observed at no more than 68%
   load on the R840s and 86% on the C6320s (median eligible C6320: 58%). The fitted
   full-load value is about 64% higher at the median on the R840s and 33% on the C6320s.
   Eq. (19) was kept as written.

**Assumptions to confirm**

4. **Carbon intensity.** The 621.73 g/kWh mean is the Philippines 2024 figure from the
   thesis's cited source, read through an automated summary of the page rather than
   checked by hand. The country is inferred from the university, not stated in the
   thesis. The daily shape is synthetic.
5. **C6320 inlet (decision 15).** Borrowed from the R840 room. If the C6320s stood in
   warmer or cooler air, their fitted offset $a$ absorbs the difference on average but not
   its variation; their thermal fit is 0.8 °C less accurate than the R840s' at the median.
   The thesis states this as an assumption.
6. **`qh2-rcc248`** passes every gate but draws 286 to 390 W with CPUs at about 35 °C,
   unlike every other eligible C6320 (365 to 392 W idle) and like `qh2-rcc263`. It may be
   another configuration, or its power reading may come from another sensor. It is
   eligible as the gates stand, so a seeded draw can pick it; leaving it out would be a
   decision like 16.
7. **Time-sensitive share and deadline rule** are invented for the scenario and have
   no empirical basis.
8. **Six servers instead of ten** in the `consolidated6` experiment departs from the thesis
   text on purpose; the main scenario, `thesis10`, follows it.

**Data caveats**

9. **Pooled arrivals.** One simulated day combines VMs that arrived on different dates
   over a year. Time-of-day pattern is real; day-level concurrency is constructed.
10. **Different eras and sites.** Servers are from Melbourne in 2018-19 and workloads
   from Campina Grande in 2024-25. They are matched by position, not by calendar.
11. **Requested versus used capacity.** Utilization in the model follows requested
    vCPUs, while VMs used a median of 2.7% of them.

**Not yet done**

12. The optimization model, including the linearizations the thesis promises but does
    not contain (A5).
13. Solver tractability is untested. `consolidated6` has about 92,000 assignment binaries
    inside time windows; whether that solves in reasonable time is unknown.
14. Rolling-horizon state: every workload has $B_i = 0$ and every server is always
    available.

---

## 9. Sources

- Ilager, Ramamohanarao, Buyya, *Thermal Prediction for Efficient Energy Management of
  Clouds using Machine Learning*: https://ar5iv.labs.arxiv.org/html/2011.03649
- Ilager et al. (UCC 2023), the two UniMelb datasets (D1, R840; D2, C6320): Zenodo record
  https://zenodo.org/records/10069402
- SPEC CPU2017 and CPU2006 results for the processors of decision 7:
  https://www.spec.org/cpu2017/results/res2018q2/cpu2017-20180514-05589.html (Xeon Gold 6130),
  https://www.spec.org/cpu2017/results/res2018q2/cpu2017-20180514-05562.html (Xeon Gold 6148),
  https://www.spec.org/cpu2006/results/res2017q3/cpu2006-20170725-47889.html (Xeon E5-2690 v4)
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
above, 101 of the 232 workloads in `consolidated6` both before and after had switched flag, and
their deadlines moved with it. The flag is now a seeded hash of each workload's UFCG VM
id. Tested by turning imputation on, which adds 92 workloads to `consolidated6` and renumbers
478 workload ids: none of the 234 workloads in both builds changed flag. This one-time
change produced a new, equally random assignment (71 of 238 in `consolidated6`). The workload
set, peak load and reference energy are unchanged by it.

The notebook's Eq. (14) check now uses the exact rounding bound per slot. The previous
relative tolerance failed on 30 imputed workloads whose flat usage profiles round the
same way in every slot; all were within the bound.
