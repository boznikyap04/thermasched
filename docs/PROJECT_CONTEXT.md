# PROJECT_CONTEXT

Context for a Python translation of the optimization model in the DLSU IE thesis
*"An Integrated Optimization Model for Thermal-Aware Workload Scheduling and Air-Liquid
Cooling Control in Heterogeneous Data Centers"*.

The goal is a model that can be re-run across many scenarios (workload mixes, server
fleets, cooling limits, carbon intensities), not a one-off reproduction of the base run.

This file is meant to stand on its own. It was written on 2026-10-09 from a full visual
read of the sources below; equation pages were re-checked at higher zoom.

| Source | Role | How it is used here |
|---|---|---|
| `thesisb.pdf` (25 pp., "Base Run Model") | **Source of truth** for the model | Every symbol, value, and equation in sections 2 to 4 is taken from it, cited as "tb p.N" |
| `writeups_THIES4A-5.pdf`, Ch. I (PDF pp. 9-61) | Problem, scope, assumptions | Section 1 |
| `writeups_THIES4A-5.pdf`, Ch. IV (PDF pp. 111-134, printed pp. 103-126) | Reasoning behind the formulation | Explanations only; **superseded** as a definition |
| `archive/notebooks/old_notebook.ipynb` | Earlier implementation attempt | Cross-reference, section 8 |
| `data/raw/UniMelb.csv` | **Server data** (decided, see below) | Section 9.1 |
| `data/raw/UFCG/*.csv` | **Workload data** (decided, see below) | Section 9.2 |

**Data decision (project owner, 2026-10-09): Bitbrains is scrapped. Servers come from
UniMelb and workloads come from UFCG.** This is a project decision, not something either
PDF says: `thesisb.pdf` names only UniMelb, and Ch. IV and the old notebook assume
Bitbrains workloads. Wherever this file quotes those sources mentioning Bitbrains, read
it as history. The consequences of the switch are collected in section 9.2 and in open
question A10.

## Read this first: three things the sources do not contain

These shape everything downstream and are easy to assume away.

1. **`thesisb.pdf` is not a linear model as written, and no linearization exists in
   either source.** The writeup's abstract says "A Mixed-Integer Linear Programming
   approach with linearized thermal and cooling relationships is used", but neither
   `thesisb.pdf` nor Ch. IV contains a single linearized constraint, big-M constant, or
   auxiliary variable. The equations contain bilinear, cubic, quadratic, ratio, and
   piecewise terms in their raw form. See section 3.
2. **No equation defines server temperature or zone temperature.** $T^{pred}_{st}$ and
   $T^{zone}_{zt}$ are bounded and used, but nothing ties them to heat generated, heat
   removed, or the previous period's temperature. As written, workload placement and
   cooling decisions have no effect on temperature. See section 7, items A1 to A3.
3. **Ch. IV has no constant values.** Its parameter table has only symbol and
   definition columns. The only number it gives is $\Delta t = 5$ minutes. So for any
   value missing from `thesisb.pdf`, there is no superseded-source fallback either.

---

## 1. Problem and objectives (writeup Ch. I)

### 1.1 Problem

Data-center workload scheduling, thermal management, and cooling control are usually
optimized separately, although they drive each other: placement sets server
utilization, which sets heat and cooling demand; cooling sets server temperature and
thermal headroom; low headroom throttles processing, which lengthens execution and
threatens deadlines. In air-liquid systems the coupling is tighter, because all servers
get CRAC air cooling while only some also get cold-plate liquid cooling.

Problem statement (Ch. I §1.2.1, paraphrased closely): the study addresses the need for
an integrated thermal-aware workload-to-server assignment and cooling control model for
heterogeneous data centers that determines workload assignment, workload scheduling,
and CRAC and cold-plate cooling control decisions while minimizing total carbon
footprint, subject to server capacity, thermal safety, cooling system, and QoS
constraints.

### 1.2 Stated objectives

Ch. I has **no explicit "Objectives" section**. The objective is carried by the problem
statement above and by four subproblems (§1.2.2), which are the questions the model is
expected to answer through scenario and sensitivity runs:

1. How does the zoning of servers interact with workload reassignment? (Does
   reassignment favor same-zone or cross-zone servers; does restricting reassignment to
   the same zone hurt the optimum?)
2. Which cooling system (CRAC or cold plate) has the greater impact on server
   temperature reduction? (Sensitivity analysis.)
3. How does controlling thermal stress affect completion time and QoS under
   deadline-aware scheduling? (Vary the minimum thermal headroom.)
4. How does thermal-aware reassignment of workloads affect total carbon footprint and
   QoS? (Vary the conditions of reassignment.)

Why carbon rather than cost or energy (Ch. I §1.4): electricity cost reflects market
price rather than physical efficiency; energy alone ignores when the energy is drawn.
Carbon footprint is total energy (IT + CRAC + cold-plate pump) times grid carbon
intensity. Waiting time is deliberately not an objective term because it is already
bounded by the scheduling constraints (Ch. I §1.3).

### 1.3 Scope, limitations, delimitations (Ch. I §1.7)

Scope:
- A thermal-aware optimization model for workload scheduling and cooling control in
  heterogeneous data centers.
- Decides workload timing, workload-to-server assignment, and cooling control to
  minimize total carbon footprint.
- Servers differ in CPU capacity, memory capacity, processing capability, thermal
  characteristics, and cooling technology (air only, or air plus cold plate).

Limitations:
- Evaluated by computational experiment only; not validated in an operating data center.
- Thermal throttling is represented as reduced effective processing capability, not as
  hardware-level throttling mechanisms.

Delimitations:
- CRAC-based air cooling plus selected cold-plate liquid cooling only.
- Cooling is allocated at zone level; no airflow distribution or CFD.
- Assignment considers CPU, memory, processing capability, thermal conditions, and
  cooling resources. Storage and network bandwidth are excluded.
- Single data center; no geo-distributed migration.
- Running workloads are never migrated. Only not-yet-started workloads may be
  reassigned or rescheduled.

### 1.4 Assumptions (Ch. IV §4.1; `thesisb.pdf` does not restate them)

1. Each workload has known CPU demand, memory demand, arrival time, and deadline.
2. Delay-tolerant workloads may be postponed only within their allowable delay.
3. Servers may differ in CPU capacity, memory capacity, processing capability, idle and
   maximum power, and cooling configuration.
4. Each server belongs to one cooling zone and has a fixed cooling type for the horizon.
5. Optimization runs over a multi-period horizon; scheduling, assignment, server
   states, and cooling decisions are updated each interval.
6. End-of-interval state (running workloads, thermal conditions, queued workloads)
   carries forward as the next interval's initial state.
7. Time-sensitive workloads take priority over delay-tolerant ones. Within a type,
   Earliest Deadline First; FIFO is the final tiebreaker for identical deadlines.
8. Server temperature, thermal headroom, and cooling conditions update each interval.
9. All electrical power consumed by a server is dissipated as heat.
10. Grid emission factor is time-varying and known for every interval.
11. Thermal throttling reduces processing capability only; it never interrupts a
    running workload.
12. Each air-cooled zone is served by one equivalent CRAC system modelled at zone level.
13. Periods are 5 minutes ($\Delta t = 5$) because Bitbrains workload data is recorded
    every 5 minutes; UniMelb server data (10-minute) is adjusted to match. The period
    is converted to seconds or hours as each equation needs. (Bitbrains is now
    scrapped. The 5-minute rationale carries over, because UFCG usage is also recorded
    every 5 minutes; see section 9.2.)

Additional framing from Ch. I §1.3: the model is a multi-period model over a fixed
horizon, intended to be re-solved at each scheduling interval with carried-over state
(Ch. IV calls this a "rolling multi-period horizon"). "Servers with high processing
capabilities utilize cold-plate cooling, other servers are supported only by
CRAC-air-cooling." Ch. III §3.4.1 says the authors' own implementation is in GAMS.

---

## 2. Full model specification (`thesisb.pdf`)

Conventions used in this section:
- Math is reproduced **as printed**, including apparent typos. Where the printed form
  looks wrong, it is still shown as printed and flagged with a pointer into section 7.
  Nothing here has been silently corrected.
- "Domain" is what `thesisb.pdf` states. Where it states nothing, the entry says
  "not stated". Only $O$, $X$, $Y$, $r$, and the binary parameters are explicitly typed.

### 2.1 Indices and sets (tb p.1)

| Index | Definition | Values |
|---|---|---|
| $i$ | Workload | $i = 1,2,3,\dots,I$ |
| $j$ | Workload for priority comparison | $j = 1,2,3,\dots,I$ |
| $s$ | Server | $s = 1,2,3,\dots,S$ |
| $z$ | Cooling zone | $z = 1,2,3,\dots,Z$ |
| $t$ | Time period | $t = 1,2,3,\dots,T$ |

Sets that appear inside equations but not in the index table:

| Set | Where | Meaning |
|---|---|---|
| $T^{W}_i$ | Eq. (14) | "Selected workload window" of periods over which workload $i$'s CPU usage is summed. Not otherwise defined (section 7, C6). |
| $T^{idle}_s$ | Eq. (17), (18) | Near-idle observation periods of server $s$, defined by Eq. (17). |

$I$, $S$, $Z$, $T$ have no numeric values in the tables. The text beside Eq. (15)
implies $S = 10$ for the base run ("assigned to the 10 servers").

### 2.2 Parameters (tb pp.2-7)

Grouped under the source's own headings. Values are in section 4.

**Workload Arrival**

| Symbol | Definition (source wording) | Units | Domain |
|---|---|---|---|
| $A_i$ | Arrival time of workload $i$ | not stated | not stated |
| $D_i$ | Deadline of workload $i$ | not stated | not stated |
| $AD_i$ | Maximum allowable delay of workload $i$ | not stated | Eq. (22) |
| $C^{req}_i$ | CPU demand of workload $i$ | not stated | not stated |
| $M^{req}_i$ | Memory demand of workload $i$ | not stated | not stated |
| $U^{CPU}_{it}$ | CPU usage of workload $i$ during period $t$ | MHz | $\ge 0$ implied |
| $RT_i$ | 1 if workload $i$ is time sensitive, 0 if delay tolerant | n/a | binary |
| $W_i$ | Total computational work required by workload $i$, derived from its CPU usage over the selected workload window | MHz·s | Eq. (14) |
| $ET^{base}_i$ | Baseline execution time required by workload $i$ under unthrottled processing conditions | not stated | not stated |

**Existing Accepted Schedule**

| Symbol | Definition | Units | Domain |
|---|---|---|---|
| $X^{0}_{is}$ | 1 if workload $i$ is currently assigned to server $s$, 0 otherwise | n/a | binary |
| $B_i$ | 1 if workload $i$ has already started execution, 0 if it has not yet started | n/a | binary |

**Current Server State**

| Symbol | Definition | Units | Domain |
|---|---|---|---|
| $C_s$ | Total CPU capacity of server $s$ | not stated | not stated |
| $M_s$ | Total memory capacity of server $s$ | not stated | not stated |
| $AV_{st}$ | 1 if server $s$ is available at time $t$, 0 otherwise | n/a | binary |
| $Y_{ist}$ | 1 if workload $i$ is executing on server $s$ during period $t$; 0 otherwise | n/a | binary. **Also listed as a decision variable** (section 7, C2) |
| $f_s$ | Assigned nominal CPU frequency of servers | MHz | not stated |
| $T^{0}_{st}$ | Initial temperature of server $s$ at time $t$ | not stated | not stated. See also $T^0_s$ (section 7, C1) |

