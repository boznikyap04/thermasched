"""Read-only loaders for ThermaSched run outputs.

A run lives in ``results/<scenario>/<run_name>/`` (see ``scheduler/report.py``). This module
turns one into tidy pandas frames: per-variant CSVs are stacked into one long frame with a
``variant`` column ("baseline" / "optimized"), servers carry their names from
``scenarios/<scenario>/servers.csv``, and every per-period frame gets the local clock time
from ``scenarios/<scenario>/carbon.csv``.

There is no Streamlit here so the loaders can be tested directly; the UI caches them.
"""

from __future__ import annotations

import dataclasses
import json
import os
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

from scheduler import experiments as ex
from scheduler.build import scenario_fingerprint
from scheduler.types import STATUS_OPTIMAL, STATUS_TIME_LIMIT, status_text
from scheduler.version import SCHEMA_VERSION, VERSION

REPO_ROOT = Path(__file__).resolve().parents[1]
RESULTS_DIR = Path(os.environ.get("THERMASCHED_RESULTS_DIR", REPO_ROOT / "results"))
SCENARIOS_DIR = Path(os.environ.get("THERMASCHED_SCENARIOS_DIR", REPO_ROOT / "scenarios"))
# Validation tables, results/validation/<scenario>/ (written by the validation checks).
VALIDATION_DIR = RESULTS_DIR / "validation"

VARIANTS = ("baseline", "optimized")
VARIANT_LABELS = {"baseline": "Baseline", "optimized": "Optimized"}
# The variant name of the Base in against_base: the test charts draw it dashed.
BASE_LABEL = "Base"

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


# Folders under results/ named "archive-<scenario>" hold runs set aside (made before release
# 1.0.0). They are listed after the current scenarios; their summary.json still names the
# real scenario, whose servers.csv and carbon.csv they use.
ARCHIVE_PREFIX = "archive-"


def is_archive(scenario: str) -> bool:
    return scenario.startswith(ARCHIVE_PREFIX)


def scenario_order(scenario: str) -> tuple:
    """Current scenarios first, then the archived ones, each alphabetically."""
    return is_archive(scenario), scenario


def run_order(ref: RunRef) -> tuple:
    return scenario_order(ref.scenario) + (ref.name,)


def discover_runs(results_dir: str | Path = RESULTS_DIR) -> list[RunRef]:
    """Every ``<results_dir>/<scenario>/<run>/summary.json``, sorted by scenario and run."""
    root = Path(results_dir)
    if not root.is_dir():
        return []
    return sorted((RunRef(p.parent.parent.name, p.parent.name, p.parent)
                   for p in root.glob("*/*/summary.json")), key=run_order)


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
    def provenance(self) -> dict:
        return provenance(self.summary)

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


# (key, label, unit, better) for the key results tiles; better is "lower", "higher" or
# "neutral".
KPIS = [
    ("carbon_kg", "Total carbon", "kg CO₂", "lower"),
    ("E_total_kWh", "Total energy", "kWh", "lower"),
    ("E_IT_kWh", "IT energy", "kWh", "lower"),
    ("E_crac_kWh", "CRAC energy", "kWh", "lower"),
    ("E_cp_kWh", "Cold-plate pumps", "Wh", "lower"),
    ("hottest_T_C", "Hottest server", "°C", "lower"),
    ("min_headroom_C", "Lowest headroom", "°C", "higher"),
    ("n_late", "Missed deadlines", "", "lower"),
    ("n_reassigned", "Workloads moved", "", "neutral"),
]
# Stored in kWh but shown in Wh: the pumps use a fraction of a watt-hour a day.
KPI_SCALE = {"E_cp_kWh": 1000.0}


def _optimized_metrics(summary: dict | None) -> dict:
    if not summary or not summary.get("has_optimized_schedule"):
        return {}
    return (summary.get("optimized") or {}).get("metrics", {})


