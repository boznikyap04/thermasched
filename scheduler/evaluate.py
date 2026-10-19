"""Shared evaluator: the referee that scores any schedule with the same code.

Given a Scenario, a Schedule, supply temperatures and (with cold plates on) the cold-plate
flow and coolant temperatures, it recomputes, from scratch, utilisation, IT power,
cold-plate heat and pump power, server temperature, DPF, work delivered, CRAC heat /
power, energy, carbon, and every compliance check. A schedule is never rejected; every
limit is measured and reported. Equation numbers refer to docs/PROJECT_CONTEXT.md.

This module must not import from baseline.py or optimize.py.
"""

from __future__ import annotations

import numpy as np

from .types import (
    ColdPlateOps, EvalResult, RunSettings, Scenario, Schedule, cold_plate_counts, cop,
    fixed_cold_plate_ops, priority_pairs,
)

TOL = 1e-6
W_TO_KWH_FACTOR = 1.0 / 3.6e6   # W * seconds -> kWh


# ---------------------------------------------------------------------------
# Slot that is not defined yet
# ---------------------------------------------------------------------------

def fan_power_kW(scenario: Scenario, Q_crac_kW: np.ndarray) -> np.ndarray:
    """Fan slot: returns P_fan[z, t] in kW. Airflow is not modelled, so zero."""
    return np.zeros_like(Q_crac_kW)


# ---------------------------------------------------------------------------
# Model pieces
# ---------------------------------------------------------------------------

def dpf(T_C, constants):
    """Eq. (37), all three branches as printed. Works on scalars or arrays."""
    T = np.asarray(T_C, dtype=float)
    c = constants
    middle = 1.0 - c.R_dvfs * (T - c.T_dvfs_C) / (c.T_throttle_C - c.T_dvfs_C)
    out = np.where(T < c.T_dvfs_C, 1.0, np.where(T < c.T_throttle_C, middle, c.F_throttle))
    return out if out.ndim else float(out)


def temperature_recursion(scenario: Scenario, supply_temp_C: np.ndarray,
                          P_IT_W: np.ndarray, Q_cp_W: np.ndarray) -> np.ndarray:
    """T[s,t] = alpha*T[s,t-1] + (1-alpha)*(Tsup[zone,t] + a + R*(P_IT - Q_cp))."""
    S, T = scenario.S, scenario.T
    temp = np.zeros((S, T))
    for sv in scenario.servers:
        k = sv.s - 1
        prev = sv.T0_C
        for t in range(T):
            steady = (supply_temp_C[sv.zone - 1, t] + sv.th_a_C
                      + sv.th_R_C_per_W * (P_IT_W[k, t] - Q_cp_W[k, t]))
            prev = sv.th_alpha * prev + (1.0 - sv.th_alpha) * steady
            temp[k, t] = prev
    return temp


def thermal_with_cold_plates(scenario: Scenario, supply_temp_C: np.ndarray, P_IT_W: np.ndarray,
                             plates: np.ndarray, ops: ColdPlateOps):
    """Temperature recursion with cold plates. Returns (T, Q_cp, P_cp), each (S, T) in degC / W.

    Per server and period, with n plates at flow setting k and coolant temperature c:
    Q_cp = min(n * Q_max, P_IT, n * G_k * max(0, T[s,t-1] - c)), the most heat physics and
    the limits allow, using the previous period's temperature (T0 in period 1). Pump power
    is n * pump_k. Servers without cold plates have Q_cp = P_cp = 0.
    """
    cp = scenario.cold_plate
    G = cp.conductance_W_per_C()
    pump = cp.pump_W()
    S, T = scenario.S, scenario.T
    temp = np.zeros((S, T))
    Q_cp = np.zeros((S, T))
    P_cp = np.zeros((S, T))
    for sv in scenario.servers:
        k = sv.s - 1
        n = int(plates[k])
        prev = sv.T0_C
        for t in range(T):
            if n > 0:
                lv = cp.level_of(float(ops.flow_Lmin[k, t]))
                drive = max(0.0, prev - float(ops.coolant_C[k, t]))
                Q_cp[k, t] = min(n * cp.Q_max_per_plate_W, P_IT_W[k, t], n * G[lv] * drive)
                P_cp[k, t] = n * pump[lv]
            steady = (supply_temp_C[sv.zone - 1, t] + sv.th_a_C
                      + sv.th_R_C_per_W * (P_IT_W[k, t] - Q_cp[k, t]))
            prev = sv.th_alpha * prev + (1.0 - sv.th_alpha) * steady
            temp[k, t] = prev
    return temp, Q_cp, P_cp


