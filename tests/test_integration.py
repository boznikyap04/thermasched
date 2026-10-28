"""End-to-end checks: baseline -> evaluator -> optimizer -> evaluator -> report."""

from __future__ import annotations

import csv
import json
import shutil
from pathlib import Path

import numpy as np
import pytest

from scheduler.baseline import build_baseline
from scheduler.evaluate import evaluate
from scheduler.io import apply_overrides, load_reference_baseline, load_scenario
from scheduler.optimize import solve
from scheduler.run import main, parse_args, run
from scheduler.types import (
    STATUS_OPTIMAL, Constants, RunSettings, Scenario, Server, Workload, constant_supply_temp,
)


@pytest.mark.parametrize("name", ["small", "servers6_light", "servers6", "servers6_heavy", "small_running"])
def test_least_loaded_reproduces_reference_baseline(name):
    sc = load_scenario(name)
    assert build_baseline(sc, RunSettings(scenario=name)) == load_reference_baseline(name)


@pytest.mark.parametrize("name,kwh,kg", [("small", 6.87, 4.37), ("servers6_light", 35.33, 21.98),
                                         ("servers6", 39.13, 24.35), ("servers6_heavy", 42.46, 26.46)])
def test_baseline_it_energy_and_carbon(name, kwh, kg):
    sc = load_scenario(name)
    st = RunSettings(scenario=name)
    ev = evaluate(sc, build_baseline(sc, st), constant_supply_temp(sc, 18.0), st)
    assert round(ev.totals["E_IT_kWh"], 2) == kwh
    assert round(float((sc.CI_g_per_kWh * ev.E_IT_kWh).sum()) / 1000, 2) == kg


@pytest.mark.parametrize("supply,hottest,cooling", [(18.0, 66.26, 14.62), (27.0, 75.26, 7.20)])
def test_servers6_baseline_thermal_and_cooling(supply, hottest, cooling):
    sc = load_scenario("servers6")
    st = RunSettings(scenario="servers6", baseline_supply_temp_C=supply)
    ev = evaluate(sc, build_baseline(sc, st), constant_supply_temp(sc, supply), st)
    assert ev.totals["hottest_T_C"] == pytest.approx(hottest, abs=0.05)
    assert ev.totals["periods_above_cap"] == 0 and ev.T_C.max() < 80.0
    assert ev.totals["E_crac_kWh"] == pytest.approx(cooling, abs=0.05)


def test_small_none_fixed_run_passes_every_check(tmp_path):
    """reassignment=none, supply fixed at the baseline's: the optimizer can only move
    start times, so it must be no worse than the (valid) baseline."""
    st = RunSettings(scenario="small", run_name="t", reassignment="none",
                     supply_temp_mode="fixed", time_limit_s=120.0)
    summary = run(st, results_dir=tmp_path, quiet=True)
    checks = summary["checks"]
    assert set(checks) == {
        "least_loaded_reproduces_baseline_schedule_csv",
        "optimizer_objective_equals_evaluator_carbon",
        "optimized_schedule_valid_under_evaluator",
        "optimized_no_worse_than_valid_baseline"}
    assert all(c["passed"] is True for c in checks.values()), checks
    out = tmp_path / "small" / "t"
    assert json.loads((out / "summary.json").read_text())["checks"].keys() == checks.keys()
    for side in ("baseline", "optimized"):
        for table in ("schedule", "server_period", "zone_period", "period",
                      "compliance_servers", "compliance_zones", "compliance_workloads"):
            assert (out / side / f"{table}.csv").is_file()