**Server Specifications**

| Symbol | Definition | Units | Domain |
|---|---|---|---|
| $P^{idle}_s$ | Idle power consumption of server $s$ | not stated | Eq. (18) |
| $P^{max}_s$ | Maximum power consumption of server $s$ | not stated | Eq. (19) |
| $P^{obs}_{st}$ | Observed electrical power of server $s$ during observation period $t$ from the UniMelb dataset | not stated | data |
| $U^{obs}_{st}$ | Observed CPU utilization of server $s$ during observation period $t$ from the UniMelb dataset | not stated | data |
| $N^{cores}_s$ | Number of CPU cores of server $s$ | cores | data |
| $f_s$ | Assigned nominal CPU frequency of server $s$ (second listing) | (MHz above) | data |
| $PC_s$ | Processing capability of server $s$ | not stated (MHz by Eq. 15) | Eq. (15) |
| $R^{dvfs}_s$ | Maximum performance loss of server $s$ during gradual thermal throttling | fraction | constant |
| $F^{throttle}_s$ | Percentage of the server's normal processing capability that remains when it is thermally throttled | fraction | constant |

**Thermal State**

| Symbol | Definition | Units | Domain |
|---|---|---|---|
| $T^{0}_s$ | Initial temperature of server $s$ at the beginning of the planning horizon | °C implied | Eq. (30) and a conflicting table note (section 7, C1) |
| $T^{max}_s$ | Maximum allowable temperature of server $s$ | °C | constant |
| $H^{min}$ | Minimum required thermal headroom before additional workload assignment | °C | constant. Written $H_{min}$ in Eq. (32) |
| $c_{pw}$ | Specific heat capacity of water | kJ/(kg·°C) as printed | constant |
| $c_{pa}$ | Specific heat capacity of air | kJ/(kg·°C) | constant |
| $T^{dvfs}_s$ | Thermal-control temperature threshold at which the processing performance of server $s$ begins to be reduced to prevent overheating | °C | constant |
| $T^{throttle}_s$ | Temperature at which server $s$ reaches thermal throttling | °C | constant |

**CRAC Unit and Control**

| Symbol | Definition | Units | Domain |
|---|---|---|---|
| $Q^{crac}_z$ | Maximum cooling capacity of CRAC serving zone $z$ | kW | constant |
| $COP^{crac}_z$ | Coefficient of performance of CRAC serving zone $z$ | dimensionless | **given as a function of the decision variable $CRAC^{temp}_{zt}$**, see section 4 |
| $T^{crac,min}_z$ | Minimum allowable CRAC supply air temperature in zone $z$ | °C | constant |
| $T^{crac,max}_z$ | Maximum allowable CRAC supply air temperature in zone $z$ | °C | constant |
| $FR^{crac,min}_z$ | Minimum allowable CRAC supply air flow rate in zone $z$ | (m³/h or m³/s) | constant |
| $FR^{crac,max}_z$ | Maximum allowable CRAC supply air flow rate in zone $z$ | m³/h or m³/s | constant |

**Cold Plate Unit and Control**

| Symbol | Definition | Units | Domain |
|---|---|---|---|
| $CT_s$ | 1 if server $s$ has cold plate cooling, 0 if air cooled only | n/a | binary. Symbol collides with $CT_i$ (section 7, C3) |
| $Q^{cp}_s$ | Maximum cooling capacity of cold plate installed on server $s$ | kW per cold plate | constant |
| $T^{cp,min}_s$ | Minimum allowable cold plate coolant inlet temperature for server $s$ | K | constant |
| $T^{cp,max}_s$ | Maximum allowable cold plate coolant inlet temperature for server $s$ | K | constant |
| $FR^{cp,min}_s$ | Minimum allowable coolant flow rate through the cold plate installed in server $s$ | L/min | constant |
| $FR^{cp,max}_s$ | Maximum allowable coolant flow rate through the cold plate installed in server $s$ | L/min | constant |
| $P^{cp,rated}_s$ | Rated electrical power of the cold-plate circulation pump associated with server $s$ | "mW" as printed | constant |
| $FR^{cp,rated}_s$ | Rated coolant flow rate of the cold-plate circulation pump associated with server $s$ | L/min | constant |

**Cooling Zone Information, Carbon Intensity, Scheduling period**

| Symbol | Definition | Units | Domain |
|---|---|---|---|
| $Z_{sz}$ | 1 if server $s$ belongs to zone $z$, 0 otherwise | n/a | binary |
| $T^{max}_z$ | Maximum allowable cooling zone temperature | °C | constant |
| $CI_t$ | Grid carbon intensity during time period $t$ | not stated | data |
| $\Delta t$ | Duration of each scheduling period | not stated | constant |

Symbols used in equations but absent from the parameter tables: $T_{CPU1,s,0}$ and
$T_{CPU2,s,0}$ (Eq. 30; the two CPU temperatures at the first recorded period), $c$ and
$\Delta T$ (Eq. 43, 50; generic placeholders).

### 2.3 Decision variables (tb pp.7-8)

Heading in source: "DVS, system variables (these are values that are determined by the
model)".

| Symbol | Definition (source wording) | Units | Domain / bounds |
|---|---|---|---|
| $O_{ij}$ | 1 if workload $i$ is scheduled before workload $j$; 0 otherwise | n/a | binary |
| $X_{is}$ | 1 if workload $i$ is assigned to server $s$; 0 otherwise | n/a | binary |
| $Y_{ist}$ | 1 if workload $i$ is executing on server $s$ during time period $t$; 0 otherwise | n/a | binary |
| $ST_i$ | Scheduled start time of workload $i$ | not stated | not stated; $\ge A_i$ by (23) |
| $r_{is}$ | 1 if an already scheduled but unstarted workload $i$ is reassigned to server $s$, 0 otherwise | n/a | binary |
| $CP^{temp}_{st}$ | Cold plate inlet temperature "for cooling zone $z$" during time period $t$ (indexed by $s$) | K, from its bounds | not stated; bounded by (49) |
| $CP^{flow}_{st}$ | Cold plate flow rate "for cooling zone $z$" during time period $t$ (indexed by $s$) | L/min, from its bounds | not stated; bounded by (47) |
| $CRAC^{temp}_{zt}$ | CRAC supply air temperature for cooling zone $z$ during time period $t$ | °C, from its bounds | not stated; bounded by (42) |
| $CRAC^{flow}_{zt}$ | CRAC supply air flow rate for cooling zone $z$ during time period $t$ | m³/h or m³/s | not stated; bounded by (41) |

### 2.4 System variables (tb pp.8-11)

Determined by the model through the equations. No domain is stated for any of them.

| Symbol | Definition | Defined by |
|---|---|---|
| $U_{st}$ | Utilization level of server $s$ during time period $t$ | (16) |
| $P^{IT}_{st}$ | IT power consumption of server $s$ during time $t$ | (20) |
| $Q^{heat}_{st}$ | Heat generated by server $s$ during time $t$ | (21) |
| $T^{pred}_{st}$ | Predicted temperature of server $s$ during time $t$ | **no defining equation** |
| $TH_{st}$ | Thermal headroom of server $s$ during time $t$ | (31) |
| $PC^{eff}_{st}$ | Effective processing capability of server $s$ during time period $t$ | (38) |
| $DPF_{st}$ | Dynamic Performance Factor of server $s$ during time period $t$: the fraction of nominal processing capability retained under its current thermal condition | (37) |
| $ET_i$ | Expected execution time of workload $i$ | (40) |
| $CT_i$ | Expected completion time of workload $i$ | (26) |
| $WT_i$ | Waiting time of workload $i$ | (24) |
| $Q^{crac,rem}_{zt}$ | Heat removed by the CRAC system serving cooling zone $z$ during time period $t$ | appears in equations as $Q^{crac}_{zt}$, $Q^{CRAC}_{zt}$, $Q^{crac}_{st}$ (section 7, C4) |
| $T^{return}_{zt}$ | Return-air temperature entering the CRAC serving cooling zone $z$ during time period $t$ (listed twice) | (45) |
| $P^{crac}_{zt}$ | Electrical power consumption of the CRAC serving zone $z$ during time $t$ | (46) |
| $T^{zone}_{zt}$ | Temperature of cooling zone $z$ during time period $t$ | **no defining equation** |
| $Q^{cp,rem}_{st}$ | Heat removed by cold plate of server $s$ | appears in equations as $Q^{cp}_{zt}$, $Q^{cp}_{st}$ (section 7, C4) |
| $T^{cp,out}_{st}$ | Coolant outlet temperature leaving the cold plate of server $s$ during time period $t$ | (52) |
| $P^{cp}_{st}$ | Electrical power consumed by the cold-plate circulation pump of server $s$ during period $t$ (listed twice with two wordings) | (48) |
| $E^{IT}_{st}$ | IT energy consumed by server $s$ during time $t$ | (3) |
| $E^{crac}_{zt}$ | CRAC energy consumed in zone $z$ during period $t$ | (4) |
| $E^{cp}_{st}$ | Cold plate cooling energy consumed by server $s$ during period $t$ | (5) |
| $E^{total}_t$ | Total IT and cooling energy consumed during period $t$ | (2) |
| $CE_t$ | Carbon emissions during time $t$ | (6) |
| $CE^{total}$ | Total carbon emissions over the planning horizon | (7) |

$C^{cp}_{st}$ ("liquid heat capacity rate", Eq. 53) is used in an equation but is not in
the variable table.

### 2.5 Objective function (tb pp.12-13)

$$\min Z = CE^{total}_{t} \tag{1}$$

Minimize total operational carbon emissions, summed over all periods. (The subscript
$t$ on $CE^{total}$ is as printed; Eq. (7) defines $CE^{total}$ without it.)

$$E^{total}_{t} = \sum_{s=1}^{S} E^{IT}_{st} + \sum_{z=1}^{Z} E^{crac}_{zt} + \sum_{s=1}^{S} E^{cp}_{st} \tag{2}$$

Total energy in a period is server energy plus CRAC energy plus cold-plate energy.

$$E^{IT}_{st} = P^{IT}_{st}\,\Delta t \qquad \forall s,t \tag{3}$$

Server energy is server power times the period length.

$$E^{crac}_{zt} = P^{crac}_{zt}\,\Delta t \qquad \forall z,t \tag{4}$$

CRAC energy is CRAC electrical power times the period length.

$$E^{cp}_{st} = P^{cp}_{st}\,\Delta t \qquad \forall s,t \tag{5}$$

Cold-plate energy is pump power times the period length. Source note: "For servers that
are not equipped with cold plate cooling, $E^{cp}_{st} = 0$" (stated in prose only; no
constraint enforces it, section 7, B6).

$$CE_{t} = CI_{t}\,E^{total}_{t} \qquad \forall t \tag{6}$$

Emissions in a period are that period's energy times its grid carbon intensity.

$$CE^{total} = \sum_{t=1}^{T} CI_{t}\,E^{total}_{t} \tag{7}$$

