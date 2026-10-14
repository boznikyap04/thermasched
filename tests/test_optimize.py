"""Tests of scheduler/optimize.py on small hand-built instances.

Scenario objects are built directly from the dataclasses. The independent evaluator is
used (when present) only as a cross-check of the solver's objective.
"""

from __future__ import annotations

import dataclasses

import numpy as np
import pytest

from scheduler.optimize import diagnose_infeasibility, solve
from scheduler.types import (
    RELAX_CAPACITY, RELAX_COOLING, RELAX_DEADLINES, RELAX_THERMAL, STATUS_INFEASIBLE,
    STATUS_OPTIMAL, Constants, NotDefinedYet, Placement, RunSettings, Scenario, Schedule,
    Server, Workload, cop)

DT = 3600.0           # one-hour periods: kW * 1 period = kWh
F = 2000.0            # MHz
BIG_MEM = 1.0e6


def constants(**kw) -> Constants:
    d = dict(R_dvfs=0.378, F_throttle=0.662, T_max_server_C=90.0, H_min_C=10.0,
             T_dvfs_C=75.0, T_throttle_C=100.0, Q_crac_kW=116.0,
             COP_coeffs=(0.0068, 0.0008, 0.458), T_crac_min_C=18.0, T_crac_max_C=27.0,
             T_max_zone_C=32.0)
    d.update(kw)
    return Constants(**d)


def server(s, zone=1, cores=4, p_idle=100.0, p_max=400.0, T0=30.0, a=0.0, R=0.01,
           alpha=0.5, f=F, plates=0) -> Server:
    return Server(s=s, name=f"srv{s}", zone=zone, f_MHz=f, C_cores=cores, M_MB=BIG_MEM,
                  P_idle_W=p_idle, P_max_W=p_max, T0_C=T0, CT_cold_plate=int(plates > 0),
                  th_a_C=a, th_R_C_per_W=R, th_alpha=alpha, n_cold_plates=plates)


def work(i, A, D, AD, cores, n_periods, B=0, f=F) -> Workload:
    """A workload needing ``n_periods`` full-speed periods of its own cores on a server of
    frequency f."""
    return Workload(i=i, workload_id=f"w{i}", flavor="x", A=A, D=D, AD=AD,
                    ET_base=n_periods, RT=0, B=B, X0=None, C_req=cores, M_req_MB=1.0,
                    W_MHz_s=cores * f * DT * n_periods)


def scenario(workloads, servers, CI, consts=None, n_zones=None) -> Scenario:
    CI = np.asarray(CI, dtype=float)
    return Scenario(name="t", T=len(CI), dt_seconds=DT, workloads=tuple(workloads),
                    servers=tuple(servers),
                    n_zones=n_zones or max(sv.zone for sv in servers),
                    CI_g_per_kWh=CI, constants=consts or constants())


def settings(**kw) -> RunSettings:
    d = dict(supply_temp_mode="fixed", fixed_supply_temp_C=20.0, time_limit_s=60.0,
             mip_rel_gap=1e-9)
    d.update(kw)
    return RunSettings(**d)


def placements(res):
    return {p.i: (p.server, p.start, p.end) for p in res.schedule.placements}


def evaluate_or_skip(sc, res, st):
    ev = pytest.importorskip("scheduler.evaluate")
    return ev.evaluate(sc, res.schedule, res.supply_temp_C, st, res.cold_plate_ops)


