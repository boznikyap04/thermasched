"""Per-tick re-planning (scheduler/pertick.py) on `small`.

One unbroken run is shared by the tests that only read it; the resume test runs the same
command again, stopped twice on the way.
"""

from __future__ import annotations

import csv
import dataclasses
import json

import numpy as np
import pytest

from scheduler import experiments as ex
from scheduler.baseline import build_baseline
from scheduler.evaluate import evaluate
from scheduler.io import apply_overrides, load_scenario
from scheduler.optimize import WindowExtras, solve
from scheduler.pertick import (
    CHECKPOINT_DIR, OUTCOME_DONE, OUTCOME_STOPPED, OUTCOME_STUCK, TICK_COLUMNS, TICKS_FILE,
    run_per_tick,
)
from scheduler.run import main, parse_args
from scheduler.types import (
    RELAX_DEADLINES, RELAX_THERMAL, Constants, RunSettings, Scenario, Server,
)

ARGS = ["--scenario", "small", "--per-tick"]


def _setup(argv):
    st, _ = parse_args(argv)
    sc = apply_overrides(load_scenario(st.scenario), st)
    return st, sc, build_baseline(sc, st).server_of()


@pytest.fixture(scope="module")
def unbroken(tmp_path_factory):
    """An unbroken per-tick run on small, with every tick's kept starts recorded."""
    st, sc, original = _setup(ARGS)
    snaps = []

    def on_tick(t, tick, res, state):
        snaps.append((t, dict(state.server), dict(state.start), list(tick.waiting),
                      list(tick.running)))

    out = run_per_tick(sc, original, st, tmp_path_factory.mktemp("unbroken") / "run",
                       on_tick=on_tick)
    assert out.status == OUTCOME_DONE
    return sc, st, out, snaps


def test_evaluator_accepts_the_per_tick_schedule(unbroken):
    sc, st, out, _ = unbroken
    ev = evaluate(sc, out.schedule, out.supply_temp_C, st, out.cold_plate_ops)
    assert ev.valid, ev.compliance["violations"]
    for flag in ("cpu_ok", "mem_ok", "thermal_cap_ok", "workloads_ok", "ramp_ok",
                 "crac_capacity_ok", "priority_ok", "availability_ok"):
        assert ev.compliance[flag], flag
    assert ev.on_time.all() and ev.work_complete.all()
    # the solver's own carbon for each kept period adds up to the evaluator's
    assert out.result.objective_g == pytest.approx(ev.total_carbon_g, rel=1e-6)


def test_no_start_before_arrival_and_started_workloads_never_move(unbroken):
    sc, _, out, snaps = unbroken
    assert len(snaps) == sc.T
    first_seen: dict[int, tuple[int, int, int]] = {}
    for t, server, start, waiting, running in snaps:
        for i in waiting:
            assert sc.workloads[i - 1].A <= t          # only arrived workloads are seen
        for i, s in server.items():
            if i not in first_seen:
                assert start[i] == t                    # started in the tick that kept it
                first_seen[i] = (s, start[i], t)
            assert (s, start[i]) == first_seen[i][:2]   # never moved in a later tick
        for i in running:
            assert i in first_seen and first_seen[i][2] < t
    for p in out.schedule.placements:
        assert p.start >= sc.workloads[p.i - 1].A
        assert (p.server, p.start) == first_seen[p.i][:2]


def test_ramp_limits_hold_across_tick_boundaries(unbroken):
    sc, _, out, _ = unbroken
    c = sc.constants
    sup = out.supply_temp_C
    for lag, lim in ((c.ramp_short_lag, c.ramp_short_C), (c.ramp_long_lag, c.ramp_long_C)):
        assert np.abs(sup[:, lag:] - sup[:, :-lag]).max() <= lim + 1e-9


def _ramp_scenario(T=8) -> Scenario:
    consts = Constants(R_dvfs=0.378, F_throttle=0.662, T_max_server_C=90.0, H_min_C=10.0,
                       T_dvfs_C=75.0, T_throttle_C=100.0, Q_crac_kW=116.0,
                       COP_coeffs=(0.0068, 0.0008, 0.458), T_crac_min_C=18.0,
                       T_crac_max_C=27.0, T_max_zone_C=32.0)
    sv = Server(s=1, name="s", zone=1, f_MHz=2000.0, C_cores=4, M_MB=1e6, P_idle_W=100.0,
                P_max_W=400.0, T0_C=30.0, CT_cold_plate=0, th_a_C=0.0, th_R_C_per_W=0.01,
                th_alpha=0.5)
    return Scenario(name="ramp", T=T, dt_seconds=300.0, workloads=(), servers=(sv,), n_zones=1,
                    CI_g_per_kWh=np.full(T, 100.0), constants=consts)


def test_supply_history_bounds_the_window_start():
    """The window's first periods keep within the ramp of the supply before it: from 18 C
    the supply may rise 5 C per 15 minutes, while with no history it goes straight to the
    cheapest 27 C."""
    sc = _ramp_scenario()
    st = RunSettings(time_limit_s=30.0, mip_rel_gap=1e-9)
    free = solve(sc, {}, st)
    assert (free.supply_temp_C == 27.0).all()
    hist = np.full((1, 12), 18.0)
    held = solve(sc, {}, st, extras=WindowExtras(supply_history=hist))
    assert list(held.supply_temp_C[0]) == [23.0, 23.0, 23.0] + [27.0] * 5
    hist[0, -1] = 27.0   # only the period right before was 27: lag 3 still sees 18 for t = 1, 2
    held = solve(sc, {}, st, extras=WindowExtras(supply_history=hist))
    assert list(held.supply_temp_C[0]) == [23.0, 23.0] + [27.0] * 6


