# PRD: ThermaSched, a thermal-aware scheduling and air-liquid cooling model

Condensed from `thesisb.pdf` (53 pp.: Base Run Model, expected outputs, the "missing
equations" Q&A, the cold-plate follow-up, Ch. 5 checks, and the Ch. 6 scenarios).
Equation numbers (Eq. N) follow `thesisb.pdf`. Where the PDF contradicts itself, this
document records the decision that was made, or lists it under Open questions (§10).

---

## 1. Summary

ThermaSched is an optimization model for one heterogeneous data center. Over a
multi-period horizon it decides:

- which server each workload runs on
- when each workload starts
- whether workloads that are waiting (not yet started) get moved to another server
- CRAC supply-air temperature and airflow for each cooling zone
- cold-plate coolant temperature and flow for each server that has cold plates

It does this while **minimizing total operational carbon emissions** from IT, CRAC and
cold-plate energy. Every run is compared against a baseline schedule. The outputs are
the tables and charts that Ch. 4 (base run) and Ch. 6 (scenarios) of the thesis need.

## 2. Problem

Workload placement, thermal management and cooling control are usually optimized
separately, but each one drives the others:

- placement sets utilization, which sets IT power and heat
- heat and cooling settings set server temperature
- temperature sets thermal headroom and throttling (DPF)
- throttling stretches execution time, which can cause missed deadlines

In an air-liquid data center the coupling is tighter, because every server is cooled by
CRAC air and only some servers also have cold plates. The thesis needs one model that
captures all of these links together.

## 3. Goals and non-goals

**Goals**
1. Minimize total carbon emissions $CE^{total}$ (Eq. 1, 8).
2. Satisfy every hard constraint: capacity, deadlines, allowable delay, thermal safety,
   and cooling equipment limits.
3. Produce the decision and system variables, compliance tables and charts listed in §8.
4. Run the four Ch. 6 scenario families (§9) by changing inputs or switches, without
   changing code.
5. When no feasible solution exists, report that clearly and say which limits caused it.

**Non-goals**
- Turning servers off. All servers stay on for the whole horizon and draw idle power
  (decided in the Q&A, item 5). Carbon savings must come from scheduling and cooling.
- Migrating workloads that are already running ($B_i = 1$ stays on its server).
- Airflow mixing, recirculation or CFD. Cooling is modeled at zone level.
- Storage and network resources. Multi-site or geo-distributed scheduling.
- Soft constraints or extra fallback rules. Limits are strict (Q&A, "Additional
  Questions").

## 4. Users

- **Thesis authors**: run the base case and scenarios, then export tables and charts for
  Ch. 4–6.
- **Adviser and panel**: check compliance tables to confirm the model respects every
  limit.

## 5. Inputs

### 5.1 Data sources
| Data | Source | Fields used |
|---|---|---|
| Servers | UniMelb | CPU cores $N^{cores}_s$, memory $M_s$, observed power $P^{obs}_{st}$, observed utilization $U^{obs}_{st}$, CPU1/CPU2 temperatures (for $T^0_s$ and fitting α, a, R) |
| Workloads | UFCG (Bitbrains dropped, per PROJECT_CONTEXT.md) | $A_i$, $D_i$, $C^{req}_i$, $M^{req}_i$, $U^{CPU}_{it}$, $ET^{base}_i$, $RT_i$ |
| Carbon intensity $CI_t$ | Our World in Data, electricity mix, 2024 | per period |
| CPU frequency $f_s$ | Li et al. (2026): 2.1 / 2.4 / 3.0 GHz, split 4 / 3 / 3 across 10 servers (Marahatta et al., 2021) | UniMelb has no frequency data |

- Time step: Δt = 5 min.
- Base case: the `thesis10` scenario, 238 workloads on the 10-server fleet of the thesis
  text. Each workload fits on at least one server. Experiments built from it change one
  aspect each; the six-server fleet (`consolidated6`) is one of them.
- vCPU is matched to cores as 1 vCPU = 1 core. This still needs confirmation (§10).

### 5.2 Parameters (resolved values)
| Group | Parameter | Value |
|---|---|---|
| Thermal | $T^{max}_s$ (max server temp) | 90 °C |
| | $H^{min}$ (min headroom) | 10 °C |
| | $T^{dvfs}_s$ (throttling starts) | 75 °C |
| | $T^{throttle}_s$ (hard throttle) | 100 °C. Never reached because of the 90 °C cap, but kept |
| | $R^{dvfs}_s$ (max loss under DVFS) | 0.378 |
| | $F^{throttle}_s$ (fraction left when throttled) | 0.622 (= 1 − 0.378; the 0.662 in the parameter table is a typo) |
| | α_s, a_s, R_s | Fitted per server from UniMelb |
| CRAC (per zone) | $Q^{crac}_z$ (cooling capacity) | 116 kW |
| | Supply temperature range | 18–27 °C, whole degrees |
| | Airflow range | 0 – 6.56 m³/s (23,600 m³/h) |
| | $COP_z$ | $0.0068\,T^2 + 0.0008\,T + 0.458$, with T = CRAC supply temp |
| | $T^{max}_z$ (max zone temp) | 32 °C |
| Cold plate (per plate) | $Q^{cp}_s$ (cooling capacity) | 0.3 kW |
| | Coolant inlet temperature | 20–40 °C (the PDF gives 293.15–313.1 K) |
| | Flow settings | `thesisb.pdf` asks for 0.05, 0.10, 0.15, 0.20, 0.264, 0.30, 0.35 L/min. The code uses 0.10–0.30 in steps of 0.05, which follows `IE_Thesis_Master_Document.pdf` (2026-10-14). The two disagree (§10.1) |
| | Flow limits | 0.05–0.35 L/min (the printed 0.005 is a typo, already decided) |
| | Rated pump power / flow | 0.657 mW at 0.264 L/min (Wang & Tao, 2025) |
| | $R^{cp}$ vs flow (Wang et al., 2026, Fig. 10a, CPU1) | 0.1→0.1543, 0.15→0.1143, 0.2→0.0943, 0.25→0.0843, 0.3→0.0793 °C/W |
| | Plates per server | Editable. Default is 1 where $CT_s = 1$, else 0 |
| Physical | $c_{pw}$ (water) | 4,182 J/(kg·°C) (the table's "kJ" is a typo); water density 1 kg/L |
| | $c_{pa}$ (air) | 1.00643 kJ/(kg·°C) |
| Server power | $P^{idle}_s$ | Mean of $P^{obs}_{st}$ over periods with $U^{obs}_{st} \le 1\%$ (Eq. 17–18) |
| | $P^{max}_s$ | $\max_t P^{obs}_{st}$ (Eq. 19) |

## 6. Variables

**Decision variables**: $X_{is}$ (assignment), $Y_{ist}$ (running on s at t), $ST_i$
(start time), $O_{ij}$ (i scheduled before j), $r_{is}$ (reassignment),
$CRAC^{temp}_{zt}$ and $CRAC^{flow}_{zt}$, and $CP^{temp}_{st}$ and $CP^{flow}_{st}$.

**System variables**: $U_{st}$, $P^{IT}_{st}$, $Q^{heat}_{st}$, $T^{pred}_{st}$,
$TH_{st}$, $DPF_{st}$, $PC^{eff}_{st}$; $ET_i$, $CT_i$, $WT_i$; $Q^{crac,rem}_{zt}$,
$T^{return}_{zt}$, $P^{crac}_{zt}$, $T^{zone}_{zt}$; $Q^{cp,rem}_{st}$,
$T^{cp,out}_{st}$, $P^{cp}_{st}$; $E^{IT}_{st}$, $E^{crac}_{zt}$, $E^{cp}_{st}$,
$E^{total}_t$, $CE_t$, $CE^{total}$.

## 7. Model requirements

### 7.1 Objective
$$\min Z=\sum_t CI_t\Big[\sum_s E^{IT}_{st}+\sum_z E^{crac}_{zt}+\sum_s E^{cp}_{st}\Big]\quad(8)$$
Each energy term is its power × Δt (Eq. 3–5). $E^{cp}_{st}=0$ when server s has no cold
plates.

### 7.2 Constraints
| ID | Requirement | Eq. |
|---|---|---|
| **Assignment** | | |
| C1 | Each workload is assigned to exactly one server | 9 |
| C2 | A workload runs only on its assigned server, and only while that server is available | 10, 11 |
| C3 | Only workloads that have not started may be reassigned: $\sum_s r_{is} \le 1-B_i$ | 29 |
| **Capacity** | | |
| C4 | CPU and memory demand on each server stays within its capacity in every period | 12, 13 |
| **Power and heat** | | |
| C5 | $U_{st}=\sum_i C^{req}_i Y_{ist}/C_s$; $P^{IT}_{st}=P^{idle}_s+(P^{max}_s-P^{idle}_s)U_{st}$; $Q^{heat}_{st}=P^{IT}_{st}$ | 16, 20, 21 |
| **Timing and QoS** | | |
| C6 | $AD_i = D_i - A_i - ET^{base}_i$; $ST_i\ge A_i$; $WT_i=ST_i-A_i\le AD_i$; $CT_i=ST_i+ET_i\le D_i$ | 22–28 |
| C7 | Work completion: $\sum_{s,t}PC^{eff}_{st}Y_{ist}\Delta t\ge W_i$, where $W_i=\sum_t U^{CPU}_{it}\Delta t$; $ET_i=\sum_{s,t}Y_{ist}\Delta t$ | 14, 39, 40 |
| C8 | Priority: time-sensitive workloads go before delay-tolerant ones ($O_{ij}\ge RT_i-RT_j$). Ties on the same type and deadline are broken FIFO by arrival time | 56, 57 |
| **Thermal** | | |
| C9 | $T^{pred}_{st}=\alpha_s T^{pred}_{s,t-1}+(1-\alpha_s)[CRAC^{temp}_{zt}+a_s+R_s(P^{IT}_{st}-Q^{cp,rem}_{st})]$, with $T^{pred}_{s,0}=T^0_s=\max(T_{CPU1},T_{CPU2})$ at the first period | Q&A 1, 30 |
| C10 | $TH_{st}=T^{max}_s-T^{pred}_{st}\ge H^{min}$ and $T^{pred}_{st}\le T^{max}_s$ | 31–33 |
| C11 | $T^{zone}_{zt}=CRAC^{temp}_{zt}\le T^{max}_z$. Zone temperature changes by at most 5 °C in 15 min and at most 20 °C in 1 h | Q&A 3, 34–36 |
| C12 | DPF is piecewise: 1 below $T^{dvfs}$; $1-R^{dvfs}\frac{T-T^{dvfs}}{T^{throttle}-T^{dvfs}}$ between $T^{dvfs}$ and $T^{throttle}$; $F^{throttle}$ at or above $T^{throttle}$. $PC^{eff}_{st}=PC_s\cdot DPF_{st}$, where $PC_s=N^{cores}_s f_s$ | 15, 37, 38 |
| **CRAC** | | |
| C13 | Supply temperature and airflow stay within their bounds | 41, 42 |
| C14 | CRAC removes all heat the cold plates do not: $Q^{crac,rem}_{zt}\ge\sum_s Z_{sz}(Q^{heat}_{st}-Q^{cp,rem}_{st})$. Removed heat is at most $Q^{crac}_z$ | Q&A 2, 54 |
| C15 | $T^{return}_{zt}=CRAC^{temp}_{zt}+Q/(CRAC^{flow}_{zt}c_{pa})$; $P^{crac}_{zt}=Q^{crac,rem}_{zt}/COP_z$ | 44–46 |
| **Cold plate** (per plate, scaled by plate count) | | |
| C16 | Flow comes from the fixed settings list. Coolant temperature stays within 20–40 °C | 47, 49, cold-plate follow-up item 3 |
| C17 | $0\le Q^{cp,rem}_{st}\le\min\{0.3\text{ kW},\;Q^{heat}_{st},\;(T^{pred}_{s,t-1}-CP^{temp}_{st})/R^{cp}(flow),\;\dot m\,c_{pw}(T^{pred}_{s,t-1}-CP^{temp}_{st})\}$. These are "≤", not "=", and use last period's temperature to avoid a circular dependency | 50–55, Q&A 4, cold-plate follow-up |
| C18 | $P^{cp}_{st}=P^{cp,rated}(CP^{flow}_{st}/FR^{cp,rated})^3$, computed ahead of time for each flow setting | 48 |
| **Carbon** | | |
| C19 | $CE_t=CI_t E^{total}_t$ and $CE^{total}=\sum_t CE_t$ | 6, 7 |

### 7.3 Solver behavior
- Every limit is hard. If a server is full or too hot, the workload goes to another
  server. If none is free, it waits, as long as it can still meet its deadline and
  allowable delay.
- If no feasible solution exists, the run reports "no valid solution" and names the
  constraint groups causing it. No extra fallback rules are added.
- Nonlinear terms (cubic pump power, flow-dependent $R^{cp}$, quadratic COP, piecewise
  DPF) are handled by discretizing: whole-degree CRAC supply temperatures and fixed
  cold-plate flow settings. This keeps the model solvable as a MILP.

## 8. Outputs

### 8.1 Data exports
Every decision and system variable from §6, for each workload, server, zone and period.
Results are reported for both the baseline and the optimized run.

### 8.2 Compliance tables (base run)
| Table | Columns | What it verifies |
|---|---|---|
| Assignment and schedule | workload, arrival, server, start, execution time, completion, type | — |
| Deadline and waiting time | workload, arrival, start, WT, AD, completion, deadline, compliant? | C6 |
| Reassignment | workload, original server, reassigned?, final server, reason | C3 (only waiting workloads moved) |
| CPU and memory | server, CPU capacity, max CPU used, max utilization, memory capacity, max memory used | C4 |
| Temperature and headroom | server, max $T^{pred}$, min headroom, min DPF, min $PC^{eff}$ | C10, C12 |
| CRAC limits | zone, min/max supply temp used, allowed range, min/max airflow used, allowed range, capacity | C13, C14 |
| Cold-plate limits | server, min/max inlet temp used, allowed range, min/max flow used, allowed range, capacity | C16, C17 |
| Work completion | workload, $W_i$, $PC^{eff}$ delivered, min DPF | C7 |
| Energy breakdown | component (IT, CRAC, CP), kWh, % of total | — |
| Carbon | period, $E^{total}_t$, $CI_t$, $CE_t$, plus totals | C19 |

### 8.3 Charts (x-axis = time period unless noted)
1. Server CPU utilization (%): one line per server.
2. Predicted server temperature (°C): one line per server, with horizontal limit lines.
3. Thermal headroom (°C): one line per server, with an $H^{min}$ line.
4. Effective processing capability: one line per server, to show DPF derating.
5. IT power (W): one line per server.
6. Cooling decisions: CRAC supply temperature and cold-plate coolant temperature on one
   chart; airflow and coolant flow on a second chart (the units differ).
7. Energy breakdown: stacked bar of IT, CRAC and CP (kWh).
8. Carbon emissions (kg CO₂): baseline vs optimized lines, with IT, CRAC and CP
   contributions in the underlying data.
9. Gantt chart: workload ID (grouped by server) vs time, marking arrival, start,
   execution, completion and deadline; colored by $RT_i$.

## 9. Scenarios (Ch. 6)

Each scenario keeps the same servers, workloads and carbon intensity unless stated, and
is compared against the base run.

| # | Question | Variants | Key metrics |
|---|---|---|---|
| S1 | How does server zoning interact with reassignment? | Base (mixed zones); T1: group similar servers into the same zone (change $Z_{sz}$); T2: reassignment allowed only within the original zone | number of reassignments, original/new server and zone, cross-zone moves, utilization, CRAC energy per zone, total energy, carbon, deadline satisfaction, $T^{pred}$ |
| S2 | Which cooling system lowers server temperature more? | Base; T1: change the CRAC supply air temperature; airflow is not modelled (cold plate fixed); T2: change coolant temperature and flow (CRAC fixed) | average and max $T^{pred}$, average headroom, CRAC energy, CP energy, total cooling energy, carbon |
| S3 | Does a larger thermal margin hurt QoS? | $H^{min}$ = 10 °C (base) vs high, medium and low values (to be decided) | execution, waiting and completion time; missed deadlines (count and %); average and max $T^{pred}$; DPF by server; number of throttled servers; energy; carbon |
| S4 | Does thermal-aware reassignment reduce carbon? | Base (capacity + thermal + $PC^{eff}$); T1: no reassignment ($r_{is}=0$); T2: reassignment ignores temperature, in two passes: servers are chosen with server temperature left out, then start times and cooling are solved on those servers with every thermal limit (`placement = "thermal_blind"`); T3: base with a different $CI_t$ profile | number of reassignments, servers, IT/CRAC/CP energy, carbon, completion and waiting time, missed deadlines, temperatures, DPF |

## 10. Open questions

Already settled in the code, so no longer open: Eq. 36 uses $t-12$ (one hour), Eq. 46
divides by COP, and the minimum cold-plate flow is 0.05 L/min.

1. **Cold-plate flow settings and $R^{cp}$.** `thesisb.pdf` asks for seven settings,
   including 0.05, 0.264 and 0.35 L/min. The Wang et al. (2026) values cover only
   0.1–0.3 L/min, and they describe CPU1's combined cooling, not the cold plate alone.
   Which list is final? If it's the seven settings, how should $R^{cp}$ be filled in for
   the three new flows (interpolate or extrapolate)?
2. **CRAC airflow.** Decided 2026-10-21: airflow is not modelled and is dropped from S2 T1.
   The PDF has no fan-power equation, so airflow would change neither the objective nor any
   binding constraint. See `PRD_CH6_RESULTS.md` D3.
3. **Thermal-blind reassignment (S4 T2).** Decided 2026-10-21: two passes. Pass 1 chooses
   servers with server temperature left out (no temperature recursion, no safety cap,
   DPF = 1). Pass 2 fixes those servers and solves start times and cooling with every
   thermal limit. If pass 2 is infeasible, that is the result. See `PRD_CH6_RESULTS.md` R4
   and D2.
4. **S3 headroom values.** The high, medium and low $H^{min}$ values are still to be
   decided.
5. **Ch. 5 data checks.**
   - Number of servers: 6 or 10, and how they were selected.
   - Per-server CPU cores and RAM.
   - Whether per-server idle/max power is used.
   - Whether real UniMelb processor specs are used instead of literature frequencies.
   - Whether 1 vCPU = 1 core.
   - How timestamps were aligned to 5-minute periods.
   - Which UFCG fields give $C^{req}$, $M^{req}$, $A_i$, $D_i$, $AD_i$ and $RT_i$.
   - Whether UniMelb really has no 0% utilization rows but does have rows at or below 1%.

## 11. Acceptance criteria

- The base run solves to optimality or within the configured MIP gap, and every
  compliance table in §8.2 shows 100% compliance.
- The optimized run's $CE^{total}$ is no higher than the baseline's, with the same
  evaluator used to score both.
- Workloads that were already running are never reassigned.
- No server goes above $T^{max}-H^{min}$, and no cooling setting leaves its allowed
  range.
- Each S1–S4 variant runs with input or switch changes only, and produces the metrics
  in §9.
- An infeasible input produces a clear diagnosis instead of a crash or a silent result.

## 12. Gap vs current code (checked 2026-10-18, updated the same day)

Most of §7 is already built in `scheduler/`. That includes the Q&A equations (server
temperature recursion, CRAC heat balance, zone temperature = supply temperature,
cold-plate "≤" limits using last period's temperature), the ramp limits, discretized
COP and pump power, DPF, the reassignment modes, and the infeasibility diagnosis.
G3–G12 were closed on 2026-10-18 except where marked; G1 waits on §10. G2 and S4 T2 were
decided on 2026-10-21 (§10.2, §10.3).

**Model**
| # | Gap | Status |
|---|---|---|
| G1 | Cold-plate flow settings are 0.10–0.30 (5 settings), not the 7 settings in `thesisb.pdf` | Open, blocked on §10.1 |
| G2 | CRAC airflow is not modeled (Eq. 41, 44, 45) | Closed by decision (§10.2): not modelled, removed from S2 T1 |
| G3 | Priority ordering $O_{ij}$ (Eq. 56–57) | Done. Pairs with $O_{ij}=1$ come from (56) and (57). They are linked to the schedule by: on a shared server, j may not start while i waits ($A_i \le ST_j \Rightarrow ST_i \le ST_j$). Big-M rows over $ST_i$ in `optimize.py`; inversions are counted by the evaluator. On by default, `--no-priority` turns it off, and it is a family in the infeasibility diagnosis. EDF within a type is not in the equations, so it is not modelled. The thesis should state this link, because the PDF has none (PROJECT_CONTEXT A6) |
| G4 | $AV_{st}$ (Eq. 11) and $B_i$ (Eq. 29) never tested | Done. Optional `availability.csv` (`s, t, AV`), enforced by the baseline, optimizer and evaluator. New scenario `small_running`: 4 running workloads and server 3 down 15:00–16:00. Check `running_workloads_not_reassigned`. A running workload keeps its server but may still be shifted in time (Eq. 29 fixes only the server) |
| G5 | `F_throttle` 0.662 → 0.622 | Done in `data_prep.ipynb` and every `params.json` |

**Outputs (§8)**
| # | Gap | Status |
|---|---|---|
| G6 | Reassignment table: reason, original/new zone, cross-zone | Done: `optimized/reassignment.csv`, metric `n_cross_zone`, per-zone CRAC energy in `totals.E_crac_by_zone_kWh` |
| G7 | Cold-plate compliance table | Done: `compliance_cold_plates.csv` (min/max coolant and flow used, allowed ranges, peak and capacity of Q_cp) |
| G8 | Min $PC^{eff}$, max utilization, per-workload min DPF | Done: `compliance_servers.csv` gains `max_utilization`, `min_PC_eff_MHz` and `periods_unavailable`; `compliance_workloads.csv` gains `min_DPF`. `summary.json` adds mean temperature, mean headroom, throttled servers and priority inversions |
| G9 | Dashboard charts | Done. Thermal: per-server temperature, headroom (with $H^{min}$), utilization, IT power, $PC^{eff}$. Cooling: coolant temperature next to the zone's supply air, coolant flow, cold-plate limits. Compliance: cold-plate and reassignment tables |

**Scenarios (§9)**
| # | Gap | Status |
|---|---|---|
| G10 | S1 T1 zone regrouping | Done: `--zone-map 1,1,1,2,2,2` (any map, one zone per server) |
| G11 | S2 T2: fix the optimized run's cold plates | Done: `--cp-mode fixed [--fixed-cp-flow F --fixed-cp-coolant C]`. When the coolant is warmer than the server, the drive is $\max(0, T_{s,t-1} - CP^{temp})$, which costs one binary per server-period. S2 T1 changes the supply air temperature only (G2) |
| G12 | S4 T3 carbon-intensity switch; S4 T2 thermal-blind mode | T3 done: `--carbon-file <csv>` or `--ci-flat`. T2 done: `--thermal-blind`, `placement="thermal_blind"` (two passes, §10.3) |

Results under `results/` were produced before these changes. They lack the new tables,
and they were solved without priority and with $F^{throttle}$ = 0.662. Re-run them before
using them in Ch. 4–6. The dashboard still reads them.

**Results to check before running Ch. 6.** In the current `consolidated6` (formerly
`base`) `free` run, nothing is reassigned (`n_reassigned` = 0). The hottest server peaks
at 72.8 °C, below the 75 °C point where throttling starts, so min DPF = 1.0. As things stand, S1 and S4 would show
no reassignment effect. In S3, $H^{min}$ starts to bind only above about 17 °C (a cap
below 72.8 °C). Throttling cannot happen once $H^{min} \ge 15$ °C, because the cap is
then at or below 75 °C. So S3's DPF and throttled-server metrics will probably stay at
1 and 0.

**Not code.** The Ch. 4 and Ch. 5 data questions (§10.5) need written answers;
`DATA_PREP_REPORT.md` and `PROJECT_CONTEXT.md` §9 likely cover most of them. The
write-up edits marked DONE in the PDF are thesis-text changes only.
