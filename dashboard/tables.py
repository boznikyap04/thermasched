"""The Chapter 5 tables of one schedule, as the thesis group asked for them.

Each builder takes a loaded Run and a variant ("optimized" or "baseline") and returns a
display-ready frame: headers carry their units, times are in minutes and local clock
times (HH:MM). No Streamlit here, so the builders can be tested directly. A variant the run
does not have gives an empty frame.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from dashboard.data import ENERGY_COMPONENTS, Run, period_bounds

TOL = 1e-6
OK, BAD = "✅ yes", "❌ no"
MB_PER_GB = 1024.0
# Fans are not modelled (fan power is fixed at zero), so the energy tables leave them out.
ENERGY_TABLE_COMPONENTS = {k: v for k, v in ENERGY_COMPONENTS.items() if k != "E_fan_kWh"}


def _flag(ok) -> pd.Series:
    return pd.Series(np.where(ok, OK, BAD), index=getattr(ok, "index", None))


def _schedule(run: Run, variant: str) -> pd.DataFrame:
    sch = run.schedule
    if sch.empty:
        return sch
    return sch[sch["variant"] == variant].sort_values("i").reset_index(drop=True)


def _clock(run: Run, periods: pd.Series) -> pd.Series:
    """Local clock time (HH:MM) at the start of each period; blank where there is none.
    A finish or deadline is an exclusive end period, so its clock is the time it ends."""
    bound = period_bounds(run.clock, run.dt_seconds)
    times = pd.Series(bound(pd.to_numeric(periods, errors="coerce")), index=periods.index)
    return times.dt.strftime("%H:%M")


def _period(periods: pd.Series) -> pd.Series:
    return pd.to_numeric(periods, errors="coerce").astype("Int64")


def _minutes(run: Run, periods: pd.Series) -> pd.Series:
    return pd.to_numeric(periods, errors="coerce") * run.dt_seconds / 60.0


# ---------------------------------------------------------------------------
# Workloads
# ---------------------------------------------------------------------------

def workload_schedule(run: Run, variant: str) -> pd.DataFrame:
    """Where and when each workload runs: server, arrival, start, run length, completion."""
    s = _schedule(run, variant)
    if s.empty:
        return pd.DataFrame()
    return pd.DataFrame({
        "Workload": s["workload_id"],
        "Type": s["type_label"],
        "Server": s["server_name"],
        "Arrival (period)": _period(s["arrival"]),
        "Arrival (clock)": _clock(run, s["arrival"]),
        "Start (period)": _period(s["start"]),
        "Start (clock)": _clock(run, s["start"]),
        "Execution time (min)": _minutes(run, s["periods_run"]),
        "Completion (period)": _period(s["finish"]),
        "Completion (clock)": _clock(run, s["finish"]),
    })


def deadlines_and_waiting(run: Run, variant: str) -> pd.DataFrame:
    """Each workload's wait against its allowed delay, and its completion against its deadline."""
    s = _schedule(run, variant)
    if s.empty:
        return pd.DataFrame()
    return pd.DataFrame({
        "Workload": s["workload_id"],
        "Type": s["type_label"],
        "Arrival (clock)": _clock(run, s["arrival"]),
        "Start (clock)": _clock(run, s["start"]),
        "Waiting time (min)": _minutes(run, s["wait"]),
        "Allowed delay (min)": _minutes(run, s["allowed_delay"]),
        "Completion (clock)": _clock(run, s["finish"]),
        "Deadline (clock)": _clock(run, s["deadline"]),
        "Wait within allowed": _flag(s["wait_within_allowed"] == 1),
        "On time": _flag(s["on_time"] == 1),
        "Compliant": _flag(s["compliant"] == 1),
    })


def reassignment(run: Run) -> pd.DataFrame:
    """Every workload's original and final server and zone (optimized schedule only)."""
    ra = run.reassignment
    if ra.empty:
        return pd.DataFrame()
    ra = ra.sort_values("i")
    yes_no = {1: "yes", 0: "no"}
    return pd.DataFrame({
        "Workload": ra["workload_id"],
        "Type": ra["type"].map({"time_sensitive": "Time-sensitive",
                                "delay_tolerant": "Delay-tolerant"}).fillna(ra["type"]),
        "Running at start (B_i)": ra["B_running"].map(yes_no),
        "Original server": ra["original_server_name"],
        "Original zone": ra["original_zone"],
        "Moved": ra["reassigned"].map(yes_no),
        "Final server": ra["final_server_name"],
        "Final zone": ra["final_zone"],
        "Cross-zone": ra["cross_zone"].map(yes_no),
        "Reason": ra["reason"],
    }).reset_index(drop=True)


