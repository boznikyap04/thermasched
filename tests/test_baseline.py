import numpy as np
import pytest

from scheduler.baseline import build_baseline, periods_needed
from scheduler.io import load_reference_baseline, load_scenario
from scheduler.types import Constants, RunSettings, Scenario, Server, Workload

SCENARIOS = ("small", "servers6_light", "servers6", "servers6_heavy")


def cpu_usage(sc, sched):
    """cores in use, shape (S, T), recomputed independently from the schedule."""
    used = np.zeros((sc.S, sc.T), dtype=int)
    for p in sched.placements:
        if p.server is None:
            continue
        assert 1 <= p.start < p.end <= sc.T + 1
        used[p.server - 1, p.start - 1:p.end - 1] += sc.workloads[p.i - 1].C_req
    return used


def assert_capacity(sc, sched):
    used = cpu_usage(sc, sched)
    cap = np.array([sv.C_cores for sv in sc.servers])[:, None]
    assert (used <= cap).all()


def tiny_scenario(servers, workloads, T=20):
    consts = Constants(0.378, 0.662, 90.0, 10.0, 75.0, 100.0, 116.0,
                       (0.0068, 0.0008, 0.458), 18.0, 27.0, 32.0)
    return Scenario("tiny", T, 300.0, tuple(workloads), tuple(servers), 1,
                    np.full(T, 400.0), consts)


def srv(s, f, cores):
    return Server(s, f"srv{s}", 1, f, cores, 1e6, 100.0, 300.0, 50.0, 0, 0.0, 0.1, 0.9)


def wl(i, A, C, periods, f_ref, T_dt=300.0):
    # work sized so that it takes exactly `periods` periods at f_ref
    return Workload(i, f"w{i}", "x", A, 100, 50, periods, 0, 0, None, C, 1024.0,
                    C * f_ref * T_dt * (periods - 0.5))


@pytest.mark.parametrize("name", SCENARIOS)
def test_least_loaded_reproduces_reference(name):
    sc = load_scenario(name)
    ref = load_reference_baseline(name)
    got = build_baseline(sc, RunSettings(scenario=name, baseline_rule="least_loaded"))
    assert len(got.placements) == sc.I == len(ref.placements)
    for g, r in zip(got.placements, ref.placements):
        assert (g.i, g.server, g.start, g.end) == (r.i, r.server, r.start, r.end)
    assert [sc.workloads[p.i - 1].X0 for p in got.placements] == [p.server for p in got.placements]
    assert_capacity(sc, got)


def test_loader_small():
    sc = load_scenario("small")
    assert (sc.I, sc.S, sc.Z, sc.T, sc.dt_seconds) == (158, 3, 2, 96, 300)
    assert sc.CI_g_per_kWh.shape == (96,)
    assert sc.CI_g_per_kWh[0] == pytest.approx(488.67)
    assert sc.constants.Q_crac_kW == 116
    assert sc.constants.COP_coeffs == (0.0068, 0.0008, 0.458)
    assert sc.constants.T_max_zone_C == 32.0
    s1 = sc.servers[0]
    assert (s1.s, s1.name, s1.zone, s1.f_MHz, s1.C_cores) == (1, "qh2-rcc145", 1, 2100.0, 64)
    assert s1.th_alpha == pytest.approx(0.90185)
    w1 = sc.workloads[0]
    assert (w1.i, w1.workload_id, w1.A, w1.D, w1.AD, w1.C_req, w1.X0) == (1, "w0088", 3, 43, 8, 2, 1)
    assert [w.i for w in sc.workloads] == list(range(1, 159))


def test_loader_validation(tmp_path):
    import shutil
    from scheduler.io import load_scenario as load
    shutil.copytree("scenarios/small", tmp_path / "bad")
    carbon = tmp_path / "bad" / "carbon.csv"
    lines = carbon.read_text().splitlines()
    carbon.write_text("\n".join(lines[:-1]) + "\n")
    with pytest.raises(ValueError, match="rows"):
        load("bad", tmp_path)


