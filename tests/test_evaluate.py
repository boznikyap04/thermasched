"""Tests for scheduler/evaluate.py and scheduler/report.py."""

from __future__ import annotations

import csv
import json
from dataclasses import replace

import numpy as np
import pytest

from scheduler.evaluate import dpf, evaluate, fan_power_kW
from scheduler.io import load_reference_baseline, load_scenario
from scheduler.report import format_summary, write_results
from scheduler.types import (
    ColdPlateOps, ColdPlateSpec, Constants, NotDefinedYet, Placement, RunSettings, Scenario,
    Schedule, Server, Workload, constant_supply_temp, cop,
)

CONSTANTS = Constants(
    R_dvfs=0.378, F_throttle=0.662, T_max_server_C=90.0, H_min_C=10.0, T_dvfs_C=75.0,
    T_throttle_C=100.0, Q_crac_kW=116.0, COP_coeffs=(0.0068, 0.0008, 0.458),
    T_crac_min_C=18.0, T_crac_max_C=27.0, T_max_zone_C=32.0,
)


# ---------------------------------------------------------------------------
# Tiny hand-built scenario
# ---------------------------------------------------------------------------

def tiny(R1: float = 0.5, workloads=None, constants=CONSTANTS) -> Scenario:
    """Two servers in one zone, three periods of 300 s.

    Server 1: 2000 MHz, 10 cores, idle 100 W, max 300 W, T0 40, a 2, R R1, alpha 0.5.
    Server 2: 3000 MHz, 4 cores, idle 50 W, max 150 W, T0 30, a 0, R 0.2, alpha 0.8.
    """
    servers = (
        Server(1, "srv1", 1, 2000.0, 10, 1000.0, 100.0, 300.0, 40.0, 0, 2.0, R1, 0.5),
        Server(2, "srv2", 1, 3000.0, 4, 1000.0, 50.0, 150.0, 30.0, 1, 0.0, 0.2, 0.8),
    )
    if workloads is None:
        workloads = (
            # 5 cores for periods 1-2 on server 1; needs 5*2000*300 = 3e6 per full period
            Workload(1, "w1", "f", A=1, D=3, AD=0, ET_base=2, RT=1, B=0, X0=1, C_req=5,
                     M_req_MB=100.0, W_MHz_s=4_713_840.0),
            # 2 cores in period 3 on server 2: 2*3000*300 = 1.8e6
            Workload(2, "w2", "f", A=2, D=4, AD=1, ET_base=1, RT=0, B=0, X0=2, C_req=2,
                     M_req_MB=100.0, W_MHz_s=1_800_000.0),
        )
    return Scenario(name="tiny", T=3, dt_seconds=300.0, workloads=tuple(workloads),
                    servers=servers, n_zones=1,
                    CI_g_per_kWh=np.array([500.0, 600.0, 700.0]), constants=constants)


def sched(*items) -> Schedule:
    return Schedule(tuple(Placement(i, s, st, en) for i, s, st, en in items))


HAND_SCHEDULE = sched((1, 1, 1, 3), (2, 2, 3, 4))
SETTINGS = RunSettings(scenario="tiny")