Total emissions are the sum of per-period emissions.

$$\min Z = \sum_{t=1}^{T} CI_{t}\left[\sum_{s=1} E^{IT}_{st} + \sum_{z=1} E^{crac}_{zt} + \sum_{s=1} E^{cp}_{st}\right] \tag{8}$$

The complete objective: (2) substituted into (7). The source labels this "Complete
objective function".

### 2.6 Constraints (tb pp.14-25)

Section headings are the source's own.

#### Workload constraints

$$\sum_{s} X_{is} = 1 \qquad \forall i \tag{9}$$

Every workload is assigned to exactly one server.

$$Y_{ist} \le X_{is} \qquad \forall i,s,t \tag{10}$$

A workload can only execute on the server it is assigned to.

$$Y_{ist} \le AV_{st} \qquad \forall i,s,t \tag{11}$$

A workload can only execute on a server in periods when that server is available.

#### Physical Resource Limit Constraints

$$\sum_{s} C^{req}_{i}\,Y_{ist} \le C_{s} \qquad \forall s,t \tag{12}$$

Total CPU demand of workloads executing on a server in a period cannot exceed its CPU
capacity. (Summation index printed as $s$; section 7, B1.)

$$\sum_{s} M^{req}_{i}\,Y_{ist} \le M_{s} \qquad \forall s,t \tag{13}$$

Same as (12) for memory. (Same index issue.)

$$W_{i} = \sum_{t \in T^{W}_{i}} U^{CPU}_{it}\,\Delta t \tag{14}$$

A workload's total required work is its CPU usage summed over its selected window,
times the period length. Parameter preprocessing, not a model constraint.

$$PC_{s} = N^{cores}_{s}\,f_{s} \qquad \forall s \tag{15}$$

A server's processing capability is its core count times its nominal frequency.
Preprocessing. Source text: UniMelb provides core counts but not frequency, so
literature frequencies of 2.1, 2.4, and 3.0 GHz (Li et al. 2026) are assigned to the 10
servers as 4, 3, and 3 servers respectively, following the heterogeneous proportions of
Marahatta et al. (2021).

$$U_{st} = \frac{\sum_{i} C^{req}_{i}\,Y_{ist}}{C_{s}} \qquad \forall s,t \tag{16}$$

Server utilization is the CPU demand executing on it divided by its CPU capacity
(adapted from Duan et al. 2017).

$$T^{idle}_{s} = \left\{\, t \in T \mid U_{st} \le 0.01 \,\right\} \tag{17}$$

The near-idle periods of a server are those with CPU utilization at or below 1%.
Preprocessing on observed data. Source text: UniMelb has no observations at exactly 0%,
so 1% or less is treated as near-idle (Jin et al. 2022). (Printed with the model
variable $U_{st}$; section 7, C5.)

$$P^{idle}_{s} = \frac{1}{\lvert T^{idle}_{s} \rvert} \sum_{t \in T^{idle}_{s}} P^{obs}_{st} \tag{18}$$

Idle power is the mean observed power over the near-idle periods (Lin et al. 2021).
Preprocessing.

$$P^{max}_{s} = \max\left(P^{obs}_{st}\right) \tag{19}$$

Maximum power is the highest observed power of the server. Preprocessing.

$$P^{IT}_{st} = P^{idle}_{s} + \left(P^{max}_{s} - P^{idle}_{s}\right) U_{st} \qquad \forall s,t \tag{20}$$

Server power is linear in utilization between idle and maximum power (Racedo et al.
2026).

$$Q^{heat}_{st} = P^{IT}_{st} \qquad \forall s,t \tag{21}$$

All server electrical power becomes heat (Lin et al. 2024).

#### Timing and quality of service requirement Constraints

$$AD_{i} \ge D_{i} - A_{i} - ET^{base}_{i} \tag{22}$$

Maximum allowable delay is the time between arrival and deadline, less the baseline
execution time (Xu et al. 2020). (Printed as $\ge$; section 7, B2.)

$$ST_{i} \ge A_{i} \qquad \forall i \tag{23}$$

A workload cannot start before it arrives.

$$WT_{i} = ST_{i} - A_{i} \qquad \forall i \tag{24}$$

Waiting time is start time minus arrival time.

$$WT_{i} \le AD_{i} \qquad \forall i : RT_i = 0 \tag{25}$$

A delay-tolerant workload cannot wait longer than its maximum allowable delay.

$$CT_{i} = ST_{i} + ET_{i} \qquad \forall i \tag{26}$$

Completion time is start time plus (thermally adjusted) execution time.

$$CT_{i} \le D_{i} \qquad \forall i \tag{27}$$

Every workload must finish by its deadline.

$$ST_{i} - A_{i} \le AD_{i} \qquad \forall i \tag{28}$$

Start may be postponed only within the maximum allowable delay; the same limit as (25)
written on start time, but for all workloads.

#### Reassignment eligibility constraint

$$\sum_{s=1}^{S} r_{is} \le 1 - B_{i} \qquad \forall i,s \tag{29}$$

Only workloads that have not started ($B_i = 0$) may be reassigned; running workloads
stay on their current server. (Quantifier printed as $\forall i,s$ although $s$ is
summed.)

#### Temperature constraints

$$T^{0}_{s} = \max\left\{T_{CPU1,s,0},\; T_{CPU2,s,0}\right\} \tag{30}$$

A server's initial temperature is the higher of its two CPU temperatures at the first
recorded period (Lin et al. 2024). Preprocessing.

$$TH_{st} = T^{max}_{s} - T^{pred}_{st} \qquad \forall s,t \tag{31}$$

Thermal headroom is the margin between maximum allowable and predicted temperature
(Huang et al. 2025).

$$TH_{st} \ge H_{min} \qquad \forall s,t \tag{32}$$

Headroom must stay at or above the minimum required buffer.

$$T^{pred}_{st} \le T^{max}_{s} \qquad \forall s,t \tag{33}$$

Predicted server temperature cannot exceed its maximum allowable temperature (Hou 2026).

$$T^{zone}_{zt} \le T^{max}_{z} \qquad \forall z,t \tag{34}$$

Each cooling zone stays at or below its maximum allowable temperature.

$$-5 \le T^{zone}_{z,t} - \le T^{zone}_{z,t-3} \le 5 \qquad \forall z,\ t = 4,\dots,T \tag{35}$$

"Inlet air temperature should not change by more than 5C within 15 minutes." (The
second $\le$ is as printed and is taken to be a stray symbol; section 7, B3.)

$$-20 \le T^{zone}_{z,t} - \le T^{zone}_{z,t-20} \le 20 \qquad \forall z,t \tag{36}$$

"Inlet air temperature should not change by more than 20C within one hour." (Same
stray $\le$; no lower limit on $t$; lag of 20 periods; section 7, B3.)

#### Processing capability constraints

$$
DPF_{st} =
\begin{cases}
1, & T^{pred}_{st} < T^{dvfs}_{s} \\[4pt]
1 - \left(\dfrac{T^{pred}_{st} - T^{dvfs}_{s}}{T^{throttle}_{s} - T^{dvfs}_{s}}\right) R^{dvfs}_{s}, & T^{dvfs}_{s} \le T^{pred}_{st} < T^{throttle}_{s} \\[10pt]
F^{throttle}_{s}, & T^{pred}_{st} \ge T^{throttle}_{s}
\end{cases}
\qquad \forall s,t \tag{37}
$$

The fraction of normal performance a server retains: full below the DVFS threshold,
falling linearly between the DVFS and throttle thresholds, and a fixed floor at or above
the throttle threshold. Huang et al. (2025) express this as if-else logic; the thesis
rewrites it as a piecewise function.

$$PC^{eff}_{st} = PC_{s}\,DPF_{st} \qquad \forall s,t \tag{38}$$

Effective processing capability is nominal capability scaled by the performance factor
(developed for this study; supported by Krzywda et al. 2018).

$$\sum_{s=1}^{S}\sum_{t=1}^{T} PC^{eff}_{st}\,Y_{ist}\,\Delta t \ge W_{i} \qquad \forall i \tag{39}$$

Across the periods it executes, each workload must receive at least its required work,
after thermal derating.

$$ET_{i} = \sum_{s,t} Y_{ist}\,\Delta t \tag{40}$$

Execution time is the number of periods the workload runs times the period length.

#### Cooling equipment operating limits constraints

$$FR^{crac,min}_{z} \le CRAC^{flow}_{z,t} \le FR^{crac,max}_{z} \qquad \forall z,t \tag{41}$$

CRAC supply airflow stays within its operating bounds.

$$T^{crac,min}_{z} \le CRAC^{temp}_{z,t} \le T^{crac,max}_{z} \qquad \forall z,t \tag{42}$$

CRAC supply air temperature stays within its allowable range.

$$Q^{crac}_{zt} = CRAC^{flow}_{zt}\,c\,\Delta T \tag{43}$$

Generic form: heat removed by the CRAC is airflow times specific heat times temperature
difference. $c$ and $\Delta T$ are placeholders made specific in (44).

$$Q^{crac}_{zt} = CRAC^{flow}_{zt}\,c_{pa}\left(T^{return}_{zt} - CRAC^{temp}_{zt}\right) \tag{44}$$

Heat removed by the CRAC is airflow times the specific heat of air times the difference
between return and supply air temperature.

$$T^{return}_{zt} = CRAC^{temp}_{zt} + \frac{Q^{CRAC}_{zt}}{CRAC^{flow}_{zt}\,c_{pa}} \tag{45}$$

Return air temperature is supply temperature plus the rise caused by the heat removed.
Source note: "Used to solve Eqn (44)". This is (44) rearranged (section 7, A4).

$$P^{crac}_{zt} = \sum_{s} Z_{sz}\,Q^{crac}_{st}\,COP^{crac}_{z} \qquad \forall z,t \tag{46}$$

CRAC electrical power, from the heat removed for the zone's servers and the CRAC's COP.
Source note: "Power consumption of CRAC". (Printed as a product with COP and with $Q$
indexed by $s$; section 7, B4.)

$$FR^{cp,min}_{s} \le CP^{flow}_{s,t} \le FR^{cp,max}_{s} \qquad \forall s,t \tag{47}$$

Cold-plate coolant flow stays within its operating bounds.

$$P^{CP}_{st} = P^{CP,rated}_{s}\left(\frac{CP^{flow}_{st}}{FR^{cp,rated}_{s}}\right)^{3} \qquad \forall s,t \tag{48}$$

Pump power scales with the cube of the ratio of actual to rated coolant flow. Source
note: "Power consumption of cold plate".

$$T^{cp,min}_{s} \le CP^{temp}_{s,t} \le T^{cp,max}_{s} \qquad \forall s,t \tag{49}$$

Cold-plate coolant inlet temperature stays within its allowable range.

$$Q^{cp}_{zt} = CP^{flow}_{st}\,c\,\Delta T \tag{50}$$

Generic form of cold-plate heat removal; placeholders made specific in (51).

$$Q^{cp}_{zt} = CP^{flow}_{st}\,c_{pw}\left(T^{cp,out}_{st} - CP^{temp}_{st}\right) \tag{51}$$

