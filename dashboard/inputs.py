"""Scenario inputs for the thesis's Chapter 5: servers, workloads, carbon intensity and the
model's fixed parameters, read from ``scenarios/<scenario>/``.

No Streamlit here so the tables can be tested directly; the Inputs page shows them.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from dashboard.data import SCENARIOS_DIR, is_archive


def scenarios(scenarios_dir: str | Path = SCENARIOS_DIR) -> list[str]:
    """Scenarios with a servers.csv and workloads.csv, alphabetically."""
    root = Path(scenarios_dir)
    if not root.is_dir():
        return []
    return sorted(p.name for p in root.iterdir()
                  if (p / "servers.csv").is_file() and (p / "workloads.csv").is_file()
                  and not is_archive(p.name))


def load_params(scenario: str, scenarios_dir: str | Path = SCENARIOS_DIR) -> dict:
    path = Path(scenarios_dir) / scenario / "params.json"
    return json.loads(path.read_text()) if path.is_file() else {}


def dt_seconds(params: dict) -> float:
    return float((params.get("time") or {}).get("dt_seconds")
                 or (params.get("settings") or {}).get("dt_seconds") or 300.0)


def start_hour(params: dict) -> float | None:
    h = (params.get("time") or {}).get("period_1_local_hour")
    if h is None:
        h = (params.get("settings") or {}).get("start_hour_local")
    return None if h is None else float(h)


def clock(period: int, hour: float | None, dt: float) -> str | None:
    """Local clock time at the start of ``period`` (1-based); None without a start hour."""
    if hour is None:
        return None
    minutes = round(hour * 60 + (period - 1) * dt / 60) % (24 * 60)
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def server_table(scenario: str, scenarios_dir: str | Path = SCENARIOS_DIR) -> pd.DataFrame:
    """One row per server: hardware, power and thermal parameters, with units."""
    df = pd.read_csv(Path(scenarios_dir) / scenario / "servers.csv")
    plates = df["n_cold_plates"] if "n_cold_plates" in df else df.get("CT_s_cold_plate", 0)
    return pd.DataFrame({
        "Server": df["server"],
        "Zone": df["zone"].astype(int),
        "CPU cores": df["N_cores"].astype(int),
        "RAM (GB)": (df["M_s_MB"] / 1024.0).round(1),
        "Frequency (MHz per core)": df["f_s_MHz"],
        "Processing capability (MHz)": df["PC_s_MHz"],
        "Idle power (W)": df["P_idle_W"],
        "Maximum power (W)": df["P_max_W"],
        "Cold plates": pd.Series(plates, index=df.index).fillna(0).astype(int),
        "Starting temperature (°C)": df["T0_C"],
        "Temperature offset a_s (°C)": df["th_a_C"],
        "Thermal resistance R_s (°C/W)": df["th_R_C_per_W"],
        "Thermal persistence α_s (–)": df["th_alpha_5min"],
    })


def workload_table(scenario: str, scenarios_dir: str | Path = SCENARIOS_DIR) -> pd.DataFrame:
    """One row per workload: what it asks for and when, with units (Section 5.2.2).

    The same columns and values as the release's validation table ``workload_inputs.csv``."""
    params = load_params(scenario, scenarios_dir)
    dt, hour = dt_seconds(params), start_hour(params)
    dt_min = dt / 60.0
    w = pd.read_csv(Path(scenarios_dir) / scenario / "workloads.csv")
    return pd.DataFrame({
        "Workload": w["i"].astype(int),
        "Workload ID": w["workload_id"],
        "Flavor": w.get("flavor"),
        "Type": w["RT_i"].map({1: "time-sensitive", 0: "delay-tolerant"}),
        "Requested CPU cores (vCPU)": w["C_req_i"].astype(int),
        "Requested RAM (GB)": (w["M_req_i_MB"] / 1024.0).round(3),
        "Arrival (period)": w["A_i"].astype(int),
        "Arrival (clock)": [clock(int(a), hour, dt) for a in w["A_i"]],
        "Deadline (period)": w["D_i"].astype(int),
        "Deadline (clock)": [clock(int(d), hour, dt) for d in w["D_i"]],
        "Base runtime (min)": w["ET_base_i"] * dt_min,
        "Allowed delay (min)": w["AD_i"] * dt_min,
        "Work required (MHz·s)": w["W_i_MHz_s"].astype(float),
    })


def carbon_table(scenario: str, scenarios_dir: str | Path = SCENARIOS_DIR) -> pd.DataFrame:
    """Period, Time (start of the period), grid carbon intensity."""
    params = load_params(scenario, scenarios_dir)
    dt, hour = dt_seconds(params), start_hour(params)
    c = pd.read_csv(Path(scenarios_dir) / scenario / "carbon.csv")
    return pd.DataFrame({
        "Period": c["t"].astype(int),
        "Time": [clock(int(t), hour, dt) for t in c["t"]],
        "Grid carbon intensity (g CO2/kWh)": c["CI_t_g_per_kWh"],
    })


def _row(parameter: str, symbol: str, value, unit: str) -> dict:
    return {"Parameter": parameter, "Symbol": symbol, "Value": value, "Unit": unit}