def test_hand_calculation():
    sc = tiny()
    ev = evaluate(sc, HAND_SCHEDULE, constant_supply_temp(sc, 20.0), SETTINGS)

    # CPU and utilization: w1 uses 5 of 10 cores in t=1,2; w2 uses 2 of 4 cores in t=3.
    assert ev.cpu_used_cores[0].tolist() == [5, 5, 0]
    assert ev.cpu_used_cores[1].tolist() == [0, 0, 2]
    assert ev.mem_used_MB[0].tolist() == [100, 100, 0]
    np.testing.assert_allclose(ev.util, [[0.5, 0.5, 0.0], [0.0, 0.0, 0.5]])

    # P_IT = idle + (max - idle) * util
    np.testing.assert_allclose(ev.P_IT_W, [[200, 200, 100], [50, 50, 100]])
    assert np.all(ev.Q_cp_W == 0) and np.all(ev.P_cp_W == 0)    # cold plates off by default

    # Server 1: steady = 20 + 2 + 0.5 * 200 = 122; T = 0.5 * prev + 0.5 * steady
    #   t1 = 0.5*40 + 0.5*122 = 81
    #   t2 = 0.5*81 + 0.5*122 = 101.5
    #   t3 (P=100, steady = 20 + 2 + 50 = 72) = 0.5*101.5 + 0.5*72 = 86.75
    # Server 2: steady = 20 + 0.2*50 = 30 -> stays 30; t3: steady = 20 + 20 = 40
    #   t3 = 0.8*30 + 0.2*40 = 32
    np.testing.assert_allclose(ev.T_C[0], [81.0, 101.5, 86.75])
    np.testing.assert_allclose(ev.T_C[1], [30.0, 30.0, 32.0])
    np.testing.assert_allclose(ev.headroom_C[0], [9.0, -11.5, 3.25])

    # DPF: t1 middle branch 1 - 0.378 * (81-75)/(100-75) = 1 - 0.09072; t2 >= 100 -> 0.662
    #      t3 middle 1 - 0.378 * 11.75/25 = 1 - 0.17766
    np.testing.assert_allclose(ev.DPF[0], [0.90928, 0.662, 0.82234])
    np.testing.assert_allclose(ev.DPF[1], [1.0, 1.0, 1.0])
    np.testing.assert_allclose(ev.PC_eff_MHz[0], 10 * 2000.0 * ev.DPF[0])

    # Work delivered: w1 = 5 * 2000 * 300 * (0.90928 + 0.662) = 3e6 * 1.57128 = 4,713,840
    #                 w2 = 2 * 3000 * 300 * 1.0 = 1.8e6
    np.testing.assert_allclose(ev.work_delivered_MHz_s, [4_713_840.0, 1_800_000.0])
    assert ev.work_complete.all() and ev.compliant.all()
    np.testing.assert_allclose(ev.wait_periods, [0, 1])

    # Heat balance: Q_crac = sum P_IT / 1000 = 0.25, 0.25, 0.20 kW
    np.testing.assert_allclose(ev.Q_crac_kW[0], [0.25, 0.25, 0.20])
    # COP(20) = 0.0068*400 + 0.0008*20 + 0.458 = 2.72 + 0.016 + 0.458 = 3.194
    np.testing.assert_allclose(ev.COP[0], 3.194)
    assert cop(CONSTANTS, 20.0) == pytest.approx(3.194)
    # P_crac = Q / COP (division, not multiplication)
    np.testing.assert_allclose(ev.P_crac_kW[0], np.array([0.25, 0.25, 0.20]) / 3.194)
    assert ev.P_crac_kW[0, 0] < ev.Q_crac_kW[0, 0]
    assert np.all(ev.P_fan_kW == 0) and ev.airflow_modelled is False

    # Energy: E_IT = P * 300 s / 3.6e6 = 250 W -> 0.0208333 kWh, 200 W -> 0.0166667 kWh
    np.testing.assert_allclose(ev.E_IT_kWh, [250 / 12000, 250 / 12000, 200 / 12000])
    # E_crac = P_crac_kW * 300/3600
    np.testing.assert_allclose(ev.E_crac_kWh, np.array([0.25, 0.25, 0.20]) / 3.194 / 12)
    np.testing.assert_allclose(ev.E_total_kWh, ev.E_IT_kWh + ev.E_crac_kWh)
    assert np.all(ev.E_cp_kWh == 0) and np.all(ev.E_fan_kWh == 0)
    np.testing.assert_allclose(ev.carbon_g, [500, 600, 700] * ev.E_total_kWh)
    assert ev.total_carbon_g == pytest.approx(float(ev.carbon_g.sum()))
    assert ev.totals["carbon_kg"] == pytest.approx(ev.total_carbon_g / 1000)
    assert ev.totals["E_IT_kWh"] == pytest.approx(700 / 12000)

    # Totals and compliance on this deliberately hot server
    t = ev.totals
    assert t["hottest_T_C"] == pytest.approx(101.5)
    assert t["hottest_server"] == 1 and t["hottest_period"] == 2
    assert t["min_headroom_C"] == pytest.approx(-11.5)
    assert t["periods_above_dvfs"] == 3 and t["periods_above_cap"] == 3
    assert t["min_DPF"] == pytest.approx(0.662)
    assert t["mean_wait_RT"] == 0 and t["max_wait_DT"] == 1 and t["max_wait_RT"] == 0
    assert ev.compliance["thermal_cap_C"] == 80.0
    assert ev.compliance["thermal_cap_ok"] is False and ev.valid is False
    assert any("thermal cap" in v for v in ev.compliance["violations"])


# ---------------------------------------------------------------------------
# DPF
# ---------------------------------------------------------------------------