def test_fastest_first_capacity_and_real_data():
    for name in SCENARIOS:
        sc = load_scenario(name)
        sched = build_baseline(sc, RunSettings(scenario=name, baseline_rule="fastest_first"))
        assert_capacity(sc, sched)


def test_fastest_first_hand_made():
    # s1 slow, s2 fast (4 cores), s3 fast (4 cores, tie -> lowest s = 2 first)
    servers = [srv(1, 2000.0, 4), srv(2, 3000.0, 4), srv(3, 3000.0, 4)]
    wls = [wl(1, 1, 2, 3, 3000.0), wl(2, 1, 2, 3, 3000.0),
           wl(3, 1, 2, 3, 3000.0), wl(4, 1, 2, 3, 3000.0),
           wl(5, 1, 2, 3, 3000.0), wl(6, 1, 2, 3, 3000.0),
           wl(7, 1, 2, 3, 3000.0)]
    sc = tiny_scenario(servers, wls)
    sched = build_baseline(sc, RunSettings(baseline_rule="fastest_first"))
    # two per server fill 4 cores: s2, s2, s3, s3, then slow s1, s1, then no room at start 1
    assert [p.server for p in sched.placements[:6]] == [2, 2, 3, 3, 1, 1]
    assert all(p.start == 1 for p in sched.placements[:6])
    # 7th: all full at start 1 -> earliest later start with room (after the 3-period runs
    # on s1 the run is longer: ceil(2.5 * 3000/2000) = 4 periods; on s2/s3 it is 3)
    p7 = sched.placements[6]
    assert p7.server == 2 and p7.start == 4 and p7.end == 7
    assert_capacity(sc, sched)


def test_least_loaded_hand_made_tie_and_balance():
    servers = [srv(1, 2000.0, 4), srv(2, 3000.0, 4)]
    wls = [wl(1, 1, 2, 3, 2000.0), wl(2, 1, 2, 3, 2000.0), wl(3, 1, 2, 3, 2000.0)]
    sc = tiny_scenario(servers, wls)
    sched = build_baseline(sc, RunSettings(baseline_rule="least_loaded"))
    # tie at 0 cores -> s1; then s2 is less loaded; then tie 2/2 -> s1
    assert [p.server for p in sched.placements] == [1, 2, 1]


def test_random_seed_behaviour():
    sc = load_scenario("small")
    a = build_baseline(sc, RunSettings(baseline_rule="random", seed=1))
    b = build_baseline(sc, RunSettings(baseline_rule="random", seed=1))
    c = build_baseline(sc, RunSettings(baseline_rule="random", seed=2))
    assert a == b
    assert a != c
    assert_capacity(sc, a)
    assert_capacity(sc, c)


def test_unplaceable_workload_is_none():
    servers = [srv(1, 2000.0, 4), srv(2, 3000.0, 4)]
    wls = [wl(1, 1, 8, 3, 2000.0), wl(2, 1, 2, 3, 2000.0)]
    sc = tiny_scenario(servers, wls)
    for rule in ("least_loaded", "fastest_first", "random"):
        sched = build_baseline(sc, RunSettings(baseline_rule=rule))
        p = sched.placements[0]
        assert (p.i, p.server, p.start, p.end) == (1, None, None, None)
        assert sched.placements[1].server is not None


def test_run_must_fit_in_horizon():
    servers = [srv(1, 2000.0, 4)]
    # arrives in the last period but needs 3 periods
    sc = tiny_scenario(servers, [wl(1, 20, 2, 3, 2000.0)], T=20)
    p = build_baseline(sc, RunSettings()).placements[0]
    assert p.server is None


def test_periods_needed():
    s = srv(1, 2000.0, 4)
    w = wl(1, 1, 2, 3, 2000.0)  # 2.5 periods at 2000 MHz
    assert periods_needed(w, s, 300.0) == 3