# ---------------------------------------------------------------------------
# Hand-checkable instance
# ---------------------------------------------------------------------------
#
# Periods t = 1..4 of one hour, CI = [400, 100, 50, 80] g/kWh. Constant COP = 2 (so the
# CRAC adds heat / 2 and every kWh of IT costs 1.5 kWh in total), supply fixed at 20 degC.
# Two servers in one zone, 4 cores each, P_idle = 100 W:
#   server 1 is efficient   P_max = 200 W -> 25 W per busy core
#   server 2 is inefficient P_max = 400 W -> 75 W per busy core (3 times as much)
# Workloads (all need whole periods at full speed, DPF stays 1: temperatures are ~25 degC):
#   w1: 2 cores, 1 period,  may start in 1..4
#   w2: 2 cores, 2 periods, may start in 1..3 (finish by 5)
#   w3: 4 cores, 1 period,  must run exactly in period 3 (A=3, D=4, AD=0)
# Both servers draw idle power throughout: 200 W for 4 h -> 0.2 kWh per hour.
#   idle carbon = 0.2 kWh * 1.5 * (400+100+50+80) = 0.3 * 630 = 189 g
# Active carbon = 0.0375 kWh per core-period on server 1 (25 W * 1 h * 1.5) and 0.1125 on
# server 2, times CI. Candidate plans, in "core-period * CI" units at server-1 prices:
#   w3 on server 1 in t=3 (4*50 = 200) takes the whole server in the cheapest hour, so w1, w2
#   go elsewhere/later: best is w2 on server 2 in 3,4 (3*2*(50+80) = 780) and w1 on server 1
#   in 4 (2*80 = 160): 1140.
#   w3 on server 2 in t=3 costs 3*4*50 = 600 but frees server 1 in t=3 and 4: w2 on server 1
#   in 3,4 (2*(50+80) = 260) and w1 on server 1 in 3 (2*50 = 100), 4 cores used in t=3.
#   Total 600 + 260 + 100 = 960 (units at server-1 price, 600 already includes the 3x).
# 960 < 1140 < the rest (w2 on server 1 in 1,2 = 1000 alone), so the optimum is plan two:
#   w1 -> server 1, start 3, end 4;  w2 -> server 1, start 3, end 5;  w3 -> server 2, 3..4
#   active carbon = 960 * 0.0375 = 36 g;  total = 189 + 36 = 225 g.
HAND_CI = [400.0, 100.0, 50.0, 80.0]
HAND_EXPECTED_G = 189.0 + 0.0375 * (600 + 260 + 100)


def hand_scenario(servers=None, workloads=None):
    cs = constants(COP_coeffs=(0.0, 0.0, 2.0))
    servers = servers or [server(1, p_max=200.0), server(2, p_max=400.0)]
    workloads = workloads or [work(1, 1, 5, 3, 2, 1), work(2, 1, 5, 2, 2, 2),
                              work(3, 3, 4, 0, 4, 1)]
    return scenario(workloads, servers, HAND_CI, cs)


def test_hand_checked_optimum():
    sc = hand_scenario()
    st = settings()
    res = solve(sc, {1: 1, 2: 1, 3: 1}, st)
    assert res.status == STATUS_OPTIMAL
    assert placements(res) == {1: (1, 3, 4), 2: (1, 3, 5), 3: (2, 3, 4)}
    assert HAND_EXPECTED_G == pytest.approx(225.0)
    assert res.objective_g == pytest.approx(HAND_EXPECTED_G, rel=1e-6)
    assert np.all(res.supply_temp_C == 20.0)
    assert res.n_variables > 0 and res.n_binaries > 0 and res.n_constraints > 0
    # the evaluator (if present) agrees, and the schedule is valid
    try:
        ev = evaluate_or_skip(sc, res, st)
    except pytest.skip.Exception:
        return
    assert ev.total_carbon_g == pytest.approx(res.objective_g, rel=1e-6)
    assert ev.valid


# ---------------------------------------------------------------------------
# Reassignment modes
# ---------------------------------------------------------------------------

def three_server_scenario(B1=0):
    """Servers 1, 2 in zone 1 (2 is dearer), server 3 in zone 2 (cheapest)."""
    cs = constants(COP_coeffs=(0.0, 0.0, 2.0))
    servers = [server(1, zone=1, p_max=300.0), server(2, zone=1, p_max=400.0),
               server(3, zone=2, p_max=200.0)]
    ws = [work(1, 1, 5, 3, 2, 1, B=B1), work(2, 1, 5, 2, 2, 2), work(3, 3, 4, 0, 4, 1)]
    return scenario(ws, servers, HAND_CI, cs)