def test_dpf_three_branches():
    c = CONSTANTS
    assert dpf(60.0, c) == 1.0
    assert dpf(74.999, c) == 1.0
    assert dpf(75.0, c) == pytest.approx(1.0)                 # start of middle branch
    assert dpf(87.5, c) == pytest.approx(1 - 0.378 * 12.5 / 25)
    assert dpf(99.999, c) == pytest.approx(1 - 0.378, abs=1e-4)  # just below the jump
    assert dpf(100.0, c) == 0.662                              # >= T_throttle
    assert dpf(130.0, c) == 0.662
    np.testing.assert_allclose(dpf(np.array([[50.0, 80.0, 120.0]]), c),
                               [[1.0, 1 - 0.378 * 5 / 25, 0.662]])


# ---------------------------------------------------------------------------
# Compliance flags flipping
# ---------------------------------------------------------------------------

CALM_W = (
    Workload(1, "w1", "f", A=1, D=3, AD=1, ET_base=2, RT=1, B=0, X0=1, C_req=5,
             M_req_MB=100.0, W_MHz_s=3_000_000.0),
)
CALM_SCHEDULE = sched((1, 1, 1, 2))     # one period, 5 cores * 2000 * 300 = 3e6 exactly


def calm(workloads=CALM_W, constants=CONSTANTS) -> Scenario:
    return tiny(R1=0.05, workloads=workloads, constants=constants)


def run_calm(sc=None, schedule=CALM_SCHEDULE, supply=None):
    sc = sc or calm()
    supply = constant_supply_temp(sc, 20.0) if supply is None else supply
    return evaluate(sc, schedule, supply, SETTINGS)


def test_calm_baseline_is_fully_valid():
    ev = run_calm()
    assert ev.compliance["all_ok"] and ev.valid
    assert ev.compliance["violations"] == []
    for k in ("cpu_ok", "mem_ok", "thermal_cap_ok", "workloads_ok", "supply_range_ok",
              "zone_temp_ok", "ramp_ok", "crac_capacity_ok"):
        assert ev.compliance[k] is True, k
    assert ev.compliant.all()
    assert ev.work_delivered_MHz_s[0] == pytest.approx(3_000_000.0)


def test_cpu_over_capacity():
    ws = CALM_W + (Workload(2, "w2", "f", 1, 3, 1, 1, 0, 0, 1, 6, 100.0, 1.0),)
    ev = run_calm(calm(ws), sched((1, 1, 1, 2), (2, 1, 1, 2)))
    assert ev.compliance["cpu_ok"] is False and ev.compliance["all_ok"] is False
    assert ev.compliance["servers"][0]["cpu_peak_cores"] == 11
    assert any("CPU" in v for v in ev.compliance["violations"])


def test_memory_over_capacity():
    ws = (replace(CALM_W[0], M_req_MB=2000.0),)
    ev = run_calm(calm(ws))
    assert ev.compliance["mem_ok"] is False and ev.compliance["cpu_ok"] is True


def test_late_workload():
    ev = run_calm(schedule=sched((1, 1, 2, 3)))     # ends at 3 = D, still on time
    assert ev.on_time[0] and ev.compliant[0]
    ev = run_calm(calm((replace(CALM_W[0], D=2),)), sched((1, 1, 2, 3)))
    assert not ev.on_time[0] and not ev.compliant[0]
    assert ev.totals["n_late"] == 1 and ev.compliance["workloads_ok"] is False


def test_wait_exceeded():
    ws = (replace(CALM_W[0], A=1, AD=0, D=4),)
    ev = run_calm(calm(ws), sched((1, 1, 2, 3)))
    assert ev.wait_periods[0] == 1
    assert not ev.wait_within_allowed[0] and ev.on_time[0] and ev.work_complete[0]
    assert ev.totals["n_wait_exceeded"] == 1 and not ev.compliant[0]


def test_starts_before_arrival():
    ws = (replace(CALM_W[0], A=2, D=4),)
    ev = run_calm(calm(ws), sched((1, 1, 1, 2)))
    assert not ev.starts_on_or_after_arrival[0] and ev.wait_periods[0] == -1
    assert not ev.compliant[0]


def test_work_short():
    ws = (replace(CALM_W[0], W_MHz_s=3_000_001.0 * 1.001),)
    ev = run_calm(calm(ws))
    assert not ev.work_complete[0] and not ev.compliant[0]
    assert ev.totals["n_work_short"] == 1 and ev.compliance["workloads_ok"] is False
    # within the 1e-6 relative tolerance counts as complete
    ws = (replace(CALM_W[0], W_MHz_s=3_000_000.0 * (1 + 5e-7)),)
    assert run_calm(calm(ws)).work_complete[0]


