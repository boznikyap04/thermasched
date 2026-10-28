# Server configuration: three questions before we rebuild the runs

*Reply to the edit guide of 28 October 2026. Answered the same day: A to all three.*

We checked the new server setup (R840 at 2.1 and 2.4 GHz with CRAC cooling, C6320 at 2.6 GHz
with CRAC and a cold plate) against the SPEC pages you sent, the UniMelb dataset and its paper.
Most of it fits. Three values do not line up between the sources, and each one changes the
results, so we need your decision on each before we rebuild the scenarios and re-run
Chapter 6. Each question ends with what we recommend and what to reply.

## What we found on your guide

**The C6320 has its own UniMelb data.** The UniMelb dataset [1] has two files. We have used
only the first, 80 Dell R840 servers. The second covers **64 Dell C6320 servers** (February to
June 2019), with power, CPU temperature, memory and core counts. So the C6320 servers can use
their own measured power, as your guide asks, and nothing has to be borrowed from the R840s.

**The core check.** Neither the dataset nor its paper [2] names the processors. Against the
SPEC pages:

| Server | Processor on the SPEC page | Frequency | Cores (threads) per server | Matches the dataset? |
|---|---|---|---|---|
| R840 | Xeon Gold 6130 [3] | 2.1 GHz | 32 (64), 2 chips | **Yes**: the dataset gives 64 |
| R840 | Xeon Gold 6148 [4] | 2.4 GHz | 80 (160), 4 chips | No |
| C6320 | Xeon E5-2690 v4 [5] | 2.6 GHz | 28 (56), 2 chips | No: the dataset gives 80 |

So, as your guide allows, the thesis should say that **the frequencies are assumptions taken
from SPEC results for these server models**.

**The links.** Both "exact location" links in the guide go to the same page, the C6320 result
[5]. No R840 page was linked; we used the 2018 Q2 CPU2017 results [3], [4]. Please tell us if
you meant different pages.

**How long a run takes.** With the current setup, one run (one 24-hour day, re-planned every
5 minutes) typically takes 4 to 34 min on 6 servers (slowest 1.4 h) and 16 min to 2.3 h on 10
servers (slowest 2.7 h), depending on the day. The 39 runs of
a fleet go in parallel, so a full set takes about 1.5 h (6 servers) or 3 h (10 servers). The
new setup will likely be slower (see Question 2).

---

## Question 1: How many cores per server?

**Why it matters.** Chapter 4 computes a server's processing capability as cores × frequency,
so the core count sets how much work each server can do and how efficient it looks.

**The mismatch.** The sources disagree, but in a consistent pattern:

| Source | R840 | C6320 |
|---|---|---|
| Paper, text [2] (§2.1): "cores/CPU" × 2 CPUs | 64 × 2 = **128** | 80 × 2 = **160** |
| Paper, Table 1 [2]: total cores ÷ hosts | 10,240 ÷ 80 = 128 | 16,384 ÷ 64 = **256** |
| Dataset [1], before mid-March 2019 | **64** | **80** |
| Dataset [1], after mid-March 2019 | 128 | 160 (some 320) |
| SPEC pages [3]–[5] | 32 or 80 | 28 |

In March 2019 the cloud doubled the number of virtual CPUs it offered per server, in both
clusters. The paper's text matches the dataset *after* that change. Before it, the dataset gives
64 and 80, which are the servers' hardware threads. No processor these servers can hold has 64
or 80 cores per chip, so the paper's "cores/CPU" means virtual CPUs, not physical cores. The
paper's Table 1 does not match its own text for the C6320 (256 against 160).

**Options.**

- **A. R840 64, C6320 80** (dataset, before the doubling). The R840 keeps the 64 cores used in
  every run so far.
