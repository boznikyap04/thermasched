"""Chapter 5 tables (dashboard/tables.py) against real runs under results/."""

from __future__ import annotations

import pandas as pd
import pytest

from dashboard import data, tables

BY_KEY = {r.key: r for r in data.discover_runs()
          + data.discover_runs(data.REPO_ROOT / "archive" / "results_2026-10-25")}
BASE = "servers10/base"
COLD_PLATES = "servers10/s2_base"
INFEASIBLE = "archive-small/infeasible_demo_hmin20"

pytestmark = pytest.mark.skipif(not {BASE, COLD_PLATES, INFEASIBLE} <= set(BY_KEY),
                                reason="the servers10 runs or the archived small runs are missing")


@pytest.fixture(scope="module")
def run():
    return data.load_run(BY_KEY[BASE].path)


@pytest.fixture(scope="module")
def cp_run():
    return data.load_run(BY_KEY[COLD_PLATES].path)


@pytest.fixture(scope="module")
def infeasible():
    return data.load_run(BY_KEY[INFEASIBLE].path)


def _sched(run, v="optimized"):
    return run.schedule[run.schedule["variant"] == v].sort_values("i").reset_index(drop=True)


@pytest.mark.parametrize("v", ["optimized", "baseline"])
def test_workload_schedule(run, v):
    df, s = tables.workload_schedule(run, v), _sched(run, v)
    assert len(df) == 238
    assert (df["Execution time (min)"] == s["periods_run"] * 5).all()
    assert (df["Start (period)"] == s["start"]).all()
    assert (df["Completion (period)"] == s["start"] + s["periods_run"]).all()
    # Period 1 starts at 06:00; a period is 5 minutes.
    first = df.iloc[0]
    assert first["Arrival (period)"] == 26 and first["Arrival (clock)"] == "08:05"
    assert df["Start (clock)"].str.fullmatch(r"\d\d:\d\d").all()


def test_deadlines_and_waiting(run):
    df, s = tables.deadlines_and_waiting(run, "optimized"), _sched(run)
    assert len(df) == 238
    assert (df["Waiting time (min)"] == s["wait"] * 5).all()
    assert (df["Allowed delay (min)"] == s["allowed_delay"] * 5).all()
    assert (df["Waiting time (min)"] <= df["Allowed delay (min)"]).all()
    assert (df[["Wait within allowed", "On time", "Compliant"]] == tables.OK).all().all()


def test_reassignment(run):
    df = tables.reassignment(run)
    assert len(df) == 238
    assert set(df["Moved"]) <= {"yes", "no"}
    assert (df["Moved"] == "yes").sum() == run.summary["optimized"]["metrics"]["n_reassigned"]
    assert df["Original server"].notna().all() and df["Final server"].notna().all()


def test_server_tables(run):
    cpu = tables.cpu_and_memory(run, "optimized")
    assert len(cpu) == 10 and (cpu["Within capacity"] == tables.OK).all()
    assert (cpu["Peak CPU used (cores)"] <= cpu["CPU capacity (cores)"]).all()
    assert cpu["Memory capacity (GB)"].iloc[0] == pytest.approx(528286 / 1024)
    assert cpu["Server"].tolist() == run.servers["name"].tolist()     # display order

    temp = tables.temperature_and_headroom(run, "optimized")
    assert len(temp) == 10 and (temp["Within limits"] == tables.OK).all()
    assert (temp["Thermal cap (°C)"] == 80).all()
    assert temp["Required H_min (°C)"].iloc[0] == pytest.approx(10.0)
    assert temp["Hottest predicted temperature (°C)"].max() == pytest.approx(
        run.summary["optimized"]["metrics"]["hottest_T_C"])


def test_cooling_limits(run, cp_run):
    crac = tables.crac_limits(run, "optimized")
    assert crac["Zone"].tolist() == [1, 2] and (crac["Within limits"] == tables.OK).all()
    assert tables.cold_plate_limits(run, "optimized").empty          # cold plates off
    cp = tables.cold_plate_limits(cp_run, "optimized")
    assert len(cp) == 3 and (cp["Within limits"] == tables.OK).all()
    assert (cp["Peak heat removed (W)"] <= cp["Capacity (W)"]).all()


def test_work_completion(run):
    df = tables.work_completion(run, "optimized")
    assert len(df) == 238
    assert (df["Delivered / required"] >= 1 - 1e-9).all()
    assert (df["Work complete"] == tables.OK).all()
    assert (df["Lowest DPF while running"] == 1.0).all()            # no throttling at 73 °C
    caps = set(run.server_period["PC_eff_MHz"].unique())
    assert set(df["Lowest server PC_eff while running (MHz)"]) <= caps


def test_energy_and_carbon(run, cp_run):
    for r in (run, cp_run):
        e = tables.energy_breakdown(r, "optimized")
        parts, total = e[e["Component"] != "Total"], e[e["Component"] == "Total"].iloc[0]
        assert "Fans" not in set(e["Component"])
        assert parts["Share of total (%)"].sum() == pytest.approx(100.0)
        assert total["Energy (kWh)"] == pytest.approx(
            r.summary["optimized"]["totals"]["E_total_kWh"])

        c = tables.carbon_per_period(r, "optimized")
        assert len(c) == 288 and c["Period"].tolist() == list(range(1, 289))
        energy, carbon = tables.carbon_totals(r, "optimized")
        assert c["Total energy (kWh)"].sum() == pytest.approx(energy)
        assert carbon == pytest.approx(r.summary["optimized"]["totals"]["carbon_kg"])
        assert c["Carbon (g CO2)"].to_numpy() == pytest.approx(
            (c["Total energy (kWh)"] * c["Grid carbon intensity (g CO2/kWh)"]).to_numpy(),
            rel=1e-9)
    assert "Cold-plate pumps (kWh)" in tables.carbon_per_period(cp_run, "optimized")


def test_baseline_only_run(infeasible):
    n = infeasible.summary["scenario"]["I"]
    for build in (tables.workload_schedule, tables.deadlines_and_waiting,
                  tables.work_completion):
        assert build(infeasible, "optimized").empty
        assert len(build(infeasible, "baseline")) == n
    assert tables.reassignment(infeasible).empty
    for build in (tables.cpu_and_memory, tables.temperature_and_headroom, tables.crac_limits,
                  tables.cold_plate_limits, tables.energy_breakdown, tables.carbon_per_period):
        assert build(infeasible, "optimized").empty
        assert isinstance(build(infeasible, "baseline"), pd.DataFrame)
    assert not tables.energy_breakdown(infeasible, "baseline").empty


def test_unplaced_workloads_do_not_break_the_tables(run):
    """A workload left out (placed = 0, no server or start) gives blank cells, not an error."""
    sch = run.schedule.copy()
    first = sch.index[sch["variant"] == "optimized"][0]
    sch.loc[first, ["server", "start", "finish", "periods_run", "wait"]] = float("nan")
    sch.loc[first, ["server_name", "placed"]] = [None, 0]
    hacked = data.Run(**{**run.__dict__, "schedule": sch})
    df = tables.workload_schedule(hacked, "optimized")
    assert pd.isna(df.loc[0, "Start (period)"]) and pd.isna(df.loc[0, "Start (clock)"])
    work = tables.work_completion(hacked, "optimized")
    assert pd.isna(work.loc[0, "Lowest DPF while running"])
    assert len(tables.deadlines_and_waiting(hacked, "optimized")) == 238
