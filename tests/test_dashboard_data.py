"""Dashboard loaders (dashboard/data.py) against the real folders under results/."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from dashboard import data

# The runs on the site, and the runs taken off it on 2026-10-25 (small, infeasible and older
# runs the loader tests use).
RUNS = data.discover_runs()
ARCHIVE_DIR = data.REPO_ROOT / "archive" / "results_2026-10-25"
ARCHIVED = data.discover_runs(ARCHIVE_DIR)
BY_KEY = {r.key: r for r in RUNS + ARCHIVED}
INFEASIBLE = "archive-small/infeasible_demo_hmin20"
CONSOLIDATED6_FREE = "archive-consolidated6/least_loaded_base18_free_optimize"
SMALL_FREE = "archive-small/least_loaded_base18_free_optimize"
FASTEST = "archive-small/fastest_first_base27_free_optimize"
COLD_PLATES = "servers10/s2_base"

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
    assert sorted(r.path for r in RUNS) == on_disk
    assert {INFEASIBLE, CONSOLIDATED6_FREE, SMALL_FREE, FASTEST} <= set(BY_KEY)
    assert ARCHIVED == sorted(ARCHIVED, key=data.run_order)  # current scenarios, then archives
    archived = [data.is_archive(r.scenario) for r in ARCHIVED]
    assert archived == sorted(archived)
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
    if run.has_optimized:
        assert not kpis["value"].isna().any()


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


def test_infeasible_run_limits(loaded):
    run = loaded(INFEASIBLE)
    kpis = data.kpi_frame(run.summary)
    assert kpis["value"].isna().all() and kpis["diff"].isna().all()
    diag = data.infeasibility_frame(run.summary)
    assert dict(zip(diag["family"], diag["result"]))["thermal_cap"] == "feasible"
    assert run.thermal_cap_C == 70.0 and run.H_min_C == pytest.approx(20.0)


def test_compare_runs_handles_infeasible(loaded):
    df = data.compare_runs([r for r in ARCHIVED if r.scenario == "archive-small"]).set_index("run")
    assert np.isnan(df.loc["infeasible_demo_hmin20", "carbon_saved_pct"])
    assert df.loc["infeasible_demo_hmin20", "status"] == "infeasible"
    assert df.loc["least_loaded_base18_free_optimize", "carbon_saved_pct"] > 0


# -- all-zero and unmodelled columns -------------------------------------------------

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
    kpis = data.kpi_frame(run.summary)
    assert not {"E_cp_kWh", "E_fan_kWh"} & set(kpis["key"])
    # "not modelled" airflow is turned into a numeric (all-NaN) column
    assert run.zone_period["airflow"].dtype.kind == "f"
    assert run.summary["model_note"]


# -- time mapping --------------------------------------------------------------------

def test_consolidated6_clock_covers_24_hours_from_6am(loaded):
    run = loaded(CONSOLIDATED6_FREE)
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
    run = loaded(CONSOLIDATED6_FREE)
    servers = pd.read_csv(data.REPO_ROOT / "archive" / "scenarios_516GB" / "consolidated6" / "servers.csv")
    assert dict(zip(run.servers["s"], run.servers["name"])) == \
        dict(zip(servers["s"], servers["server"]))
    assert run.server_name(1) == "qh2-rcc188"
    assert run.servers["zone"].is_monotonic_increasing          # grouped by zone
    assert run.servers["label"].iloc[0].endswith("(Z1)")
    sch = run.schedule
    assert not sch["server_name"].isna().any()


def test_kpis_match_summary(loaded):
    kpis = data.kpi_frame(loaded(CONSOLIDATED6_FREE).summary).set_index("key")
    assert kpis.loc["min_headroom_C", "better"] == "higher"
    assert list(kpis.index) == ["carbon_kg", "E_total_kWh", "E_IT_kWh", "E_crac_kWh",
                                "hottest_T_C", "min_headroom_C", "n_late", "n_reassigned"]
    assert kpis["base"].isna().all() and kpis["pct"].isna().all()     # nothing to compare


def test_pump_energy_kpi_is_in_wh():
    summary = data.load_summary(BY_KEY[COLD_PLATES].path) if COLD_PLATES in BY_KEY else None
    if summary is None:
        pytest.skip("the 6.2 cold-plate run is not under results/")
    row = data.kpi_frame(summary).set_index("key").loc["E_cp_kWh"]
    assert row["unit"] == "Wh"
    assert row["value"] == pytest.approx(summary["optimized"]["metrics"]["E_cp_kWh"] * 1000)


def test_kpis_against_the_base():
    def summary(carbon, late):
        return {"has_optimized_schedule": True,
                "optimized": {"metrics": {"carbon_kg": carbon, "n_late": late}}}
    kpis = data.kpi_frame(summary(30.0, 0), summary(40.0, 0)).set_index("key")
    assert kpis.loc["carbon_kg", "value"] == 30.0 and kpis.loc["carbon_kg", "base"] == 40.0
    assert kpis.loc["carbon_kg", "diff"] == pytest.approx(-10.0)
    assert kpis.loc["carbon_kg", "pct"] == pytest.approx(-25.0)
    assert kpis.loc["n_late", "diff"] == 0 and pd.isna(kpis.loc["n_late", "pct"])  # base 0
    no_schedule = {"has_optimized_schedule": False, "optimized": None}
    assert data.kpi_frame(summary(30.0, 0), no_schedule)["base"].isna().all()


def test_server_stats_match_server_period(loaded):
    run = loaded(SMALL_FREE)
    stats = data.server_stats(run).set_index("s")
    sp = run.server_period[run.server_period["variant"] == "optimized"]
    assert list(stats.index) == run.servers["s"].tolist()
    assert set(data.SERVER_STATS) <= set(stats.columns)
    for s, g in sp.groupby("s"):
        assert stats.loc[s, "T_max_C"] == g["temperature_C"].max()
        assert stats.loc[s, "util_max_pct"] == pytest.approx(g["utilization"].max() * 100)
        assert stats.loc[s, "E_IT_kWh"] == pytest.approx(g["P_IT_W"].sum() * run.dt_seconds
                                                         / 3.6e6)
    assert data.server_stats(loaded(INFEASIBLE)).empty


def test_gantt_lanes_never_overlap(loaded):
    run = loaded(SMALL_FREE)
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
    assert data.throttled_servers(loaded(CONSOLIDATED6_FREE)).empty
    checks = data.checks_frame(loaded(CONSOLIDATED6_FREE).summary)
    assert checks["passed"].tolist() == [True, True, True]


def test_unzipped_export_carries_its_scenario(tmp_path):
    """A run export unzipped into results/ shows server names and clock times even when
    the scenario is not in scenarios/ (a scenario built in a notebook elsewhere)."""
    import io
    import zipfile

    from dashboard import uploads

    src = ARCHIVE_DIR / "archive-small"
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


# -- provenance ------------------------------------------------------------------------

def test_runs_from_before_versioning_still_load():
    """Older summary.json layouts keep opening: the archived runs predate 1.0.0."""
    archived = data.discover_runs(data.REPO_ROOT / "archive" / "results_2026-10-13")
    assert archived
    for ref in archived:
        run = data.load_run(ref.path)
        assert run.provenance == {}
        assert data.UNVERSIONED in data.provenance_caption(run.summary)
        assert data.provenance_warnings(run.summary) == []


def test_archived_scenarios_come_last_and_use_the_real_scenario(tmp_path):
    """results/archive-<scenario>/ is listed after the current scenarios, and its runs read
    server names and the clock from the scenario named in summary.json."""
    import shutil
    from dashboard.uploads import runs_zip
    import zipfile, io
    src = BY_KEY[SMALL_FREE].path
    shutil.copytree(src, tmp_path / "small" / "new_run")
    shutil.copytree(src, tmp_path / "archive-small" / "old_run")
    refs = data.discover_runs(tmp_path)
    assert [r.scenario for r in refs] == ["small", "archive-small"]
    run = data.load_run(refs[1].path)
    assert not run.servers["name"].str.startswith("server ").any()
    names = zipfile.ZipFile(io.BytesIO(runs_zip([(refs[1], data.SCENARIOS_DIR)]))).namelist()
    assert "small/old_run/summary.json" in names
    assert "small/servers.csv" in names and "small/carbon.csv" in names


def test_provenance_warnings():
    from scheduler.build import scenario_fingerprint
    here = scenario_fingerprint(data.SCENARIOS_DIR / "small")
    summary = {"scenario": {"name": "small"},
               "provenance": {"schema_version": 1, "thermasched_version": "1.0.0",
                              "made_with": "notebook", "scenario_fingerprint": here}}
    assert data.provenance_warnings(summary) == []
    assert "in the notebook" in data.provenance_caption(summary)
    other = {**summary, "provenance": {**summary["provenance"], "scenario_fingerprint": "0" * 12}}
    assert "different build of `small`" in data.provenance_warnings(other)[0]
    newer = {**summary, "provenance": {**summary["provenance"], "schema_version": 99}}
    assert "newer" in data.provenance_warnings(newer)[0]


# -- Chapter 6: configurations, tests and the results table -------------------------------

BASE = "servers10/base"
# The runs kept on the site on 2026-10-25, renamed by their test.
SERVERS10_TESTS = {
    "servers10/base": "base", "servers10/s1_t1_zones": "s1_t1_zones",
    "servers10/s1_t2_same_zone": "s1_t2_same_zone", "servers10/s2_base": "s2_base",
    "servers10/s2_t1_crac": "s2_t1_crac", "servers10/s2_t2_cold_plate": "s2_t2_cold_plate",
    "servers10/s3_t2_hmin_med": "s3_t2_hmin_med", "servers10/s3_t3_hmin_low": "s3_t3_hmin_low",
    "servers10/s4_t1_no_moves": "s4_t1_no_moves", "servers10/s4_t2_blind": "s4_t2_blind",
    "servers10/s4_t3a_ci_flat": "s4_t3a_ci_flat", "servers10/s4_t3b_ci_swing": "s4_t3b_ci_swing",
    "servers6/base": "base", "servers6/s4_t1_no_moves": "s4_t1_no_moves",
}
needs_site_runs = pytest.mark.skipif(not set(SERVERS10_TESTS) <= set(BY_KEY),
                                     reason="the Chapter 6 runs are not under results/")


@needs_site_runs
@pytest.mark.parametrize("key", sorted(SERVERS10_TESTS))
def test_each_site_run_matches_the_test_in_its_folder_name(key):
    ref = BY_KEY[key]
    info = data.run_info(ref)
    assert info.config.key == ref.scenario                  # results/<configuration>/
    assert [t.id for t in info.tests] == [SERVERS10_TESTS[key]] == [ref.name]


@needs_site_runs
def test_validation_runs_match_no_test_but_their_configuration():
    for ref in RUNS:
        if ref.name.startswith("v_"):
            info = data.run_info(ref)
            assert info.config.key == "servers10" and info.tests == ()


def test_archived_runs_get_no_configuration():
    for ref in ARCHIVED:
        if data.is_archive(ref.scenario):
            assert data.run_info(ref).config is None, ref.key


@needs_site_runs
def test_run_titles():
    infos = data.run_infos(RUNS)
    ref = BY_KEY["servers10/s1_t1_zones"]
    assert data.run_title(infos[ref.key], ref) == \
        "6.1 · Test 1 · Same-type servers regrouped into one zone"
    assert data.run_long_title(infos[ref.key], ref).startswith("10 servers · normal day · 6.1 · Test 1")
    base = BY_KEY[BASE]
    assert data.run_title(infos[base.key], base) == "Base"
    v = BY_KEY["servers10/v_crac27_moves"]
    assert data.run_title(infos[v.key], v) == "v_crac27_moves"
    row = data.compare_runs([BY_KEY[BASE]]).iloc[0]
    assert (row["configuration"], row["test"]) == ("10 servers · normal day", "Base")


@needs_site_runs
def test_chapter6_table_rows_and_columns():
    from scheduler import experiments as ex
    table = data.chapter6_table(RUNS)
    per_config = sum(len(s.tests) for s in ex.SECTIONS)
    assert len(table) == per_config * len(ex.CONFIGURATIONS)
    assert list(table.columns) == list(data.CHAPTER6_COLUMNS)
    ten = table[table["configuration"] == "10 servers · normal day"]
    assert (ten["servers"] == "10 servers").all() and (ten["level"] == "Normal day").all()
    assert list(zip(ten["section"], ten["tag"])) == \
        [(s.key, tag) for s in ex.SECTIONS for tag, _ in s.tests]
    # One base run is the reference (first row) of 6.1, 6.3 and 6.4.
    firsts = ten.groupby("section", sort=False)["run"].first()
    assert firsts["6.1"] == firsts["6.3"] == firsts["6.4"] == "base"
    assert firsts["6.2"] == "s2_base"
    for _, row in table.iterrows():
        if row["run"] is None or pd.isna(row["run"]):
            assert row["status"] in (data.NOT_RUN_YET, data.NOT_APPLICABLE)
            assert row[list(data.CHAPTER6_METRICS)].isna().all()
        else:
            assert row["status"] not in (data.NOT_RUN_YET, data.NOT_APPLICABLE)
    status = table.set_index(["configuration", "section", "tag"])["status"]
    assert status["10 servers · normal day", "6.3", "Test 1"] == data.NOT_RUN_YET
    assert status["2 servers · normal day", "6.1", "Test 1"] == data.NOT_RUN_YET
    assert status["2 servers · normal day", "6.2", "Base"] == data.NOT_APPLICABLE
    assert status["10 servers · heavy day", "6.1", "Base"] == data.NOT_RUN_YET


@needs_site_runs
def test_chapter6_base_row_matches_summary_and_schedule():
    ref = BY_KEY[BASE]
    summary = data.load_summary(ref.path)
    row = data.chapter6_row(ref, summary)
    tot, met = summary["optimized"]["totals"], summary["optimized"]["metrics"]
    assert row["release"] == summary["provenance"]["thermasched_version"]
    assert [row["E_crac_zone1_kWh"], row["E_crac_zone2_kWh"]] == tot["E_crac_by_zone_kWh"][:2]
    assert row["E_crac_kWh"] == tot["E_crac_kWh"]
    assert row["E_IT_kWh"] == tot["E_IT_kWh"] and row["E_total_kWh"] == tot["E_total_kWh"]
    assert row["E_cp_Wh"] == pytest.approx(tot["E_cp_kWh"] * 1000)
    assert row["carbon_kg"] == pytest.approx(31.017, abs=1e-3) == tot["carbon_kg"]
    assert row["T_mean_C"] == met["mean_T_C"]
    assert row["T_max_C"] == pytest.approx(73.3, abs=0.05) == met["hottest_T_C"]
    assert row["n_moved_server"] == met["n_reassigned"]
    assert row["n_moved_zone"] == met["n_cross_zone"]
    assert row["n_late"] == met["n_late"] and row["n_throttled_servers"] == \
        met["n_throttled_servers"]
    assert row["pct_late"] == pytest.approx(met["n_late"] / summary["scenario"]["I"] * 100)
    assert (row["status"], row["mip_gap"]) == (summary["solver"]["status"],
                                               summary["solver"]["mip_gap"])
    assert row["time_limit_s"] == summary["settings"]["time_limit_s"] == 1800

    # By hand from schedule.csv and server_period.csv.
    sch = pd.read_csv(ref.path / "optimized" / "schedule.csv")
    sp = pd.read_csv(ref.path / "optimized" / "server_period.csv")
    placed = sch[sch["placed"] == 1]
    assert row["n_unplaced"] == len(sch) - len(placed) == 0
    assert (placed["wait"] == placed["start"] - placed["arrival"]).all()
    assert row["wait_mean_min"] == pytest.approx(placed["wait"].mean() * 5)
    assert row["wait_max_min"] == placed["wait"].max() * 5
    turnaround = placed["finish"] - placed["arrival"]
    assert row["turnaround_mean_min"] == pytest.approx(turnaround.mean() * 5)
    assert row["turnaround_max_min"] == turnaround.max() * 5
    assert row["exec_mean_min"] == pytest.approx(sch["periods_run"].mean() * 5)
    assert row["util_mean_pct"] == pytest.approx(sp["utilization"].mean() * 100)
    assert row["H_mean_C"] == pytest.approx(sp["headroom_C"].mean())
    assert row["DPF_min"] == sp["DPF"].min() == 1.0
    assert row["E_cooling_kWh"] == pytest.approx(row["E_crac_kWh"] + row["E_cp_Wh"] / 1000)


@needs_site_runs
def test_chapter6_changes_against_section_reference():
    table = data.chapter6_table(RUNS)
    changes = data.chapter6_changes(table)
    metrics = list(data.CHAPTER6_METRICS)
    for _, idx in table.groupby(["configuration", "section"], sort=False).groups.items():
        ref = changes.loc[idx[0], metrics]
        if data.has_result(table.loc[[idx[0]]]).iloc[0]:
            assert (ref.dropna() == 0).all() and ref.notna().any()
    others = [c for c in table.columns if c not in metrics]
    pd.testing.assert_frame_equal(changes[others], table[others])
    ten_61 = table.index[(table["configuration"] == "10 servers · normal day")
                         & (table["section"] == "6.1")]
    base, zones = ten_61[0], ten_61[1]          # the Base, then Test 1
    assert changes.at[zones, "E_crac_zone1_kWh"] == pytest.approx(
        (table.at[zones, "E_crac_zone1_kWh"] / table.at[base, "E_crac_zone1_kWh"] - 1) * 100)


def test_chapter6_uses_the_newest_matching_run(tmp_path):
    """Several runs match a test: the table shows the newest, and the catalogue lists every
    match. The folder name decides nothing."""
    import json
    import shutil
    if BASE not in BY_KEY:
        pytest.skip("the servers10 base run is not under results/")
    for name, created in (("old", "2026-01-01T00:00:00Z"), ("new", "2026-12-01T00:00:00Z")):
        dst = tmp_path / "anything" / name
        shutil.copytree(BY_KEY[BASE].path, dst)
        summary = json.loads((dst / "summary.json").read_text())
        summary["provenance"]["created_utc"] = created
        (dst / "summary.json").write_text(json.dumps(summary))
    runs = data.discover_runs(tmp_path)
    cat = data.catalogue(runs)
    used, found = cat[("servers10", "base")]
    assert used.name == "new" and [r.name for r in found] == ["old", "new"]
    assert cat[("servers10", "s1_t1_zones")] == (None, [])
    table = data.chapter6_table(runs, configs=["servers10"])
    assert table.loc[(table["tag"] == "Base") & (table["section"] != "6.2"), "run"].tolist() \
        == ["new"] * 3
    groups = data.config_runs(runs)
    assert [r.name for r in groups["servers10"]] == ["new", "old"]   # used first, then older


@needs_site_runs
def test_config_runs():
    groups = data.config_runs(RUNS)
    assert list(groups) == ["servers10", "servers6"]
    every = [r.key for refs in groups.values() for r in refs]
    assert sorted(every) == sorted(r.key for r in RUNS)            # each run once
    ten = [r.name for r in groups["servers10"]]
    assert ten[:12] == [k.split("/")[1] for k in SERVERS10_TESTS if k.startswith("servers10")]
    assert all(n.startswith("v_") for n in ten[12:])
    mixed = data.config_runs(RUNS + [r for r in ARCHIVED if r.scenario == "archive-small"])
    assert data.OTHER in mixed


def test_chapter6_row_of_a_run_without_optimized_schedule(loaded):
    run = loaded(INFEASIBLE)
    row = data.chapter6_row(run.ref, run.summary)
    assert row["status"] == "infeasible"
    assert not set(data.CHAPTER6_METRICS) & set(row)


@needs_site_runs
def test_reassignment_table(loaded):
    run = loaded(BASE)
    df = data.reassignment_table(run)
    assert len(df) == 238
    assert set(df["Moved"]) <= {"yes", "no"}
    assert (df["Moved"] == "yes").sum() == run.summary["optimized"]["metrics"]["n_reassigned"]
    assert df["Original server"].notna().all() and df["Final server"].notna().all()
    if INFEASIBLE in BY_KEY:
        assert data.reassignment_table(loaded(INFEASIBLE)).empty


# -- Test charts: a test against its Base --------------------------------------------------

@needs_site_runs
def test_same_schedule(loaded):
    base = loaded(BASE)
    assert data.same_schedule(base, base)
    # 6.1 Test 2 keeps the Base's schedule; 6.4 Test 3a (flat carbon intensity) changes it.
    assert data.same_schedule(loaded("servers10/s1_t2_same_zone"), base)
    assert not data.same_schedule(loaded("servers10/s4_t3a_ci_flat"), base)
    if INFEASIBLE in BY_KEY:
        assert not data.same_schedule(loaded(INFEASIBLE), base)


@needs_site_runs
def test_against_base_stacks_the_two_optimized_schedules(loaded):
    test, base = loaded("servers10/s1_t1_zones"), loaded(BASE)
    pair = data.against_base(test, "Test 1", base)
    assert pair.variants == ("Test 1", data.BASE_LABEL)
    for frame in (pair.period, pair.server_period, pair.zone_period, pair.schedule):
        assert set(frame["variant"]) == {"Test 1", data.BASE_LABEL}
    sp = pair.server_period
    # The Base's rows carry this test's zones (Test 1 regroups them), so servers line up.
    zones = test.servers.set_index("s")["zone"]
    assert (sp["zone"] == sp["s"].map(zones)).all()
    base_rows = sp[sp["variant"] == data.BASE_LABEL].set_index(["s", "t"])["temperature_C"]
    opt = base.server_period[base.server_period["variant"] == "optimized"]
    assert base_rows.sort_index().equals(opt.set_index(["s", "t"])["temperature_C"].sort_index())
    alone = data.against_base(test, "Test 1")
    assert alone.variants == ("Test 1",) and set(alone.period["variant"]) == {"Test 1"}
    assert test.variants == ("baseline", "optimized")       # the loaded run is left as it is