def _placement_arrays(scenario: Scenario, schedule: Schedule):
    """Per workload: placed flag, server (1-based), start, end (ints; 0 if unplaced)."""
    I, S = scenario.I, scenario.S
    placed = np.zeros(I, dtype=bool)
    srv = np.zeros(I, dtype=int)
    start = np.zeros(I, dtype=int)
    end = np.zeros(I, dtype=int)
    by_i = {p.i: p for p in schedule.placements}
    for w in scenario.workloads:
        p = by_i.get(w.i)
        if p is None or p.server is None or p.start is None or p.end is None:
            continue
        if not (1 <= p.server <= S):
            continue    # a server that does not exist is treated as not placed
        placed[w.i - 1] = True
        srv[w.i - 1], start[w.i - 1], end[w.i - 1] = p.server, p.start, p.end
    return placed, srv, start, end


def priority_violations(scenario: Scenario, placed, srv, start) -> list[tuple[int, int]]:
    """Pairs (i, j) of priority_pairs where j started on i's server while i was waiting:
    A_i <= ST_j < ST_i, Eq. (56)-(57)."""
    out = []
    for i, j in priority_pairs(scenario):
        a, b = i - 1, j - 1
        if not (placed[a] and placed[b]) or srv[a] != srv[b]:
            continue
        if scenario.workloads[a].A <= start[b] < start[a]:
            out.append((i, j))
    return out


def _f(x) -> float:
    return float(x)