def test_unplaced_workload():
    ev = run_calm(schedule=sched((1, None, None, None)))
    assert not ev.placed[0] and not ev.compliant[0]
    assert np.isnan(ev.wait_periods[0]) and np.isnan(ev.work_delivered_MHz_s[0])
    t = ev.totals
    assert t["n_unplaced"] == 1 and t["n_late"] == 1 and t["n_noncompliant"] == 1
    assert t["mean_wait_RT"] is None and t["mean_wait_DT"] is None
    assert ev.compliance["workloads_ok"] is False
    # idle servers still draw power
    assert ev.E_IT_kWh.sum() == pytest.approx((100 + 50) * 3 * 300 / 3.6e6)
    # an empty schedule (no placement object at all) also works
    ev2 = run_calm(schedule=Schedule(()))
    assert not ev2.placed[0]


def test_run_outside_horizon_does_not_crash():
    ws = (replace(CALM_W[0], D=10, AD=10),)
    ev = run_calm(calm(ws), sched((1, 1, 3, 5)))     # occupies periods 3, 4 (horizon is 3)
    assert not ev.compliant[0] and ev.placed[0]
    ev = run_calm(calm(ws), sched((1, 1, 0, 2)))     # starts before period 1
    assert not ev.compliant[0]
    ev = run_calm(calm(ws), sched((1, 1, 1, 9)))
    assert not ev.compliant[0] and ev.compliance["workloads_ok"] is False


def test_supply_out_of_range():
    sc = calm()
    for value, zone_ok in ((17.0, True), (28.0, True), (33.0, False)):
        ev = run_calm(sc, supply=constant_supply_temp(sc, value))
        assert ev.compliance["supply_range_ok"] is False, value
        assert ev.compliance["zone_temp_ok"] is zone_ok, value
        assert ev.compliance["all_ok"] is False
    z = ev.compliance["zones"][0]
    assert z["supply_max_C"] == 33.0 and z["zone_limit_C"] == 32.0


def test_ramp_short_and_long():
    # short: a 6 degC step within one lag violates the 5 degC limit
    c = replace(CONSTANTS, ramp_short_lag=1, ramp_long_lag=2)
    sc = calm(constants=c)
    ev = run_calm(sc, supply=np.array([[20.0, 26.0, 26.0]]))
    assert ev.compliance["ramp_ok"] is False
    assert ev.compliance["zones"][0]["max_ramp_short_C"] == pytest.approx(6.0)
    assert ev.compliance["supply_range_ok"] is True
    ev = run_calm(sc, supply=np.array([[20.0, 25.0, 25.0]]))      # exactly 5: allowed
    assert ev.compliance["ramp_ok"] is True
    # long: lag 2, limit 20 (range widened so only the ramp can fail)
    c = replace(CONSTANTS, ramp_short_lag=1, ramp_short_C=100.0, ramp_long_lag=2,
                T_crac_max_C=60.0, T_max_zone_C=60.0)
    sc = calm(constants=c)
    ev = run_calm(sc, supply=np.array([[18.0, 30.0, 40.0]]))      # t3 - t1 = 22
    assert ev.compliance["ramp_ok"] is False
    assert ev.compliance["zones"][0]["max_ramp_long_C"] == pytest.approx(22.0)
    ev = run_calm(sc, supply=np.array([[18.0, 30.0, 38.0]]))      # 20: allowed
    assert ev.compliance["ramp_ok"] is True


def test_ramp_default_lags_on_small_scenario():
    sc = load_scenario("small")
    base = load_reference_baseline("small")
    s = constant_supply_temp(sc, 18.0)
    s[:, 10:] = 24.0                          # +6 degC over 3 periods at t=11..13
    ev = evaluate(sc, base, s, RunSettings(scenario="small"))
    assert ev.compliance["ramp_ok"] is False
    s = constant_supply_temp(sc, 18.0)
    s[:, 10:] = 22.0                          # +4: allowed
    assert evaluate(sc, base, s, RunSettings(scenario="small")).compliance["ramp_ok"] is True


