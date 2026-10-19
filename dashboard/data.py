"""Read-only loaders for ThermaSched run outputs.

A run lives in ``results/<scenario>/<run_name>/`` (see ``scheduler/report.py``). This module
turns one into tidy pandas frames: per-variant CSVs are stacked into one long frame with a
``variant`` column ("baseline" / "optimized"), servers carry their names from
``scenarios/<scenario>/servers.csv``, and every per-period frame gets the local clock time
from ``scenarios/<scenario>/carbon.csv``.

There is no Streamlit here so the loaders can be tested directly; the UI caches them.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
RESULTS_DIR = Path(os.environ.get("THERMASCHED_RESULTS_DIR", REPO_ROOT / "results"))
SCENARIOS_DIR = Path(os.environ.get("THERMASCHED_SCENARIOS_DIR", REPO_ROOT / "scenarios"))

VARIANTS = ("baseline", "optimized")
VARIANT_LABELS = {"baseline": "Baseline", "optimized": "Optimized"}

# Energy components in stacking order: column -> label.
ENERGY_COMPONENTS = {
    "E_IT_kWh": "IT",
    "E_crac_kWh": "CRAC",
    "E_cp_kWh": "Cold-plate pumps",
    "E_fan_kWh": "Fans",
}

# Workload types as written in schedule.csv.
WORKLOAD_TYPES = {"time_sensitive": "Time-sensitive", "delay_tolerant": "Delay-tolerant"}

# Constraint families relaxed one at a time by scheduler.optimize.diagnose_infeasibility.
RELAX_FAMILY_LABELS = {
    "deadlines_and_waiting": "Deadlines and waiting limits, Eq. (27)-(28)",
    "thermal_cap": "Thermal cap T <= T_max - H_min, Eq. (31)-(33)",
    "capacity": "CPU and memory capacity, Eq. (12)-(13)",
    "cooling_capacity": "CRAC cooling capacity, Eq. (54)",
    "priority": "Priority order, Eq. (56)-(57)",
}

# Monday 2000-01-03 as a dummy date: only the clock time is shown.
CLOCK_ORIGIN = pd.Timestamp("2000-01-03")
ZERO_TOL = 1e-12


# ---------------------------------------------------------------------------
# Run discovery
# ---------------------------------------------------------------------------

@dataclass(frozen=True, order=True)
class RunRef:
    scenario: str
    name: str
    path: Path = field(compare=False)

    @property
    def key(self) -> str:
        return f"{self.scenario}/{self.name}"


def discover_runs(results_dir: str | Path = RESULTS_DIR) -> list[RunRef]:
    """Every ``<results_dir>/<scenario>/<run>/summary.json``, sorted by scenario and run."""
    root = Path(results_dir)
    if not root.is_dir():
        return []
    return sorted(RunRef(p.parent.parent.name, p.parent.name, p.parent)
                  for p in root.glob("*/*/summary.json"))


def load_summary(run_dir: str | Path) -> dict:
    with open(Path(run_dir) / "summary.json") as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Scenario inputs: servers and clock
# ---------------------------------------------------------------------------

def scenario_file(scenario: str, name: str, scenarios_dir: str | Path = SCENARIOS_DIR,
                  run_dir: str | Path | None = None) -> Path | None:
    """``scenarios/<scenario>/<name>``, else ``<name>`` next to the run folders
    (``results/<scenario>/<name>``, where an unzipped run export puts it), else None."""
    for path in (Path(scenarios_dir) / scenario / name,
                 Path(run_dir).parent / name if run_dir is not None else None):
        if path is not None and path.is_file():
            return path
    return None


def load_servers(scenario: str, run_dir: str | Path | None = None,
                 scenarios_dir: str | Path = SCENARIOS_DIR) -> pd.DataFrame:
    """Columns s, name, zone, label, zone_label; sorted by zone then s (display order).

    Names come from the scenario's ``servers.csv`` (see ``scenario_file``), else from the
    run's ``compliance_servers.csv``, else "server <s>".
    """
    path = scenario_file(scenario, "servers.csv", scenarios_dir, run_dir)
    if path is not None:
        df = pd.read_csv(path, usecols=["s", "server", "zone"]).rename(columns={"server": "name"})
    else:
        df = pd.DataFrame(columns=["s", "name", "zone"])
        if run_dir is not None:
            comp = Path(run_dir) / "baseline" / "compliance_servers.csv"
            if comp.is_file():
                df = pd.read_csv(comp, usecols=["s", "name", "zone"])
    df = df.astype({"s": int, "zone": int})
    df["name"] = df["name"].fillna(df["s"].map(lambda s: f"server {s}")).astype(str)
    df["zone_label"] = "Zone " + df["zone"].astype(str)
    df["label"] = df["name"] + " (Z" + df["zone"].astype(str) + ")"
    return df.sort_values(["zone", "s"]).reset_index(drop=True)


def _with_zones(servers: pd.DataFrame, zones: list[int]) -> pd.DataFrame:
    df = servers.copy()
    df["zone"] = df["s"].map(dict(zip(range(1, len(zones) + 1), zones))).astype(int)
    df["zone_label"] = "Zone " + df["zone"].astype(str)
    df["label"] = df["name"] + " (Z" + df["zone"].astype(str) + ")"
    return df.sort_values(["zone", "s"]).reset_index(drop=True)


def hours_to_clock(hour_local: pd.Series) -> pd.Series:
    """Decimal local hours -> Timestamps on a dummy date, rolling to the next day at midnight.

    ``hour_local`` is printed to 3 decimals (3.6 s), so it is snapped to the nearest 30 s.
    """
    seconds = (np.round(hour_local.to_numpy(float) * 120) * 30).astype(np.int64)
    day = np.concatenate([[0], np.cumsum(np.diff(seconds) < 0)])
    return pd.Series(CLOCK_ORIGIN + pd.to_timedelta(day * 86400 + seconds, unit="s"),
                     index=hour_local.index)


def load_clock(scenario: str, T: int, dt_seconds: float,
               scenarios_dir: str | Path = SCENARIOS_DIR,
               run_dir: str | Path | None = None) -> pd.DataFrame:
    """Columns t, hour_local, time, clock for t = 1..T.

    ``time`` is the local time at the middle of period t (``carbon.csv:hour_local``, found
    by ``scenario_file``); a period covers ``time +/- dt/2``. Without carbon.csv the clock
    starts at 00:00.
    """
    path = scenario_file(scenario, "carbon.csv", scenarios_dir, run_dir)
    t = pd.DataFrame({"t": np.arange(1, T + 1)})
    if path is not None:
        carbon = pd.read_csv(path, usecols=["t", "hour_local"])
        t = t.merge(carbon, on="t", how="left")
    else:
        t["hour_local"] = np.nan
    if t["hour_local"].isna().any():
        # Fill gaps (or a missing file) by extending the known periods at dt per period.
        known = t.dropna(subset=["hour_local"])
        h0 = (known["hour_local"].iloc[0] - (known["t"].iloc[0] - 1) * dt_seconds / 3600
              if len(known) else 0.5 * dt_seconds / 3600)
        t["hour_local"] = t["hour_local"].fillna(((h0 + (t["t"] - 1) * dt_seconds / 3600) % 24))
    t["time"] = hours_to_clock(t["hour_local"])
    t["clock"] = t["time"].dt.strftime("%H:%M")
    return t


def period_bounds(clock: pd.DataFrame, dt_seconds: float):
    """Function t -> Timestamp of the *start* of period t, extrapolated past 1..T.

    Used for schedule bars: a workload starting in period ``start`` with exclusive end
    ``finish`` spans ``bound(start)`` to ``bound(finish)``.
    """
    t0 = clock["time"].iloc[0] - pd.Timedelta(seconds=dt_seconds / 2)

    def bound(t):
        return t0 + pd.to_timedelta((np.asarray(t, dtype=float) - 1) * dt_seconds, unit="s")
    return bound


# ---------------------------------------------------------------------------
# One run
# ---------------------------------------------------------------------------

def _read_variants(run_dir: Path, filename: str, variants: tuple[str, ...]) -> pd.DataFrame:
    frames = []
    for v in variants:
        path = run_dir / v / filename
        if path.is_file():
            df = pd.read_csv(path)
            df.insert(0, "variant", v)
            frames.append(df)
    if not frames:
        return pd.DataFrame(columns=["variant"])
    return pd.concat(frames, ignore_index=True)


@dataclass
class Run:
    ref: RunRef
    summary: dict
    variants: tuple[str, ...]          # variants with a folder on disk, baseline first
    servers: pd.DataFrame
    clock: pd.DataFrame
    period: pd.DataFrame               # variant, t, energy, CI, carbon_g, time, clock
    comparison_period: pd.DataFrame    # t, CI, baseline_/optimized_/diff_ columns, time, clock
    server_period: pd.DataFrame        # variant, s, t, ..., name, zone, label, time, clock
    zone_period: pd.DataFrame          # variant, z, t, ..., zone_label, time, clock
    schedule: pd.DataFrame             # variant, i, ..., server_name, original_server_name
    compliance_servers: pd.DataFrame
    compliance_zones: pd.DataFrame
    compliance_workloads: pd.DataFrame
    compliance_cold_plates: pd.DataFrame = field(default_factory=pd.DataFrame)
    reassignment: pd.DataFrame = field(default_factory=pd.DataFrame)   # optimized only

    # -- summary shortcuts ------------------------------------------------------------
    @property
    def settings(self) -> dict:
        return self.summary.get("settings", {})

    @property
    def solver(self) -> dict:
        return self.summary.get("solver") or {}

    @property
    def has_optimized(self) -> bool:
        return bool(self.summary.get("has_optimized_schedule")) and "optimized" in self.variants

    @property
    def dt_seconds(self) -> float:
        return float(self.summary.get("scenario", {}).get("dt_seconds", 300.0))

    @property
    def thermal_cap_C(self) -> float:
        return float(self.summary.get("thermal_cap_C", 80.0))

    @property
    def T_dvfs_C(self) -> float:
        return float(self.summary.get("T_dvfs_C", 75.0))

    @property
    def T_max_C(self) -> float | None:
        """Server temperature limit T_max (headroom is measured from it)."""
        sp = self.server_period
        if sp.empty or "headroom_C" not in sp:
            return None
        return float((sp["temperature_C"] + sp["headroom_C"]).median())

    @property
    def H_min_C(self) -> float | None:
        t_max = self.T_max_C
        return None if t_max is None else t_max - self.thermal_cap_C

    def server_name(self, s) -> str:
        if s is None:
            return "–"
        m = self.servers.set_index("s")["name"]
        return str(m.get(int(s), f"server {s}"))


def load_run(run_dir: str | Path, scenarios_dir: str | Path = SCENARIOS_DIR) -> Run:
    run_dir = Path(run_dir)
    ref = RunRef(run_dir.parent.name, run_dir.name, run_dir)
    summary = load_summary(run_dir)
    sc = summary.get("scenario", {})
    scenario = sc.get("name", ref.scenario)
    variants = tuple(v for v in VARIANTS if (run_dir / v).is_dir())

    servers = load_servers(scenario, run_dir, scenarios_dir)
    zones = sc.get("zones")       # the run's own zones (a --zone-map run differs from servers.csv)
    if zones and len(zones) == len(servers):
        servers = _with_zones(servers, zones)
    dt = float(sc.get("dt_seconds", 300.0))
    T = int(sc.get("T") or _max_t(run_dir / "baseline" / "period.csv"))
    clock = load_clock(scenario, T, dt, scenarios_dir, run_dir)
    tcols = clock[["t", "time", "clock"]]

    def with_time(df: pd.DataFrame) -> pd.DataFrame:
        return df.merge(tcols, on="t", how="left") if "t" in df else df

    period = with_time(_read_variants(run_dir, "period.csv", variants))
    cmp_path = run_dir / "comparison_period.csv"
    comparison = with_time(pd.read_csv(cmp_path)) if cmp_path.is_file() else pd.DataFrame()

    server_cols = servers[["s", "name", "zone", "zone_label", "label"]]
    server_period = _read_variants(run_dir, "server_period.csv", variants)
    if not server_period.empty:
        server_period = with_time(server_period.merge(server_cols, on="s", how="left"))

    zone_period = _read_variants(run_dir, "zone_period.csv", variants)
    if not zone_period.empty:
        zone_period["zone_label"] = "Zone " + zone_period["z"].astype(str)
        if "airflow" in zone_period:
            # "not modelled" when airflow is off; keep a numeric column either way.
            zone_period["airflow"] = pd.to_numeric(zone_period["airflow"], errors="coerce")
        zone_period = with_time(zone_period)

    names = servers.set_index("s")["name"]
    schedule = _read_variants(run_dir, "schedule.csv", variants)
    if not schedule.empty:
        for col in ("server", "original_server"):
            schedule[f"{col}_name"] = schedule[col].map(names)
        schedule["type_label"] = schedule["type"].map(WORKLOAD_TYPES).fillna(schedule["type"])

    comp_servers = _read_variants(run_dir, "compliance_servers.csv", variants)
    if not comp_servers.empty and "name" not in comp_servers:
        comp_servers["name"] = comp_servers["s"].map(names)

    return Run(
        ref=ref, summary=summary, variants=variants, servers=servers, clock=clock,
        period=period, comparison_period=comparison, server_period=server_period,
        zone_period=zone_period, schedule=schedule, compliance_servers=comp_servers,
        compliance_zones=_read_variants(run_dir, "compliance_zones.csv", variants),
        compliance_workloads=_read_variants(run_dir, "compliance_workloads.csv", variants),
        compliance_cold_plates=_read_variants(run_dir, "compliance_cold_plates.csv", variants),
        reassignment=_read_reassignment(run_dir / "optimized" / "reassignment.csv", names),
    )


def _read_reassignment(path: Path, names: pd.Series) -> pd.DataFrame:
    """optimized/reassignment.csv with server names; empty for older runs without it."""
    if not path.is_file():
        return pd.DataFrame()
    df = pd.read_csv(path)
    for col in ("original_server", "final_server"):
        df[f"{col}_name"] = df[col].map(names)
    return df


def _max_t(path: Path) -> int:
    return int(pd.read_csv(path, usecols=["t"])["t"].max()) if path.is_file() else 0


# ---------------------------------------------------------------------------
# Derived views
# ---------------------------------------------------------------------------

def is_all_zero(series: pd.Series) -> bool:
    """True when a column has no non-zero number (all zero, blank or non-numeric)."""
    values = pd.to_numeric(series, errors="coerce").to_numpy(float)
    return bool(np.all(np.isnan(values) | (np.abs(values) <= ZERO_TOL)))


def nonzero_columns(df: pd.DataFrame, columns) -> list[str]:
    """The given columns that exist in ``df`` and are not all zero, in the given order."""
    return [c for c in columns if c in df and not is_all_zero(df[c])]


def active_energy_components(run: Run) -> list[str]:
    """Energy columns with any non-zero value in any variant (E_IT and E_crac always)."""
    always = ["E_IT_kWh", "E_crac_kWh"]
    extra = nonzero_columns(run.period, [c for c in ENERGY_COMPONENTS if c not in always])
    return always + extra


# (key, label, unit, better) for the KPI tiles; better is "lower", "higher" or "neutral".
KPIS = [
    ("carbon_kg", "Total carbon", "kg CO₂", "lower"),
    ("E_total_kWh", "Total energy", "kWh", "lower"),
    ("E_IT_kWh", "IT energy", "kWh", "lower"),
    ("E_crac_kWh", "CRAC energy", "kWh", "lower"),
    ("E_cp_kWh", "Cold-plate pump energy", "kWh", "lower"),
    ("E_fan_kWh", "Fan energy", "kWh", "lower"),
    ("hottest_T_C", "Hottest server temperature", "°C", "lower"),
    ("min_headroom_C", "Minimum thermal headroom", "°C", "higher"),
    ("periods_above_dvfs", "Server-periods above DVFS", "", "lower"),
    ("periods_above_cap", "Server-periods above cap", "", "lower"),
    ("n_late", "Late workloads", "", "lower"),
    ("n_noncompliant", "Non-compliant workloads", "", "lower"),
    ("n_priority_violations", "Priority inversions", "", "lower"),
    ("n_reassigned", "Reassigned workloads", "", "neutral"),
    ("n_cross_zone", "Moved to another zone", "", "neutral"),
]
# KPIs older runs do not have; dropped from the tiles when missing on both sides.
OPTIONAL_KPIS = ("n_priority_violations", "n_cross_zone")


def kpi_frame(summary: dict) -> pd.DataFrame:
    """One row per KPI: key, label, unit, better, baseline, optimized, diff, pct.

    ``optimized``/``diff``/``pct`` are NaN without an optimized schedule; ``pct`` is NaN
    when the baseline is 0. All-zero energy components (not modelled) are dropped.
    """
    base = (summary.get("baseline") or {}).get("metrics", {})
    opt = (summary.get("optimized") or {}).get("metrics", {}) \
        if summary.get("has_optimized_schedule") else {}
    rows = []
    for key, label, unit, better in KPIS:
        b, o = base.get(key), opt.get(key)
        if key in ("E_cp_kWh", "E_fan_kWh") and not b and not o:
            continue
        if key in OPTIONAL_KPIS and b is None and o is None:
            continue
        b = np.nan if b is None else float(b)
        o = np.nan if o is None else float(o)
        diff = o - b
        pct = diff / b * 100 if b and not np.isnan(diff) else np.nan
        rows.append(dict(key=key, label=label, unit=unit, better=better,
                         baseline=b, optimized=o, diff=diff, pct=pct))
    return pd.DataFrame(rows)


def checks_frame(summary: dict) -> pd.DataFrame:
    """Self-checks: name, label, passed (True/False/None), detail."""
    rows = []
    for name, c in (summary.get("checks") or {}).items():
        c = c if isinstance(c, dict) else {"passed": c}
        detail = {k: v for k, v in c.items() if k != "passed"}
        rows.append(dict(name=name, label=name.replace("_", " ").capitalize(),
                         passed=c.get("passed"),
                         detail="; ".join(f"{k.replace('_', ' ')}: {_fmt_detail(v)}"
                                          for k, v in detail.items())))
    return pd.DataFrame(rows, columns=["name", "label", "passed", "detail"])


def _fmt_detail(v) -> str:
    if isinstance(v, float):
        return f"{v:,.6g}"
    if isinstance(v, list):
        return "none" if not v else "; ".join(map(str, v))
    return str(v)


def infeasibility_frame(summary: dict) -> pd.DataFrame:
    """family, label, result: one row per constraint family the diagnosis relaxed."""
    diag = summary.get("infeasibility") or {}
    return pd.DataFrame(
        [dict(family=k, label=RELAX_FAMILY_LABELS.get(k, k.replace("_", " ")), result=v)
         for k, v in diag.items()], columns=["family", "label", "result"])


SAVINGS_COLUMNS = ["component", "label", "energy_saved_kWh", "carbon_saved_kg",
                   "energy_effect_kg", "timing_effect_kg"]


def savings_breakdown(run: Run) -> pd.DataFrame:
    """Where the savings came from, one row per energy component.

    Carbon per period is CI * E_total, so carbon saved splits exactly by component:
    ``carbon_saved_kg = sum_t CI_t * (E_base - E_opt)``. Positive means the optimized run
    emitted less. It is split further into an energy effect (the kWh saved at the mean
    carbon intensity) and a timing effect (the rest: energy moved to cleaner or dirtier
    periods), which explains carbon saved on IT even when IT kWh do not change.
    """
    cp = run.comparison_period
    if cp.empty or not run.has_optimized:
        return pd.DataFrame(columns=SAVINGS_COLUMNS)
    ci = cp["CI_g_per_kWh"]
    rows = []
    for col in active_energy_components(run):
        saved = -cp[f"diff_{col}"].fillna(0.0)
        saved = saved.where(saved.abs() > ZERO_TOL, 0.0)
        carbon = _clean(float((saved * ci).sum() / 1000))
        energy_effect = _clean(float(saved.sum() * ci.mean() / 1000))
        rows.append(dict(component=col, label=ENERGY_COMPONENTS[col],
                         energy_saved_kWh=_clean(float(saved.sum())), carbon_saved_kg=carbon,
                         energy_effect_kg=energy_effect,
                         timing_effect_kg=carbon - energy_effect))
    return pd.DataFrame(rows, columns=SAVINGS_COLUMNS)


def _clean(x: float, tol: float = 1e-9) -> float:
    """Round float noise (e.g. -7e-16 kWh) to an exact 0 so it does not print as -0.0000."""
    return 0.0 if abs(x) < tol else x


def cumulative_savings(run: Run) -> pd.DataFrame:
    """t, time, clock, carbon_saved_kg (running total) and per-component running totals."""
    cp = run.comparison_period
    if cp.empty or not run.has_optimized:
        return pd.DataFrame(columns=["t", "time", "clock", "carbon_saved_kg"])
    out = cp[["t", "time", "clock"]].copy()
    out["carbon_saved_kg"] = (-cp["diff_carbon_g"].fillna(0.0)).cumsum() / 1000
    for col in active_energy_components(run):
        out[f"{col}_carbon_saved_kg"] = \
            (-(cp[f"diff_{col}"].fillna(0.0) * cp["CI_g_per_kWh"])).cumsum() / 1000
    return out


def workload_moves(run: Run) -> pd.DataFrame:
    """One row per workload, baseline next to optimized (server, start, finish, wait).

    Without an optimized schedule the optimized columns are NaN.
    """
    sch = run.schedule
    if sch.empty:
        return pd.DataFrame()
    keep = ["i", "workload_id", "type", "type_label", "arrival", "allowed_delay", "deadline"]
    per = ["server_name", "start", "finish", "wait", "compliant"]
    b = sch[sch["variant"] == "baseline"]
    out = b[keep + per].rename(columns={c: f"{c}_baseline" for c in per})
    if run.has_optimized:
        o = sch[sch["variant"] == "optimized"]
        o = o[["i", "original_server_name", "reassigned"] + per].rename(
            columns={c: f"{c}_optimized" for c in per})
        out = out.merge(o, on="i", how="left")
    else:
        out["original_server_name"] = out["server_name_baseline"]
        out["reassigned"] = 0
        for c in per:
            out[f"{c}_optimized"] = np.nan
    ra = run.reassignment
    if not ra.empty:
        out = out.merge(ra[["i", "original_zone", "final_zone", "cross_zone", "reason"]],
                        on="i", how="left")
    out["wait_change"] = out["wait_optimized"] - out["wait_baseline"]
    out["start_shift"] = out["start_optimized"] - out["start_baseline"]
    out["reassigned"] = out["reassigned"].fillna(0).astype(bool)
    return out.reset_index(drop=True)


def gantt_lanes(schedule: pd.DataFrame) -> pd.Series:
    """Lane index per row so workloads running at once on a server get separate rows.

    Greedy interval partitioning per (variant, server) on [start, finish); unplaced
    workloads (no server or start) get lane -1.
    """
    lanes = pd.Series(-1, index=schedule.index, dtype=int)
    ok = schedule["server"].notna() & schedule["start"].notna() & schedule["finish"].notna()
    for _, grp in schedule[ok].groupby(["variant", "server"]):
        ends: list[float] = []
        for idx, row in grp.sort_values(["start", "finish", "i"]).iterrows():
            for k, end in enumerate(ends):
                if end <= row["start"]:
                    ends[k] = row["finish"]
                    lanes[idx] = k
                    break
            else:
                ends.append(row["finish"])
                lanes[idx] = len(ends) - 1
    return lanes


def throttled_servers(run: Run) -> pd.DataFrame:
    """Servers with DPF < 1 anywhere: variant, s, name, periods_throttled, min_DPF."""
    sp = run.server_period
    if sp.empty or "DPF" not in sp:
        return pd.DataFrame(columns=["variant", "s", "name", "periods_throttled", "min_DPF"])
    low = sp[sp["DPF"] < 1 - 1e-9]
    if low.empty:
        return pd.DataFrame(columns=["variant", "s", "name", "periods_throttled", "min_DPF"])
    return (low.groupby(["variant", "s", "name"], as_index=False)
            .agg(periods_throttled=("t", "size"), min_DPF=("DPF", "min")))


def compare_runs(runs: list[RunRef]) -> pd.DataFrame:
    """One row per run (summary.json only): settings, solver and key metrics."""
    rows = []
    for ref in runs:
        try:
            s = load_summary(ref.path)
        except (OSError, json.JSONDecodeError) as e:
            rows.append(dict(scenario=ref.scenario, run=ref.name, status=f"unreadable: {e}"))
            continue
        st, sol = s.get("settings", {}), s.get("solver") or {}
        base = (s.get("baseline") or {}).get("metrics", {})
        has_opt = bool(s.get("has_optimized_schedule"))
        opt = (s.get("optimized") or {}).get("metrics", {}) if has_opt else {}
        supply = (f"fixed {_supply_fixed(st):g} °C" if st.get("supply_temp_mode") == "fixed"
                  else "optimized")
        b_c, o_c = base.get("carbon_kg"), opt.get("carbon_kg")
        b_e, o_e = base.get("E_total_kWh"), opt.get("E_total_kWh")
        rows.append(dict(
            scenario=ref.scenario, run=ref.name,
            baseline_rule=st.get("baseline_rule"),
            baseline_supply_C=st.get("baseline_supply_temp_C"),
            reassignment=st.get("reassignment"), supply_temp=supply,
            H_min_C=st.get("H_min_C"), cold_plates=bool(st.get("cold_plates")),
            cp_mode=st.get("cp_mode", "optimize") if st.get("cold_plates") else None,
            priority=st.get("priority", False),
            zone_map=",".join(map(str, st["zone_map"])) if st.get("zone_map") else None,
            carbon=_carbon_label(st),
            status=sol.get("status"), solve_time_s=sol.get("solve_time_s"),
            mip_gap=sol.get("mip_gap"),
            baseline_valid=(s.get("baseline") or {}).get("valid"),
            optimized_valid=(s.get("optimized") or {}).get("valid") if has_opt else None,
            baseline_carbon_kg=b_c, optimized_carbon_kg=o_c,
            carbon_saved_kg=(b_c - o_c) if has_opt and b_c is not None else None,
            carbon_saved_pct=(b_c - o_c) / b_c * 100 if has_opt and b_c else None,
            baseline_E_total_kWh=b_e, optimized_E_total_kWh=o_e,
            energy_saved_pct=(b_e - o_e) / b_e * 100 if has_opt and b_e else None,
            baseline_hottest_C=base.get("hottest_T_C"), optimized_hottest_C=opt.get("hottest_T_C"),
            n_reassigned=opt.get("n_reassigned"), n_cross_zone=opt.get("n_cross_zone"),
            optimized_n_noncompliant=opt.get("n_noncompliant"),
        ))
    return pd.DataFrame(rows)


def _carbon_label(settings: dict) -> str:
    if settings.get("carbon_file"):
        return Path(settings["carbon_file"]).name
    return "flat (mean)" if settings.get("ci_flat") else "scenario"


def _supply_fixed(settings: dict) -> float:
    v = settings.get("fixed_supply_temp_C")
    return float(settings.get("baseline_supply_temp_C", 18.0) if v is None else v)


def settings_badges(summary: dict) -> list[tuple[str, str]]:
    """(label, value) pairs that describe a run's switches, in display order."""
    st = summary.get("settings", {})
    supply = (f"fixed at {_supply_fixed(st):g} °C" if st.get("supply_temp_mode") == "fixed"
              else "optimized")
    cp = "off"
    if st.get("cold_plates"):
        n = st.get("cold_plate_count")
        cp = "on (servers.csv)" if n is None else f"{n} per server"
        if st.get("cp_mode") == "fixed":
            flow = st.get("fixed_cp_flow_Lmin") or st.get("baseline_cp_flow_Lmin")
            cool = st.get("fixed_cp_coolant_C") or st.get("baseline_cp_coolant_C")
            cp += f", fixed at {flow:g} L/min, {cool:g} °C"
    h_min = st.get("H_min_C")
    return [
        ("Baseline rule", str(st.get("baseline_rule", "?")).replace("_", " ")),
        ("Baseline supply", f"{st.get('baseline_supply_temp_C', '?'):g} °C"
         if isinstance(st.get("baseline_supply_temp_C"), (int, float)) else "?"),
        ("Reassignment", str(st.get("reassignment", "?")).replace("_", " ")),
        ("Supply temperature", supply),
        ("H_min", "scenario default" if h_min is None else f"{h_min:g} °C"),
        ("Cold plates", cp),
        ("Priority (56)-(57)", "on" if st.get("priority") else "off"),
        ("Zones", "servers.csv" if not st.get("zone_map")
         else ",".join(map(str, st["zone_map"]))),
        ("Carbon intensity", _carbon_label(st)),
        ("Fan power", "on" if st.get("fan_power") else "off"),
        ("Time limit", f"{st.get('time_limit_s', 0):g} s"),
        ("MIP gap", f"{st.get('mip_rel_gap', 0):g}"),
    ]