def test_reassignment_none_keeps_every_server():
    sc = three_server_scenario()
    orig = {1: 2, 2: 1, 3: 2}
    res = solve(sc, orig, settings(reassignment="none"))
    assert res.status == STATUS_OPTIMAL
    assert {i: p[0] for i, p in placements(res).items()} == orig


def test_reassignment_same_zone_keeps_zone():
    sc = three_server_scenario()
    orig = {1: 2, 2: 1, 3: 3}                 # zones 1, 1, 2
    res = solve(sc, orig, settings(reassignment="same_zone"))
    assert res.status == STATUS_OPTIMAL
    zone = {sv.s: sv.zone for sv in sc.servers}
    for i, (s, _, _) in placements(res).items():
        assert zone[s] == zone[orig[i]]
    assert placements(res)[3][0] == 3         # only server in its zone
    # the cheapest server of zone 1 is server 1: w1 (original 2) moves there
    assert placements(res)[1][0] == 1


def test_free_moves_to_cheapest_and_B1_pins():
    sc = three_server_scenario()
    orig = {1: 2, 2: 2, 3: 2}
    free = solve(sc, orig, settings(reassignment="free"))
    assert free.status == STATUS_OPTIMAL
    assert any(s != 2 for s, _, _ in placements(free).values())
    pinned_sc = three_server_scenario(B1=1)
    pinned = solve(pinned_sc, orig, settings(reassignment="free"))
    assert pinned.status == STATUS_OPTIMAL
    assert placements(pinned)[1][0] == orig[1] == 2           # B = 1 stays put
    assert pinned.objective_g >= free.objective_g - 1e-6


# ---------------------------------------------------------------------------
# Supply temperature
# ---------------------------------------------------------------------------

def test_fixed_supply_is_constant_and_checked():
    sc = hand_scenario()
    res = solve(sc, {1: 1, 2: 1, 3: 1}, settings(fixed_supply_temp_C=22.5))
    assert res.status == STATUS_OPTIMAL
    assert res.supply_temp_C.shape == (1, 4)
    assert np.all(res.supply_temp_C == 22.5)
    with pytest.raises(ValueError, match="CRAC range"):
        solve(sc, {1: 1, 2: 1, 3: 1}, settings(fixed_supply_temp_C=30.0))
    with pytest.raises(ValueError, match="CRAC range"):
        solve(sc, {1: 1, 2: 1, 3: 1}, settings(fixed_supply_temp_C=10.0))
    sc_zone = dataclasses.replace(sc, constants=constants(T_crac_max_C=40.0, T_max_zone_C=32.0,
                                                          COP_coeffs=(0.0, 0.0, 2.0)))
    with pytest.raises(ValueError, match="zone limit"):
        solve(sc_zone, {1: 1, 2: 1, 3: 1}, settings(fixed_supply_temp_C=35.0))


def thermal_scenario(R2=None):
    """Heavy 4-core workload that runs exactly in periods 2..5 of 6 (alpha = 0, so
    T = Tsup + R * P_IT). With H_min = 25 the cap is 65 degC (no derating below it).
    Server 1: R = 0.1125 -> 45 degC above supply at 400 W, so supply <= 20 while loaded."""
    servers = [server(1, R=0.1125, alpha=0.0, T0=30.0)]
    if R2 is not None:
        servers.append(server(2, R=R2, alpha=0.0, T0=30.0))
    ws = [work(1, 2, 6, 0, 4, 4)]
    return scenario(ws, servers, [100.0] * 6)