def work_completion(run: Run, variant: str) -> pd.DataFrame:
    """Work delivered against work required, with the slowest the server ran while it did."""
    s = _schedule(run, variant)
    if s.empty:
        return pd.DataFrame()
    sp = run.server_period
    sp = sp[sp["variant"] == variant] if not sp.empty else sp
    low_pc, low_dpf = [], []
    for _, w in s.iterrows():
        if pd.isna(w["server"]) or pd.isna(w["start"]) or pd.isna(w["finish"]):
            low_pc.append(np.nan)
            low_dpf.append(np.nan)
            continue
        on = sp[(sp["s"] == w["server"]) & (sp["t"] >= w["start"]) & (sp["t"] < w["finish"])]
        low_pc.append(on["PC_eff_MHz"].min() if len(on) else np.nan)
        low_dpf.append(on["DPF"].min() if len(on) else np.nan)
    required = s["work_required_MHz_s"].astype(float)
    delivered = s["work_delivered_MHz_s"].astype(float)
    return pd.DataFrame({
        "Workload": s["workload_id"],
        "Server": s["server_name"],
        "Work required W_i (MHz·s)": required,
        "Work delivered (MHz·s)": delivered,
        "Delivered / required": delivered / required,
        "Lowest server PC_eff while running (MHz)": low_pc,
        "Lowest DPF while running": low_dpf,
        "Work complete": _flag(s["work_complete"] == 1),
    })


# ---------------------------------------------------------------------------
# Servers
# ---------------------------------------------------------------------------

def _servers(run: Run, variant: str) -> pd.DataFrame:
    cs = run.compliance_servers
    if cs.empty:
        return cs
    cs = cs[cs["variant"] == variant]
    order = {s: k for k, s in enumerate(run.servers["s"])}
    return cs.sort_values("s", key=lambda x: x.map(order)).reset_index(drop=True)


def cpu_and_memory(run: Run, variant: str) -> pd.DataFrame:
    """Peak CPU and memory each server used against its capacity."""
    cs = _servers(run, variant)
    if cs.empty:
        return pd.DataFrame()
    ok = ((cs["cpu_peak_cores"] <= cs["cpu_capacity_cores"] + TOL)
          & (cs["mem_peak_MB"] <= cs["mem_capacity_MB"] + TOL))
    return pd.DataFrame({
        "Server": cs["name"],
        "Zone": cs["zone"],
        "CPU capacity (cores)": cs["cpu_capacity_cores"],
        "Peak CPU used (cores)": cs["cpu_peak_cores"],
        "Peak CPU utilization (%)": cs.get(
            "max_utilization", cs["cpu_peak_cores"] / cs["cpu_capacity_cores"]) * 100.0,
        "Memory capacity (GB)": cs["mem_capacity_MB"] / MB_PER_GB,
        "Peak memory used (GB)": cs["mem_peak_MB"] / MB_PER_GB,
        "Within capacity": _flag(ok),
    })


def temperature_and_headroom(run: Run, variant: str) -> pd.DataFrame:
    """Hottest temperature and smallest headroom of each server against the limits, with the
    slowest it ran (DPF and effective processing capability)."""
    cs = _servers(run, variant)
    if cs.empty:
        return pd.DataFrame()
    cap, h_min = run.thermal_cap_C, run.H_min_C
    ok = (cs["hottest_T_C"] <= cap + TOL) & (cs["periods_above_cap"] == 0)
    if h_min is not None:
        ok &= cs["min_headroom_C"] >= h_min - TOL
    return pd.DataFrame({
        "Server": cs["name"],
        "Zone": cs["zone"],
        "Hottest predicted temperature (°C)": cs["hottest_T_C"],
        "Thermal cap (°C)": cap,
        "Lowest headroom (°C)": cs["min_headroom_C"],
        "Required H_min (°C)": np.nan if h_min is None else h_min,
        "Lowest DPF": cs["min_DPF"],
        # Runs made before release 1.0.0 do not record it.
        "Lowest effective capability (MHz)": cs.get("min_PC_eff_MHz", np.nan),
        "Periods above DVFS": cs["periods_above_dvfs"],
        "Within limits": _flag(ok),
    })


# ---------------------------------------------------------------------------
# Cooling
# ---------------------------------------------------------------------------

def crac_limits(run: Run, variant: str) -> pd.DataFrame:
    """Each zone's CRAC: supply temperatures used, ramps and heat removed, against the limits."""
    cz = run.compliance_zones
    cz = cz[cz["variant"] == variant].sort_values("z") if not cz.empty else cz
    if cz.empty:
        return pd.DataFrame()
    ok = ((cz["supply_min_C"] >= cz["supply_allowed_min_C"] - TOL)
          & (cz["supply_max_C"] <= cz["supply_allowed_max_C"] + TOL)
          & (cz["max_ramp_short_C"] <= cz["ramp_short_limit_C"] + TOL)
          & (cz["max_ramp_long_C"] <= cz["ramp_long_limit_C"] + TOL)
          & (cz["Q_crac_peak_kW"] <= cz["Q_crac_capacity_kW"] + TOL))
    return pd.DataFrame({
        "Zone": cz["z"],
        "Lowest supply used (°C)": cz["supply_min_C"],
        "Highest supply used (°C)": cz["supply_max_C"],
        "Allowed min (°C)": cz["supply_allowed_min_C"],
        "Allowed max (°C)": cz["supply_allowed_max_C"],
        "Peak heat removed (kW)": cz["Q_crac_peak_kW"],
        "Capacity (kW)": cz["Q_crac_capacity_kW"],
        "Largest 15-min change (°C)": cz["max_ramp_short_C"],
        "15-min limit (°C)": cz["ramp_short_limit_C"],
        "Largest 1-h change (°C)": cz["max_ramp_long_C"],
        "1-h limit (°C)": cz["ramp_long_limit_C"],
        "Within limits": _flag(ok),
    }).reset_index(drop=True)