def test_no_worse_than_valid_baseline_without_warm_start():
    """Same check on a small instance solved to optimality with no starting schedule."""
    consts = Constants(R_dvfs=0.378, F_throttle=0.662, T_max_server_C=90.0, H_min_C=10.0,
                       T_dvfs_C=75.0, T_throttle_C=100.0, Q_crac_kW=116.0,
                       COP_coeffs=(0.0068, 0.0008, 0.458), T_crac_min_C=18.0,
                       T_crac_max_C=27.0, T_max_zone_C=32.0)
    servers = tuple(
        Server(s=s, name=f"s{s}", zone=s, f_MHz=f, C_cores=4, M_MB=1e6, P_idle_W=100.0,
               P_max_W=pmax, T0_C=40.0, CT_cold_plate=0, th_a_C=5.0, th_R_C_per_W=0.05,
               th_alpha=0.8)
        for s, f, pmax in ((1, 2000.0, 300.0), (2, 3000.0, 350.0)))
    dt = 300.0
    workloads = tuple(
        Workload(i=i, workload_id=f"w{i}", flavor="x", A=A, D=A + n + AD, AD=AD, ET_base=n,
                 RT=0, B=0, X0=None, C_req=c, M_req_MB=1.0, W_MHz_s=c * 2000.0 * dt * n)
        for i, (A, n, AD, c) in enumerate(
            [(1, 2, 4, 2), (1, 3, 3, 2), (2, 2, 5, 1), (3, 1, 6, 4), (4, 2, 4, 2)], 1))
    sc = Scenario(name="t", T=12, dt_seconds=dt, workloads=workloads, servers=servers,
                  n_zones=2, CI_g_per_kWh=np.linspace(700.0, 400.0, 12), constants=consts)
    st = RunSettings(reassignment="none", supply_temp_mode="fixed", mip_rel_gap=1e-9,
                     time_limit_s=60.0)
    base = build_baseline(sc, st)
    supply = constant_supply_temp(sc, st.baseline_supply_temp_C)
    base_ev = evaluate(sc, base, supply, st)
    assert base_ev.valid
    res = solve(sc, base.server_of(), st)
    assert res.status == STATUS_OPTIMAL
    ev = evaluate(sc, res.schedule, res.supply_temp_C, st)
    assert ev.valid
    assert res.schedule.server_of() == base.server_of()
    assert ev.total_carbon_g == pytest.approx(res.objective_g, rel=1e-6)
    # carbon intensity falls over the horizon, so waiting is strictly better
    assert ev.total_carbon_g < base_ev.total_carbon_g


def test_undefined_switch_is_refused(capsys):
    assert main(["--scenario", "small", "--fan-power"]) == 2
    assert "not defined yet" in capsys.readouterr().err.lower()


def test_small_cold_plate_run_passes_every_check(tmp_path):
    rc = main(["--scenario", "small", "--cold-plates", "--reassignment", "none",
               "--supply-temp-mode", "fixed", "--results-dir", str(tmp_path)])
    assert rc == 0
    out = tmp_path / "small" / "least_loaded_base18_none_fixed18_cp"
    summary = json.loads((out / "summary.json").read_text())
    assert all(c["passed"] in (True, None) for c in summary["checks"].values())
    assert summary["cold_plates"]["enabled"] and summary["cold_plates"]["plates_per_server"] == [0, 0, 1]
    assert "FLAGGED" in summary["model_note"]
    assert summary["baseline"]["totals"]["Q_cp_kWh"] > 0


def test_cold_plate_count_from_csv_and_cli(tmp_path):
    src = Path("scenarios/small")
    dst = tmp_path / "small"
    shutil.copytree(src, dst)
    rows = list(csv.DictReader(open(dst / "servers.csv")))
    for r in rows:
        r["n_cold_plates"] = {"1": "0", "2": "3", "3": ""}[r["s"]]   # blank: use CT_s
    with open(dst / "servers.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    sc = load_scenario("small", tmp_path)
    assert [sv.plates for sv in sc.servers] == [0, 3, 1]
    assert sc.cold_plate.coolant_min_C == 20.0 and sc.cold_plate.coolant_max_C == 39.95
    assert sc.cold_plate.pump_ref_W == pytest.approx(0.657e-3)
    st, _ = parse_args(["--cold-plate-count", "2"])
    assert st.cold_plates and st.cold_plate_count == 2
    assert st.run_name == "least_loaded_base18_free_optimize_cp2"


def test_run_name_is_built_from_the_switches():
    st, _ = parse_args(["--baseline-rule", "fastest_first", "--baseline-supply-temp", "27",
                        "--reassignment", "same_zone", "--supply-temp-mode", "fixed"])
    assert st.run_name == "fastest_first_base27_same_zone_fixed27"
    assert st.optimized_fixed_supply_temp_C() == 27.0


def test_small_running_exercises_availability_and_running_workloads(tmp_path):
    sc = load_scenario("small_running")
    assert [w.i for w in sc.workloads if w.B == 1] == [1, 2, 3, 4, 5, 6, 7]
    AV = sc.availability()
    assert int((AV == 0).sum()) == 12 and not AV[2, 36:48].any()
    st = RunSettings(scenario="small_running", run_name="t", time_limit_s=60.0)
    summary = run(st, results_dir=tmp_path, quiet=True)
    checks = summary["checks"]
    assert checks["running_workloads_not_reassigned"]["passed"] is True
    assert all(c["passed"] in (True, None) for c in checks.values())
    assert summary["scenario"]["n_running"] == 7
    assert summary["scenario"]["n_unavailable_server_periods"] == 12
    rows = list(csv.DictReader(open(tmp_path / "small_running" / "t" / "optimized" /
                                    "reassignment.csv")))
    assert all(r["reassigned"] == "0" and "Eq. (29)" in r["reason"] for r in rows[:7])
    sp = list(csv.DictReader(open(tmp_path / "small_running" / "t" / "optimized" /
                                  "server_period.csv")))
    assert all(float(r["cpu_used_cores"]) == 0 for r in sp
               if r["s"] == "3" and 37 <= int(r["t"]) <= 48)


def test_zone_map_and_carbon_overrides(tmp_path):
    sc = load_scenario("servers6")
    st, _ = parse_args(["--scenario", "servers6", "--zone-map", "1,1,1,2,2,2"])
    assert st.zone_map == (1, 1, 1, 2, 2, 2)
    assert st.run_name == "least_loaded_base18_free_optimize_zones111222"
    sc2 = apply_overrides(sc, st)
    assert [sv.zone for sv in sc2.servers] == [1, 1, 1, 2, 2, 2] and sc2.Z == 2
    assert [sv.zone for sv in sc.servers] == [1, 2, 1, 2, 1, 2]       # loaded copy untouched
    with pytest.raises(ValueError, match="entries"):
        apply_overrides(sc, RunSettings(zone_map=(1, 2)))
    with pytest.raises(ValueError, match="every zone"):
        apply_overrides(sc, RunSettings(zone_map=(1, 1, 1, 3, 3, 3)))

    st, _ = parse_args(["--scenario", "servers6", "--ci-flat"])
    assert st.run_name.endswith("_ciflat")
    flat = apply_overrides(sc, st).CI_g_per_kWh
    assert np.allclose(flat, sc.CI_g_per_kWh.mean())

    path = tmp_path / "night.csv"
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["t", "CI_t_g_per_kWh"])
        w.writerows([t, 500.0 + t] for t in range(1, sc.T + 1))
    st, _ = parse_args(["--scenario", "servers6", "--carbon-file", str(path)])
    assert st.run_name.endswith("_ci-night")
    assert apply_overrides(sc, st).CI_g_per_kWh[0] == 501.0
    with pytest.raises(SystemExit):
        parse_args(["--ci-flat", "--carbon-file", str(path)])