def test_above_cap_and_h_min_setting():
    sc = calm()
    assert run_calm(sc).compliance["thermal_cap_ok"] is True
    hot = tiny(R1=0.5, workloads=CALM_W)       # reaches 81 degC in period 1
    ev = evaluate(hot, CALM_SCHEDULE, constant_supply_temp(hot, 20.0), SETTINGS)
    assert ev.compliance["thermal_cap_ok"] is False
    assert ev.totals["periods_above_cap"] >= 1
    # raising the allowed temperature by setting H_min = 5 (cap 85) clears period 1
    ev5 = evaluate(hot, CALM_SCHEDULE, constant_supply_temp(hot, 20.0),
                   RunSettings(scenario="tiny", H_min_C=5.0))
    assert ev5.compliance["thermal_cap_C"] == 85.0
    assert ev5.totals["periods_above_cap"] < ev.totals["periods_above_cap"]


def test_crac_capacity():
    c = replace(CONSTANTS, Q_crac_kW=0.1)
    ev = run_calm(calm(constants=c))
    assert ev.compliance["crac_capacity_ok"] is False
    assert ev.compliance["zones"][0]["Q_crac_peak_kW"] > 0.1
    assert run_calm().compliance["crac_capacity_ok"] is True


def test_supply_shape_checked():
    sc = calm()
    with pytest.raises(ValueError):
        evaluate(sc, CALM_SCHEDULE, np.full((2, 3), 20.0), SETTINGS)


# ---------------------------------------------------------------------------
# Slots
# ---------------------------------------------------------------------------

def test_not_defined_yet():
    sc = calm()
    with pytest.raises(NotDefinedYet):
        evaluate(sc, CALM_SCHEDULE, constant_supply_temp(sc, 20.0),
                 RunSettings(scenario="tiny", fan_power=True))


def test_fan_slot_returns_zeros():
    assert not fan_power_kW(calm(), np.ones((1, 3))).any()


# ---------------------------------------------------------------------------
# Cold plates
# ---------------------------------------------------------------------------

CP_SETTINGS = RunSettings(scenario="tiny", cold_plates=True)
G_030 = 1 / 0.0793                       # 0.30 L/min: 1/R = 12.61 < water 0.005 kg/s * 4182 = 20.9
PUMP_030 = 0.657e-3 * (0.30 / 0.264) ** 3


def test_cold_plate_spec_numbers():
    cp = ColdPlateSpec()
    cp.validate()
    G = cp.conductance_W_per_C()
    np.testing.assert_allclose(G, 1 / np.array([0.1543, 0.1143, 0.0943, 0.0843, 0.0793]))
    np.testing.assert_allclose(cp.pump_W(), 0.657e-3 * (np.array(cp.flow_settings_Lmin) / 0.264) ** 3)
    assert cp.level_of(0.25) == 3
    with pytest.raises(ValueError):
        cp.level_of(0.264)                # the pump reference flow is not a setting
    # the water's heat capacity rate caps the conductance when R is very small
    water = ColdPlateSpec(R_C_per_W=(1e-4,) * 5).conductance_W_per_C()
    np.testing.assert_allclose(water, np.array(cp.flow_settings_Lmin) / 60 * 4182.0)
    with pytest.raises(ValueError):
        ColdPlateSpec(flow_settings_Lmin=(0.01, 0.1, 0.2, 0.25, 0.3)).validate()   # below 0.05


def test_cold_plate_hand_calculation():
    """Server 2 of tiny() has a cold plate (CT = 1); the baseline runs it at 0.30 L/min, 20 C."""
    sc = tiny()
    ev = evaluate(sc, HAND_SCHEDULE, constant_supply_temp(sc, 20.0), CP_SETTINGS)
    # Server 2: T0 30, a 0, R 0.2, alpha 0.8, P_IT 50, 50, 100.
    #   t1: drive 30-20 = 10 -> 126 W, capped by P_IT 50; steady 20 -> T = 0.8*30 + 0.2*20 = 28
    #   t2: drive 8 -> 101 W, capped at 50; T = 0.8*28 + 4 = 26.4
    #   t3: drive 6.4 -> 80.7 W < P_IT 100; steady = 20 + 0.2*(100 - 80.7)
    q3 = G_030 * 6.4
    t3 = 0.8 * 26.4 + 0.2 * (20 + 0.2 * (100 - q3))
    np.testing.assert_allclose(ev.Q_cp_W[1], [50.0, 50.0, q3])
    np.testing.assert_allclose(ev.T_C[1], [28.0, 26.4, t3])
    np.testing.assert_allclose(ev.P_cp_W[1], PUMP_030)
    # server 1 has no cold plate: nothing changes there
    assert not ev.Q_cp_W[0].any() and not ev.P_cp_W[0].any()
    np.testing.assert_allclose(ev.T_C[0], [81.0, 101.5, 86.75])
    assert np.isnan(ev.cp_flow_Lmin[0]).all() and (ev.cp_flow_Lmin[1] == 0.30).all()
    # heat balance and energy
    np.testing.assert_allclose(ev.Q_crac_kW[0], (ev.P_IT_W - ev.Q_cp_W).sum(axis=0) / 1000)
    np.testing.assert_allclose(ev.E_cp_kWh, PUMP_030 * 300 / 3.6e6)
    np.testing.assert_allclose(ev.E_total_kWh, ev.E_IT_kWh + ev.E_crac_kWh + ev.E_cp_kWh)
    assert ev.totals["Q_cp_kWh"] == pytest.approx((100 + q3) * 300 / 3.6e6)
    assert ev.compliance["cold_plate_coolant_ok"] and ev.compliance["cold_plate_flow_ok"]
    assert ev.compliance["servers"][1]["n_cold_plates"] == 1