def test_stopped_and_resumed_run_matches_the_unbroken_run(unbroken, tmp_path):
    sc, _, out, _ = unbroken
    argv = ARGS + ["--results-dir", str(tmp_path)]
    st, sc2, original = _setup(argv)
    folder = tmp_path / "small" / st.run_name
    assert st.run_name.endswith("_pertick")

    # stopped by the wall-time limit after its first tick; a summary left by an earlier run
    # of this name goes, so the stopped run does not look finished
    folder.mkdir(parents=True)
    (folder / "summary.json").write_text("{}")
    assert main(argv + ["--wall-time-limit", "0"]) == 3
    assert (folder / CHECKPOINT_DIR / "state.json").is_file()
    assert not (folder / "summary.json").exists()
    with open(folder / TICKS_FILE) as fh:
        rows = list(csv.DictReader(fh))
    assert len(rows) == 1 and set(TICK_COLUMNS) <= set(rows[0])

    # resumed, and stopped again mid-way
    part = run_per_tick(sc2, original, st, folder, stop_after_ticks=40)
    assert part.status == OUTCOME_STOPPED and part.resumed_from_tick == 2
    assert part.next_tick == 42

    # resumed to the end by the same command
    assert main(argv) == 0
    assert not (folder / CHECKPOINT_DIR).exists()
    summary = json.loads((folder / "summary.json").read_text())
    assert summary["mode"] == "per_tick" and summary["settings"]["per_tick"] is True
    assert summary["per_tick"]["outcome"] == OUTCOME_DONE
    assert summary["per_tick"]["resumed_from_tick"] == 42
    assert summary["per_tick"]["n_ticks"] == sc.T
    with open(folder / TICKS_FILE) as fh:
        assert [int(r["tick"]) for r in csv.DictReader(fh)] == list(range(1, sc.T + 1))
    with open(folder / "optimized" / "schedule.csv") as fh:
        got = {int(r["i"]): (int(r["server"]), int(r["start"]), int(r["finish"]))
               for r in csv.DictReader(fh)}
    assert got == {p.i: (p.server, p.start, p.end) for p in out.schedule.placements}
    with open(folder / "optimized" / "zone_period.csv") as fh:
        sup = {(int(r["z"]), int(r["t"])): float(r["supply_temp_C"]) for r in csv.DictReader(fh)}
    assert sup == {(z + 1, t + 1): float(out.supply_temp_C[z, t])
                   for z in range(sc.Z) for t in range(sc.T)}


def test_checkpoint_of_other_settings_is_refused(tmp_path):
    argv = ARGS + ["--results-dir", str(tmp_path), "--run-name", "x"]
    assert main(argv + ["--wall-time-limit", "0"]) == 3
    with pytest.raises(ValueError, match="other settings"):
        main(argv + ["--no-priority"])


def test_impossible_tick_exits_4_and_names_the_limit(tmp_path):
    argv = ARGS + ["--results-dir", str(tmp_path), "--h-min", "30"]
    st = parse_args(argv)[0]
    assert main(argv) == 4
    folder = tmp_path / "small" / st.run_name
    summary = json.loads((folder / "summary.json").read_text())
    stuck = summary["per_tick"]["stuck"]
    assert summary["per_tick"]["outcome"] == OUTCOME_STUCK and stuck["tick"] == 1
    assert stuck["limits"] == [RELAX_THERMAL] and "thermal cap" in stuck["limit_text"]
    assert summary["has_optimized_schedule"] is False
    assert not (folder / CHECKPOINT_DIR).exists()
    with open(folder / TICKS_FILE) as fh:
        rows = list(csv.DictReader(fh))
    assert rows[-1]["tick"] == "1" and rows[-1]["status"] == "infeasible"


def test_stuck_mid_run_names_the_deadline(tmp_path):
    """A workload that cannot finish by its deadline stops the run at its arrival tick."""
    st, sc, original = _setup(ARGS)
    w = next(w for w in sc.workloads if w.A >= 20 and w.ET_base >= 3)
    bad = dataclasses.replace(w, D=w.A + 1, AD=0)
    sc = dataclasses.replace(sc, workloads=tuple(bad if x.i == w.i else x for x in sc.workloads))
    out = run_per_tick(sc, original, st, tmp_path / "run")
    assert out.status == OUTCOME_STUCK
    assert out.stuck["tick"] == w.A and out.stuck["limits"] == [RELAX_DEADLINES]
    assert out.stuck["workloads"] == [w.workload_id]
    assert len(out.ticks) == w.A
    assert (tmp_path / "run" / "partial_schedule.csv").is_file()


def test_per_tick_run_names_and_test_matching():
    names = {tuple(v): parse_args(["--scenario", "small"] + v)[0].run_name
             for v in ([], ["--per-tick"], ["--per-tick", "--tick-time-limit", "20"],
                       ["--per-tick", "--time-limit", "100"])}
    assert names[()] == "least_loaded_base18_free_optimize"
    assert names[("--per-tick",)] == "least_loaded_base18_free_optimize_pertick"
    assert names[("--per-tick", "--tick-time-limit", "20")] == \
        "least_loaded_base18_free_optimize_pertick_ttl20"
    assert names[("--per-tick", "--time-limit", "100")] == names[("--per-tick",)]
    # per-tick runs match the same tests as whole-day ones
    st = RunSettings(per_tick=True, tick_time_limit_s=20.0).as_dict()
    assert [t.id for t in ex.identify(st, "servers6")[1]] == ["base"]