def test_switch_run_names():
    st, _ = parse_args(["--cold-plates", "--cp-mode", "fixed", "--no-priority"])
    assert st.run_name == "least_loaded_base18_free_optimize_cp_cpfixed_noprio"
    assert st.cp_mode == "fixed" and not st.priority
    assert st.optimized_fixed_cp() == (0.30, 20.0)
    st, _ = parse_args(["--cold-plates", "--cp-mode", "fixed", "--fixed-cp-flow", "0.2",
                        "--fixed-cp-coolant", "30"])
    assert st.optimized_fixed_cp() == (0.2, 30.0)


def test_run_names_differ_for_every_switch_that_changes_the_result():
    """A sweep over any one switch writes each run to its own folder."""
    variants = [[], ["--h-min", "5"], ["--h-min", "15"], ["--time-limit", "120"],
                ["--mip-gap", "0.01"], ["--baseline-rule", "random", "--seed", "1"],
                ["--baseline-rule", "random", "--seed", "2"], ["--cold-plates"],
                ["--cold-plates", "--baseline-cp-flow", "0.2"],
                ["--cold-plates", "--cp-mode", "fixed"],
                ["--cold-plates", "--cp-mode", "fixed", "--fixed-cp-flow", "0.2"],
                ["--thermal-blind"]]
    names = [parse_args(v)[0].run_name for v in variants]
    assert len(set(names)) == len(names), names
    assert names[1] == "least_loaded_base18_free_optimize_hmin5"
    assert names[-1] == "least_loaded_base18_free_optimize_tblind"
    assert parse_args(["--thermal-blind"])[0].placement == "thermal_blind"
    assert parse_args([])[0].placement == "thermal_aware"


def test_summary_records_provenance(tmp_path):
    """Every run says which release made it and which scenario build it was solved on."""
    from scheduler.version import SCHEMA_VERSION, VERSION
    st = RunSettings(scenario="small", run_name="t", reassignment="none", time_limit_s=60.0)
    pv = run(st, results_dir=tmp_path, quiet=True, made_with="notebook")["provenance"]
    assert pv["schema_version"] == SCHEMA_VERSION and pv["thermasched_version"] == VERSION
    assert pv["made_with"] == "notebook"
    assert pv["scenario_fingerprint"] == load_scenario("small").fingerprint
    assert pv["scenario_built_with"] == VERSION
    assert pv["highspy"] and pv["created_utc"].endswith("Z")