def kpi_frame(summary: dict, base: dict | None = None) -> pd.DataFrame:
    """One row per KPI of the optimized schedule: key, label, unit, better, value, base,
    diff, pct.

    ``base`` is the summary of the run to compare with (the Base of the test's section);
    ``base``/``diff``/``pct`` are NaN without it, ``value`` without an optimized schedule,
    and ``pct`` when the Base's value is 0. Cold-plate pump energy is dropped when it is zero
    in both (plates off).
    """
    mine, other = _optimized_metrics(summary), _optimized_metrics(base)
    rows = []
    for key, label, unit, better in KPIS:
        v, b = mine.get(key), other.get(key)
        if key == "E_cp_kWh" and not v and not b:
            continue
        scale = KPI_SCALE.get(key, 1.0)
        v = np.nan if v is None else float(v) * scale
        b = np.nan if b is None else float(b) * scale
        diff = v - b
        pct = diff / abs(b) * 100 if b and not np.isnan(diff) else np.nan
        rows.append(dict(key=key, label=label, unit=unit, better=better,
                         value=v, base=b, diff=diff, pct=pct))
    return pd.DataFrame(rows, columns=["key", "label", "unit", "better", "value", "base",
                                       "diff", "pct"])


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


def same_schedule(a: Run, b: Run) -> bool:
    """True when two runs' optimized schedules put every workload on the same server at the
    same start. Cooling and carbon can still differ (other zones, another carbon intensity)."""
    def key(run: Run) -> pd.DataFrame:
        sch = run.schedule
        sch = sch[sch["variant"] == "optimized"] if not sch.empty else sch
        return sch[["i", "server", "start"]].sort_values("i").reset_index(drop=True)
    if not (a.has_optimized and b.has_optimized):
        return False
    ka, kb = key(a), key(b)
    return len(ka) > 0 and ka.equals(kb)


def against_base(run: Run, label: str, base: Run | None = None) -> Run:
    """The optimized schedule of ``run`` as variant ``label`` and, when given, that of
    ``base`` as variant BASE_LABEL, in one Run for the test charts (the first variant drawn
    solid, the Base dashed). The Base's per-server rows take this run's server names and
    zones, so a test that regroups the zones lines up server by server. The limits (thermal
    cap, DVFS temperature, H_min) stay this run's."""
    pairs = [(run, label)]
    if base is not None and base.has_optimized:
        pairs.append((base, BASE_LABEL))
    server_cols = run.servers[["s", "name", "zone", "zone_label", "label"]]

    def stack(attr: str) -> pd.DataFrame:
        frames = []
        for r, name in pairs:
            df = getattr(r, attr)
            if df.empty or "variant" not in df:
                continue
            df = df[df["variant"] == "optimized"].assign(variant=name)
            if attr == "server_period" and r is not run:
                df = (df.drop(columns=[c for c in server_cols if c != "s" and c in df])
                      .merge(server_cols, on="s", how="left"))
            frames.append(df)
        return pd.concat(frames, ignore_index=True) if frames else getattr(run, attr).iloc[0:0]

    return dataclasses.replace(
        run, variants=tuple(name for _, name in pairs), period=stack("period"),
        server_period=stack("server_period"), zone_period=stack("zone_period"),
        schedule=stack("schedule"), compliance_zones=stack("compliance_zones"))


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


UNVERSIONED = "before 1.0.0"     # runs made before summary.json had a provenance block
UNKNOWN_BUILD = "unknown"


def provenance(summary: dict) -> dict:
    """summary.json's provenance block; empty for runs made before release 1.0.0."""
    p = summary.get("provenance")
    return p if isinstance(p, dict) else {}


def provenance_caption(summary: dict) -> str:
    """One line on what made a run: release, where, when, and the scenario build."""
    p = provenance(summary)
    if not p:
        return (f"Made {UNVERSIONED}: this run records no release or scenario build, so it "
                "cannot be checked against other runs.")
    where = {"command line": "from the command line", "dashboard": "on the dashboard"}.get(
        p.get("made_with"), f"in the {p.get('made_with')}")
    when = str(p.get("created_utc", "")).replace("T", " ").replace("Z", " UTC")
    return (f"Made with ThermaSched {p.get('thermasched_version')} {where}"
            + (f" on {when}" if when else "")
            + (f" (commit {p['git_commit']})" if p.get("git_commit") else "")
            + f" · scenario build `{p.get('scenario_fingerprint') or UNKNOWN_BUILD}`")