def _fmt_list(values, fmt: str = "g") -> str:
    return ", ".join(format(float(v), fmt) for v in values)


def parameter_table(scenario: str, scenarios_dir: str | Path = SCENARIOS_DIR) -> pd.DataFrame:
    """The model's fixed parameters, from params.json, as text values with units.

    Values are text so that ranges and lists sit in the same column as single numbers."""
    p = load_params(scenario, scenarios_dir)
    c = p.get("constants_as_printed") or {}
    s = p.get("settings") or {}
    cp = p.get("cold_plate") or {}
    t = p.get("time") or {}
    dt = dt_seconds(p)
    rows = []

    def add(parameter, symbol, value, unit=""):
        if value is not None:
            rows.append(_row(parameter, symbol, value if isinstance(value, str) else f"{value:g}",
                             unit))

    # Thermal limits and throttling (Table 5.X)
    add("DVFS onset temperature", "T_dvfs", c.get("T_dvfs_C"), "°C")
    add("Thermal throttling temperature", "T_throttle", c.get("T_throttle_C"), "°C")
    add("DVFS performance reduction", "R_dvfs", c.get("R_dvfs"), "–")
    add("Remaining performance fraction", "F_throttle", c.get("F_throttle"), "–")
    add("Maximum server temperature", "T_max", c.get("T_max_server_C"), "°C")
    add("Minimum thermal headroom", "H_min", c.get("H_min_C"), "°C")
    if c.get("T_max_server_C") is not None and c.get("H_min_C") is not None:
        add("Thermal cap (T_max − H_min)", "", c["T_max_server_C"] - c["H_min_C"], "°C")
    # CRAC
    if c.get("T_crac_min_C") is not None:
        add("CRAC supply-air temperature range", "CRAC_temp",
            f"{c['T_crac_min_C']:g}–{c['T_crac_max_C']:g}", "°C")
    add("CRAC cooling capacity per zone", "Q_crac", c.get("Q_crac_kW"), "kW")
    if c.get("COP_crac_coeffs"):
        a, b, k = c["COP_crac_coeffs"]
        add("CRAC COP (supply temperature T in °C)", "COP",
            f"{a:g}·T² + {b:g}·T + {k:g}", "–")
    add("Maximum zone temperature", "T_zone,max", c.get("T_max_zone_C"), "°C")
    # Cold plates
    add("Cold-plate heat removal capacity per plate", "Q_cp", c.get("Q_cp_kW"), "kW")
    if c.get("FR_cp_min_Lmin") is not None:
        add("Coolant flow limits", "CP_flow",
            f"{c['FR_cp_min_Lmin']:g}–{c['FR_cp_max_Lmin']:g}", "L/min")
    if cp.get("flow_settings_Lmin"):
        add("Coolant flow settings", "CP_flow", _fmt_list(cp["flow_settings_Lmin"]), "L/min")
    if cp.get("R_C_per_W"):
        add("Cold-plate thermal resistance at each flow setting", "R_cp",
            _fmt_list(cp["R_C_per_W"]), "°C/W")
    if c.get("T_cp_min_K") is not None:
        add("Coolant (inlet water) temperature range", "CP_temp",
            f"{c['T_cp_min_K'] - 273.15:.2f}–{c['T_cp_max_K'] - 273.15:.2f}", "°C")
    if c.get("P_cp_rated_as_printed_mW") is not None:
        add("Reference pumping power", "P_cp,rated",
            f"{c['P_cp_rated_as_printed_mW']:g} at {c.get('FR_cp_rated_Lmin', 0):g} L/min", "mW")
    add("Specific heat of water", "c_pw", c.get("c_pw"), "J/(kg·°C)")
    # Time
    add("Period length", "Δt", dt / 60.0, "min")
    T = t.get("T") or s.get("periods")
    if T:
        add("Planning horizon", "T", f"{int(T)} periods ({int(T) * dt / 3600:g} h)", "")
    hour = start_hour(p)
    if hour is not None:
        add("Start of period 1", "", clock(1, hour, dt), "local time")
    # Workload rules
    if s.get("rt_slack_frac") is not None:
        add("Time-sensitive workloads: extra time", "",
            f"{s['rt_slack_frac']:.0%} of runtime, at least {dt / 60:g} min", "")
    if s.get("dt_slack_mult") is not None:
        add("Delay-tolerant workloads: extra time", "",
            f"{s['dt_slack_mult']:g} × runtime, within {s['dt_slack_min'] * dt / 3600:g}–"
            f"{s['dt_slack_max'] * dt / 3600:g} h", "")
    if s.get("rt_share") is not None:
        add("Share of time-sensitive workloads", "", f"{s['rt_share']:.0%}", "")
    if p.get("f_ref_MHz") is not None:
        add("Reference frequency for base runtime", "f_ref", p["f_ref_MHz"], "MHz")
    if s.get("freq_mhz"):
        add("Server frequencies (servers per frequency)", "f_s",
            ", ".join(f"{f:g} ({n})" for f, n in zip(s["freq_mhz"], s.get("freq_split", []))),
            "MHz")
    return pd.DataFrame(rows, columns=["Parameter", "Symbol", "Value", "Unit"])