def _none_if_nan(x):
    x = float(x)
    return None if np.isnan(x) else x


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def evaluate(scenario: Scenario, schedule: Schedule, supply_temp_C: np.ndarray,
             settings: RunSettings, cold_plate_ops: ColdPlateOps | None = None) -> EvalResult:
    """Score a schedule. ``cold_plate_ops`` gives the cold-plate flow and coolant temperature
    per server and period; None runs every cold plate at the baseline's fixed settings."""
    settings.validate()
    S, Z, T, I = scenario.S, scenario.Z, scenario.T, scenario.I
    c = scenario.constants
    dt = scenario.dt_seconds
    supply = np.asarray(supply_temp_C, dtype=float)
    if supply.shape != (Z, T):
        raise ValueError(f"supply_temp_C must have shape (Z, T) = {(Z, T)}, got {supply.shape}")
    cap = settings.thermal_cap_C(scenario)

    placed, srv, start, end = _placement_arrays(scenario, schedule)

    # Which periods does each placed workload occupy inside the horizon (0-based)?
    cpu_used = np.zeros((S, T))
    mem_used = np.zeros((S, T))
    run_idx: list[np.ndarray] = []
    for w in scenario.workloads:
        k = w.i - 1
        if not placed[k]:
            run_idx.append(np.zeros(0, dtype=int))
            continue
        lo = max(start[k], 1)
        hi = min(end[k] - 1, T)           # last occupied period (1-based), clipped
        idx = np.arange(lo - 1, hi) if hi >= lo else np.zeros(0, dtype=int)
        run_idx.append(idx)
        cpu_used[srv[k] - 1, idx] += w.C_req
        mem_used[srv[k] - 1, idx] += w.M_req_MB

    C_cores = np.array([sv.C_cores for sv in scenario.servers], dtype=float)
    M_MB = np.array([sv.M_MB for sv in scenario.servers], dtype=float)
    P_idle = np.array([sv.P_idle_W for sv in scenario.servers])
    P_max = np.array([sv.P_max_W for sv in scenario.servers])
    f_MHz = np.array([sv.f_MHz for sv in scenario.servers])
    zone_of = np.array([sv.zone for sv in scenario.servers], dtype=int)

    util = cpu_used / C_cores[:, None]                                    # Eq. (16)
    P_IT = P_idle[:, None] + (P_max - P_idle)[:, None] * util            # Eq. (20), (21)
    plates = cold_plate_counts(scenario, settings)
    has_cp = plates > 0
    if has_cp.any():
        ops = cold_plate_ops or fixed_cold_plate_ops(
            scenario, plates, settings.baseline_cp_flow_Lmin, settings.baseline_cp_coolant_C)
        for name in ("flow_Lmin", "coolant_C"):
            if np.shape(getattr(ops, name)) != (S, T):
                raise ValueError(f"cold_plate_ops.{name} must have shape (S, T) = {(S, T)}")
        temp, Q_cp, P_cp = thermal_with_cold_plates(scenario, supply, P_IT, plates, ops)
        cp_flow = np.where(has_cp[:, None], ops.flow_Lmin, np.nan)
        cp_coolant = np.where(has_cp[:, None], ops.coolant_C, np.nan)
    else:
        Q_cp, P_cp = np.zeros_like(P_IT), np.zeros_like(P_IT)
        temp = temperature_recursion(scenario, supply, P_IT, Q_cp)
        cp_flow = cp_coolant = np.full((S, T), np.nan)
    headroom = c.T_max_server_C - temp                                   # Eq. (31)
    DPF = dpf(temp, c)                                                   # Eq. (37)
    PC_eff = C_cores[:, None] * f_MHz[:, None] * DPF                     # Eq. (38)

    # Zones: heat balance at equality, divide by COP.
    Q_crac = np.zeros((Z, T))
    for z in range(1, Z + 1):
        members = zone_of == z
        Q_crac[z - 1] = (P_IT[members] - Q_cp[members]).sum(axis=0) / 1000.0
    COP = cop(c, supply)
    P_crac = Q_crac / COP
    P_fan = fan_power_kW(scenario, Q_crac)

    # Energy and carbon per period.
    E_IT = P_IT.sum(axis=0) * dt * W_TO_KWH_FACTOR
    E_cp = P_cp.sum(axis=0) * dt * W_TO_KWH_FACTOR
    E_crac = P_crac.sum(axis=0) * dt / 3600.0
    E_fan = P_fan.sum(axis=0) * dt / 3600.0
    E_total = E_IT + E_crac + E_cp + E_fan
    carbon = scenario.CI_g_per_kWh * E_total
    total_carbon = float(carbon.sum())

    # Per workload.
    nan = float("nan")
    wait = np.full(I, nan)
    delivered = np.full(I, nan)
    required = np.array([w.W_MHz_s for w in scenario.workloads], dtype=float)
    starts_ok = np.zeros(I, dtype=bool)
    wait_ok = np.zeros(I, dtype=bool)
    on_time = np.zeros(I, dtype=bool)
    work_ok = np.zeros(I, dtype=bool)
    within_horizon = np.zeros(I, dtype=bool)
    min_dpf_run = np.full(I, nan)
    for w in scenario.workloads:
        k = w.i - 1
        if not placed[k]:
            continue
        wait[k] = start[k] - w.A
        starts_ok[k] = start[k] >= w.A
        wait_ok[k] = wait[k] <= w.AD + TOL
        on_time[k] = end[k] <= w.D
        idx = run_idx[k]
        delivered[k] = float(w.C_req * f_MHz[srv[k] - 1] * dt * DPF[srv[k] - 1, idx].sum())
        if len(idx):
            min_dpf_run[k] = float(DPF[srv[k] - 1, idx].min())
        work_ok[k] = delivered[k] >= w.W_MHz_s * (1.0 - 1e-6)
        within_horizon[k] = start[k] >= 1 and end[k] <= T + 1 and end[k] > start[k]
    compliant = placed & starts_ok & wait_ok & on_time & work_ok & within_horizon

    # ---- compliance checks ------------------------------------------------
    cpu_ok = bool(np.all(cpu_used <= C_cores[:, None] + TOL))
    mem_ok = bool(np.all(mem_used <= M_MB[:, None] + TOL))
    thermal_cap_ok = bool(np.all(temp <= cap + TOL))
    workloads_ok = bool(np.all(compliant))
    supply_range_ok = bool(np.all(supply >= c.T_crac_min_C - TOL)
                           and np.all(supply <= c.T_crac_max_C + TOL))
    zone_temp_ok = bool(np.all(supply <= c.T_max_zone_C + TOL))

    def max_ramp(lag: int) -> float:
        if T <= lag:
            return 0.0
        return float(np.abs(supply[:, lag:] - supply[:, :-lag]).max())

    ramp_short = max_ramp(c.ramp_short_lag)
    ramp_long = max_ramp(c.ramp_long_lag)
    ramp_ok = bool(ramp_short <= c.ramp_short_C + TOL and ramp_long <= c.ramp_long_C + TOL)
    crac_capacity_ok = bool(np.all(Q_crac <= c.Q_crac_kW + TOL))
    cps = scenario.cold_plate
    cp_coolant_ok = bool(np.all((cp_coolant[has_cp] >= cps.coolant_min_C - TOL)
                                & (cp_coolant[has_cp] <= cps.coolant_max_C + TOL)))
    cp_flow_ok = bool(np.all((cp_flow[has_cp] >= cps.flow_min_Lmin - TOL)
                             & (cp_flow[has_cp] <= cps.flow_max_Lmin + TOL)))
    AV = scenario.availability()
    unavailable_used = (AV == 0) & (cpu_used > 0)
    availability_ok = not bool(unavailable_used.any())                   # Eq. (11)
    prio_bad = priority_violations(scenario, placed, srv, start)
    priority_ok = not prio_bad                                           # Eq. (56)-(57)

    above_dvfs = temp > c.T_dvfs_C
    above_cap = temp > cap + TOL

    servers_detail = []
    for sv in scenario.servers:
        k = sv.s - 1
        servers_detail.append({
            "s": sv.s, "name": sv.name, "zone": sv.zone, "cold_plate": int(sv.CT_cold_plate),
            "n_cold_plates": int(plates[k]),
            "Q_cp_peak_W": _f(Q_cp[k].max()), "Q_cp_capacity_W": _f(plates[k] * cps.Q_max_per_plate_W),
            "cpu_peak_cores": _f(cpu_used[k].max()), "cpu_capacity_cores": _f(sv.C_cores),
            "max_utilization": _f(util[k].max()),
            "mem_peak_MB": _f(mem_used[k].max()), "mem_capacity_MB": _f(sv.M_MB),
            "hottest_T_C": _f(temp[k].max()), "min_headroom_C": _f(headroom[k].min()),
            "periods_above_dvfs": int(above_dvfs[k].sum()),
            "periods_above_cap": int(above_cap[k].sum()),
            "min_DPF": _f(DPF[k].min()), "min_PC_eff_MHz": _f(PC_eff[k].min()),
            "periods_unavailable": int((AV[k] == 0).sum()),
        })
    cold_plates_detail = []
    for sv in scenario.servers:
        k = sv.s - 1
        if not has_cp[k]:
            continue
        cold_plates_detail.append({
            "s": sv.s, "name": sv.name, "n_cold_plates": int(plates[k]),
            "coolant_min_C": _f(cp_coolant[k].min()), "coolant_max_C": _f(cp_coolant[k].max()),
            "coolant_allowed_min_C": _f(cps.coolant_min_C),
            "coolant_allowed_max_C": _f(cps.coolant_max_C),
            "flow_min_Lmin": _f(cp_flow[k].min()), "flow_max_Lmin": _f(cp_flow[k].max()),
            "flow_allowed_min_Lmin": _f(cps.flow_min_Lmin),
            "flow_allowed_max_Lmin": _f(cps.flow_max_Lmin),
            "Q_cp_peak_W": _f(Q_cp[k].max()),
            "Q_cp_capacity_W": _f(plates[k] * cps.Q_max_per_plate_W),
        })
    zones_detail = []
    for z in range(1, Z + 1):
        zones_detail.append({
            "z": z,
            "supply_min_C": _f(supply[z - 1].min()), "supply_max_C": _f(supply[z - 1].max()),
            "supply_allowed_min_C": _f(c.T_crac_min_C), "supply_allowed_max_C": _f(c.T_crac_max_C),
            "zone_limit_C": _f(c.T_max_zone_C),
            "max_ramp_short_C": (float(np.abs(supply[z - 1, c.ramp_short_lag:]
                                              - supply[z - 1, :-c.ramp_short_lag]).max())
                                 if T > c.ramp_short_lag else 0.0),
            "ramp_short_limit_C": _f(c.ramp_short_C),
            "max_ramp_long_C": (float(np.abs(supply[z - 1, c.ramp_long_lag:]
                                             - supply[z - 1, :-c.ramp_long_lag]).max())
                                if T > c.ramp_long_lag else 0.0),
            "ramp_long_limit_C": _f(c.ramp_long_C),
            "Q_crac_peak_kW": _f(Q_crac[z - 1].max()), "Q_crac_capacity_kW": _f(c.Q_crac_kW),
        })

    checks = {"cpu_ok": cpu_ok, "mem_ok": mem_ok, "thermal_cap_ok": thermal_cap_ok,
              "workloads_ok": workloads_ok, "supply_range_ok": supply_range_ok,
              "zone_temp_ok": zone_temp_ok, "ramp_ok": ramp_ok,
              "crac_capacity_ok": crac_capacity_ok, "cold_plate_coolant_ok": cp_coolant_ok,
              "cold_plate_flow_ok": cp_flow_ok, "availability_ok": availability_ok,
              "priority_ok": priority_ok}
    # Priority is measured either way but is only a limit when the run enforces it.
    binding = {k: v for k, v in checks.items() if settings.priority or k != "priority_ok"}

    violations: list[str] = []
    if not cpu_ok:
        bad = [d for d in servers_detail if d["cpu_peak_cores"] > d["cpu_capacity_cores"] + TOL]
        violations.append("CPU capacity exceeded on server(s) "
                          + ", ".join(str(d["s"]) for d in bad) + " (Eq. 12)")
    if not mem_ok:
        bad = [d for d in servers_detail if d["mem_peak_MB"] > d["mem_capacity_MB"] + TOL]
        violations.append("memory capacity exceeded on server(s) "
                          + ", ".join(str(d["s"]) for d in bad) + " (Eq. 13)")
    if not thermal_cap_ok:
        violations.append(f"server temperature above thermal cap {cap:g} C in "
                          f"{int(above_cap.sum())} server-periods (Eq. 31-33), "
                          f"hottest {temp.max():.2f} C")
    if not workloads_ok:
        n_unp = int((~placed).sum())
        parts = []
        if n_unp:
            parts.append(f"{n_unp} unplaced")
        for label, flag in (("starts before arrival", ~starts_ok), ("wait exceeds allowed delay", ~wait_ok),
                            ("finishes after deadline", ~on_time), ("work short", ~work_ok),
                            ("runs outside horizon", ~within_horizon)):
            n = int((placed & flag).sum())
            if n:
                parts.append(f"{n} {label}")
        violations.append(f"{int((~compliant).sum())} non-compliant workload(s): " + "; ".join(parts))
    if not supply_range_ok:
        violations.append(f"supply temperature outside [{c.T_crac_min_C:g}, {c.T_crac_max_C:g}] C (Eq. 42)")
    if not zone_temp_ok:
        violations.append(f"zone temperature above {c.T_max_zone_C:g} C (Eq. 34)")
    if not ramp_ok:
        violations.append(f"supply ramp too steep: short {ramp_short:.2f} C (limit {c.ramp_short_C:g}), "
                          f"long {ramp_long:.2f} C (limit {c.ramp_long_C:g}) (Eq. 35-36)")
    if not crac_capacity_ok:
        violations.append(f"CRAC heat above capacity {c.Q_crac_kW:g} kW, peak {Q_crac.max():.2f} kW (Eq. 54)")
    if not cp_coolant_ok:
        violations.append(f"cold-plate coolant temperature outside [{cps.coolant_min_C:g}, "
                          f"{cps.coolant_max_C:g}] C (Eq. 49)")
    if not cp_flow_ok:
        violations.append(f"cold-plate flow outside [{cps.flow_min_Lmin:g}, {cps.flow_max_Lmin:g}] "
                          f"L/min (Eq. 47)")
    if not availability_ok:
        bad = sorted({int(k) + 1 for k in np.nonzero(unavailable_used)[0]})
        violations.append(f"work runs on unavailable server-periods ({int(unavailable_used.sum())}, "
                          f"server(s) {', '.join(map(str, bad))}) (Eq. 11)")
    if not priority_ok and settings.priority:
        ex = ", ".join(f"{scenario.workloads[j - 1].workload_id} before "
                       f"{scenario.workloads[i - 1].workload_id}" for i, j in prio_bad[:3])
        violations.append(f"{len(prio_bad)} priority inversion(s): a lower-priority workload "
                          f"started on a server while a higher-priority one waited for it, "
                          f"e.g. {ex} (Eq. 56-57)")

    compliance = {
        "all_ok": all(binding.values()), **checks,
        "servers": servers_detail, "zones": zones_detail, "cold_plates": cold_plates_detail,
        "priority_violations": [list(x) for x in prio_bad],
        "thermal_cap_C": _f(cap), "violations": violations,
        "within_horizon": [bool(x) for x in within_horizon],
    }

    # ---- totals -----------------------------------------------------------
    rt = np.array([w.RT for w in scenario.workloads])
    placed_rt = placed & (rt == 1)
    placed_dt = placed & (rt == 0)

    def mean_max(mask):
        if not mask.any():
            return None, None
        return float(wait[mask].mean()), float(wait[mask].max())

    mean_rt, max_rt = mean_max(placed_rt)
    mean_dt, max_dt = mean_max(placed_dt)
    deadline = np.array([w.D for w in scenario.workloads])
    late = (~placed) | (placed & (end > deadline))
    k_hot, t_hot = np.unravel_index(int(np.argmax(temp)), temp.shape)
    totals = {
        "E_IT_kWh": _f(E_IT.sum()), "E_crac_kWh": _f(E_crac.sum()),
        "E_cp_kWh": _f(E_cp.sum()), "E_fan_kWh": _f(E_fan.sum()),
        "Q_cp_kWh": _f(Q_cp.sum() * dt * W_TO_KWH_FACTOR),
        "E_total_kWh": _f(E_total.sum()),
        "carbon_g": total_carbon, "carbon_kg": total_carbon / 1000.0,
        "n_workloads": int(I), "n_unplaced": int((~placed).sum()),
        "n_late": int(late.sum()),
        "n_wait_exceeded": int((placed & ~wait_ok).sum()),
        "n_work_short": int((placed & ~work_ok).sum()),
        "n_noncompliant": int((~compliant).sum()),
        "mean_wait_RT": mean_rt, "max_wait_RT": max_rt,
        "mean_wait_DT": mean_dt, "max_wait_DT": max_dt,
        "hottest_T_C": _f(temp.max()), "hottest_server": int(k_hot + 1),
        "hottest_period": int(t_hot + 1),
        "min_headroom_C": _f(headroom.min()),
        "periods_above_dvfs": int(above_dvfs.sum()),
        "periods_above_cap": int(above_cap.sum()),
        "min_DPF": _f(DPF.min()),
        "n_throttled_servers": int((DPF < 1.0 - 1e-12).any(axis=1).sum()),
        "mean_T_C": _f(temp.mean()),
        "mean_headroom_C": _f(headroom.mean()),
        "n_priority_violations": len(prio_bad),
        "E_crac_by_zone_kWh": [_f(P_crac[z].sum() * dt / 3600.0) for z in range(Z)],
    }

    return EvalResult(
        cpu_used_cores=cpu_used, mem_used_MB=mem_used, util=util, P_IT_W=P_IT,
        Q_cp_W=Q_cp, P_cp_W=P_cp, T_C=temp, headroom_C=headroom, DPF=DPF, PC_eff_MHz=PC_eff,
        T_supply_C=supply.copy(), Q_crac_kW=Q_crac, COP=COP, P_crac_kW=P_crac, P_fan_kW=P_fan,
        E_IT_kWh=E_IT, E_crac_kWh=E_crac, E_cp_kWh=E_cp, E_fan_kWh=E_fan,
        E_total_kWh=E_total, carbon_g=carbon,
        wait_periods=wait, work_delivered_MHz_s=delivered, work_required_MHz_s=required,
        placed=placed, starts_on_or_after_arrival=starts_ok, wait_within_allowed=wait_ok,
        on_time=on_time, work_complete=work_ok, compliant=compliant, min_DPF_run=min_dpf_run,
        total_carbon_g=total_carbon, totals=totals, compliance=compliance,
        airflow_modelled=False,
        n_cold_plates=plates, cp_flow_Lmin=cp_flow, cp_coolant_C=cp_coolant,
    )