Heat removed by the cold plate is coolant flow times the specific heat of water times
the coolant's temperature rise. (Left side indexed $zt$, right side $st$, as printed.)

$$T^{cp,out}_{st} = CP^{temp}_{st} + \frac{Q^{cp}_{zt}}{CP^{flow}_{st}\,c_{pw}} \tag{52}$$

Coolant outlet temperature is inlet temperature plus the rise caused by the heat
removed. Source note: "Used to calculate Eqn (51)". This is (51) rearranged.

$$C^{cp}_{st} = CP^{flow}_{st}\,c_{pw} \tag{53}$$

Liquid heat capacity rate: coolant flow times the specific heat of water.

$$Q^{crac}_{zt} \le Q^{crac}_{z} \qquad \forall z,t \tag{54}$$

Heat removed in a zone cannot exceed the CRAC's maximum cooling capacity.

$$Q^{cp}_{st} \le Q^{cp}_{s} \qquad \forall s,t \tag{55}$$

Heat removed by a cold plate cannot exceed its maximum cooling capacity.

#### Workload priority constraints

$$O_{ij} \ge RT_{i} - RT_{j} \qquad \forall i,j,\ i \ne j \tag{56}$$

A time-sensitive workload is ordered before a delay-tolerant one.

$$D_{i} = D_{j},\ \ A_{i} < A_{j} \ \Rightarrow\ O_{ij} = 1 \qquad \forall i,j :\ RT_{i} = RT_{ij},\ i \ne j \tag{57}$$

FIFO tiebreak: between two workloads of the same type with identical deadlines, the
earlier arrival goes first. ($RT_{ij}$ is as printed and is presumably $RT_j$.)

### 2.7 Which equations are constraints and which are preprocessing

Only data appears on the right-hand side of (14), (15), (17), (18), (19), (22), (30),
and the antecedent of (57). These are parameter derivations, not optimization
constraints. The remaining equations involve decision or system variables.

### 2.8 The source's own system diagram (tb p.2) and its numbering

`thesisb.pdf` p.2 groups constraints by entity and labels each group with equation
numbers. The labels are stale against the document's own numbering from Eq. (35) on:

| Diagram group | Diagram label | Actual numbers in the document |
|---|---|---|
| Objective: IT energy / cooling energy / $\min Z$ | (3) / (4),(5) / (8) | same |
| Assignment constraints | (9-11) | (9)-(11) |
| Server capacity constraints | (12-21) | (12)-(21) |
| QoS constraints | (22-28; 54-55) | (22)-(28); priority is (56)-(57) |
| Reschedule and reassignment | (29) | (29) |
| Server-level thermal and headroom | (30-34) | (30)-(33); (34) is zone-level |
| Capability constraints | (35-38) | (37)-(40) |
| Cooling: CRAC | (39-44) | (41)-(46) |
| Cooling: cold plate | (45-51) | (47)-(53) |
| Zone-level thermal | (52-53) | (54)-(55) as numbered; by content (34)-(36) |

The offset is exactly two, consistent with (35) and (36) having been inserted after the
diagram was drawn. Several prose cross-references in the right-hand column are also
stale (for example the text beside (16) calls it "Equation (10)", the text beside (21)
calls it "Equation (12)", and the text beside (8) says it substitutes "Equation 5 into
Equation 7").

---

## 3. Linearizations

### 3.1 What the sources actually contain

**None.** This section was meant to document, for each linearized relationship, the
original nonlinear form, the linearization, and any big-M or auxiliary variables. After
reading all of `thesisb.pdf` and all of Ch. IV:

- `thesisb.pdf` states every thermal and cooling relationship in its original nonlinear
  form. It introduces no big-M constant, no auxiliary binary, no SOS or breakpoint set,
  and no McCormick or similar envelope.
- Ch. IV contains the same raw forms and no derivations. Its text on the piecewise DPF
  says only that Huang et al.'s if-else conditions "are changed into a piecewise
  equation so the model can directly reduce the server's performance".
- The only place "linearized" appears is the writeup's abstract (and its Filipino
  translation), as a one-sentence claim. Applied to this model, "MILP" otherwise
  appears once, in Ch. I §1.4 ("within a holistic MILP framework").

So there is no "final form from `thesisb.pdf`" and no "derivation from Ch. IV" to
record. What can be recorded is the inventory of relationships that are nonlinear as
written, which is what any linearization would have to cover.

### 3.2 Inventory of nonlinear relationships as written

| Eq. | Relationship | Why it is not linear | Variables involved | Linearization in `thesisb.pdf` | In Ch. IV |
|---|---|---|---|---|---|
| (37) | $DPF_{st}$ as a three-branch function of $T^{pred}_{st}$ | Piecewise, with strict inequalities on branch conditions and a jump at $T^{throttle}_s$ (section 7, D3) | $DPF_{st}$, $T^{pred}_{st}$ continuous | none | none |
| (38)-(39) | $\sum_s\sum_t PC_s\,DPF_{st}\,Y_{ist}\,\Delta t \ge W_i$ | Product of a continuous variable ($DPF_{st}$) and a binary variable ($Y_{ist}$) | $DPF_{st}$, $Y_{ist}$ | none | none |
| (44) | $Q^{crac}_{zt} = CRAC^{flow}_{zt}\,c_{pa}\,(T^{return}_{zt} - CRAC^{temp}_{zt})$ | Product of two continuous variables (flow times temperature difference) | $CRAC^{flow}_{zt}$, $T^{return}_{zt}$, $CRAC^{temp}_{zt}$ | none | equation absent |
| (45) | $T^{return}_{zt} = CRAC^{temp}_{zt} + Q^{CRAC}_{zt} / (CRAC^{flow}_{zt}\,c_{pa})$ | Ratio of two continuous variables; undefined at zero flow, and $FR^{crac,min}_z = 0$ | same as (44) | none | equation absent |
| (46) | $P^{crac}_{zt} = \sum_s Z_{sz}\,Q^{crac}_{st}\,COP^{crac}_z$ with $COP = 0.0068\,(CRAC^{temp}_{zt})^2 + 0.0008\,CRAC^{temp}_{zt} + 0.458$ | COP is quadratic in a decision variable, then multiplied by (or, if corrected, dividing) another variable | $Q$, $CRAC^{temp}_{zt}$ | none | same raw form; COP treated as a plain parameter |
| (48) | $P^{CP}_{st} = P^{CP,rated}_s\,(CP^{flow}_{st}/FR^{cp,rated}_s)^3$ | Cubic in a decision variable | $CP^{flow}_{st}$ | none | same raw form ("the original cubic relationship is retained") |
| (51) | $Q^{cp} = CP^{flow}_{st}\,c_{pw}\,(T^{cp,out}_{st} - CP^{temp}_{st})$ | Product of two continuous variables | $CP^{flow}_{st}$, $T^{cp,out}_{st}$, $CP^{temp}_{st}$ | none | equation absent |
| (52) | $T^{cp,out}_{st} = CP^{temp}_{st} + Q^{cp}/(CP^{flow}_{st}\,c_{pw})$ | Ratio of two continuous variables | same as (51) | none | equation absent |
| (53) | $C^{cp}_{st} = CP^{flow}_{st}\,c_{pw}$ | Linear on its own; listed because it only matters as a factor in a product | $CP^{flow}_{st}$ | n/a | equation absent |

Relationships that look nonlinear but are already linear in the decision variables:

| Eq. | Why it is fine as written |
|---|---|
| (16) | The denominator $C_s$ is a parameter, so $U_{st}$ is linear in $Y_{ist}$. |
| (20) | Linear in $U_{st}$; coefficients are parameters. |
| (37), middle branch only | Linear in $T^{pred}_{st}$ once the branch is known. |
| (17)-(19), (30) | Set-builder, mean, and max over observed data. Preprocessing, never seen by the solver. |
| (57) | The antecedent involves only parameters, so it reduces to fixing $O_{ij} = 1$ for a known list of pairs. |
| (56) | Linear. |

### 3.3 Consequence

How each of the relationships in 3.2 is handled (linearize, approximate, fix, or keep
nonlinear) is an open modelling decision that the sources do not make. It is listed in
section 7 (A5) rather than resolved here.

---

## 4. Constants and base-run values (`thesisb.pdf`)

"Value" is exactly what `thesisb.pdf` prints. "not specified in thesisb.pdf" means the
value cell is blank or the symbol has no table row.

**Superseded-source column omitted on purpose:** Ch. IV gives no numeric value for any
parameter. Its only number is $\Delta t = 5$ minutes (assumption 13), shown in the
$\Delta t$ row below and labelled as such.

### 4.1 Constants with values

| Symbol | Value as printed | Units as printed | Page | Remarks |
|---|---|---|---|---|
| $R^{dvfs}_s$ | 0.378 | none (fraction) | tb p.4 | Same for all servers |
| $F^{throttle}_s$ | 0.662 | none (fraction) | tb p.5 | Same for all servers. See section 7, D3 |
| $T^{max}_s$ | 90C | °C | tb p.5 | |
| $H^{min}$ | 10C | °C | tb p.5 | |
| $c_{pw}$ | 4182 | kJ/(kg * C) | tb p.5 | Magnitude and unit label disagree with $c_{pa}$ by a factor of 1000 (section 7, D1) |
| $c_{pa}$ | 1.00643 | kJ/(kg*C) | tb p.5 | |
| $T^{dvfs}_s$ | 75 C | °C | tb p.5 | |
| $T^{throttle}_s$ | 100 C | °C | tb p.5 | Above $T^{max}_s$ (section 7, D2) |
| $Q^{crac}_z$ | 116kW | kW | tb p.5 | |
| $COP^{crac}_z$ | $0.0068\,(CRAC^{temp}_{zt})^2 + 0.0008\,(CRAC^{temp}_{zt}) + 0.458$ | none | tb p.5 | A function of a decision variable, not a constant. Temperature unit for the formula not stated |
| $T^{crac,min}_z$ | 18C | °C | tb p.6 | |
| $T^{crac,max}_z$ | 27C | °C | tb p.6 | |
| $FR^{crac,min}_z$ | 0 | none | tb p.6 | |
| $FR^{crac,max}_z$ | 23,600 m^3/h or 6.56 m^3/s | m³/h, m³/s | tb p.6 | The two figures agree (23,600 / 3600 = 6.56) |
| $Q^{cp}_s$ | 0.3 kW/ cold plate | kW per cold plate | tb p.6 | Number of cold plates per server not stated |
| $T^{cp,min}_s$ | 293.15K | K | tb p.6 | Kelvin, while all other temperatures are °C |
| $T^{cp,max}_s$ | 313.1K | K | tb p.6 | Printed 313.1, not 313.15 |
| $FR^{cp,min}_s$ | 0.005L/min | L/min | tb p.6 | |
| $FR^{cp,max}_s$ | 0.35 L/min | L/min | tb p.6 | |
| $P^{cp,rated}_s$ | 0.657mW | "mW" | tb p.6 | Unit ambiguous (section 7, D1) |
| $FR^{cp,rated}_s$ | 0.264 L,min | L/min (printed "L,min") | tb p.6 | |
| $T^{max}_z$ | 32C | °C | tb p.7 | |
| $f_s$ | 2.1, 2.4, 3.0 GHz assigned to 4, 3, 3 of the 10 servers | GHz in text; MHz in table | tb p.16 (text beside Eq. 15) | Which servers get which frequency is not stated |
| Near-idle threshold | 0.01 | fraction of CPU utilization | tb p.16, Eq. (17) | |
| Zone ramp limits | 5 over 3 periods; 20 over 20 periods | °C | tb p.21, Eq. (35), (36) | Described as 15 minutes and one hour |

