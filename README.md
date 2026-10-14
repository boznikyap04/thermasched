# ThermaSched

Integrated optimization model for **thermal-aware workload scheduling and air-liquid
cooling control** in heterogeneous data centers. Python translation of the DLSU IE
thesis *"An Integrated Optimization Model for Thermal-Aware Workload Scheduling and
Air-Liquid Cooling Control in Heterogeneous Data Centers"*.

- `scheduler/` — model, baseline, optimizer, evaluation, reporting
- `scenarios/` — scenario inputs (`small`, `base`, `thesis10`)
- `results/` — run outputs
- `data_prep.ipynb`, `Data/clean/` — data cleaning pipeline and cleaned data
- `PROJECT_CONTEXT.md` — full model specification and design decisions

Raw datasets (`Data/UniMelb.csv`, `UFCG/*.csv`) are not tracked because of their size.

## Setup

```sh
uv sync
uv run pytest
```