def test_thermal_cap_forces_lower_supply_and_ramp_binds():
    sc = thermal_scenario()
    st = settings(supply_temp_mode="optimize", fixed_supply_temp_C=None, H_min_C=25.0)
    res = solve(sc, {1: 1}, st)
    assert res.status == STATUS_OPTIMAL
    assert placements(res)[1] == (1, 2, 6)
    sup = res.supply_temp_C[0]
    assert np.all(sup == np.round(sup)) and np.all((sup >= 18) & (sup <= 27))
    # loaded periods 2..5 are held to 20 degC by the cap (T = Tsup + 45 + ... <= 65); the idle
    # periods 1 and 6 would like 27 but the 5 degC / 3 period ramp limits them to 25
    assert sup.tolist() == [25.0, 20.0, 20.0, 20.0, 20.0, 25.0]
    for t in range(3, 6):
        assert abs(sup[t] - sup[t - 3]) <= 5 + 1e-9
    assert np.all(res.model_values["T_C"] <= 65.0 + 1e-6)
    ev = pytest.importorskip("scheduler.evaluate")
    e = ev.evaluate(sc, res.schedule, res.supply_temp_C, st)
    assert e.total_carbon_g == pytest.approx(res.objective_g, rel=1e-6)
    assert e.valid


def test_thermal_cap_prefers_cool_placement():
    sc = thermal_scenario(R2=0.025)          # server 2 is 10 degC above supply at 400 W
    st = settings(supply_temp_mode="optimize", fixed_supply_temp_C=None, H_min_C=25.0,
                  reassignment="free")
    res = solve(sc, {1: 1}, st)
    assert res.status == STATUS_OPTIMAL
    assert placements(res)[1][0] == 2
    assert np.all(res.supply_temp_C == 27.0)
    pinned = solve(sc, {1: 1}, dataclasses.replace(st, reassignment="none"))
    assert pinned.objective_g > res.objective_g


@pytest.mark.parametrize("R, expected_periods", [(0.145, 5), (0.10, 4)])
def test_derating_lengthens_run(R, expected_periods):
    """Supply 20 degC, alpha = 0: T = 20 + R * 400 under load. R = 0.145 gives 78 degC,
    DPF = 1 - 0.378 * (78 - 75) / 25 = 0.9546, so 4 periods of work take 5 periods
    (4 * 0.9546 = 3.82 < 4 <= 5 * 0.9546). R = 0.10 gives 60 degC, DPF = 1, 4 periods."""
    servers = [server(1, R=R, alpha=0.0, T0=30.0)]
    ws = [work(1, 2, 9, 3, 4, 4)]
    sc = scenario(ws, servers, [100, 90, 80, 70, 60, 50, 40, 30])
    st = settings()
    res = solve(sc, {1: 1}, st)
    assert res.status == STATUS_OPTIMAL
    s, start, end = placements(res)[1]
    assert end - start == expected_periods
    n_min = 4                                  # W / (C_req * f * dt)
    assert end - start - n_min == (1 if R == 0.145 else 0)    # one tail period is used when derated
    if R == 0.145:
        assert res.model_values["T_C"][0, start - 1] == pytest.approx(78.0, abs=1e-6)
        assert np.all(res.model_values["DPF"][0, start - 1:end - 1] <= 0.95464 + 1e-6)
    ev = pytest.importorskip("scheduler.evaluate")
    e = ev.evaluate(sc, res.schedule, res.supply_temp_C, st)
    assert e.valid and e.total_carbon_g == pytest.approx(res.objective_g, rel=1e-6)


def test_no_room_for_tail_is_infeasible_when_derated():
    """Regression: with DPF < 1 the n_min core periods are not enough, so a window of exactly
    n_min periods is infeasible (the tail has no room), and widening the deadline fixes it."""
    servers = [server(1, R=0.145, alpha=0.0, T0=30.0)]
    sc = scenario([work(1, 2, 6, 0, 4, 4)], servers, [100.0] * 8)    # window 2..5, n_min = 4
    st = settings()
    assert solve(sc, {1: 1}, st).status == STATUS_INFEASIBLE
    assert diagnose_infeasibility(sc, {1: 1}, st, time_limit_s=20)[RELAX_DEADLINES] == "feasible"


