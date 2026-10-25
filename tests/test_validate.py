"""Tests of scheduler/validate.py: each check gives the answer it is built to show."""

from __future__ import annotations

import json
import math

import pytest

from dashboard import data
from scheduler import validate
from scheduler.io import load_scenario
from scheduler.types import STATUS_TIME_LIMIT, status_text


@pytest.fixture(scope="module")
def small():
    return load_scenario("small", "scenarios")


@pytest.fixture(scope="module")
def thesis10():
    # The thesis group's examples (workloads 211, 232, 5 on qh2-rcc165 and qh2-rcc183) were
    # posed on thesis10, archived with the 516 GB scenarios; memory plays no part in them.
    return load_scenario("thesis10", "archive/scenarios_516GB")


def test_power_is_linear_in_cpu_use(small):
    rows = validate.power_check(small)
    assert len(rows) == 3 * small.S
    assert all(r["Pass"] for r in rows)
    for r in rows:
        share = r["CPU use (%)"] / 100
        assert r["Optimizer power (W)"] == pytest.approx(
            r["Idle power (W)"] + (r["Maximum power (W)"] - r["Idle power (W)"]) * share, abs=0.01)


def test_run_length_follows_server_speed(thesis10):
    """The examples of the thesis group: workload 232 meets its deadline only on the fast
    server; workload 5 takes 3 periods on both (rounding up)."""
    rows = {(r["Workload"], r["Server"]): r for r in validate.execution_check(thesis10)}
    assert all(r["Pass"] for r in rows.values())
    slow, fast = validate.EXAMPLE_SERVERS
    assert not rows[(232, slow)]["Meets deadline"] and rows[(232, fast)]["Meets deadline"]
    assert rows[(5, slow)]["Periods, rounded up"] == rows[(5, fast)]["Periods, rounded up"] == 3
    for r in rows.values():
        assert r["Periods, rounded up"] == math.ceil(r["Periods, exact"] - 1e-9) or \
            r["Periods, exact"] == pytest.approx(r["Periods, rounded up"], abs=0.005)
        assert r["Lowest DPF during the run"] == 1.0
    eq = validate.equal_time_count(thesis10)
    assert 0 < eq["same_periods"] < thesis10.I


def test_server_choice_keeps_idle_electricity_fixed(thesis10):
    rows = validate.server_choice_check(thesis10, workloads=(211,))
    idle = {r["Fleet idle electricity, whole day (kWh)"] for r in rows}
    assert len(idle) == 1
    for r in rows:
        assert r["of which idle (kWh)"] + r["of which added by the workload (kWh)"] == pytest.approx(
            r["Server electricity during the run (kWh)"], abs=1e-4)
        assert r["Fleet IT electricity, whole day (kWh)"] > idle.pop() if idle else True


def test_reassignment_moves_when_needed_or_helpful(small):
    rows = validate.reassignment_check(small)
    assert len(rows) == 4 and all(r["Pass"] for r in rows)
    by = {(r["Case"], r["Reassignment"]): r for r in rows}
    assert by[("Move needed", "none")]["Solver status"] == "No valid schedule (proven)"
    assert by[("Move needed", "free")]["Moved"]
    assert by[("Move helps", "free")]["Carbon (g CO2)"] < by[("Move helps", "none")]["Carbon (g CO2)"]


def test_crac_supply_is_a_decision(small):
    rows, supply, cops = validate.crac_check(small, h_mins=(None,), time_limit_s=60)
    assert rows[0]["Solver status"] == "Proven best"
    assert len(supply) == small.Z * small.T
    assert cops[-1]["COP"] > cops[0]["COP"]          # warmer supply air, better COP


def test_heat_slows_the_run(thesis10):
    cool, warm = validate.slowdown_check(thesis10)
    assert cool["Pass"] and warm["Pass"]
    assert cool["Periods run"] == 6 and warm["Periods run"] == 7
    assert warm["Lowest DPF during the run"] < 1.0 <= cool["Lowest DPF during the run"]


def test_run_based_tables_and_write_all(tmp_path, small):
    """write_all on small: every table is written and listed in validation.json, the
    run-based ones are skipped without their runs, and the dashboard reads them back."""
    results = tmp_path / "results"
    results.mkdir()
    meta = validate.write_all("small", "scenarios", results, log=lambda *_: None)
    out = results / "validation" / "small"
    assert json.loads((out / "validation.json").read_text())["checks"] == meta["checks"]
    for key in ("workload_inputs", "power", "execution_time", "server_choice", "reassignment",
                "crac", "crac_supply", "crac_cop", "slowdown", "solver"):
        assert (out / f"{key}.csv").is_file(), key
    assert "cold_plates" not in meta["checks"] and "throttled_servers" not in meta["checks"]
    assert not [k for k, v in meta["checks"].items() if v["passed"] is False]
    assert data.validation_scenarios(results / "validation") == ["small"]
    meta2, tables = data.load_validation("small", results / "validation")
    assert meta2["scenario"] == "small"
    assert len(tables["workload_inputs"]) == small.I
    assert "Requested RAM (GB)" in tables["workload_inputs"]


def test_solver_rows_say_how_complete_each_run_is():
    rows = {r["Run"]: r for r in validate.solver_rows("results", "thesis10")}
    if "base" not in rows:
        pytest.skip("the thesis10 whole-day runs are not under results/ (moved to archive/)")
    base = rows["base"]                         # results/servers10/base, a thesis10 run
    assert base["Solver status"] == "Stopped at time limit"
    assert base["Most a better schedule could save (kg CO2)"] == pytest.approx(
        base["Carbon (kg CO2)"] - base["Lower bound (kg CO2)"], abs=1e-3)
    assert rows["s4_t1_no_moves"]["Solver status"] == "Proven best"
    assert "s4_t3b_ci_swing" not in rows        # solved on thesis10_swing


def test_status_words():
    assert status_text(STATUS_TIME_LIMIT) == "Stopped at time limit"
    assert status_text("something_else") == "something_else"
    assert data.solver_short({"status": "time_limit", "mip_gap": 0.016}) == \
        "Stopped at time limit, gap 1.60 %"
    assert data.solver_short({"status": "optimal", "mip_gap": 0.0}) == "Proven best"
    assert "1.60 %" in data.solver_sentence({"status": "time_limit", "mip_gap": 0.016,
                                             "solve_time_s": 1800})
