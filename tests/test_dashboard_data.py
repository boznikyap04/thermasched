"""Dashboard loaders (dashboard/data.py) against the real folders under results/."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from dashboard import data

RUNS = data.discover_runs()
BY_KEY = {r.key: r for r in RUNS}
INFEASIBLE = "small/infeasible_demo_hmin20"
BASE_FREE = "base/least_loaded_base18_free_optimize"
SMALL_FREE = "small/least_loaded_base18_free_optimize"
FASTEST = "small/fastest_first_base27_free_optimize"

pytestmark = pytest.mark.skipif(not RUNS, reason="no run outputs under results/")


@pytest.fixture(scope="module")
def loaded():
    cache: dict[str, data.Run] = {}

    def get(key: str) -> data.Run:
        if key not in cache:
            cache[key] = data.load_run(BY_KEY[key].path)
        return cache[key]
    return get


# -- run discovery -------------------------------------------------------------------

def test_discovers_every_run_folder_with_a_summary():
    on_disk = sorted(p.parent for p in data.RESULTS_DIR.glob("*/*/summary.json"))
    assert [r.path for r in RUNS] == on_disk
    assert {INFEASIBLE, BASE_FREE, SMALL_FREE, FASTEST} <= set(BY_KEY)
    assert RUNS == sorted(RUNS)
    assert all(r.key == f"{r.scenario}/{r.name}" for r in RUNS)


def test_discovery_of_missing_or_empty_results_dir(tmp_path):
    assert data.discover_runs(tmp_path / "nope") == []
    assert data.discover_runs(tmp_path) == []
    (tmp_path / "small" / "half_written").mkdir(parents=True)   # no summary.json yet
    assert data.discover_runs(tmp_path) == []


@pytest.mark.parametrize("key", sorted(BY_KEY))
def test_every_run_loads(loaded, key):
    run = loaded(key)
    assert run.variants[0] == "baseline"
    assert set(run.period["variant"]) == set(run.variants)
    assert not run.server_period["name"].isna().any()
    assert not run.period["time"].isna().any()
    kpis = data.kpi_frame(run.summary)
    assert {"carbon_kg", "E_total_kWh", "hottest_T_C", "n_reassigned"} <= set(kpis["key"])
    assert not kpis["baseline"].isna().any()


# -- missing optimized/ ------------------------------------------------------------

def test_infeasible_run_has_baseline_only(loaded):
    run = loaded(INFEASIBLE)
    assert not (run.ref.path / "optimized").exists()
    assert run.variants == ("baseline",)
    assert not run.has_optimized
    assert run.solver["status"] == "infeasible"
    for df in (run.period, run.server_period, run.zone_period, run.schedule,
               run.compliance_servers, run.compliance_zones, run.compliance_workloads):
        assert set(df["variant"]) == {"baseline"}
    # comparison_period.csv exists, with blank optimized columns
    assert run.comparison_period["optimized_carbon_g"].isna().all()


def test_infeasible_run_derived_views(loaded):
    run = loaded(INFEASIBLE)
    kpis = data.kpi_frame(run.summary)
    assert kpis["optimized"].isna().all() and kpis["diff"].isna().all()
    assert data.savings_breakdown(run).empty
    assert data.cumulative_savings(run).empty
    moves = data.workload_moves(run)
    assert len(moves) == run.summary["scenario"]["I"]
    assert moves["server_name_optimized"].isna().all() and not moves["reassigned"].any()
    diag = data.infeasibility_frame(run.summary)
    assert dict(zip(diag["family"], diag["result"]))["thermal_cap"] == "feasible"
    assert run.thermal_cap_C == 70.0 and run.H_min_C == pytest.approx(20.0)


def test_compare_runs_handles_infeasible(loaded):
    df = data.compare_runs([r for r in RUNS if r.scenario == "small"]).set_index("run")
    assert np.isnan(df.loc["infeasible_demo_hmin20", "carbon_saved_pct"])
    assert df.loc["infeasible_demo_hmin20", "status"] == "infeasible"
    assert df.loc["least_loaded_base18_free_optimize", "carbon_saved_pct"] > 0


# -- all-zero columns ----------------------------------------------------------------

def test_is_all_zero():
    assert data.is_all_zero(pd.Series([0.0, 0, -0.0]))
    assert data.is_all_zero(pd.Series(["not modelled"] * 3))
    assert data.is_all_zero(pd.Series([0.0, np.nan]))
    assert not data.is_all_zero(pd.Series([0.0, 1e-3]))


NO_COLD_PLATES = sorted(k for k, r in BY_KEY.items()
                        if not data.load_summary(r.path)["settings"].get("cold_plates"))


@pytest.mark.parametrize("key", NO_COLD_PLATES)
def test_unmodelled_columns_are_hidden(loaded, key):
    run = loaded(key)
    assert not run.settings["cold_plates"] and not run.settings["fan_power"]
    assert data.active_energy_components(run) == ["E_IT_kWh", "E_crac_kWh"]
    assert data.nonzero_columns(run.zone_period, ["Q_crac_kW", "P_fan_kW", "airflow"]) == \
        ["Q_crac_kW"]
    assert data.nonzero_columns(run.server_period, ["P_IT_W", "Q_cp_W"]) == ["P_IT_W"]
    # "not modelled" airflow is turned into a numeric (all-NaN) column
    assert run.zone_period["airflow"].dtype.kind == "f"
    kpis = data.kpi_frame(run.summary)
    assert not {"E_cp_kWh", "E_fan_kWh"} & set(kpis["key"])
    assert run.summary["model_note"]


# -- time mapping --------------------------------------------------------------------

def test_base_clock_covers_24_hours_from_6am(loaded):
    run = loaded(BASE_FREE)
    clock = run.clock
    assert len(clock) == 288 and clock["t"].tolist() == list(range(1, 289))
    # hour_local is the middle of each 5-minute period
    assert clock["clock"].iloc[0] == "06:02" and clock["clock"].iloc[-1] == "05:57"
    step = clock["time"].diff().dropna()
    assert (step == pd.Timedelta(minutes=5)).all()        # rolls past midnight, no jump back
    assert clock["time"].iloc[-1].day == clock["time"].iloc[0].day + 1
    bound = data.period_bounds(clock, run.dt_seconds)
    assert bound([1])[0].strftime("%H:%M") == "06:00"
    assert bound([289])[0] - bound([1])[0] == pd.Timedelta(hours=24)


def test_small_clock_and_time_on_frames(loaded):
    run = loaded(SMALL_FREE)
    assert run.clock["clock"].iloc[0] == "12:02" and run.clock["clock"].iloc[-1] == "19:57"
    sp = run.server_period
    row = sp[(sp["t"] == 13)].iloc[0]
    assert row["clock"] == "13:02"
    carbon = pd.read_csv(data.SCENARIOS_DIR / "small" / "carbon.csv")
    hours = run.clock["time"].dt.hour + run.clock["time"].dt.minute / 60 \
        + run.clock["time"].dt.second / 3600
    assert np.allclose(hours, carbon["hour_local"], atol=0.001)


def test_hours_to_clock_rolls_over_midnight():
    ts = data.hours_to_clock(pd.Series([23.875, 23.958, 0.042, 0.125]))
    assert ts.dt.strftime("%H:%M:%S").tolist() == ["23:52:30", "23:57:30", "00:02:30",
                                                     "00:07:30"]
    assert (ts.diff().dropna() == pd.Timedelta(minutes=5)).all()


def test_clock_without_carbon_csv(tmp_path):
    clock = data.load_clock("missing", T=4, dt_seconds=300, scenarios_dir=tmp_path)
    assert clock["clock"].tolist() == ["00:02", "00:07", "00:12", "00:17"]


# -- names and derived views ---------------------------------------------------------

def test_server_names_and_zones_from_scenario(loaded):
    run = loaded(BASE_FREE)
    servers = pd.read_csv(data.SCENARIOS_DIR / "base" / "servers.csv")
    assert dict(zip(run.servers["s"], run.servers["name"])) == \
        dict(zip(servers["s"], servers["server"]))
    assert run.server_name(1) == "qh2-rcc188"
    assert run.servers["zone"].is_monotonic_increasing          # grouped by zone
    assert run.servers["label"].iloc[0].endswith("(Z1)")
    sch = run.schedule
    assert not sch["server_name"].isna().any()


def test_savings_breakdown_adds_up(loaded):
    run = loaded(BASE_FREE)
    sb = data.savings_breakdown(run)
    total_kg = run.summary["comparison"]["carbon_kg"]["diff"]
    assert sb["carbon_saved_kg"].sum() == pytest.approx(-total_kg, rel=1e-9)
    assert (sb["energy_effect_kg"] + sb["timing_effect_kg"]).tolist() == \
        pytest.approx(sb["carbon_saved_kg"].tolist())
    it = sb.set_index("component").loc["E_IT_kWh"]
    assert it["energy_saved_kWh"] == 0.0               # same IT energy, shifted in time
    cum = data.cumulative_savings(run)
    assert cum["carbon_saved_kg"].iloc[-1] == pytest.approx(-total_kg)


def test_kpis_match_summary(loaded):
    kpis = data.kpi_frame(loaded(BASE_FREE).summary).set_index("key")
    assert kpis.loc["carbon_kg", "pct"] == pytest.approx(-14.3145, abs=1e-3)
    assert kpis.loc["min_headroom_C", "better"] == "higher"


def test_moves_and_lanes(loaded):
    run = loaded(SMALL_FREE)
    moves = data.workload_moves(run)
    assert moves["reassigned"].sum() == run.summary["optimized"]["metrics"]["n_reassigned"]
    moved = moves[moves["reassigned"]]
    assert (moved["original_server_name"] != moved["server_name_optimized"]).all()
    sch = run.schedule.copy()
    sch["lane"] = data.gantt_lanes(sch)
    assert (sch["lane"] >= 0).all()
    for _, g in sch.groupby(["variant", "server", "lane"]):
        g = g.sort_values("start")
        assert (g["start"].iloc[1:].to_numpy() >= g["finish"].iloc[:-1].to_numpy()).all()


def test_throttling_and_checks(loaded):
    run = loaded(FASTEST)
    thr = data.throttled_servers(run).set_index("variant")
    assert thr.loc["baseline", "periods_throttled"] == 60
    if run.has_optimized:
        assert thr.loc["optimized", "min_DPF"] < 1
    assert data.throttled_servers(loaded(BASE_FREE)).empty
    checks = data.checks_frame(loaded(BASE_FREE).summary)
    assert checks["passed"].tolist() == [True, True, True]


def test_unzipped_export_carries_its_scenario(tmp_path):
    """A run export unzipped into results/ shows server names and clock times even when
    the scenario is not in scenarios/ (a scenario built in a notebook elsewhere)."""
    import io
    import zipfile

    from dashboard import uploads

    src = data.RESULTS_DIR / "small"
    run_dir = next(p.parent for p in sorted(src.glob("*/summary.json")))
    ref = data.RunRef("small", run_dir.name, run_dir)
    zipfile.ZipFile(io.BytesIO(uploads.runs_zip([(ref, data.SCENARIOS_DIR)]))).extractall(
        tmp_path / "results")
    empty = tmp_path / "scenarios"
    empty.mkdir()

    run = data.load_run(tmp_path / "results" / "small" / run_dir.name, empty)
    expected = data.load_run(run_dir)
    assert run.servers["name"].tolist() == expected.servers["name"].tolist()
    assert run.period["clock"].tolist() == expected.period["clock"].tolist()
    assert run.period["clock"].iloc[0] == "12:02"