def test_cap_above_throttle_is_rejected():
    sc = hand_scenario()
    with pytest.raises(ValueError, match="T_throttle"):
        solve(sc, {1: 1, 2: 1, 3: 1}, settings(H_min_C=-20.0))


# ---------------------------------------------------------------------------
# Infeasibility and diagnosis
# ---------------------------------------------------------------------------

def feasible_only_when(family):
    return {f: ("feasible" if f == family else "infeasible")
            for f in (RELAX_DEADLINES, RELAX_THERMAL, RELAX_CAPACITY, RELAX_COOLING)}


def test_infeasible_only_because_of_deadline():
    # needs 3 periods but the window A=1..D=3 is 2 periods long; horizon is 6
    sc = scenario([work(1, 1, 3, 0, 2, 3)], [server(1)], [100.0] * 6)
    st = settings()
    res = solve(sc, {1: 1}, st)
    assert res.status == STATUS_INFEASIBLE
    assert res.schedule is None and res.supply_temp_C is None
    assert diagnose_infeasibility(sc, {1: 1}, st, time_limit_s=20) == \
        feasible_only_when(RELAX_DEADLINES)
    relaxed = solve(sc, {1: 1}, st, relax=(RELAX_DEADLINES,))
    assert relaxed.status == STATUS_OPTIMAL and relaxed.relaxed == (RELAX_DEADLINES,)


def test_infeasible_only_because_of_cpu_capacity():
    # two 4-core workloads, one 4-core server, both pinned to periods 1-2; the horizon is 2
    # periods, so widening the windows cannot help
    ws = [work(1, 1, 3, 0, 4, 2), work(2, 1, 3, 0, 4, 2)]
    sc = scenario(ws, [server(1)], [100.0, 100.0])
    st = settings()
    res = solve(sc, {1: 1, 2: 1}, st)
    assert res.status == STATUS_INFEASIBLE
    assert diagnose_infeasibility(sc, {1: 1, 2: 1}, st, time_limit_s=20) == \
        feasible_only_when(RELAX_CAPACITY)


def test_infeasible_only_because_of_thermal_cap():
    # a = 70: even idle at 18 degC supply gives 18 + 70 + 1 = 89 > 80; the throttle limit of
    # 100 is enough
    sc = scenario([work(1, 1, 4, 2, 1, 1)], [server(1, a=70.0, R=0.01, alpha=0.0)],
                  [100.0] * 3)
    st = settings()
    res = solve(sc, {1: 1}, st)
    assert res.status == STATUS_INFEASIBLE
    assert diagnose_infeasibility(sc, {1: 1}, st, time_limit_s=20) == \
        feasible_only_when(RELAX_THERMAL)


def test_infeasible_only_because_of_cooling_capacity():
    # idle heat 0.1 kW exceeds a 0.05 kW CRAC
    sc = scenario([work(1, 1, 4, 2, 1, 1)], [server(1)], [100.0] * 3,
                  constants(Q_crac_kW=0.05))
    st = settings()
    res = solve(sc, {1: 1}, st)
    assert res.status == STATUS_INFEASIBLE
    assert diagnose_infeasibility(sc, {1: 1}, st, time_limit_s=20) == \
        feasible_only_when(RELAX_COOLING)


# ---------------------------------------------------------------------------
# Switches that are not defined yet
# ---------------------------------------------------------------------------

def test_not_defined_yet():
    sc = hand_scenario()
    st = settings(fan_power=True)
    with pytest.raises(NotDefinedYet):
        solve(sc, {1: 1, 2: 1, 3: 1}, st)
    with pytest.raises(NotDefinedYet):
        diagnose_infeasibility(sc, {1: 1, 2: 1, 3: 1}, st)


# ---------------------------------------------------------------------------
# Warm start
# ---------------------------------------------------------------------------