def provenance_warnings(summary: dict, scenarios_dir: str | Path = SCENARIOS_DIR) -> list[str]:
    """Reasons to be careful with a run: a newer summary layout than this dashboard reads,
    or a scenario build that differs from the one in ``scenarios_dir``."""
    p, out = provenance(summary), []
    if int(p.get("schema_version", 0)) > SCHEMA_VERSION:
        out.append(f"This run was made with ThermaSched {p.get('thermasched_version')}, newer "
                   f"than this dashboard ({VERSION}). Some figures may be missing until the "
                   "dashboard is updated.")
    name = (summary.get("scenario") or {}).get("name")
    run_fp = p.get("scenario_fingerprint")
    here = scenario_fingerprint(Path(scenarios_dir) / name) if name and run_fp else None
    if run_fp and here and run_fp != here:
        out.append(f"This run was solved on a different build of `{name}` (run: `{run_fp}`, "
                   f"this dashboard: `{here}`), for example one made with other settings or "
                   "other data. Compare it only with runs of the same build.")
    return out


def solver_short(solver: dict) -> str:
    """The solver's outcome in a few words: 'Proven best', or 'Stopped at time limit, gap
    1.60 %' (the gap tells how far from the best possible the schedule may be)."""
    status, gap = solver.get("status"), solver.get("mip_gap")
    text = status_text(status)
    if status == STATUS_TIME_LIMIT and gap is not None:
        text += f", gap {gap * 100:.2f} %"
    return text


