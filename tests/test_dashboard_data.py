"""Dashboard loaders (dashboard/data.py) against the real folders under results/."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from dashboard import data

RUNS = data.discover_runs()
BY_KEY = {r.key: r for r in RUNS}
INFEASIBLE = "archive-small/infeasible_demo_hmin20"
CONSOLIDATED6_FREE = "archive-consolidated6/least_loaded_base18_free_optimize"
SMALL_FREE = "archive-small/least_loaded_base18_free_optimize"
FASTEST = "archive-small/fastest_first_base27_free_optimize"

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
    assert RUNS == sorted(RUNS, key=data.run_order)        # current scenarios, then archives
    archived = [data.is_archive(r.scenario) for r in RUNS]
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
    df = data.compare_runs([r for r in RUNS if r.scenario == "archive-small"]).set_index("run")
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
    servers = pd.read_csv(data.SCENARIOS_DIR / "consolidated6" / "servers.csv")
    assert dict(zip(run.servers["s"], run.servers["name"])) == \
        dict(zip(servers["s"], servers["server"]))
    assert run.server_name(1) == "qh2-rcc188"
    assert run.servers["zone"].is_monotonic_increasing          # grouped by zone
    assert run.servers["label"].iloc[0].endswith("(Z1)")
    sch = run.schedule
    assert not sch["server_name"].isna().any()


def test_savings_breakdown_adds_up(loaded):
    run = loaded(CONSOLIDATED6_FREE)
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
    kpis = data.kpi_frame(loaded(CONSOLIDATED6_FREE).summary).set_index("key")
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
    assert data.throttled_servers(loaded(CONSOLIDATED6_FREE)).empty
    checks = data.checks_frame(loaded(CONSOLIDATED6_FREE).summary)
    assert checks["passed"].tolist() == [True, True, True]


def test_unzipped_export_carries_its_scenario(tmp_path):
    """A run export unzipped into results/ shows server names and clock times even when
    the scenario is not in scenarios/ (a scenario built in a notebook elsewhere)."""
    import io
    import zipfile

    from dashboard import uploads

    src = data.RESULTS_DIR / "archive-small"
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


# -- Chapter 6 labels and results table --------------------------------------------------

BASE = "thesis10/least_loaded_base18_free_optimize"
# docs/PRD_CH6_RESULTS.md §1.1: the 1.0.1 runs of thesis10 and their labels.
THESIS10_LABELS = {
    BASE: ["6.1 Base", "6.3 Base 10 °C safety margin", "6.4 Reassignment allowed"],
    "thesis10/least_loaded_base18_free_optimize_zones1111222222": ["6.1 Regrouped zones"],
    "thesis10/least_loaded_base18_same_zone_optimize": ["6.1 Same-zone moves only"],
    "thesis10/least_loaded_base18_free_optimize_cp_cpfixed":
        ["6.2 CRAC changed, cold plates fixed"],
    "thesis10/least_loaded_base18_free_fixed18_cp": ["6.2 Cold plates changed, CRAC fixed"],
    "thesis10/least_loaded_base18_free_optimize_hmin5": ["6.3 Low 5 °C safety margin"],
    "thesis10/least_loaded_base18_free_optimize_hmin15": ["6.3 High 15 °C safety margin"],
    "thesis10/least_loaded_base18_none_optimize": ["6.4 No reassignment"],
    "thesis10/least_loaded_base18_free_optimize_ciflat_tl1800": ["6.4 Flat carbon intensity"],
}
needs_thesis10 = pytest.mark.skipif(not set(THESIS10_LABELS) <= set(BY_KEY),
                                    reason="the 1.0.1 thesis10 runs are not under results/")


def _titles(key: str) -> list[str]:
    ref = BY_KEY[key]
    return [tr.title for tr in data.thesis_labels(data.load_summary(ref.path), ref.scenario)]


@needs_thesis10
@pytest.mark.parametrize("key", sorted(THESIS10_LABELS))
def test_thesis10_runs_get_their_labels(key):
    assert _titles(key) == THESIS10_LABELS[key]


@needs_thesis10
def test_label_text_and_map():
    texts = data.thesis_label_texts(RUNS)
    assert texts[BASE] == "6.1 Base / 6.3 Base 10 °C safety margin / 6.4 Reassignment allowed"
    assert {k for k, r in BY_KEY.items() if r.scenario != "thesis10"}.isdisjoint(texts)
    row = data.compare_runs([BY_KEY[BASE]]).iloc[0]
    assert row["thesis_label"] == texts[BASE]
    assert list(data.compare_runs([BY_KEY[BASE]]).columns[:3]) == ["scenario", "run",
                                                                  "thesis_label"]


def test_archived_and_other_scenarios_get_no_label():
    others = [k for k, r in BY_KEY.items() if r.scenario != "thesis10"]
    assert any(data.is_archive(BY_KEY[k].scenario) for k in others)
    assert any(BY_KEY[k].scenario == "consolidated6" for k in others)
    for key in others:
        assert _titles(key) == [], key
    # An archived thesis10 run carries thesis10 in its summary.json; the folder decides.
    archived = BY_KEY.get("archive-thesis10/least_loaded_base18_free_optimize")
    if archived is not None:
        summary = data.load_summary(archived.path)
        assert data.thesis_labels(summary, archived.scenario) == []


def test_labels_match_settings_not_names():
    blind = {"scenario": {"name": "thesis10"}, "settings": {"placement": "thermal_blind"}}
    assert [tr.title for tr in data.thesis_labels(blind)] == \
        ["6.4 Temperature ignored when choosing servers"]
    # A run made before a switch existed (no "placement", no "ci_flat") is at the defaults.
    old = {"scenario": {"name": "thesis10"},
           "settings": {"reassignment": "free", "time_limit_s": 1800, "run_name": "x"}}
    assert [tr.title for tr in data.thesis_labels(old)] == \
        ["6.1 Base", "6.3 Base 10 °C safety margin", "6.4 Reassignment allowed"]
    two = {"scenario": {"name": "thesis10"},
           "settings": {"reassignment": "none", "H_min_C": 5}}
    assert data.thesis_labels(two) == []                   # two switches: no label
    assert data.thesis_labels({"scenario": {"name": "consolidated6"}, "settings": {}}) == []
    assert data.thesis_labels(blind, "archive-thesis10") == []


@needs_thesis10
def test_chapter6_table_rows_and_columns():
    table = data.chapter6_table(RUNS)
    assert len(table) == len(data.THESIS_RUNS) == 13
    assert list(table.columns) == list(data.CHAPTER6_COLUMNS)
    assert list(zip(table["section"], table["label"])) == \
        [(tr.section, tr.label) for tr in data.THESIS_RUNS]
    assert table["section"].tolist() == sorted(table["section"])
    # One base run is the reference (first row) of 6.1, 6.3 and 6.4; which one is the newest
    # match, so a later rerun of the base may take the place of BASE.
    firsts = table.groupby("section", sort=False)["run"].first()
    assert firsts["6.1"] == firsts["6.3"] == firsts["6.4"]
    assert "6.1 Base" in _titles(f"thesis10/{firsts['6.1']}")
    for _, row in table.iterrows():
        if row["run"] is None or pd.isna(row["run"]):
            assert row["status"] == data.NOT_RUN_YET
            assert row[list(data.CHAPTER6_METRICS)].isna().all()
        else:
            assert row["status"] != data.NOT_RUN_YET


@needs_thesis10
def test_chapter6_base_row_matches_summary_and_schedule():
    ref = BY_KEY[BASE]
    summary = data.load_summary(ref.path)
    row = data.chapter6_row(ref, summary)
    tot, met = summary["optimized"]["totals"], summary["optimized"]["metrics"]
    assert row["release"] == summary["provenance"]["thermasched_version"]
    assert [row["E_crac_zone1_kWh"], row["E_crac_zone2_kWh"]] == tot["E_crac_by_zone_kWh"][:2]
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
    assert row["time_limit_s"] == summary["settings"]["time_limit_s"]

    # By hand from schedule.csv: wait and finish - arrival, in 5-minute periods.
    sch = pd.read_csv(ref.path / "optimized" / "schedule.csv")
    placed = sch[sch["placed"] == 1]
    assert row["n_unplaced"] == len(sch) - len(placed) == 0
    assert (placed["wait"] == placed["start"] - placed["arrival"]).all()
    assert row["wait_mean_min"] == pytest.approx(placed["wait"].mean() * 5)
    assert row["wait_max_min"] == placed["wait"].max() * 5
    turnaround = placed["finish"] - placed["arrival"]
    assert row["turnaround_mean_min"] == pytest.approx(turnaround.mean() * 5)
    assert row["turnaround_max_min"] == turnaround.max() * 5
    assert row["wait_mean_min"] == pytest.approx(71.28, abs=0.01)
    assert row["turnaround_mean_min"] == pytest.approx(229.94, abs=0.01)


@needs_thesis10
def test_chapter6_changes_against_section_reference():
    table = data.chapter6_table(RUNS)
    changes = data.chapter6_changes(table)
    metrics = list(data.CHAPTER6_METRICS)
    for _, idx in table.groupby("section", sort=False).groups.items():
        ref = changes.loc[idx[0], metrics]
        if table.loc[idx[0], "status"] != data.NOT_RUN_YET:
            assert (ref.dropna() == 0).all() and ref.notna().any()
    # Non-metric columns are left as they are.
    others = [c for c in table.columns if c not in metrics]
    pd.testing.assert_frame_equal(changes[others], table[others])
    zones = table.index[table["label"] == "Regrouped zones"][0]
    assert changes.at[zones, "E_crac_zone1_kWh"] == pytest.approx(
        (table.at[zones, "E_crac_zone1_kWh"] / table.at[0, "E_crac_zone1_kWh"] - 1) * 100)


def test_chapter6_uses_the_newest_matching_run(tmp_path):
    """Several runs match a label: the table shows the newest, and lists every match."""
    import json
    import shutil
    if BASE not in BY_KEY:
        pytest.skip("the thesis10 base run is not under results/")
    for name, created in (("old", "2026-01-01T00:00:00Z"), ("new", "2026-12-01T00:00:00Z")):
        dst = tmp_path / "thesis10" / name
        shutil.copytree(BY_KEY[BASE].path, dst)
        summary = json.loads((dst / "summary.json").read_text())
        summary["provenance"]["created_utc"] = created
        (dst / "summary.json").write_text(json.dumps(summary))
    runs = data.discover_runs(tmp_path)
    entries = {tr.title: (used, found) for tr, used, found in data.chapter6_runs(runs)}
    used, found = entries["6.1 Base"]
    assert used.name == "new" and [r.name for r in found] == ["old", "new"]
    assert entries["6.1 Regrouped zones"] == (None, [])
    table = data.chapter6_table(runs)
    assert table.loc[table["label"] == "Base", "run"].tolist() == ["new"]
    assert (table.loc[table["run"].isna(), "status"] == data.NOT_RUN_YET).all()


def test_chapter6_row_of_a_run_without_optimized_schedule(loaded):
    run = loaded(INFEASIBLE)
    row = data.chapter6_row(run.ref, run.summary)
    assert row["status"] == "infeasible"
    assert not set(data.CHAPTER6_METRICS) & set(row)
