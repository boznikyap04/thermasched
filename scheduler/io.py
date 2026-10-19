"""Scenario loader: reads scenarios/<name>/*.csv and params.json into the shared types.

``availability.csv`` (columns s, t, AV) is optional: server-periods it does not list are
available, Eq. (11).
"""

from __future__ import annotations

import csv
import dataclasses
import json
from pathlib import Path

import numpy as np

from scheduler.build import scenario_fingerprint
from scheduler.types import (
    ColdPlateSpec, Constants, Placement, RunSettings, Scenario, Schedule, Server, Workload,
)


def _read_rows(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        raise ValueError(f"missing scenario file: {path}")
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def _blank(v: str | None) -> bool:
    return v is None or v.strip() == ""


def _int(v: str) -> int:
    return int(round(float(v)))


def _opt_int(v: str | None) -> int | None:
    return None if _blank(v) else _int(v)


def _check_contiguous(values: list[int], what: str, path: Path) -> None:
    expected = list(range(1, len(values) + 1))
    if values != expected:
        raise ValueError(f"{path}: column '{what}' must be 1..{len(values)} in order, "
                         f"got {values[:5]}...")


def _scenario_dir(name: str, scenarios_dir: str | Path) -> Path:
    d = Path(scenarios_dir) / name
    if not d.is_dir():
        raise ValueError(f"scenario directory not found: {d}")
    return d


def load_scenario(name: str, scenarios_dir: str | Path = "scenarios") -> Scenario:
    d = _scenario_dir(name, scenarios_dir)
    with open(d / "params.json") as f:
        params = json.load(f)

    T = int(params["time"]["T"])
    dt = float(params["time"]["dt_seconds"])

    # servers
    srv_path = d / "servers.csv"
    srv_rows = _read_rows(srv_path)
    if not srv_rows:
        raise ValueError(f"{srv_path}: no servers")
    _check_contiguous([_int(r["s"]) for r in srv_rows], "s", srv_path)
    servers = tuple(
        Server(
            s=_int(r["s"]), name=r["server"], zone=_int(r["zone"]),
            f_MHz=float(r["f_s_MHz"]), C_cores=_int(r["C_s_cores"]), M_MB=float(r["M_s_MB"]),
            P_idle_W=float(r["P_idle_W"]), P_max_W=float(r["P_max_W"]), T0_C=float(r["T0_C"]),
            CT_cold_plate=_int(r["CT_s_cold_plate"]), th_a_C=float(r["th_a_C"]),
            th_R_C_per_W=float(r["th_R_C_per_W"]), th_alpha=float(r["th_alpha_5min"]),
            n_cold_plates=_opt_int(r.get("n_cold_plates")),
        )
        for r in srv_rows
    )
    for sv in servers:
        if sv.plates < 0:
            raise ValueError(f"{srv_path}: server {sv.s} has {sv.plates} cold plates")
    n_zones = max(sv.zone for sv in servers)
    for sv in servers:
        if not 1 <= sv.zone <= n_zones:
            raise ValueError(f"{srv_path}: server {sv.s} has zone {sv.zone}, "
                             f"outside 1..{n_zones}")

    # workloads
    wl_path = d / "workloads.csv"
    wl_rows = _read_rows(wl_path)
    _check_contiguous([_int(r["i"]) for r in wl_rows], "i", wl_path)
    workloads = tuple(
        Workload(
            i=_int(r["i"]), workload_id=r["workload_id"], flavor=r["flavor"],
            A=_int(r["A_i"]), D=_int(r["D_i"]), AD=_int(r["AD_i"]),
            ET_base=_int(r["ET_base_i"]), RT=_int(r["RT_i"]), B=_int(r["B_i"]),
            X0=_opt_int(r["X0_s"]), C_req=_int(r["C_req_i"]),
            M_req_MB=float(r["M_req_i_MB"]), W_MHz_s=float(r["W_i_MHz_s"]),
            usage_imputed=_int(r["usage_imputed"]) if not _blank(r.get("usage_imputed")) else 0,
        )
        for r in wl_rows
    )

    # carbon
    ci = _read_carbon(d / "carbon.csv", T)

    # availability, Eq. (11)
    av_path = d / "availability.csv"
    AV = _read_availability(av_path, len(servers), T) if av_path.is_file() else None

    # constants
    c = params["constants_as_printed"]
    constants = Constants(
        R_dvfs=c["R_dvfs"], F_throttle=c["F_throttle"], T_max_server_C=c["T_max_server_C"],
        H_min_C=c["H_min_C"], T_dvfs_C=c["T_dvfs_C"], T_throttle_C=c["T_throttle_C"],
        Q_crac_kW=c["Q_crac_kW"], COP_coeffs=tuple(float(x) for x in c["COP_crac_coeffs"]),
        T_crac_min_C=c["T_crac_min_C"], T_crac_max_C=c["T_crac_max_C"],
        T_max_zone_C=c["T_max_zone_C"],
    )
    if len(constants.COP_coeffs) != 3:
        raise ValueError(f"{d / 'params.json'}: COP_crac_coeffs must have 3 entries")

    cold_plate = _cold_plate_spec(c, params.get("cold_plate", {}))
    cold_plate.validate()

    sc = Scenario(name=name, T=T, dt_seconds=dt, workloads=workloads, servers=servers,
                  n_zones=n_zones, CI_g_per_kWh=ci, constants=constants, cold_plate=cold_plate,
                  AV=AV, fingerprint=scenario_fingerprint(d),
                  built_with=params.get("built_with", {}).get("thermasched"))
    settings_dt = params.get("settings", {}).get("dt_seconds")
    if settings_dt is not None and float(settings_dt) != dt:
        raise ValueError(f"{d / 'params.json'}: time.dt_seconds={dt} does not match "
                         f"settings.dt_seconds={settings_dt}")
    return sc


def _read_carbon(path: Path, T: int) -> np.ndarray:
    rows = _read_rows(path)
    if len(rows) != T:
        raise ValueError(f"{path}: has {len(rows)} rows, the scenario has T={T}")
    _check_contiguous([_int(r["t"]) for r in rows], "t", path)
    return np.array([float(r["CI_t_g_per_kWh"]) for r in rows], dtype=float)


def _read_availability(path: Path, S: int, T: int) -> np.ndarray:
    AV = np.ones((S, T), dtype=int)
    for r in _read_rows(path):
        s, t, v = _int(r["s"]), _int(r["t"]), _int(r["AV"])
        if not (1 <= s <= S and 1 <= t <= T) or v not in (0, 1):
            raise ValueError(f"{path}: row s={s}, t={t}, AV={v} is outside 1..{S}, 1..{T}, {{0, 1}}")
        AV[s - 1, t - 1] = v
    return AV


def apply_overrides(scenario: Scenario, settings: RunSettings) -> Scenario:
    """Scenario switches of a run: zone map (S1 T1) and carbon intensity (S4 T3)."""
    sc = scenario
    if settings.zone_map is not None:
        zones = [int(z) for z in settings.zone_map]
        if len(zones) != sc.S:
            raise ValueError(f"zone_map has {len(zones)} entries, the scenario has {sc.S} servers")
        n_zones = max(zones)
        if sorted(set(zones)) != list(range(1, n_zones + 1)):
            raise ValueError(f"zone_map {zones}: every zone 1..{n_zones} must have a server")
        servers = tuple(dataclasses.replace(sv, zone=z) for sv, z in zip(sc.servers, zones))
        sc = dataclasses.replace(sc, servers=servers, n_zones=n_zones)
    if settings.carbon_file is not None:
        sc = dataclasses.replace(sc, CI_g_per_kWh=_read_carbon(Path(settings.carbon_file), sc.T))
    elif settings.ci_flat:
        sc = dataclasses.replace(sc, CI_g_per_kWh=np.full(sc.T, float(np.mean(sc.CI_g_per_kWh))))
    return sc


def _cold_plate_spec(c: dict, cp: dict) -> ColdPlateSpec:
    """Printed constants (kelvin and mW converted) plus the params.json "cold_plate" block.
    Anything missing keeps the ColdPlateSpec default."""
    kw: dict = {}
    if "Q_cp_kW" in c:
        kw["Q_max_per_plate_W"] = 1000.0 * float(c["Q_cp_kW"])
    if "T_cp_min_K" in c:
        kw["coolant_min_C"] = round(float(c["T_cp_min_K"]) - 273.15, 6)
    if "T_cp_max_K" in c:
        kw["coolant_max_C"] = round(float(c["T_cp_max_K"]) - 273.15, 6)
    if "FR_cp_min_Lmin" in c:
        kw["flow_min_Lmin"] = float(c["FR_cp_min_Lmin"])
    if "FR_cp_max_Lmin" in c:
        kw["flow_max_Lmin"] = float(c["FR_cp_max_Lmin"])
    if "P_cp_rated_as_printed_mW" in c:
        kw["pump_ref_W"] = float(c["P_cp_rated_as_printed_mW"]) / 1000.0
    if "FR_cp_rated_Lmin" in c:
        kw["pump_ref_flow_Lmin"] = float(c["FR_cp_rated_Lmin"])
    if "c_pw" in c:
        kw["c_pw_J_per_kgC"] = float(c["c_pw"])
    for key in ("flow_settings_Lmin", "R_C_per_W"):
        if key in cp:
            kw[key] = tuple(float(x) for x in cp[key])
    if "water_density_kg_per_L" in cp:
        kw["water_density_kg_per_L"] = float(cp["water_density_kg_per_L"])
    return ColdPlateSpec(**kw)


def load_reference_baseline(name: str, scenarios_dir: str | Path = "scenarios") -> Schedule:
    """Read scenarios/<name>/baseline_schedule.csv (columns i, s, start, end, late)."""
    path = _scenario_dir(name, scenarios_dir) / "baseline_schedule.csv"
    rows = _read_rows(path)
    _check_contiguous([_int(r["i"]) for r in rows], "i", path)
    placements = tuple(
        Placement(i=_int(r["i"]), server=_opt_int(r["s"]), start=_opt_int(r["start"]),
                  end=_opt_int(r["end"]))
        for r in rows
    )
    return Schedule(placements)