### 4.2 Parameters derived by equation ("See Eqn part")

| Symbol | Derivation | Inputs |
|---|---|---|
| $AD_i$ | Eq. (22) | $D_i$, $A_i$, $ET^{base}_i$ |
| $W_i$ | Eq. (14) | $U^{CPU}_{it}$, $T^W_i$, $\Delta t$ |
| $P^{idle}_s$ | Eq. (17)-(18) | $P^{obs}_{st}$, $U^{obs}_{st}$ |
| $P^{max}_s$ | Eq. (19) | $P^{obs}_{st}$ |
| $PC_s$ | Eq. (15) | $N^{cores}_s$, $f_s$ |
| $T^{0}_s$ | Eq. (30); table note says "Initially set to 0, then based on the initial temp that the model solves, the values are updated for each run" | CPU1 and CPU2 temperatures at the first recorded period |

### 4.3 Parameters marked "From dataset" (no value in `thesisb.pdf`)

$A_i$, $D_i$, $C^{req}_i$, $M^{req}_i$, $U^{CPU}_{it}$, $ET^{base}_i$, $C_s$, $M_s$,
$f_s$ (but see 4.1), $T^{0}_{st}$, $P^{obs}_{st}$, $U^{obs}_{st}$, $N^{cores}_s$.

`thesisb.pdf` names the UniMelb dataset as the source of $P^{obs}_{st}$,
$U^{obs}_{st}$, and core counts. It does not name the workload dataset. Ch. IV
(superseded source) names Bitbrains for $U^{CPU}_{it}$ and $W_i$; that is replaced by
UFCG per the project decision at the top of this file.

### 4.4 Not specified in `thesisb.pdf`

| Symbol | Status in `thesisb.pdf` | Ch. IV (superseded source) |
|---|---|---|
| $\Delta t$ | value cell blank | 5 minutes (assumption 13), converted to seconds or hours as needed |
| $I$, $Z$, $T$ | no value | no value |
| $S$ | no table value; 10 implied by the text beside Eq. (15) | no value |
| $RT_i$ | value cell blank | no value |
| $X^{0}_{is}$, $B_i$ | value cells blank | no value |
| $AV_{st}$ | value cell blank | no value |
| $CT_s$ | value cell blank | no value. Ch. I says high-capability servers get cold plates |
| $Z_{sz}$ | value cell blank | no value |
| $CI_t$ | a URL only: `https://ourworldindata.org/grapher/electricity-mix?time=2024&source=total&metric=carbon_intensity&frequency=annual`. No number, country, or unit | no value |
| $T^{W}_i$ | undefined | undefined |
| $T_{CPU1,s,0}$, $T_{CPU2,s,0}$ | no table row; implied to be UniMelb CPU temperatures | no mention |
| Air and water density | absent (needed to combine volumetric flows with per-kg specific heats) | absent |

---

## 5. Changes from Chapter IV

Ch. IV is an earlier draft of the same formulation: highlighted passages, unnumbered
equations shown as "( )", duplicated equation numbers, and "start"/"End" editing
markers. `thesisb.pdf` is the same model, renumbered and extended.

### 5.1 Bottom line: how far Ch. IV can be trusted

- **The explanations still apply.** Every constraint that exists in both documents has
  identical math, and `thesisb.pdf` reuses Ch. IV's explanatory sentences almost
  verbatim in its right-hand column. Nothing was rewritten in a way that invalidates a
  Ch. IV explanation.
- **Ch. IV cannot fill gaps.** It has no values, no linearizations, no temperature
  dynamics, and none of the new cooling physics equations. Everything missing from
  `thesisb.pdf` is also missing from Ch. IV.
- **The shared typos are shared.** The index on (12)/(13), the stray $\le$ in
  (35)/(36), $RT_{ij}$ in (57), and the product with COP in (46) are identical in both.
  They are not transcription slips introduced in `thesisb.pdf`.

### 5.2 Equation numbering

Ch. IV numbers only (1)-(32), reuses (10), (11), and (12) for different equations, and
leaves many unnumbered. `thesisb.pdf` numbers (1)-(57) sequentially.

| `thesisb.pdf` | Ch. IV | Status |
|---|---|---|
| (1) | (1) | Same. `thesisb.pdf` adds a stray subscript $t$ |
| (2) | (3) | Same |
| (3) | unnumbered | **Corrected**: Ch. IV printed $E^{total}_t = P^{IT}_{st}\Delta t$; now $E^{IT}_{st} = P^{IT}_{st}\Delta t$ |
| (4), (5) | unnumbered | Same |
| (6) | unnumbered | Same |
| (7) | (2) | Same |
| (8) | (4) | Same; left side now $\min Z$ instead of $\min CE^{total}$ |
| (9)-(11) | (5)-(7) | Same |
| (12), (13) | (8), (9) | Same |
| (14) | unnumbered | Same |
| (15) | none | **Added** |
| (16) | (10) | Same |
| (17)-(19) | none | **Added** |
| (20), (21) | (11), (12) | Same |
| (22) | none (an empty table row captioned "How to get deadline using service time") | **Added** |
| (23) | (10), reused | Same |
| (24) | (11), reused | Same |
| (25) | (12), reused | Same |
| (26) | (11), reused again | Same |
| (27) | unnumbered | Same |
| (28) | (13) | Same |
| (29) | (14) | Same |
| (30) | none | **Added** |
| (31)-(34) | (15)-(18) | Same |
| (35), (36) | in the summary table only, unnumbered, not discussed in text | **Promoted** to numbered constraints |
| (37) | unnumbered (referred to as (19)) | Same |
| (38)-(40) | (20)-(22) | Same |
| (41), (42) | (25), (26) | Same |
| (43)-(45) | none | **Added** |
| (46) | unnumbered | Same |
| (47) | (27) | Same |
| (48) | unnumbered | Same |
| (49) | (28) | Same |
| (50)-(53) | none | **Added** |
| (54), (55) | (29), (30) | Same |
| (56), (57) | (31), (32) | Same |

### 5.3 Constraints added

- (15) $PC_s = N^{cores}_s f_s$, with the 2.1/2.4/3.0 GHz assignment.
- (17)-(19) idle and maximum power estimated from UniMelb observations.
- (22) maximum allowable delay.
- (30) initial server temperature from CPU1/CPU2 temperatures.
- (43)-(45) CRAC heat removal and return air temperature.
- (50)-(53) cold-plate heat removal, coolant outlet temperature, heat capacity rate.

### 5.4 Constraints removed

None. Ch. IV's table presented "$WT_i \le AD_i\ \forall i: RT_i = 0$ **or**
$ST_i - A_i \le AD_i\ \forall i$" as alternatives; `thesisb.pdf` keeps both, as (25) and
(28).

### 5.5 Symbols added, renamed, or reclassified

| Change | Ch. IV | `thesisb.pdf` |
|---|---|---|
| Heat removed by CRAC | $Q^{crac}_{st}$ ("heat removed by the CRAC system serving cooling zone $z$") | $Q^{crac,rem}_{zt}$ in the variable table; equations still use $Q^{crac}_{zt}$ and $Q^{crac}_{st}$ |
| Heat removed by cold plate | $Q^{cp}_{st}$ | $Q^{cp,rem}_{st}$ in the variable table; equations still use $Q^{cp}_{zt}$ and $Q^{cp}_{st}$ |
| Mislabelled rows | $Q^{crac}_{zt}$ and $Q^{cp}_{st}$ were also listed as "electrical power consumption" of the CRAC and cold plate | Those rows now use $P^{crac}_{zt}$ and $P^{cp}_{st}$ |
| New parameters | n/a | $ET^{base}_i$, $P^{obs}_{st}$, $U^{obs}_{st}$, $N^{cores}_s$, $f_s$, $c_{pw}$, $c_{pa}$, $T^0_s$ |
| New system variables | n/a | $T^{return}_{zt}$, $T^{cp,out}_{st}$, $C^{cp}_{st}$ (equation only) |
| $Y_{ist}$ | decision variable only | decision variable, and also listed as a Current Server State parameter |
| $T^{dvfs}_s$ wording | "Temperature at which server ss begins reducing its processing performance due to thermal conditions" | "Thermal-control temperature threshold at which the processing performance of server $s$ begins to be reduced to prevent overheating" |
| $\Delta t$ wording | "How long a server works in each time period" | "Duration of each scheduling period" |
| Parameter grouping | one flat list | grouped by input entity (Workload Arrival, Existing Accepted Schedule, and so on) |

### 5.6 Constants changed

Not applicable: Ch. IV has no constant values to change. Every numeric value in
section 4.1 is new in `thesisb.pdf`. $\Delta t = 5$ minutes went the other way: stated
in Ch. IV, blank in `thesisb.pdf`.

### 5.7 Other differences

- The system diagram is the same figure; Ch. IV's version carries Ch. IV equation
  numbers, and `thesisb.pdf`'s carries the partly stale numbers described in 2.8.
- Ch. IV's assumptions list (section 1.4 above) is not restated in `thesisb.pdf`.
- Ch. IV assumption 7 names Earliest Deadline First within a workload type. Neither
  document has an EDF constraint; only the type priority (56) and FIFO tiebreak (57).

---

## 6. Scenario levers

Grouped by the scenario dimensions named in the project goal, then by the thesis's own
subproblems. "Structural" means the item defines the shape of the model rather than a
run of it.

### 6.1 Natural to vary between runs

**Problem size and horizon**

| Lever | Symbols |
|---|---|
| Number of workloads, servers, zones, periods | $I$, $S$, $Z$, $T$ |
| Period length | $\Delta t$ (also changes the meaning of the lags in (35), (36)) |

**Workload mix**

| Lever | Symbols |
|---|---|
| Arrival pattern and deadlines | $A_i$, $D_i$ (and derived $AD_i$) |
| Resource demand | $C^{req}_i$, $M^{req}_i$ |
| Work content | $U^{CPU}_{it}$, $T^W_i$ (and derived $W_i$), $ET^{base}_i$ |
| Share of time-sensitive workloads | $RT_i$ |

**Server fleet**

| Lever | Symbols |
|---|---|
| Capacity | $C_s$, $M_s$ |
| Processing capability | $N^{cores}_s$, $f_s$ (and derived $PC_s$); the 4/3/3 split across 2.1/2.4/3.0 GHz |
| Power curve | $P^{idle}_s$, $P^{max}_s$ |
| Availability | $AV_{st}$ |
| Which servers have cold plates | $CT_s$ |
| Zone layout | $Z_{sz}$ |

**Thermal limits**

| Lever | Symbols |
|---|---|
| Server temperature ceiling | $T^{max}_s$ |
| Minimum headroom | $H^{min}$ (subproblem 3 varies exactly this) |
| Throttling curve | $T^{dvfs}_s$, $T^{throttle}_s$, $R^{dvfs}_s$, $F^{throttle}_s$ |
| Zone temperature ceiling and ramp limits | $T^{max}_z$; the 5 and 20 °C limits in (35), (36) |
| Initial thermal state | $T^0_s$ |