def test_warm_start_is_accepted_and_not_worse():
    sc = hand_scenario()
    st = settings()
    # feasible but poor: everything on the dear server 2 at the hour the workload may start
    warm = Schedule(placements=(Placement(1, 2, 1, 2), Placement(2, 2, 1, 3),
                                Placement(3, 2, 3, 4)))
    warm_supply = np.full((1, 4), 20.0)
    cold = solve(sc, {1: 1, 2: 1, 3: 1}, st)
    res = solve(sc, {1: 1, 2: 1, 3: 1}, st, warm_start=warm,
                warm_start_supply_temp_C=warm_supply)
    assert res.status == STATUS_OPTIMAL
    assert res.model_values["warm_start_columns_set"] > 0
    log = res.model_values["warm_start_log"].lower()
    assert "mip start" in log and "infeasible" not in log
    assert res.objective_g <= cold.objective_g + 1e-6
    # a start that cannot be expressed (start outside the window) is skipped, not an error
    bad = Schedule(placements=(Placement(1, 1, 1, 2), Placement(2, 1, 4, 6),
                               Placement(3, 2, 3, 4)))
    res2 = solve(sc, {1: 1, 2: 1, 3: 1}, st, warm_start=bad)
    assert res2.status == STATUS_OPTIMAL
    assert res2.objective_g == pytest.approx(res.objective_g, rel=1e-6)


def test_warm_start_in_optimize_mode_with_whole_degree_supply():
    sc = hand_scenario()
    st = settings(supply_temp_mode="optimize", fixed_supply_temp_C=None)
    warm = Schedule(placements=(Placement(1, 2, 1, 2), Placement(2, 2, 1, 3),
                                Placement(3, 2, 3, 4)))
    res = solve(sc, {1: 1, 2: 1, 3: 1}, st, warm_start=warm,
                warm_start_supply_temp_C=np.full((1, 4), 18.0))
    assert res.status == STATUS_OPTIMAL
    assert res.model_values["warm_start_columns_set"] > 0
    assert np.all(res.supply_temp_C == np.round(res.supply_temp_C))
    # constant COP: the supply level does not change the objective
    assert res.objective_g == pytest.approx(HAND_EXPECTED_G, rel=1e-6)


# ---------------------------------------------------------------------------
# Cross-check against the evaluator on the 'small' scenario
# ---------------------------------------------------------------------------

def load_small():
    io = pytest.importorskip("scheduler.io")
    pytest.importorskip("scheduler.evaluate")
    sc = io.load_scenario("small", scenarios_dir="scenarios")
    base = io.load_reference_baseline("small")
    return sc, base, {p.i: p.server for p in base.placements}


def test_small_none_fixed18_matches_evaluator():
    from scheduler.evaluate import evaluate
    sc, base, orig = load_small()
    st = RunSettings(scenario="small", reassignment="none", supply_temp_mode="fixed",
                     fixed_supply_temp_C=18.0, time_limit_s=60.0)
    res = solve(sc, orig, st, warm_start=base,
                warm_start_supply_temp_C=np.full((sc.Z, sc.T), 18.0))
    assert res.status in (STATUS_OPTIMAL, "time_limit")
    ev = evaluate(sc, res.schedule, res.supply_temp_C, st)
    assert ev.total_carbon_g == pytest.approx(res.objective_g, rel=1e-6)
    assert ev.valid
    base_g = evaluate(sc, base, np.full((sc.Z, sc.T), 18.0), st).total_carbon_g
    assert res.objective_g <= base_g * (1 + 1e-9)      # the baseline is a feasible start