def cold_plate_limits(run: Run, variant: str) -> pd.DataFrame:
    """Each cold plate's coolant temperature, flow and heat removed, against the limits.
    Empty when the run has no cold plates."""
    ccp = run.compliance_cold_plates
    ccp = ccp[ccp["variant"] == variant] if not ccp.empty else ccp
    if ccp.empty:
        return pd.DataFrame()
    ok = ((ccp["coolant_min_C"] >= ccp["coolant_allowed_min_C"] - TOL)
          & (ccp["coolant_max_C"] <= ccp["coolant_allowed_max_C"] + TOL)
          & (ccp["flow_min_Lmin"] >= ccp["flow_allowed_min_Lmin"] - TOL)
          & (ccp["flow_max_Lmin"] <= ccp["flow_allowed_max_Lmin"] + TOL)
          & (ccp["Q_cp_peak_W"] <= ccp["Q_cp_capacity_W"] + TOL))
    return pd.DataFrame({
        "Server": ccp["name"],
        "Cold plates": ccp["n_cold_plates"],
        "Lowest coolant used (°C)": ccp["coolant_min_C"],
        "Highest coolant used (°C)": ccp["coolant_max_C"],
        "Coolant allowed min (°C)": ccp["coolant_allowed_min_C"],
        "Coolant allowed max (°C)": ccp["coolant_allowed_max_C"],
        "Lowest flow used (L/min)": ccp["flow_min_Lmin"],
        "Highest flow used (L/min)": ccp["flow_max_Lmin"],
        "Flow allowed min (L/min)": ccp["flow_allowed_min_Lmin"],
        "Flow allowed max (L/min)": ccp["flow_allowed_max_Lmin"],
        "Peak heat removed (W)": ccp["Q_cp_peak_W"],
        "Capacity (W)": ccp["Q_cp_capacity_W"],
        "Within limits": _flag(ok),
    }).reset_index(drop=True)


# ---------------------------------------------------------------------------
# Energy and carbon
# ---------------------------------------------------------------------------

def _periods(run: Run, variant: str) -> pd.DataFrame:
    p = run.period
    return p[p["variant"] == variant].sort_values("t") if not p.empty else p


def energy_breakdown(run: Run, variant: str) -> pd.DataFrame:
    """Energy per component over the horizon and its share of the total, plus a Total row."""
    p = _periods(run, variant)
    if p.empty:
        return pd.DataFrame()
    rows = [(label, float(p[col].sum())) for col, label in ENERGY_TABLE_COMPONENTS.items()
            if col in p]
    total = sum(e for _, e in rows)
    out = pd.DataFrame(rows, columns=["Component", "Energy (kWh)"])
    out["Share of total (%)"] = out["Energy (kWh)"] / total * 100.0 if total else np.nan
    out.loc[len(out)] = ["Total", total, 100.0 if total else np.nan]
    return out


def carbon_per_period(run: Run, variant: str) -> pd.DataFrame:
    """Energy by component, grid carbon intensity and carbon in every period."""
    p = _periods(run, variant)
    if p.empty:
        return pd.DataFrame()
    out = pd.DataFrame({"Period": p["t"].astype(int),
                        "Period start (clock)": _clock(run, p["t"])})
    for col, label in ENERGY_TABLE_COMPONENTS.items():
        if col in p:
            out[f"{label} (kWh)"] = p[col]
    out["Total energy (kWh)"] = p[[c for c in ENERGY_TABLE_COMPONENTS if c in p]].sum(axis=1)
    out["Grid carbon intensity (g CO2/kWh)"] = p["CI_g_per_kWh"]
    out["Carbon (g CO2)"] = p["carbon_g"]
    return out.reset_index(drop=True)


def carbon_totals(run: Run, variant: str) -> tuple[float, float]:
    """(total energy in kWh, total carbon in kg CO2) of one schedule over the horizon."""
    p = _periods(run, variant)
    if p.empty:
        return float("nan"), float("nan")
    energy = float(p[[c for c in ENERGY_TABLE_COMPONENTS if c in p]].sum(axis=1).sum())
    return energy, float(p["carbon_g"].sum()) / 1000.0