def test_cold_plate_given_ops_and_limits():
    sc = tiny()
    supply = constant_supply_temp(sc, 20.0)
    # two plates on every server; slowest flow, coolant 25 C on server 2
    st = RunSettings(scenario="tiny", cold_plates=True, cold_plate_count=2)
    ops = ColdPlateOps(flow_Lmin=np.full((2, 3), 0.10), coolant_C=np.full((2, 3), 25.0))
    ev = evaluate(sc, HAND_SCHEDULE, supply, st, ops)
    G = 1 / 0.1543
    # server 1, t1: drive 40 - 25 = 15 -> 2 * 6.48 * 15 = 194 W, capped by P_IT 200? no: 194 < 200
    assert ev.Q_cp_W[0, 0] == pytest.approx(2 * G * 15)
    # every value respects n * 0.3 kW and P_IT
    assert np.all(ev.Q_cp_W <= np.minimum(600.0, ev.P_IT_W) + 1e-9)
    np.testing.assert_allclose(ev.P_cp_W, 2 * 0.657e-3 * (0.10 / 0.264) ** 3)
    # coolant outside 20-39.95 C is reported, not refused
    bad = ColdPlateOps(flow_Lmin=ops.flow_Lmin, coolant_C=np.full((2, 3), 45.0))
    ev = evaluate(sc, HAND_SCHEDULE, supply, st, bad)
    assert not ev.compliance["cold_plate_coolant_ok"] and not ev.valid
    assert any("Eq. 49" in v for v in ev.compliance["violations"])
    # coolant hotter than the server: no heat removed, never negative
    assert np.all(ev.Q_cp_W >= 0)


def test_cold_plate_count_zero_equals_off():
    sc = tiny()
    supply = constant_supply_temp(sc, 20.0)
    off = evaluate(sc, HAND_SCHEDULE, supply, SETTINGS)
    zero = evaluate(sc, HAND_SCHEDULE, supply,
                    RunSettings(scenario="tiny", cold_plates=True, cold_plate_count=0))
    assert zero.total_carbon_g == off.total_carbon_g
    np.testing.assert_array_equal(zero.T_C, off.T_C)


def test_cold_plate_settings_checked():
    sc = tiny()
    supply = constant_supply_temp(sc, 20.0)
    with pytest.raises(ValueError):
        RunSettings(cold_plate_count=1).validate()          # count without the switch
    with pytest.raises(ValueError):
        RunSettings(cold_plates=True, cold_plate_count=-1).validate()
    with pytest.raises(ValueError):                          # baseline flow must be a setting
        evaluate(sc, HAND_SCHEDULE, supply,
                 RunSettings(scenario="tiny", cold_plates=True, baseline_cp_flow_Lmin=0.264))


# ---------------------------------------------------------------------------
# Acceptance numbers from the project owner (reference least-loaded baseline)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("name,e_it,carbon_kg", [
    ("small", 4.45, 2.82), ("base", 26.27, 16.33), ("thesis10", 42.27, 26.29)])
def test_reference_baseline_it_energy_and_carbon(name, e_it, carbon_kg):
    sc = load_scenario(name)
    ev = evaluate(sc, load_reference_baseline(name), constant_supply_temp(sc, 18.0),
                  RunSettings(scenario=name))
    assert round(ev.totals["E_IT_kWh"], 2) == e_it
    it_carbon_kg = float((sc.CI_g_per_kWh * ev.E_IT_kWh).sum()) / 1000.0
    assert round(it_carbon_kg, 2) == carbon_kg
    assert ev.valid, ev.compliance["violations"]
    assert ev.totals["n_noncompliant"] == 0 and ev.totals["n_unplaced"] == 0