- **B. R840 128, C6320 160** (the paper's text). Every server's capacity doubles, the R840s
  too, so the current R840 setup changes as well.

Both keep the same 5 : 4 ratio between the C6320 and the R840, so the comparison between
server types comes out the same either way. We do not recommend the SPEC core counts: they
describe different machines from the ones the power data comes from.

**Effect on the results.** With either option, the C6320 servers become the *least* efficient
per unit of work (option A: 1.76 W per GHz, against 1.34 to 1.53 for the R840s; option B: half
of each). Today the cold-plate tier is the *most* efficient (1.07). So the optimizer will move
work off the cold-plate servers, and Section 6.2 (cold plates) will likely show a smaller
effect than in the current results.

**We recommend A.** **Reply with:** A or B.

---

## Question 2: How much memory does a C6320 have?

**Why it matters.** The light, normal and heavy days are built by drawing workloads until 30,
60 or 85 % of the fleet's memory or cores is in use, whichever fills first. Today memory fills
first in every scenario, so the memory value decides how many workloads each day has.

**The mismatch.**

| Source | R840 | C6320 |
|---|---|---|
| Paper, text [2] (§2.1) | 64 GB | **196 GB** |
| Paper, Table 1 [2]: total memory ÷ hosts | 128 GB | 384 GB |
| Paper, Table 3 [2]: highest memory in use | 64.42 GB | 191.41 GB |
| Dataset [1], measured | **64.5 GB** (used today) | **193.3 GB** on 62 servers, 258 GB on 2 |

The text, Table 3 and the dataset agree; Table 1 does not, and we take it as a typo. 196 GB is
most likely the nominal figure and 193.3 GB what the servers report. The 2 servers with 258 GB
are a different configuration; we leave them out.

**Options.**

- **A. 193 GB** (measured, as we already use 64.5 GB measured for the R840).
- **B. 64 GB**, the same as the R840. This keeps today's workload counts and run times, but it
  gives the C6320 a third of the memory it has.

**Effect of A on the days** (estimated before rebuilding):

| Day | 6 servers: now → with A | 10 servers: now → with A |
|---|---|---|
| Light | 45 → about 75 workloads | 91 → about 145 |
| Normal | 132 → about 220 | 257 → about 410 |
| Heavy | 210 → about 350 | 370 → about 590 |

The days get bigger with no change to the 30 / 60 / 85 % rule. Two costs: only 339 workloads in
the UFCG catalogue fit within a day, so beyond that the same workloads are drawn again (on the
10-server heavy day, about 250 of the 590); and runs will be slower, most on the 10-server
heavy day. This bears on your adviser's question about metaheuristics.

**We recommend A.** **Reply with:** A or B.

---

## Question 3: What inlet temperature do we use for the C6320?

**Why it matters.** Each server's CPU temperature is modelled as inlet temperature + a fixed
offset + thermal resistance × power. To fit that offset and resistance, we need the server's
measured inlet temperature. The cold-plate servers are the C6320s, so this feeds Section 6.2
and the 90 °C CPU limit.

**The mismatch.** The R840 file has an inlet temperature for each server, every 10 minutes. The
C6320 file has none, and no fan speeds. The paper [2] (§2.1, §5) only says these "are not
available" for the C6320 and gives no reason. We traced it in the data: every server whose
records start on **1 February 2019** has neither reading. That includes all 64 C6320s **and 5
R840s** (`qh2-rcc196` to `200`), while the 76 R840s monitored since October 2018 have both. The
same server model has the reading or not depending on when it was added, so the gap comes from
how the monitoring was set up in February 2019, not from the hardware. (The 5 R840s were already
excluded from our model because most of their data is missing.)

**Options.**

- **A. Use the R840s' measured inlet at the same time.** Same data center, same months
  (February to June 2019): mean 18.8 °C, standard deviation 0.6 °C, leaving out the 4.0 °C
  readings a failed sensor gives.
- **B. Use a fixed 18.8 °C**, the R840s' average. Simpler, but it ignores the room's swings.
- **C. Ask the dataset's authors** whether the C6320 inlet exists and where those racks sit.
  The contact is on the Zenodo page [1]. This may take time; we can start with A and switch if
  they answer.

Either way, the thesis states it as an assumption, since we do not know where the C6320s sit
relative to the R840s.

**We recommend A** (and C in parallel if you want to try). **Reply with:** A, B, or A + C.

---

## Reply template

```
Q1 cores:   A / B
Q2 memory:  A / B
Q3 inlet:   A / B / A + C
SPEC pages: the R840 pages we used are right / please use: <links>
```

## References

1. Ilager, S. (2023). *A Data-driven Analysis of a Cloud Data Center: Statistical
   Characterization of Workload, Energy and Temperature* [Dataset]. Zenodo.
   <https://doi.org/10.5281/zenodo.10069402> (files: `dataset1_combined.csv` = R840,
   `dataset2_combined.csv` = C6320)
2. Ilager, S., Toosi, A. N., Jha, M. R., Brandic, I., & Buyya, R. (2023). A data-driven
   analysis of a cloud data center: Statistical characterization of workload, energy and
   temperature. *Proc. 16th IEEE/ACM Int. Conf. on Utility and Cloud Computing (UCC 2023)*.
   <https://doi.org/10.1145/3603166.3632137>. PDF:
   <http://hpc.ec.tuwien.ac.at/files/UCC_23_data_center_analysis.pdf> (§2.1, Tables 1 and 3, §5)
3. SPEC CPU2017 Integer Rate result, Dell PowerEdge R840, Intel Xeon Gold 6130 (2018 Q2).
   <https://www.spec.org/cpu2017/results/res2018q2/cpu2017-20180514-05589.html>
4. SPEC CPU2017 Integer Rate result, Dell PowerEdge R840, Intel Xeon Gold 6148 (2018 Q2).
   <https://www.spec.org/cpu2017/results/res2018q2/cpu2017-20180514-05562.html>
5. SPEC CPU2006 Integer Rate result, Dell PowerEdge C6320, Intel Xeon E5-2690 v4 (2017 Q3).
   <https://www.spec.org/cpu2006/results/res2017q3/cpu2006-20170725-47889.html>
