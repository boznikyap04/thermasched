"""tools/runlist.py: the 39 per-tick runs of the six-server fleet (docs/PLAN.md §3)."""

from __future__ import annotations

import json

import pytest

from scheduler.experiments import TEST_BY_ID, configuration_of, identify, switches_for
from scheduler.run import parse_args
from scheduler.types import RunSettings
from tools import runlist

RUNS = runlist.runs()
# Settings that name or limit a run but never change which test it is.
NOT_A_SWITCH = {"run_name", "time_limit_s", "mip_rel_gap"}


def _per_tick_supported() -> bool:
    try:
        parse_args(["--per-tick"])
    except SystemExit:
        return False
    return True


FIRST_BATCH = {"base", "s1_t1_zones", "s1_t2_same_zone", "s2_base", "s2_t1_crac",
               "s2_t2_cold_plate"}
DAYS = {"servers6_light", "servers6", "servers6_heavy"}


def test_thirty_nine_runs_with_unique_ids():
    assert len(RUNS) == 39
    assert len({r["id"] for r in RUNS}) == 39
    assert len({(r["scenario"], r["run_name"]) for r in RUNS}) == 39
    assert {r["configuration"] for r in RUNS} == DAYS
    assert {r["run_name"] for r in RUNS} == FIRST_BATCH | {
        "s3_t1_hmin_high", "s3_t2_hmin_med", "s3_t3_hmin_low", "s4_t1_no_moves", "s4_t2_blind",
        "s4_t3a_ci_flat", "s4_t3b_ci_swing"}
    assert runlist.TIMING_RUN in {r["id"] for r in RUNS}


def test_first_batch_is_sections_6_1_and_6_2():
    first = runlist.runs(sections=("6.1", "6.2"))
    assert len(first) == 18 and {r["run_name"] for r in first} == FIRST_BATCH
    assert [r["id"] for r in first] == [r["id"] for r in RUNS[:18]]


def test_carbon_tests_run_flat_or_on_the_swing_twin():
    by = {(r["configuration"], r["run_name"]): r for r in RUNS}
    for day in DAYS:
        flat, swing = by[(day, "s4_t3a_ci_flat")], by[(day, "s4_t3b_ci_swing")]
        assert flat["scenario"] == day and "--ci-flat" in flat["args"]
        assert swing["scenario"] == f"{day}_swing" and "--ci-flat" not in swing["args"]
    assert all(r["scenario"] == r["configuration"] for r in RUNS
               if r["run_name"] != "s4_t3b_ci_swing")


@pytest.mark.parametrize("r", RUNS, ids=[r["id"] for r in RUNS])
def test_args_reproduce_the_batch_notebook(r):
    """The usual flags parse, and give the settings the batch notebook builds for the same
    test (RunSettings with the test's switches); the run is recognized as that test."""
    settings, a = parse_args(r["args"])
    assert (settings.scenario, settings.run_name) == (r["scenario"], r["run_name"])
    assert a.results_dir == "results"
    config, implied = configuration_of(r["scenario"])
    assert config.key == r["configuration"]
    test = TEST_BY_ID[r["run_name"]]
    # as the batch notebook sets it: a flat profile is ci_flat, the swing is the scenario
    switches = {k: v for k, v in switches_for(test, config).items() if k not in implied}
    if switches.pop("ci_amplitude", None) == 0:
        switches["ci_flat"] = True
    notebook = RunSettings(scenario=r["scenario"], **switches)
    got = {k: v for k, v in settings.as_dict().items() if k not in NOT_A_SWITCH}
    want = {k: v for k, v in notebook.as_dict().items() if k not in NOT_A_SWITCH}
    assert got == want
    assert test in identify(settings.as_dict(), r["scenario"])[1]


@pytest.mark.skipif(not _per_tick_supported(), reason="scheduler.run has no --per-tick yet")
@pytest.mark.parametrize("r", RUNS, ids=[r["id"] for r in RUNS])
def test_full_argv_parses_with_per_tick(r):
    settings, _ = parse_args(r["args"] + r["per_tick_args"])
    assert (settings.scenario, settings.run_name) == (r["scenario"], r["run_name"])


def test_matrix_and_selection(capsys):
    assert runlist.main(["--format", "matrix", "--only", runlist.TIMING_RUN,
                         "--results-dir", "_ci/results", "--tick-time-limit", "60"]) == 0
    (entry,) = json.loads(capsys.readouterr().out)["include"]
    assert entry["id"] == runlist.TIMING_RUN
    argv = json.loads(entry["argv"])
    assert argv[:4] == ["--scenario", "servers6_heavy", "--run-name", "base"]
    assert argv[argv.index("--results-dir") + 1] == "_ci/results"
    assert argv[argv.index("--tick-time-limit") + 1] == "60"
    assert argv[argv.index("--wall-time-limit") + 1] == "19800"
    assert runlist.main(["--format", "matrix", "--timing"]) == 0
    timing = json.loads(capsys.readouterr().out)["include"]
    assert [e["id"] for e in timing] == [runlist.TIMING_RUN]
    with pytest.raises(SystemExit):
        runlist.main(["--only", "servers6__nope"])


def test_unknown_switch_is_an_error():
    with pytest.raises(ValueError):
        runlist.switch_args({"ci_amplitude": 0.5})