def test_small_free_optimize_matches_evaluator_and_beats_baseline():
    from scheduler.evaluate import evaluate
    sc, base, orig = load_small()
    st = RunSettings(scenario="small", reassignment="free", supply_temp_mode="optimize",
                     time_limit_s=40.0)
    res = solve(sc, orig, st, warm_start=base,
                warm_start_supply_temp_C=np.full((sc.Z, sc.T), 18.0))
    assert res.schedule is not None
    ev = evaluate(sc, res.schedule, res.supply_temp_C, st)
    assert ev.total_carbon_g == pytest.approx(res.objective_g, rel=1e-6)
    assert ev.valid
    base_g = evaluate(sc, base, np.full((sc.Z, sc.T), 18.0), st).total_carbon_g
    assert res.objective_g <= base_g * (1 + 1e-9)
    sup = res.supply_temp_C
    assert np.all(sup == np.round(sup)) and sup.min() >= 18 and sup.max() <= 27
    assert np.abs(sup[:, 3:] - sup[:, :-3]).max() <= 5 + 1e-9
    assert cop(sc.constants, 18.0) > 0


# ---------------------------------------------------------------------------
# Cold plates
# ---------------------------------------------------------------------------
#
# Two identical hot servers (a = 40 degC, so T is about 60 degC); only server 2 has a cold
# plate. Run on server 2, a 2-core workload draws 250 W, all of which the plate can take
# (250 W < 300 W and 12.6 W/C * (60 - 20) C), so it costs no CRAC energy there.

def cold_plate_scenario(plates2=1):
    servers = [server(1, T0=60.0, a=40.0), server(2, T0=60.0, a=40.0, plates=plates2)]
    return scenario([work(1, 1, 4, 2, 2, 1), work(2, 2, 4, 1, 2, 1)], servers,
                    [300.0, 300.0, 300.0], constants(COP_coeffs=(0.0, 0.0, 2.0)))


def test_cold_plates_move_work_and_match_the_evaluator():
    sc = cold_plate_scenario()
    st = settings(cold_plates=True)
    res = solve(sc, {1: 1, 2: 1}, st)
    assert res.status == STATUS_OPTIMAL
    assert {i: p[0] for i, p in placements(res).items()} == {1: 2, 2: 2}
    ops = res.cold_plate_ops
    assert np.isnan(ops.flow_Lmin[0]).all() and np.isfinite(ops.flow_Lmin[1]).all()
    assert np.all((ops.coolant_C[1] >= 20.0) & (ops.coolant_C[1] <= 39.95))
    ev = evaluate_or_skip(sc, res, st)
    assert ev.valid
    assert ev.total_carbon_g == pytest.approx(res.objective_g, rel=1e-6)
    np.testing.assert_allclose(ev.Q_cp_W[1], ev.P_IT_W[1])       # the plate takes all the heat
    np.testing.assert_allclose(res.model_values["Q_cp_W"], ev.Q_cp_W, atol=1e-6)
    off = solve(sc, {1: 1, 2: 1}, settings())
    assert res.objective_g < off.objective_g


def test_cold_plate_count_zero_matches_off():
    sc = cold_plate_scenario()
    off = solve(sc, {1: 1, 2: 1}, settings())
    zero = solve(sc, {1: 1, 2: 1}, settings(cold_plates=True, cold_plate_count=0))
    assert zero.objective_g == pytest.approx(off.objective_g, rel=1e-9)
    assert zero.cold_plate_ops is None


def test_two_plates_take_more_heat():
    """At 0.5 kW load the limit is 0.3 kW per plate: two plates remove 0.5 kW, one only 0.3."""
    sc = scenario([work(1, 1, 2, 0, 4, 1)],
                  [server(1, p_idle=100.0, p_max=500.0, T0=70.0, a=50.0, plates=1)],
                  [300.0], constants(COP_coeffs=(0.0, 0.0, 2.0)))
    one = solve(sc, {1: 1}, settings(cold_plates=True))
    two = solve(sc, {1: 1}, settings(cold_plates=True, cold_plate_count=2))
    assert one.model_values["Q_cp_W"][0, 0] == pytest.approx(300.0)
    assert two.model_values["Q_cp_W"][0, 0] == pytest.approx(500.0)
    assert two.objective_g < one.objective_g