def solver_sentence(solver: dict) -> str:
    """How complete the result is, in one sentence for the thesis."""
    status, gap, t = solver.get("status"), solver.get("mip_gap"), solver.get("solve_time_s")
    took = f" in {t:,.0f} s" if t is not None else ""
    if status == STATUS_OPTIMAL:
        return f"Proven best{took}: no valid schedule emits less carbon (within the requested gap)."
    if status == STATUS_TIME_LIMIT and gap is not None:
        return (f"Stopped at the time limit{took}. This is the best schedule found, within "
                f"{gap * 100:.2f} % of the best possible (the solver's lower bound); it is not "
                "proven best.")
    return f"{status_text(status)}{took}."


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
        pv = provenance(s)
        info = run_info(ref, s)
        rows.append(dict(
            scenario=ref.scenario, run=ref.name,
            configuration=info.config.label if info.config else None,
            test=run_title(info, ref) if info.tests else None,
            scenario_build=pv.get("scenario_fingerprint") or UNKNOWN_BUILD,
            version=pv.get("thermasched_version") or UNVERSIONED,
            made_with=pv.get("made_with"),
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


# ---------------------------------------------------------------------------
# Chapter 6 of the thesis: configurations, tests and the results tables
# ---------------------------------------------------------------------------

# The configurations, tests and sections live in scheduler/experiments.py, shared with the
# solver and the batch notebook. A run is matched to a test by its settings.
CONFIGURATIONS = ex.CONFIGURATIONS
SECTIONS = ex.SECTIONS
OTHER = "other"                 # runs of no configuration (another scenario, an archive)
NOT_RUN_YET = "not run yet"
NOT_APPLICABLE = "not applicable"


@dataclass(frozen=True)
class RunInfo:
    """What a run is: its configuration (None for another scenario), the tests it matches
    and when it was made (for picking the newest of several matches)."""
    config: ex.Configuration | None
    tests: tuple[ex.Test, ...]
    created: str

    @property
    def config_key(self) -> str:
        return self.config.key if self.config else OTHER


def run_info(ref: RunRef, summary: dict | None = None) -> RunInfo:
    try:
        summary = summary if summary is not None else load_summary(ref.path)
    except (OSError, json.JSONDecodeError):
        return RunInfo(None, (), "")
    created = str(provenance(summary).get("created_utc") or "")
    if is_archive(ref.scenario):
        return RunInfo(None, (), created)
    scenario = (summary.get("scenario") or {}).get("name") or ref.scenario
    config, tests = ex.identify(summary.get("settings") or {}, scenario)
    return RunInfo(config, tuple(tests), created)


def run_infos(runs: list[RunRef]) -> dict[str, RunInfo]:
    return {ref.key: run_info(ref) for ref in runs}


def run_title(info: RunInfo, ref: RunRef) -> str:
    """'6.1 · Test 1 · …' for a test run, else its folder name."""
    return " / ".join(ex.title_of(t) for t in info.tests) or ref.name


def run_long_title(info: RunInfo, ref: RunRef) -> str:
    """'10 servers · 6.1 · Test 1 · …', for page headers."""
    title = run_title(info, ref) if info.tests else ref.name
    return f"{info.config.label} · {title}" if info.config else title


def catalogue(runs: list[RunRef], infos: dict[str, RunInfo] | None = None
              ) -> dict[tuple[str, str], tuple[RunRef | None, list[RunRef]]]:
    """(configuration key, test id) -> (the run used: the newest match, or None; every
    match, oldest first), for every configuration and test."""
    infos = infos if infos is not None else run_infos(runs)
    found: dict[tuple[str, str], list[tuple[str, RunRef]]] = {}
    for ref in runs:
        info = infos.get(ref.key)
        if info is None or info.config is None:
            continue
        for test in info.tests:
            found.setdefault((info.config.key, test.id), []).append((info.created, ref))
    out = {}
    for config in CONFIGURATIONS:
        for test in ex.TESTS:
            matches = [r for _, r in sorted(found.get((config.key, test.id), []),
                                            key=lambda m: m[0])]
            out[(config.key, test.id)] = (matches[-1] if matches else None, matches)
    return out


def cell_status(config: ex.Configuration, test: ex.Test, used: RunRef | None) -> str | None:
    """None when the test has a run, else NOT_APPLICABLE or NOT_RUN_YET."""
    if not ex.applicable(test, config):
        return NOT_APPLICABLE
    return None if used is not None else NOT_RUN_YET


def config_runs(runs: list[RunRef], infos: dict[str, RunInfo] | None = None
                ) -> dict[str, list[RunRef]]:
    """Configuration key (or OTHER) -> its runs for the run picker: the run used for each
    test, in test order, then the configuration's other runs (validation runs, older solves
    of a test) by folder name. Configurations without runs are left out."""
    infos = infos if infos is not None else run_infos(runs)
    cat = catalogue(runs, infos)
    out: dict[str, list[RunRef]] = {}
    for config in CONFIGURATIONS:
        used = [cat[(config.key, t.id)][0] for t in ex.TESTS]
        used = list(dict.fromkeys(r for r in used if r is not None))
        rest = sorted((r for r in runs if infos[r.key].config_key == config.key
                       and r not in used), key=lambda r: r.name)
        if used or rest:
            out[config.key] = used + rest
    other = [r for r in runs if infos[r.key].config is None]
    if other:
        out[OTHER] = other
    return out


# Columns of the Chapter 6 results table: key -> header (with its unit).
CHAPTER6_COLUMNS = {
    "configuration": "Configuration",
    "servers": "Servers",
    "level": "Load level",
    "section": "Section",
    "tag": "Test",
    "label": "Run",
    "run": "Run folder",
    "release": "Release",
    "wait_mean_min": "Average waiting time (min)",
    "wait_max_min": "Longest waiting time (min)",
    "exec_mean_min": "Average execution time (min)",
    "turnaround_mean_min": "Average completion time, from arrival (min)",
    "turnaround_max_min": "Longest completion time, from arrival (min)",
    "util_mean_pct": "Average server utilization (%)",
    "E_crac_zone1_kWh": "CRAC electricity, Zone 1 (kWh)",
    "E_crac_zone2_kWh": "CRAC electricity, Zone 2 (kWh)",
    "E_crac_kWh": "CRAC electricity (kWh)",
    "E_IT_kWh": "IT electricity (kWh)",
    "E_cp_Wh": "Cold-plate pump electricity (Wh)",
    "E_cooling_kWh": "Cooling electricity, CRAC + cold plates (kWh)",
    "E_total_kWh": "Total electricity (kWh)",
    "carbon_kg": "Total carbon emissions (kg CO2)",
    "T_mean_C": "Average server temperature (°C)",
    "T_max_C": "Highest server temperature (°C)",
    "H_mean_C": "Average thermal headroom (°C)",
    "n_moved_server": "Workloads moved to another server",
    "n_moved_zone": "Workloads moved to another zone",
    "n_late": "Missed deadlines",
    "pct_late": "Missed deadlines (%)",
    "n_throttled_servers": "Servers slowed by temperature",
    "DPF_min": "Lowest DPF",
    "n_unplaced": "Unplaced workloads",
    "status": "Solver status",
    "mip_gap": "MIP gap",
    "solve_time_s": "Solve time (s)",
    "time_limit_s": "Time limit (s)",
}
# Columns that hold results, for the change against each section's reference.
CHAPTER6_METRICS = tuple(k for k in CHAPTER6_COLUMNS if k not in {
    "configuration", "servers", "level", "section", "tag", "label", "run", "release",
    "n_unplaced", "status", "mip_gap", "solve_time_s", "time_limit_s"})
# What each section measures (the Chapter 6 document's "What to measure"), in its order.
SECTION_MEASURES = {
    "6.1": ("n_moved_server", "n_moved_zone", "util_mean_pct", "E_crac_zone1_kWh",
            "E_crac_zone2_kWh", "E_total_kWh", "carbon_kg", "n_late", "pct_late", "T_mean_C",
            "T_max_C"),
    "6.2": ("T_mean_C", "T_max_C", "H_mean_C", "E_crac_kWh", "E_cp_Wh", "E_cooling_kWh",
            "carbon_kg"),
    "6.3": ("exec_mean_min", "wait_mean_min", "turnaround_mean_min", "n_late", "pct_late",
            "T_mean_C", "T_max_C", "DPF_min", "n_throttled_servers", "E_total_kWh",
            "carbon_kg"),
    "6.4": ("n_moved_server", "E_IT_kWh", "E_crac_kWh", "E_cp_Wh", "carbon_kg",
            "turnaround_mean_min", "wait_mean_min", "n_late", "T_mean_C", "T_max_C",
            "DPF_min"),
}


def schedule_times(schedule_csv: str | Path, dt_seconds: float) -> dict:
    """Waiting time (start - arrival), execution time (end - start) and time from arrival to
    completion (end - arrival), the end being exclusive, in minutes, over the placed workloads
    of one schedule.csv."""
    df = pd.read_csv(schedule_csv)
    placed = df[df["placed"] == 1] if "placed" in df else df.dropna(subset=["start"])
    per_min = dt_seconds / 60.0
    wait = placed["wait"].astype(float) * per_min
    run = (placed["finish"].astype(float) - placed["start"].astype(float)) * per_min
    turn = (placed["finish"].astype(float) - placed["arrival"].astype(float)) * per_min
    nan = float("nan")
    return dict(
        wait_mean_min=wait.mean() if len(placed) else nan,
        wait_max_min=wait.max() if len(placed) else nan,
        exec_mean_min=run.mean() if len(placed) else nan,
        turnaround_mean_min=turn.mean() if len(placed) else nan,
        turnaround_max_min=turn.max() if len(placed) else nan,
        n_unplaced=int(len(df) - len(placed)))


def chapter6_row(ref: RunRef, summary: dict) -> dict:
    """The Chapter 6 figures of one run, from its optimized result."""
    pv, sol, st = provenance(summary), summary.get("solver") or {}, summary.get("settings") or {}
    row = dict(run=ref.name, release=pv.get("thermasched_version") or UNVERSIONED,
               status=sol.get("status"), mip_gap=sol.get("mip_gap"),
               solve_time_s=sol.get("solve_time_s"), time_limit_s=st.get("time_limit_s"))
    if not summary.get("has_optimized_schedule"):
        return row
    opt = summary.get("optimized") or {}
    tot, met = opt.get("totals") or {}, opt.get("metrics") or {}
    zones = list(tot.get("E_crac_by_zone_kWh") or [])
    n = tot.get("n_workloads") or (summary.get("scenario") or {}).get("I")
    e_cp, e_crac = tot.get("E_cp_kWh"), tot.get("E_crac_kWh")
    row.update(
        E_crac_zone1_kWh=zones[0] if len(zones) > 0 else None,
        E_crac_zone2_kWh=zones[1] if len(zones) > 1 else None,
        E_crac_kWh=e_crac,
        E_IT_kWh=tot.get("E_IT_kWh"),
        E_cp_Wh=None if e_cp is None else e_cp * 1000.0,
        E_cooling_kWh=None if e_crac is None else e_crac + (e_cp or 0.0),
        E_total_kWh=tot.get("E_total_kWh"),
        carbon_kg=tot.get("carbon_kg"),
        T_mean_C=met.get("mean_T_C"), T_max_C=met.get("hottest_T_C"),
        n_moved_server=met.get("n_reassigned"), n_moved_zone=met.get("n_cross_zone"),
        n_late=met.get("n_late"),
        pct_late=(met.get("n_late") / n * 100.0) if n and met.get("n_late") is not None else None,
        n_throttled_servers=met.get("n_throttled_servers"),
    )
    dt = (summary.get("scenario") or {}).get("dt_seconds", 300.0)
    schedule = Path(ref.path) / "optimized" / "schedule.csv"
    if schedule.is_file():
        row.update(schedule_times(schedule, float(dt)))
    sp_path = Path(ref.path) / "optimized" / "server_period.csv"
    if sp_path.is_file():
        sp = pd.read_csv(sp_path, usecols=["utilization", "headroom_C", "DPF"])
        row.update(util_mean_pct=float(sp["utilization"].mean()) * 100.0,
                   H_mean_C=float(sp["headroom_C"].mean()), DPF_min=float(sp["DPF"].min()))
    return row


# Per-server figures of one schedule, for the Chapter 6 section detail: column -> header.
SERVER_STATS = {
    "util_mean_pct": "Average CPU utilization (%)",
    "util_max_pct": "Peak CPU utilization (%)",
    "T_mean_C": "Average temperature (°C)",
    "T_max_C": "Highest temperature (°C)",
    "H_mean_C": "Average thermal headroom (°C)",
    "H_min_C": "Lowest thermal headroom (°C)",
    "DPF_mean": "Average DPF",
    "DPF_min": "Lowest DPF",
    "periods_throttled": "Periods slowed (DPF < 1)",
    "E_IT_kWh": "IT electricity (kWh)",
}
# The per-server figures each section shows first.
SECTION_SERVER_STATS = {
    "6.1": "util_mean_pct",
    "6.2": "T_max_C",
    "6.3": "DPF_min",
    "6.4": "DPF_min",
}


def server_stats(run: Run, variant: str = "optimized") -> pd.DataFrame:
    """One row per server (display order): s, name, zone and the SERVER_STATS columns."""
    sp = run.server_period
    sp = sp[sp["variant"] == variant] if not sp.empty else sp
    if sp.empty:
        return pd.DataFrame(columns=["s", "name", "zone", *SERVER_STATS])
    g = sp.groupby("s")
    out = pd.DataFrame({
        "util_mean_pct": g["utilization"].mean() * 100,
        "util_max_pct": g["utilization"].max() * 100,
        "T_mean_C": g["temperature_C"].mean(),
        "T_max_C": g["temperature_C"].max(),
        "H_mean_C": g["headroom_C"].mean(),
        "H_min_C": g["headroom_C"].min(),
        "DPF_mean": g["DPF"].mean(),
        "DPF_min": g["DPF"].min(),
        "periods_throttled": g["DPF"].apply(lambda d: int((d < 1 - 1e-9).sum())),
        "E_IT_kWh": g["P_IT_W"].sum() * run.dt_seconds / 3600 / 1000,
    }).reset_index()
    return run.servers[["s", "name", "zone"]].merge(out, on="s", how="left")


def reassignment_table(run: Run) -> pd.DataFrame:
    """Every workload's original and final server and zone (optimized schedule only)."""
    ra = run.reassignment
    if ra.empty:
        return pd.DataFrame()
    ra = ra.sort_values("i")
    yes_no = {1: "yes", 0: "no"}
    return pd.DataFrame({
        "Workload": ra["workload_id"],
        "Type": ra["type"].map(WORKLOAD_TYPES).fillna(ra["type"]),
        "Running at start (B_i)": ra["B_running"].map(yes_no),
        "Original server": ra["original_server_name"],
        "Original zone": ra["original_zone"],
        "Moved": ra["reassigned"].map(yes_no),
        "Final server": ra["final_server_name"],
        "Final zone": ra["final_zone"],
        "Cross-zone": ra["cross_zone"].map(yes_no),
        "Reason": ra["reason"],
    }).reset_index(drop=True)


def chapter6_table(runs: list[RunRef], infos: dict[str, RunInfo] | None = None,
                   configs: list[str] | None = None) -> pd.DataFrame:
    """One row per configuration, section and test, in that order, with the columns of
    CHAPTER6_COLUMNS. The base run appears in 6.1, 6.3 and 6.4, so every test sits right
    below its section's reference. A test without a run says why in *status*."""
    infos = infos if infos is not None else run_infos(runs)
    cat = catalogue(runs, infos)
    rows, cache = [], {}
    for config in CONFIGURATIONS:
        if configs is not None and config.key not in configs:
            continue
        for section in SECTIONS:
            for tag, tid in section.tests:
                test = ex.TEST_BY_ID[tid]
                used, _ = cat[(config.key, tid)]
                row = dict(configuration=config.label, servers=config.size_label,
                           level=config.level_label, section=section.key, tag=tag,
                           label=test.name)
                missing = cell_status(config, test, used)
                if missing:
                    row.update(run=None, status=missing)
                else:
                    if used.key not in cache:
                        cache[used.key] = chapter6_row(used, load_summary(used.path))
                    row.update(cache[used.key])
                rows.append(row)
    return pd.DataFrame(rows, columns=list(CHAPTER6_COLUMNS))


def has_result(table: pd.DataFrame) -> pd.Series:
    return ~table["status"].isin([NOT_RUN_YET, NOT_APPLICABLE])


def _clean(x: float, tol: float = 1e-9) -> float:
    """Round float noise (e.g. -7e-16) to an exact 0 so it does not print as -0.00."""
    return 0.0 if abs(x) < tol else x


def chapter6_changes(table: pd.DataFrame) -> pd.DataFrame:
    """Each result against the first row of its configuration and section (the section's
    reference), in %. Zero against zero is 0 %; anything against zero is left blank."""
    out = table.copy()
    groups = table.groupby(["configuration", "section"], sort=False).groups
    for _, idx in groups.items():
        ref = table.loc[idx[0], list(CHAPTER6_METRICS)]
        for i in idx:
            for col in CHAPTER6_METRICS:
                v, r = table.at[i, col], ref[col]
                if pd.isna(v) or pd.isna(r):
                    out.at[i, col] = None
                elif r == 0:
                    out.at[i, col] = 0.0 if v == 0 else None
                else:
                    out.at[i, col] = _clean((float(v) - float(r)) / abs(float(r)) * 100.0)
    return out


def _supply_fixed(settings: dict) -> float:
    v = settings.get("fixed_supply_temp_C")
    return float(settings.get("baseline_supply_temp_C", 18.0) if v is None else v)


def _carbon_label(settings: dict) -> str:
    if settings.get("carbon_file"):
        return Path(settings["carbon_file"]).name
    return "flat (mean)" if settings.get("ci_flat") else "scenario"


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
    carbon = _carbon_label(st)
    if carbon == "scenario":
        carbon = f"scenario {(summary.get('scenario') or {}).get('name', '?')}"
    return [
        ("Reassignment", str(st.get("reassignment", "?")).replace("_", " ")),
        ("Server choice", "temperature ignored (two passes)"
         if st.get("placement") == "thermal_blind" else "temperature-aware"),
        ("Supply temperature", supply),
        ("H_min", "scenario default" if h_min is None else f"{h_min:g} °C"),
        ("Cold plates", cp),
        ("Zones", "servers.csv" if not st.get("zone_map")
         else ",".join(map(str, st["zone_map"]))),
        ("Carbon intensity", carbon),
        ("Time limit", f"{st.get('time_limit_s', 0):g} s"),
        ("MIP gap", f"{st.get('mip_rel_gap', 0):g}"),
    ]


# ---------------------------------------------------------------------------
# Validation tables
# ---------------------------------------------------------------------------

def validation_scenarios(root: str | Path = VALIDATION_DIR) -> list[str]:
    """Scenarios with validation tables, ``<root>/<scenario>/validation.json``."""
    root = Path(root)
    return sorted(p.parent.name for p in root.glob("*/validation.json")) if root.is_dir() else []


def load_validation(scenario: str, root: str | Path = VALIDATION_DIR
                    ) -> tuple[dict, dict[str, pd.DataFrame]] | None:
    """validation.json and every table of one scenario's validation, or None if there is none."""
    folder = Path(root) / scenario
    meta_path = folder / "validation.json"
    if not meta_path.is_file():
        return None
    meta = json.loads(meta_path.read_text())
    tables = {}
    for p in sorted(folder.glob("*.csv")):
        try:
            tables[p.stem] = pd.read_csv(p)
        except pd.errors.EmptyDataError:
            tables[p.stem] = pd.DataFrame()
    return meta, tables