**Cooling limits**

| Lever | Symbols |
|---|---|
| CRAC capacity and operating window | $Q^{crac}_z$, $T^{crac,min}_z$, $T^{crac,max}_z$, $FR^{crac,min}_z$, $FR^{crac,max}_z$ |
| Cold-plate capacity and operating window | $Q^{cp}_s$, $T^{cp,min}_s$, $T^{cp,max}_s$, $FR^{cp,min}_s$, $FR^{cp,max}_s$ |
| Pump rating | $P^{cp,rated}_s$, $FR^{cp,rated}_s$ |

**Carbon intensity**

| Lever | Symbols |
|---|---|
| Grid carbon intensity profile | $CI_t$ (flat, time-varying, or by country) |

**Carried-over state (rolling horizon)**

| Lever | Symbols |
|---|---|
| Existing schedule | $X^0_{is}$, $B_i$ |
| Initial temperatures | $T^0_s$ |

### 6.2 Levers implied by the thesis subproblems

| Subproblem | What has to be switchable |
|---|---|
| 1. Zoning and reassignment | $Z_{sz}$; a restriction limiting reassignment to servers in the workload's current zone. This restriction is described in Ch. I but has **no equation** in either source |
| 2. CRAC versus cold plate | CRAC and cold-plate limits varied independently; cold plates enabled or disabled via $CT_s$ |
| 3. Thermal stress versus QoS | $H^{min}$ |
| 4. Reassignment versus carbon and QoS | Reassignment allowed or forbidden; $X^0_{is}$, $B_i$ |

### 6.3 Structural (fixed across scenarios)

- The index structure: workloads, servers, zones, periods; one zone per server; one
  equivalent CRAC per zone; a fixed cooling type per server.
- The objective form (8): carbon from IT, CRAC, and cold-plate pump energy.
- One server per workload (9); no migration of running workloads.
- The linear power model (20) and heat-equals-power (21).
- The functional forms of (37), (44), (46), (48), (51): piecewise DPF, flow times
  temperature difference, COP-based CRAC power, cubic pump law.
- Physical constants $c_{pw}$, $c_{pa}$.
- The near-idle threshold 0.01 in (17) and the rules (18), (19), (30) for deriving
  parameters from observed data. These are data-preparation conventions rather than
  model inputs.

### 6.4 Borderline

- **COP curve coefficients** (0.0068, 0.0008, 0.458): equipment-specific, so a
  different CRAC unit would change them, but the source gives a single curve.
- **Ramp-limit lags** (3 and 20 periods): fixed numbers in the source, but they encode
  "15 minutes" and "one hour" and so should follow $\Delta t$.
- **$T^W_i$**: undefined in the source; whether it is a scenario input or a fixed
  preprocessing rule depends on how section 7, C6 is answered.

---

## 7. Open questions

Problems in `thesisb.pdf` itself. None has been resolved here, and none should be
resolved by falling back to Ch. IV without saying so; for almost all of them Ch. IV has
the identical problem or is silent. Grouped by how much they block the Python model.

### A. Blocking: the model is not well-posed without an answer