def test_base_thermal_and_cooling_numbers():
    sc = load_scenario("base")
    ref = load_reference_baseline("base")
    st = RunSettings(scenario="base")
    ev18 = evaluate(sc, ref, constant_supply_temp(sc, 18.0), st)
    ev27 = evaluate(sc, ref, constant_supply_temp(sc, 27.0), st)
    assert ev18.totals["hottest_T_C"] == pytest.approx(68.1, abs=0.1)
    assert ev27.totals["hottest_T_C"] == pytest.approx(73.4, abs=0.1)
    assert ev18.T_C.max() < 80 and ev27.T_C.max() < 80
    assert ev18.totals["periods_above_cap"] == 0 and ev27.totals["periods_above_cap"] == 0
    assert ev18.totals["E_crac_kWh"] == pytest.approx(9.8, abs=0.1)
    assert ev27.totals["E_crac_kWh"] == pytest.approx(4.8, abs=0.1)
    # E_total is the sum of its parts
    t = ev18.totals
    assert t["E_total_kWh"] == pytest.approx(t["E_IT_kWh"] + t["E_crac_kWh"])


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

def _small():
    sc = load_scenario("small")
    base = load_reference_baseline("small")
    st = RunSettings(scenario="small")
    ev = evaluate(sc, base, constant_supply_temp(sc, 18.0), st)
    orig = {w.i: w.X0 for w in sc.workloads}
    return sc, base, st, ev, orig


TABLES = ["schedule.csv", "server_period.csv", "zone_period.csv", "period.csv",
          "compliance_servers.csv", "compliance_zones.csv", "compliance_workloads.csv",
          "compliance_cold_plates.csv"]


def test_report_without_optimized(tmp_path):
    from scheduler.types import STATUS_NO_SOLUTION, SolveResult
    sc, base, st, ev, orig = _small()
    sr = SolveResult(status=STATUS_NO_SOLUTION, schedule=None, supply_temp_C=None,
                     objective_g=None, best_bound_g=float("nan"), mip_gap=None,
                     solve_time_s=1.5, n_variables=10, n_binaries=4, n_constraints=7,
                     notes=["no schedule"])
    out = tmp_path / "run"
    summary = write_results(out, sc, st, orig, base, ev, None, None, sr,
                            {"deadlines_and_waiting": "feasible", "thermal_cap": None},
                            {"baseline_matches_reference": True})
    for f in TABLES:
        assert (out / "baseline" / f).is_file(), f
    assert not (out / "optimized").exists()
    assert (out / "comparison_period.csv").is_file() and (out / "summary.json").is_file()
    loaded = json.loads((out / "summary.json").read_text())
    assert loaded["optimized"] is None and loaded["has_optimized_schedule"] is False
    assert loaded["baseline"]["valid"] is True
    assert loaded["baseline"]["metrics"]["carbon_kg"] == pytest.approx(ev.totals["carbon_kg"])
    assert loaded["baseline"]["metrics"]["n_reassigned"] == 0
    assert loaded["scenario"] == {"name": "small", "I": sc.I, "S": sc.S, "Z": sc.Z,
                                  "T": sc.T, "dt_seconds": 300.0, "zones": [1, 2, 1],
                                  "n_running": 0, "n_unavailable_server_periods": 0,
                                  "CI_mean_g_per_kWh": pytest.approx(sc.CI_g_per_kWh.mean())}
    assert loaded["settings"]["baseline_rule"] == "least_loaded"
    assert loaded["solver"]["status"] == "no_solution" and loaded["solver"]["best_bound_g"] is None
    assert loaded["infeasibility"]["thermal_cap"] is None
    assert loaded["checks"] == {"baseline_matches_reference": True}
    assert "not modelled" in loaded["model_note"]
    assert summary["comparison"]["carbon_kg"]["optimized"] is None
    text = format_summary(summary)
    assert "NO VALID SCHEDULE" in text and "deadlines_and_waiting" in text
    assert "Total carbon" in text

    rows = (out / "baseline" / "schedule.csv").read_text().splitlines()
    assert len(rows) == sc.I + 1 and rows[0].startswith("i,workload_id,type,arrival")
    assert len((out / "baseline" / "server_period.csv").read_text().splitlines()) == sc.S * sc.T + 1
    assert len((out / "baseline" / "zone_period.csv").read_text().splitlines()) == sc.Z * sc.T + 1
    assert "not modelled" in (out / "baseline" / "zone_period.csv").read_text()
    assert len((out / "comparison_period.csv").read_text().splitlines()) == sc.T + 1