**A1. No equation defines $T^{pred}_{st}$.** It is bounded by (31)-(33) and drives (37),
but nothing relates it to $Q^{heat}_{st}$, to heat removed, to $T^0_s$, or to
$T^{pred}_{s,t-1}$. As written the solver can set $T^{pred}_{st}$ to any value up to 80
°C regardless of load or cooling. Ch. I describes the intent in words ("determined
based on the current server temperature, the workload-induced temperature increase, and
the cooling support provided") but neither document gives a formula or the thermal
parameters (thermal mass, thermal resistance) one would need.

**A2. No equation defines $T^{zone}_{zt}$.** It is bounded by (34)-(36) only. It is not
related to $CRAC^{temp}_{zt}$, $T^{return}_{zt}$, or server heat.

**A3. Heat generated is never balanced against heat removed.** $Q^{heat}_{st}$ is
defined in (21) and then used nowhere. $Q^{crac}$ and $Q^{cp}$ are bounded above by (54)
and (55) but never bounded below by the heat that must be removed. Together with A1 and
A2 this means cooling has no purpose in the model as written: the cost-minimizing
solution is $CRAC^{flow}_{zt} = FR^{crac,min}_z = 0$ and minimum pump flow, with
temperatures unaffected.

**A4. The cooling physics equations are circular.** (45) is (44) solved for
$T^{return}_{zt}$, and (52) is (51) solved for $T^{cp,out}_{st}$ (the source says so:
"Used to solve Eqn (44)"). Each pair is one equation in two unknowns ($Q$ and the
outlet/return temperature), so neither is determined. (43) and (50) are the same
relationships again with placeholder symbols $c$ and $\Delta T$.

**A5. No linearization exists (section 3).** The abstract promises a MILP with
linearized thermal and cooling relationships; the formulation contains none. Whether to
linearize, and how, for (37), (38)-(39), (44)-(46), (48), (51)-(52) is undecided in the
sources.

**A6. $O_{ij}$ does nothing.** (56) and (57) set lower bounds on $O_{ij}$, but no
constraint links $O_{ij}$ to $ST_i$, $ST_j$, or $Y$. Priority therefore has no effect on
the schedule. There is also no antisymmetry ($O_{ij} + O_{ji}$) condition and no EDF
rule, although Ch. IV assumption 7 names EDF.

**A7. $r_{is}$ does nothing.** It appears only in (29). It is not linked to $X_{is}$ or
$X^0_{is}$, and nothing forces a running workload ($B_i = 1$) to keep
$X_{is} = X^0_{is}$, which is the stated intent.

**A8. $ST_i$ is not linked to $Y_{ist}$.** Nothing prevents $Y_{ist} = 1$ before $ST_i$
or after $CT_i$, and nothing requires execution periods to be contiguous. Yet
$CT_i = ST_i + ET_i$ in (26) with $ET_i = \sum Y_{ist}\Delta t$ in (40) only gives the
true completion time if execution is contiguous and starts at $ST_i$. $ST_i$ is in time
units while $t$ is a period index, with no stated conversion.

**A9. $\Delta t$ and the horizon have no values.** $\Delta t$ is blank; $I$, $Z$, $T$ are
unspecified. Ch. IV (superseded source) says 5 minutes. Different equations need
different units: seconds for $W_i$ in MHz·s (14, 39), hours for energy in kWh if $CI_t$
is per kWh (3-5).

**A10. Workload parameters under the UFCG decision.** `thesisb.pdf` marks $A_i$,
$D_i$, $C^{req}_i$, $M^{req}_i$, $U^{CPU}_{it}$, $ET^{base}_i$ "From dataset" without
naming one. With UFCG as the workload source (section 9.2), these remain open:
- **Units of work.** The model defines $U^{CPU}_{it}$ in MHz, $W_i$ in MHz·s (14), and
  $PC_s$ in MHz (15), so that (39) balances. UFCG `vcpu_usage` is not in MHz; it looks
  like percent of one vCPU summed over the VM's vCPUs. Either a conversion to MHz is
  needed (which requires a frequency for the UFCG hosts, not in the data) or the work
  unit in (14), (15), (39) changes. Neither document covers this, because both assumed
  Bitbrains, which reports MHz directly.
- **What a workload is.** UFCG rows are long-lived cloud VMs (many run for weeks or
  months), not finite jobs. The model needs each workload to have an arrival, a finite
  amount of work, and a deadline within the horizon. How a VM trace is cut into
  workloads, and what $T^W_i$ (C6) is, is undecided.
- **No deadlines or priority classes.** UFCG has no deadline, no time-sensitive flag,
  and no baseline execution time, so $D_i$, $RT_i$, and $ET^{base}_i$ need a generation
  rule that neither document gives.
- **Capacity units across datasets.** $C^{req}_i$ from UFCG flavors is in vCPUs and
  $M^{req}_i$ in MB; UniMelb gives 64 cores and `Ram` near 64.45 in an unverified unit.
  (12), (13), and (16) need these on a common scale.

### B. Equations that look wrong as printed

**B1. (12), (13): summation index.** Printed $\sum_s$ with $\forall s,t$. The sum must
be over $i$ for the constraint to mean what the text says; (16) writes the same quantity
with $\sum_i$. Identical in Ch. IV.

**B2. (22): inequality defining a parameter.** $AD_i \ge D_i - A_i - ET^{base}_i$ leaves
$AD_i$ unbounded above. The text ("determines the maximum allowable delay by
subtracting") reads as an equality. Also, (28) applies the delay limit to all workloads
while (25) applies it only to delay-tolerant ones, so (25) is redundant; and it is not
stated whether time-sensitive workloads are meant to have a tighter limit (for example
$AD_i = 0$).

**B3. (35), (36): stray symbols, missing range, inconsistent lags.**
- Both are printed with an extra "$\le$" after the minus sign.
- (35) uses a lag of 3 periods for "15 minutes", which implies $\Delta t = 5$ minutes.
  (36) uses a lag of 20 periods for "one hour", which implies $\Delta t = 3$ minutes. At
  5 minutes, one hour is 12 periods. **Resolved 2026-10-10: 12 periods (section 10).**
- (36) is stated $\forall z,t$ with no lower limit on $t$ ($t - 20 \ge 1$ needs
  $t \ge 21$).
- The text describes "inlet air temperature" but the variable is the zone temperature
  $T^{zone}_{zt}$.

**B4. (46): COP multiplied, and $Q$ indexed by server.** The source's own text beside
(43)-(44) defines COP as "the ratio of cooling capacity to the total electrical power
consumed", which gives power = heat / COP. (46) prints power = heat × COP. It also uses
$Q^{crac}_{st}$ (per server) summed with $Z_{sz}$, while every other equation uses the
zone-level $Q^{crac}_{zt}$; no per-server CRAC heat is defined. Identical in Ch. IV.

**B5. (57): $RT_{ij}$.** Printed $RT_i = RT_{ij}$; $RT$ has one index. Presumably
$RT_j$. Identical in Ch. IV.

**B6. Cold-plate terms are not switched by $CT_s$.** The note under (5) says
$E^{cp}_{st} = 0$ for servers without cold plates, but $CT_s$ appears in no equation.
(47) applies $\forall s$ with $FR^{cp,min}_s = 0.005$ L/min, so every server would have
a running pump.

**B7. (1): stray subscript.** $\min Z = CE^{total}_t$; (7) defines $CE^{total}$.

**B8. (29): quantifier.** $\forall i,s$ on a constraint that sums over $s$.

**B9. (39): no sharing of capacity among co-located workloads.** Each workload executing
on a server is credited the server's full $PC^{eff}_{st}$, regardless of how many other
workloads run there in the same period. (12) limits CPU demand, but (39) does not divide
processing capability. This may be intended; it is not discussed.

### C. Symbol and definition inconsistencies

**C1. Three definitions of initial temperature.** $T^0_{st}$ ("Initial temperature of
server $s$ at time $t$", from dataset, under Current Server State); $T^0_s$ under
Thermal State with the note "Initially set to 0, then based on the initial temp that the
model solves, the values are updated for each run"; and Eq. (30), which sets $T^0_s$
from the CPU temperatures. "Set to 0" and (30) conflict for the first run. $T^0$ is then
used in no constraint (see A1).

**C2. $Y_{ist}$ listed as both parameter and decision variable.** It appears under
Current Server State and under Decision variables with the same definition. Possibly the
parameter listing means the carried-over execution state from the previous run.

**C3. Symbol collisions.** $CT_s$ (cold-plate binary) versus $CT_i$ (completion time).
$Z$ is the objective value, the number of zones, and the base of $Z_{sz}$. $T$ is the
number of periods and the base of every temperature. $Q^{crac}_z$ (capacity parameter)
versus $Q^{crac}_{zt}$ (heat removed).

**C4. Heat-removal variables have several names.** The variable table defines
$Q^{crac,rem}_{zt}$ and $Q^{cp,rem}_{st}$. The equations use $Q^{crac}_{zt}$ (43, 44,
54), $Q^{CRAC}_{zt}$ (45), $Q^{crac}_{st}$ (46); and $Q^{cp}_{zt}$ (50, 51, 52),
$Q^{cp}_{st}$ (55). The cold-plate ones mix zone and server indices within a single
equation.

**C5. (17) uses the model variable.** $T^{idle}_s$ is defined with $U_{st}$, the
optimization variable, but the text describes observed UniMelb utilization, which is
$U^{obs}_{st}$. $T$ in (17) is then the observation record, not the planning horizon.
(19) takes a max with no stated index range.

**C6. $T^W_i$ is undefined.** The "selected workload window" in (14) is not specified:
which periods, how many, and whether it relates to $ET^{base}_i$.

**C7. Duplicated and mislabelled rows.** $f_s$, $T^{return}_{zt}$, and $P^{cp}_{st}$ are
each listed twice. $CP^{temp}_{st}$ and $CP^{flow}_{st}$ are described as "for cooling
zone $z$" but indexed by server. $C^{cp}_{st}$ (53) is not in any table and is used
nowhere else. $H^{min}$ in the table is $H_{min}$ in (32).

**C8. Stale cross-references.** See 2.8.

### D. Units, magnitudes, and feasibility

**D1. Unit inconsistencies.**
- $c_{pw}$ is printed as 4182 kJ/(kg·°C) and $c_{pa}$ as 1.00643 kJ/(kg·°C). One of the
  two is off by a factor of 1000 relative to the other's unit label.
- Flows are volumetric (m³/s, L/min) but specific heats are per kilogram. (44) and (51)
  need air and water densities, which are not given.
- Cold-plate temperatures are in kelvin (293.15, 313.1); every other temperature is in
  °C. $T^{cp,max}_s$ is printed 313.1, not 313.15.
- $P^{cp,rated}_s$ is printed "0.657mW". Whether this is milliwatts, watts, or something
  else is unclear.
- $Q^{crac}_z$ and $Q^{cp}_s$ are in kW; server power from UniMelb is presumably in
  watts (unit not stated).
- $f_s$ is MHz in the table and GHz in the text.
- Units of $C_s$, $C^{req}_i$, $M_s$, $M^{req}_i$, $A_i$, $D_i$, $ST_i$, $ET^{base}_i$
  are not stated. $C_s$ and $C^{req}_i$ must share a unit for (12) and (16), and it is
  not said whether that is cores or MHz.
- $CI_t$ has no unit; the cited chart reports gCO₂ per kWh.

**D2. The full-throttle branch of (37) is unreachable.** (31)-(32) with
$T^{max}_s = 90$ and $H^{min} = 10$ force $T^{pred}_{st} \le 80$ °C. The third branch
needs $T^{pred}_{st} \ge T^{throttle}_s = 100$ °C, which is also above $T^{max}_s$. With
base-run values, $DPF_{st}$ ranges only from 1 down to
$1 - \tfrac{80-75}{100-75}(0.378) = 0.9244$. Also, (33) is redundant given (32)
whenever $H^{min} > 0$.

**D3. $DPF$ is discontinuous and non-monotone at $T^{throttle}_s$.** Just below 100 °C
the middle branch gives $1 - 0.378 = 0.622$; at 100 °C the third branch gives
$F^{throttle}_s = 0.662$, so performance rises when the server crosses into "throttled".
The two constants are digit transpositions of each other (0.622 and 0.662), which may
indicate a typo in one of them. Moot under D2 with base values, but live if thermal
limits are varied as scenario levers.

**D4. Carbon intensity is annual.** The only source cited for $CI_t$ is an annual
national figure. A value constant over $t$ makes the objective proportional to total
energy, so shifting work in time has no carbon benefit, which is the mechanism Ch. I
uses to motivate a carbon objective. The country is not specified. Ch. IV assumption 10
says the factor is time-varying and known per interval.

**D5. CRAC capacity is far from binding at base-run scale.** $Q^{crac}_z = 116$ kW
against ten servers whose observed maximum power in UniMelb is under 0.4 kW each (per
the notebook's output). (54) cannot bind in the base run. The number of zones and the
servers per zone are not given.

**D6. $FR^{crac,min}_z = 0$.** Zero airflow is allowed, which makes the ratio in (45)
undefined.

### E. Underspecified inputs

- **E1.** $RT_i$, $X^0_{is}$, $B_i$, $AV_{st}$, $CT_s$, $Z_{sz}$ have blank value cells
  (section 4.4). Ch. I says cold plates go on high-processing-capability servers; no
  rule or count is given.
- **E2.** Which of the 10 servers receive 2.1, 2.4, and 3.0 GHz is not stated.
- **E3.** How $ET^{base}_i$ is derived from data is not stated. Its relationship to
  $W_i$ and $PC_s$ (for example $W_i / PC_s$, which depends on the server) is not
  stated either.
- **E4.** How the 10-minute UniMelb series is "adjusted to match" 5-minute periods
  (Ch. IV assumption 13) is not described in either document. Still needed with UFCG,
  which is also 5-minute. The two datasets also cover different dates (UniMelb from
  October 2018, UFCG from May 2024), so periods can only be aligned by position, not by
  calendar time.
- **E5.** The rolling-horizon procedure (how often the model is re-solved, over what
  window, and what is carried over) is described only in prose in Ch. I and in the
  $T^0_s$ table note.

---

## 8. `old_notebook.ipynb`: what it is and where it diverges

**It is not an implementation of the optimization model.** The notebook has 20 cells of
Google Colab data preparation (pandas, with scikit-learn in the last cell). It imports
no optimization library and defines no variables, objective, or constraints. There is
therefore no formulation in it to compare against `thesisb.pdf` equation by equation.
It does contain data-preparation choices that feed model parameters, and some of those
diverge. With Bitbrains scrapped, everything it does on the workload side is obsolete;
only its UniMelb server-side work (server selection, idle and maximum power) is still
relevant.

What it does:
- Loads the UniMelb combined dataset (same 18 columns as `data/raw/UniMelb.csv`; it reports
  2,748,525 rows and 81 servers, matching the file here) and selects 10 servers
  stratified by mean CPU load: 3 low, 4 medium, 3 high, seed 42, requiring 90% row
  completeness.
- Loads 10 Bitbrains VM traces (files `1.csv` to `10.csv`, read from Google Drive; not
  in this repository) as the workloads.
- Summarizes both into per-server and per-workload profile tables, a 10 × 10
  workload-server compatibility table, and a final 10-row table pairing workload $k$
  with server $k$.
- Estimates idle and maximum power several ways and compares them.

Divergences from `thesisb.pdf`:

| Topic | `thesisb.pdf` | Notebook |
|---|---|---|
| $P^{max}_s$ | (19): highest observed power | Cells 15, 17, 18 compute $P^{max} = P^{idle}/0.7$ (labelled "Hsieh 70% assumption"); cell 18 compares it against highest observed power; cell 19 tries a CPU-load-versus-power regression. For example qh2-rcc120: 225.7 W by the 70% rule against 376.0 W observed |
| $P^{idle}_s$ | (17)-(18): mean power where utilization $\le 1\%$ | Cell 17 matches this. Cell 15 instead uses the power at the single minimum-load observation |
| $C^{req}_i$ | "CPU demand", unit not stated | CPU cores × CPU usage fraction (core-equivalents), kept as mean, P95, and max; P95 proposed as the working value |
| $W_i$ | (14): sum of $U^{CPU}_{it}\Delta t$ in MHz·s | Not computed. CPU usage in MHz is retained as a summary statistic only |
| $PC_s$, $f_s$ | (15), with 2.1/2.4/3.0 GHz | Not computed; no frequencies assigned |
| $T^0_s$ | (30): max of CPU1 and CPU2 temperature at the first period | Not computed; uses mean CPU1 temperature as a descriptive statistic |
| Time dimension | Indexed by $t$ throughout | Time series are collapsed to one row per server and per workload; the notebook states it does not build the $i \times s \times t$ table |
| $A_i$, $D_i$, $RT_i$, $ET^{base}_i$ | Required | Absent |
| Cooling, zones, carbon | Required | Absent |
| $M_s$ | "Total memory capacity" | Kept as `M_s_raw`; the notebook flags that the unit of UniMelb `Ram` is unverified and skips memory feasibility for that reason |

Other things to know:
- **The 10 selected servers are not consistent within the notebook.** Cell 3's output
  lists a stratified set (qh2-rcc168, 154, 122, 172, 120, 128, 148, 159, 126, and one
  more). Cell 10's output uses qh2-rcc120 through qh2-rcc129. Cells 15 to 18 report on
  qh2-rcc120, 123, 128, 129, 130, 136, 139, 143, 146, 149. Which set is the base run's
  "10 servers" is not established by the notebook.
- The workload-to-server pairing in the final table is, by the notebook's own comment,
  "ONLY an experimental summary pairing" that "does NOT constrain the later MILP
  assignment $X_{is}$".
- UFCG data is not used anywhere in the notebook.

---

## 9. Candidate datasets and the parameters they could feed

Skimmed for columns and basic shape only. Neither dataset has been validated.

### 9.1 `data/raw/UniMelb.csv` (613 MB; 2,748,525 data rows)

Physical server telemetry at 10-minute intervals, starting 2018-10-09. The notebook
reports 81 servers. This is the dataset `thesisb.pdf` names.

| Column | Could feed | Notes |
|---|---|---|
| `Series` | server index $s$ | Server name, e.g. `qh2-rcc120`, with trailing whitespace |
| `Time` | observation period $t$ | 10-minute spacing; model periods are 5 minutes per Ch. IV |
| `CPU_Load` | $U^{obs}_{st}$ for (17) | Appears to be on a 0-100 scale (notebook reports a maximum near 58). The 0.01 threshold in (17) needs the scale settled; the notebook applies it as `CPU_Load <= 1` |
| `Power` | $P^{obs}_{st}$, then $P^{idle}_s$ (18) and $P^{max}_s$ (19) | Unit not documented; values of roughly 70 to 380 suggest watts |
| `CPU1_Temperature`, `CPU2_Temperature` | $T^0_s$ via (30) | °C by magnitude |
| `CPU_cores` | $N^{cores}_s$, and possibly $C_s$ | 64 for every row in the first 400,000 rows (21 servers). If that holds for all servers, core count is homogeneous and heterogeneity in $PC_s$ comes only from the assigned $f_s$ |
| `Ram` | $M_s$ | About 64.45 to 64.49 in the sample; unit unverified |
| `Inlet_Temperature` | no model parameter as written | Could inform $T^{zone}_{zt}$ or CRAC supply temperature calibration. About 3% missing |
| `Ram_Used`, `CPU_cores_used`, `No_Of_Running_vms` | no model parameter as written | Describe the existing load on each server |
| `Fan_speed1`..`Fan_speed4` | none | Server fans are not modelled |
| `Network_RX`, `Network_TX` | none | Network is excluded by delimitation |

Does not provide: CPU frequency (hence the literature values in (15)), any workload-level
data, zone membership, or cooling equipment data.

### 9.2 `data/raw/UFCG/*.csv` (about 8 GB across seven files): the workload dataset

An OpenStack cloud trace: virtual machine instances, their flavors, owners, and usage.
In OpenStack terms a "server" is a VM, so **a UFCG `server_id` corresponds to a workload
$i$ in the model, not a server $s$**. Neither `thesisb.pdf` nor Ch. IV mentions this
dataset; the mapping below follows from the project decision and from the columns, not
from the thesis.

Shape, from the first 3,000,000 rows of `servers_usage.csv` plus the last row of the
file (not a full scan):
- Timestamps are Unix seconds. The file runs from about 2024-05-23 to about 2025-05-17.
- Snapshot spacing is 5 minutes (median gap 300 s, per VM and overall), with occasional
  gaps of several hours.
- The sample covers about 85 days and contains 233 distinct VMs on 49 distinct hosts.

| File | Columns | Feeds |
|---|---|---|
| `flavors.csv` (17 rows) | `flavor_id`, `flavor_name`, `vcpu`, `ram`, `disk` | $C^{req}_i$ from `vcpu` (1 to 18) and $M^{req}_i$ from `ram` (by magnitude MB: 1024 to 32768), via the VM's flavor. One flavor has `ram` = 4, which looks like a data error or a different unit |
| `servers_specs.csv` (1.5 GB) | `id`, `timestamp`, `server_id`, `flavor_id` | Joins each VM to its flavor at each snapshot. First appearance of a `server_id` is a candidate for $A_i$ |
| `servers_usage.csv` (1.9 GB) | `id`, `timestamp`, `server_id`, `vcpu_usage`, `ram_usage`, `host_id` | `vcpu_usage` is the only candidate for $U^{CPU}_{it}$ and so $W_i$. `host_id` (the physical host of each VM) is a candidate for $X^0_{is}$ only if UFCG hosts were the model's servers, which they are not under the UniMelb decision |
| `servers_ownerships.csv` (2.4 GB) | `id`, `timestamp`, `server_id`, `user_id`, `project_id` | None directly. Could support grouping workloads by project |
| `user_projects.csv` (2.1 GB) | `id`, `timestamp`, `user_id`, `project_id` | None |
| `projects_quota.csv` | `timestamp`, `project_id`, `quota_ram`, `quota_vcpu` | None |
| `projects_quota_allocated.csv` (196 MB) | `id`, `timestamp`, `project_id`, `ram_allocated`, `vcpu_allocated` | None |

Units, inferred from the sampled values and not documented in the files:
- `vcpu_usage`: quartiles 1.0 / 6.1 / 33.4, 99th percentile 174.5, maximum 1600.5. A
  ceiling of 1600 matches a 16-vCPU flavor at 100% per vCPU, so this reads as percent
  of one vCPU, summed over vCPUs (0 to 100 × `vcpu`). **Not MHz.**
- `ram_usage`: 0 to 99.98, so percent of the flavor's RAM.

Does not provide: deadlines, a time-sensitive flag, baseline execution time, CPU usage
in MHz, host CPU frequency, power, or temperature. See open question A10.

### 9.3 Parameters no dataset in the repository can supply

$D_i$, $RT_i$, $ET^{base}_i$, $AD_i$ (derived), $B_i$, $AV_{st}$, $CT_s$, $Z_{sz}$,
$CI_t$, $f_s$, and all cooling and thermal constants. $A_i$ and $W_i$ can be drawn from
UFCG only after the definitional questions in A10 are answered.

---

## 10. Data preparation as implemented (added 2026-10-09)

`data_prep.ipynb` turns the raw datasets into model inputs (run all cells, or `uv run jupyter-execute --inplace notebooks/data_prep.ipynb`). It replaced the `dataprep/` package on 2026-10-10.
Every alignment decision is a commented value in the notebook's Settings cell; cleaned tables
are in `data/clean/` (with a log of what each step removed) and ready-to-solve instances
in `scenarios/<name>/`. This section records the decisions that settle open questions
above. They are project decisions, not statements from either PDF.

| Open item | Decision | Basis |
|---|---|---|
| UniMelb core count | 64. Only records before 2019-03-14 11:40 are used | `CPU_cores` switches to 128 for every server on 2019-03-15, with a different load scale and idle power |
| `CPU_Load` scale, Eq. (17) | 0-100, so near-idle is `CPU_Load <= 1` | Only 92 rows are at or below 0.01 |
| `Ram` unit, $M_s$ | units of 8 GB, so about 516 GB per server | 64.488 x 8 x 75 hosts = 38,692 GB, the fleet total in Ilager et al. (2021), Table III |
| $C_s$ and $C^{req}_i$ unit (D1) | cores; one vCPU occupies one core | |
| E4, 10- to 5-minute adjustment | not needed | UniMelb supplies only static per-server parameters |
| A10, what a workload is; C6, $T^W_i$ | one UFCG VM whose whole life is inside the trace; $T^W_i$ is its observed slots, gaps of up to 3 slots (interpolated), and collector-outage slots (at the VM's mean usage). Longer gaps while the collector was up are left out | 502 VMs survive cleaning |
| Missing usage (`NA`, 22% of rows) | host-level: 26 of 102 UFCG hosts never report usage. Their VMs are dropped by default; same-flavor imputation is available behind `impute_unmonitored` in the notebook's Settings cell, and imputed workloads are flagged `usage_imputed` | Checked 2026-10-10. Other hosts are about 0.4% `NA` |
| A10, units of work | one vCPU at 100% = 2,400 MHz | UFCG reports percent of a vCPU |
| B9 and E3, $ET^{base}_i$ | $W_i / (C^{req}_i \cdot f_{ref})$: a workload is served by its own requested cores | With (39) as printed most workloads finish in under one period |
| B2, Eq. (22) | equality | |
| B3, Eq. (36) lag | 12 periods (one hour at $\Delta t = 5$ min), not the printed 20. Applies for $t = 13,\dots,T$. The 3-period lag of Eq. (35) is unchanged | Confirmed by the thesis group, 2026-10-10 |
| $D_i$, $RT_i$, zones, $CT_s$, which servers get which $f_s$, daily shape of $CI_t$ | generated by rule in `data_prep.ipynb` part 3; listed in each scenario's `params.json` under `assumed_not_from_data` | No dataset supplies them |
| A1, temperature equation | $T^{pred}_{st} = \alpha_s T^{pred}_{s,t-1} + (1-\alpha_s)\,[CRAC^{temp}_{zt} + a_s + R_s(P^{IT}_{st} - Q^{cp,rem}_{st})]$ for the zone $z$ of $s$, with $T^{pred}_{s,0} = T^0_s$. $\alpha_s$, $a_s$, $R_s$ are the per-server fit in `servers.csv` | Approved by the thesis group, `Findings_10-11.pdf` (2026-10-12). Cited to Lin et al. (2024) |
| A2, zone temperature | $T^{zone}_{zt} = CRAC^{temp}_{zt}$; CRAC supply air = server inlet air | Approved, `Findings_10-11.pdf` |
| A3, heat balance | $Q^{crac,rem}_{zt} \ge \sum_s Z_{sz}(Q^{heat}_{st} - Q^{cp,rem}_{st})$. The group's second line reads $0 \le Q^{crac,rem}_{st} \le Q^{heat}_{st}$, probably meaning $Q^{cp,rem}$; not yet confirmed | Approved, `Findings_10-11.pdf` |
| Cold-plate heat removal | Per server $s$ with $n_s$ plates and period $t$: $Q^{cp}_{st} \le n_s \cdot 0.3$ kW, $Q^{cp}_{st} \le Q^{heat}_{st}$, $Q^{cp}_{st} \le n_s (T^{pred}_{s,t-1} - CP^{temp}_{st}) / R^{cp}(CP^{flow}_{st})$ (all "$\le$"; previous period's temperature, $T^0_s$ in period 1). The evaluator takes the largest value these allow. $CP^{flow}_{st}$ is chosen from 0.10, 0.15, 0.20, 0.25, 0.30 L/min with $R^{cp}$ = 0.1543, 0.1143, 0.0943, 0.0843, 0.0793 °C/W; 0.05 and 0.35 L/min are only the limits of (47). Pump power (48) uses 0.657 **mW** at 0.264 L/min as its reference, and 0.264 L/min is not one of the settings. Coolant temperature is 20 to 39.95 °C (the printed kelvin values), water at 1 kg/L and $c_{pw}$ = 4182 J/(kg·°C), and the conductance is capped by the water's heat capacity rate. Plates per server: `n_cold_plates` in `servers.csv` (editable; 0 = none, which also gives $E^{cp} = 0$), or `--cold-plate-count N` for every server. Each plate is identical with its own pump. The baseline runs its plates at 0.30 L/min and 20 °C. Linearized with a one-hot flow choice and the temperature difference split across the settings. Off unless `--cold-plates` is passed | Thesis group, `IE_Thesis_Master_Document.pdf` and follow-up, 2026-10-14. $R^{cp}$ is from Wang et al. (2026), Fig. 10(a), CPU 1: $(T_{cpu,max} - T_{in})/P_{cpu}$ at 200 W. Pump power is from Wang and Tao (2025) |
| Minimum cold-plate flow | 0.05 L/min. The parameter table's 0.005 is a typo. `data_prep.ipynb` and the scenarios' `params.json` now say 0.05 | Thesis group, 2026-10-14; they will correct the table |
| **FLAGGED**: cold-plate settings carry almost no cost | Pump power is at most about 1 mW per plate, and no equation charges energy for cooling the water. The optimizer therefore runs flow and coolant wherever they remove the most heat. Where the 0.3 kW limit or $Q^{heat}$ binds (88 of 96 periods on `small`), the reported flow and coolant values are arbitrary, so the expected "how the optimizer adjusts coolant temperature" output carries no information yet. **Decision:** explain this in the writeup and revisit after the first prototype, for example with a chiller or CDU energy term. Every cold-plate run prints this flag | Thesis group, 2026-10-14 |
| Server on/off | Not modelled. All servers stay on for the whole horizon and draw idle power; Eq. (20) unchanged | Decided by the thesis group, `Findings_10-11.pdf` |
| Infeasibility | All constraints are hard; no fallback. If no schedule satisfies them, the program reports that no solution exists and which limits cause it | Decided by the thesis group, `Findings_10-11.pdf` |
| Required outputs | Tables and charts listed under "expected results" in `Findings_10-11.pdf`, including baseline versus proposed emissions per period | Thesis group, 2026-10-12 |