def test_report_with_copy_of_baseline_has_zero_differences(tmp_path):
    sc, base, st, ev, orig = _small()
    ev_opt = evaluate(sc, base, constant_supply_temp(sc, 18.0), st)
    out = tmp_path / "run"
    summary = write_results(out, sc, st, orig, base, ev, base, ev_opt, None, None, {})
    for f in TABLES:
        assert (out / "optimized" / f).is_file(), f
    loaded = json.loads((out / "summary.json").read_text())
    assert loaded["has_optimized_schedule"] is True and loaded["solver"] is None
    for key, c in loaded["comparison"].items():
        if c["baseline"] is not None:
            assert c["diff"] == 0, key
            assert c["pct"] in (0, None), key
    assert loaded["comparison"]["n_reassigned"]["optimized"] == 0
    text = format_summary(summary)
    assert "NO VALID SCHEDULE" not in text
    # comparison_period differences are all zero
    lines = (out / "comparison_period.csv").read_text().splitlines()
    header = lines[0].split(",")
    for line in lines[1:]:
        vals = dict(zip(header, line.split(",")))
        assert float(vals["diff_E_total_kWh"]) == 0.0 and float(vals["diff_carbon_g"]) == 0.0


def test_report_counts_reassigned(tmp_path):
    sc, base, st, ev, orig = _small()
    moved = Schedule(tuple(
        Placement(p.i, 1 if p.i == 1 else p.server, p.start, p.end) for p in base.placements))
    orig = {p.i: p.server for p in base.placements}
    ev_m = evaluate(sc, moved, constant_supply_temp(sc, 18.0), st)
    out = tmp_path / "run"
    summary = write_results(out, sc, st, orig, base, ev, moved, ev_m, None, None, {})
    n = 0 if base.placements[0].server == 1 else 1
    assert summary["comparison"]["n_reassigned"]["optimized"] == n
    assert summary["comparison"]["n_reassigned"]["baseline"] == 0
    rows = list(csv.DictReader(open(out / "optimized" / "reassignment.csv")))
    assert len(rows) == sc.I
    assert sum(int(r["reassigned"]) for r in rows) == n
    r1 = rows[0]
    assert int(r1["final_server"]) == 1 and int(r1["original_server"]) == base.placements[0].server
    zone = {sv.s: sv.zone for sv in sc.servers}
    assert int(r1["cross_zone"]) == int(n == 1 and zone[1] != zone[base.placements[0].server])
    assert summary["comparison"]["n_cross_zone"]["optimized"] == int(r1["cross_zone"])
    assert all(r["reason"] == "kept" for r in rows[1:])
    if n:
        assert r1["reason"] and r1["reason"] != "kept"
    assert not (out / "baseline" / "reassignment.csv").exists()


def test_new_compliance_columns(tmp_path):
    sc, base, st, ev, orig = _small()
    st = RunSettings(scenario="small", cold_plates=True)
    ev = evaluate(sc, base, constant_supply_temp(sc, 18.0), st)
    out = tmp_path / "run"
    write_results(out, sc, st, orig, base, ev, None, None, None, None, {})
    srv = list(csv.DictReader(open(out / "baseline" / "compliance_servers.csv")))
    for r, sv in zip(srv, sc.servers):
        k = sv.s - 1
        assert float(r["max_utilization"]) == pytest.approx(ev.util[k].max())
        assert float(r["min_PC_eff_MHz"]) == pytest.approx(ev.PC_eff_MHz[k].min())
        assert int(r["periods_unavailable"]) == 0
    cps = list(csv.DictReader(open(out / "baseline" / "compliance_cold_plates.csv")))
    assert [int(r["s"]) for r in cps] == [sv.s for sv in sc.servers if sv.plates > 0]
    for r in cps:
        assert float(r["coolant_min_C"]) == float(r["coolant_max_C"]) == st.baseline_cp_coolant_C
        assert float(r["flow_min_Lmin"]) == float(r["flow_max_Lmin"]) == st.baseline_cp_flow_Lmin
        assert float(r["coolant_allowed_min_C"]) == 20.0 and float(r["flow_allowed_max_Lmin"]) == 0.35
    wl = list(csv.DictReader(open(out / "baseline" / "compliance_workloads.csv")))
    for r, k in zip(wl, range(sc.I)):
        assert float(r["min_DPF"]) == pytest.approx(ev.min_DPF_run[k])
        assert 0 < float(r["min_DPF"]) <= 1
