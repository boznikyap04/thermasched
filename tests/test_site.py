"""The site's pages draw for every server count and load level, and the choice made on one page
is the one the next page opens with. Test charts draws every test and topic."""

from __future__ import annotations

import pytest
from streamlit.testing.v1 import AppTest

from dashboard import data
from scheduler import experiments as ex

ROOT = data.REPO_ROOT
CONFIGS = list(ex.FLEETS)
LEVELS = [lv.key for lv in ex.LEVELS]

pytestmark = pytest.mark.skipif(not data.discover_runs(), reason="no runs under results/")
CATALOGUE = data.catalogue(data.discover_runs())


def _has_run(config: str, test_id: str) -> bool:
    """True when the test has a run. The 1.4.0 runs with cold plates off are no test's run
    since plates became the default; their tests wait for the re-run."""
    return CATALOGUE[(config, test_id)][0] is not None


def _page(call: str) -> AppTest:
    script = f"import sys\nsys.path.insert(0, {str(ROOT)!r})\n{call}\n"
    return AppTest.from_string(script, default_timeout=120)


def _section(key: str) -> AppTest:
    return _page(f"from dashboard.views import section\nsection.page({key!r})()")


def _ok(at: AppTest) -> None:
    assert not at.exception, [e.value for e in at.exception]
    assert not at.error, [e.value for e in at.error]


def test_overview():
    at = _page("from dashboard.views import chapter6\nchapter6.render()").run()
    _ok(at)
    assert at.dataframe
    assert any(data.cold_plate_server_text() in c.value for c in at.caption)
    assert not any("MHz" in c.value for c in at.caption)
    # the 2-server fleet has no run in this release, and says so
    assert any("Not run in this release: 2 servers (every load level)" in c.value for c in at.caption)
    grid = at.dataframe[0].value.set_index("Test")
    assert grid["2 · heavy"].isin(["–", "n/a"]).all()
    # a configuration in the release: "·" (not run yet) exactly where a test has no run, as
    # for 6.5 on 10 servers; every test of 6.1 to 6.4 has its run on the heavy day
    for section in ex.SECTIONS:
        for tag, tid in section.tests:
            row = "Base (every section)" if tag == "Base" else \
                f"{section.key} · {tag} · {ex.TEST_BY_ID[tid].name}"
            for fleet in ("servers10", "servers6"):
                cell = grid.loc[row, f"{fleet.removeprefix('servers')} · heavy"]
                assert (cell == "·") == (not _has_run(f"{fleet}_heavy", tid)), (row, fleet)
                assert section.key == "6.5" or cell != "·", (row, fleet)
    # stuck runs say at which tick, and why, in the grid and in a note
    assert grid.loc["6.3 · Test 1 · High safety margin, 19 °C", "6 · heavy"] == \
        "⛔ stuck at tick 122, no schedule in cap"
    assert grid.loc["Base (every section)", "6 · heavy"].startswith("⏱ 29 at cap")
    assert grid.loc["6.4 · Test 1 · No reassignment (r_is = 0)", "6 · heavy"] == "✅ every tick"
    assert grid.loc["6.4 · Test 1 · No reassignment (r_is = 0)", "10 · heavy"] == \
        "⛔ stuck at tick 71, no valid schedule"
    note = next(i.value for i in at.info if "Stuck runs" in i.value)
    assert "5 on 10 servers · heavy day, 1 on 6 servers · heavy day" in note


@pytest.mark.parametrize("config,level", [(c, lv) for c in CONFIGS + ["across"]
                                          for lv in LEVELS + ["across"]
                                          if "across" not in (c, lv) or c != lv])
@pytest.mark.parametrize("key", [s.key for s in ex.SECTIONS])
def test_section_pages(key, config, level):
    at = _section(key)
    at.session_state["config"] = config
    at.session_state["level"] = level
    at.run()
    _ok(at)
    assert at.segmented_control(key=f"config-{key}").value == config
    assert at.segmented_control(key=f"level-{key}").value == level
    if config == "servers2" and key == "6.2" and level != "across":
        assert "does not apply" in at.info[0].value
        assert data.cold_plate_server_text() in at.info[0].value
    if config != "across" and level != "across":
        fleet = data.fleet_text(ex.configuration(config, level))
        assert any(fleet in c.value for c in at.caption)
    elif (config, level) == ("servers6", "normal"):
        assert at.dataframe                 # every 6-server section has runs (at least its base)


def test_across_both_is_never_offered():
    at = _section("6.1")
    at.session_state["level"] = "across"
    at.run()
    _ok(at)
    assert "across" not in at.segmented_control(key="config-6.1").options
    at.segmented_control(key="level-6.1").set_value("normal").run()
    at.segmented_control(key="config-6.1").set_value("across").run()
    _ok(at)
    assert "across" not in at.segmented_control(key="level-6.1").options


def test_picking_a_configuration_carries_to_the_next_page():
    at = _section("6.1").run()
    assert at.segmented_control(key="config-6.1").value == "servers10"   # first fleet with runs
    assert at.segmented_control(key="level-6.1").value == "normal"
    at.segmented_control(key="config-6.1").set_value("servers2").run()
    _ok(at)
    assert at.session_state["config"] == "servers2"
    assert at.query_params["config"] == "servers2"

    other = _section("6.4")
    at.segmented_control(key="level-6.1").set_value("heavy").run()
    assert at.query_params["level"] == "heavy"
    other.session_state["config"] = at.session_state["config"]
    other.session_state["level"] = at.session_state["level"]
    other.run()
    assert other.segmented_control(key="config-6.4").value == "servers2"
    assert other.segmented_control(key="level-6.4").value == "heavy"


def test_the_link_picks_the_configuration():
    at = _section("6.3")
    at.query_params["config"] = "servers6"
    at.run()
    assert at.segmented_control(key="config-6.3").value == "servers6"


@pytest.mark.parametrize("level", LEVELS)
@pytest.mark.parametrize("fleet", CONFIGS)
def test_output_files(fleet, level):
    at = _page("from dashboard.views import files\nfiles.render()")
    at.session_state["config"] = fleet
    at.session_state["level"] = level
    at.run()
    _ok(at)
    config = ex.configuration(fleet, level).key
    if config not in data.config_runs(data.discover_runs()):
        assert "No runs" in at.info[0].value
        return
    assert at.session_state[f"run-files-{config}"].startswith(f"{config}/")
    assert at.dataframe and len(at.dataframe[0].value) > 0


def test_output_files_keeps_the_file_across_runs():
    at = _page("from dashboard.views import files\nfiles.render()")
    at.session_state["config"] = "servers6"
    at.session_state["level"] = "normal"
    at.run()
    first = at.session_state["run-files-servers6"]
    at.selectbox(key=f"file-{first}").set_value("baseline/server_period.csv").run()
    at.selectbox(key="run-files-servers6").select_index(1).run()      # 6.1 Test 1, stuck
    _ok(at)
    second = at.session_state["run-files-servers6"]
    assert second != first
    assert at.selectbox(key=f"file-{second}").value == "baseline/server_period.csv"


def test_output_files_of_a_stuck_run_open_on_its_partial_schedule():
    at = _page("from dashboard.views import files\nfiles.render()")
    at.session_state["config"] = "servers6"
    at.session_state["level"] = "heavy"
    at.run()
    at.selectbox(key="run-files-servers6_heavy").select_index(5).run()   # 6.3 Test 1, stuck
    _ok(at)
    run = at.session_state["run-files-servers6_heavy"]
    assert run == "servers6_heavy/s3_t1_hmin_high"
    assert at.selectbox(key=f"file-{run}").value == "partial_schedule.csv"
    assert any("stuck run's schedule" in c.value for c in at.caption)


def _charts(config: str, section: str, test: str, topic: str = "Servers",
            level: str = "normal") -> AppTest:
    at = _page("from dashboard.views import detail\ndetail.render()")
    at.session_state["config"] = config
    at.session_state["level"] = level
    at.session_state["section"] = section
    at.session_state["test"] = test
    at.session_state["topic"] = topic
    return at.run()


@pytest.mark.parametrize("topic", ["Servers", "Cooling", "Energy and carbon", "Workloads"])
@pytest.mark.parametrize("section,test", [(s.key, tag) for s in ex.SECTIONS
                                          for tag, _ in s.tests])
def test_test_charts_6_servers(section, test, topic):
    at = _charts("servers6", section, test, topic)
    _ok(at)
    assert at.segmented_control(key="test-detail").value == test
    if any("No run" in i.value for i in at.info):
        return
    assert at.metric                                        # the key results, or the ticks
    assert at.get("plotly_chart")
    if any("No full-day result" in w.value for w in at.warning):     # stuck: no topics
        assert any(m.label == "Stuck at tick" for m in at.metric)
        return
    toggle = at.toggle(key="detail_base")
    base_stuck = any("has no full-day schedule" in c.value for c in at.caption)
    assert toggle.disabled == (test == "Base" or base_stuck)


@pytest.mark.parametrize("config", ["servers6", "servers2"])
def test_test_charts_other_configurations(config):
    at = _charts(config, "6.2", "Test 1")
    _ok(at)
    if config == "servers2":
        assert "does not apply" in at.info[0].value
    else:
        assert at.metric                    # 6.2 Test 1 has a run on six servers
    _ok(_charts(config, "6.1", "Base"))


def test_test_charts_say_when_a_test_keeps_the_base_schedule():
    # per-tick results: on the light day, regrouping the zones leaves the schedule as it is
    if not _has_run("servers6_light", "s1_t1_zones"):
        pytest.skip("6.1 Test 1 on the light day waits for the cold-plate re-run")
    at = _charts("servers6", "6.1", "Test 1", level="light")
    assert any("same optimized schedule as the Base" in i.value for i in at.info)
    assert not _charts("servers6", "6.1", "Test 2", level="light").info


def test_test_charts_keep_the_test_when_the_scenario_changes():
    at = _charts("servers10", "6.4", "Test 3b")
    at.segmented_control(key="section-detail").set_value("6.1").run()
    _ok(at)
    assert at.segmented_control(key="test-detail").value == "Base"   # 6.1 has no Test 3b
    assert at.session_state["test"] == "Test 3b"                    # kept for 6.4
    at.segmented_control(key="section-detail").set_value("6.4").run()
    assert at.segmented_control(key="test-detail").value == "Test 3b"
    assert at.query_params["section"] == "6.4" and at.query_params["test"] == "Test 3b"


def test_scenario_page_says_which_tests_keep_the_base_schedule():
    if not _has_run("servers6_light", "s1_t1_zones"):
        pytest.skip("6.1 Test 1 on the light day waits for the cold-plate re-run")
    at = _section("6.1")
    at.session_state["config"] = "servers6"
    at.session_state["level"] = "light"
    at.run()
    assert any("same optimized schedule" in c.value for c in at.caption)


def test_per_tick_run_shows_its_ticks():
    """A per-tick run's solver block counts the ticks at the cap and charts every tick, and
    says nothing of a whole-day time limit or best bound."""
    at = _charts("servers6", "6.2", "Test 1")       # 36 of 288 ticks at the cap
    _ok(at)
    labels = {m.label for m in at.metric}
    assert {"Ticks at the cap", "Worst tick's MIP gap"} <= labels
    assert "Best bound" not in labels
    assert next(m.value for m in at.metric if m.label == "Ticks at the cap").endswith("of 288")
    assert any("Re-planned at each of 288 ticks" in c.value for c in at.caption)
    assert not any("Time limit:" in md.value for md in at.markdown)


def test_stuck_run_says_where_and_why():
    """A run stuck at a tick is a result: its page says at which tick (and when), why, and
    what it keeps, and charts the ticks up to it, as a warning, not an error."""
    at = _charts("servers6", "6.3", "Test 1", level="heavy")
    _ok(at)
    text = next(w.value for w in at.warning if "No full-day result" in w.value)
    assert "Stuck at tick 122 of 288" in text and "within the 60 s per-tick cap" in text
    metrics = {m.label: m.value for m in at.metric}
    assert metrics["Stuck at tick"] == "122 of 288"
    assert metrics["Ticks at the cap"] == "16 of 121 solved"
    assert any("Partial schedule" in c.value for c in at.caption)
    assert at.get("plotly_chart")                           # solve time of every tick
    assert not at.toggle                                    # no topics without a full day


def test_section_page_with_stuck_runs():
    at = _section("6.3")
    at.session_state["config"] = "servers6"
    at.session_state["level"] = "heavy"
    at.run()
    _ok(at)
    note = next(i.value for i in at.info if "Stuck runs" in i.value)
    assert "**Test 1** at tick 122 (no schedule within the 60 s cap)" in note
    table = at.dataframe[0].value.set_index("Measure")
    assert table.loc["Solver status", "Test 1: High safety margin, 19 °C"] == \
        "Stuck at tick 122: no schedule within the 60 s cap"
    assert not any("No run of this section has a full-day schedule" in c.value
                   for c in at.caption)


@pytest.mark.parametrize("key", [s.key for s in ex.SECTIONS])
def test_a_configuration_not_run_in_this_release(key):
    at = _section(key)
    at.session_state["config"] = "servers2"
    at.session_state["level"] = "heavy"
    at.run()
    _ok(at)
    if key == "6.2":                        # no cold plate on 2 servers: 6.2 does not apply
        assert "does not apply" in at.info[0].value
    else:
        assert "2 servers · heavy day is not run in this release" in at.info[0].value
    at = _charts("servers2", key, "Base", level="heavy")
    _ok(at)
    assert "not run in this release" in at.info[0].value


# -- 6.5: the ablation ------------------------------------------------------------------------

def test_every_section_has_its_page():
    from dashboard.views import section
    keys = {s.key for s in ex.SECTIONS}
    assert set(section.SHORT_TITLES) == set(section.ICONS) == keys
    assert section.MOVES <= keys


def test_ablation_page_without_its_runs():
    """6.5 before its runs: the Base's column filled, Models A and B 'not run yet'."""
    if _has_run("servers6", "s5_t1_no_wait") or _has_run("servers6", "s5_t2_no_dpf"):
        pytest.skip("6.5 has runs on 6 servers")
    at = _section("6.5")
    at.session_state["config"] = "servers6"
    at.session_state["level"] = "normal"
    at.run()
    _ok(at)
    table = at.dataframe[0].value.set_index("Measure")
    a, b = ("Model A: Starts on arrival, planner without slowdown",
            "Model B: Flexible starts, planner without slowdown")
    assert list(table.columns) == ["Base", a, b]
    assert table.loc["Solver status", a] == table.loc["Solver status", b] == data.NOT_RUN_YET
    assert (table.loc["Total carbon emissions (kg CO2)", [a, b]] == "–").all()
    assert table.loc["Total carbon emissions (kg CO2)", "Base"] != "–"
    assert any("Model A: not run yet · Model B: not run yet" in c.value for c in at.caption)
    # the per-server table opens on the workloads each server ran
    assert at.selectbox(key="server-stat-6.5").value == "n_workloads"
    at = _charts("servers6", "6.5", "Model A")
    _ok(at)
    assert "No run of 6.5 Model A for 6 servers · normal day yet." in at.info[0].value


def _ablation_results(tmp_path):
    """A results folder with the 6-server light day's Base and two made-up 6.5 runs: Model A,
    the Base's outputs under Model A's settings (a full day), and Model B stuck after the last
    tick (every tick planned, ticks.csv as the Base's, work left at the end)."""
    import json
    import shutil
    src = ROOT / "results" / "servers6_light" / "base"
    root = tmp_path / "results"
    shutil.copytree(src, root / "servers6_light" / "base")
    for name, switches in (("s5_t1_no_wait", {"start_at_arrival": True, "planner_dpf": False}),
                           ("s5_t2_no_dpf", {"planner_dpf": False})):
        dst = root / "servers6_light" / name
        shutil.copytree(src, dst)
        summary = json.loads((dst / "summary.json").read_text())
        summary["settings"].update(switches, run_name=name)
        if name == "s5_t2_no_dpf":
            shutil.rmtree(dst / "optimized")
            T = summary["scenario"]["T"]
            summary.update(has_optimized_schedule=False, optimized=None)
            summary["solver"] = {"status": "infeasible", "solve_time_s": 100.0}
            summary["per_tick"].update(outcome="stuck", stuck={
                "tick": T, "status": "infeasible", "n_waiting": 0, "n_running": 2,
                "workloads": ["w0001", "w0002"], "limits": ["deadlines_and_waiting"],
                "limit_text": "deadlines", "detail": "running workload(s) ['w0001', 'w0002'] "
                "still had work left after the last tick"})
            (dst / "partial_schedule.csv").write_text(
                "i,workload_id,server,start,end\n1,w0001,1,200,\n2,w0002,2,250,\n3,w0003,1,3,9\n")
        (dst / "summary.json").write_text(json.dumps(summary))
    return root


def test_ablation_page_with_its_runs(tmp_path, monkeypatch):
    monkeypatch.setattr(data, "RESULTS_DIR", _ablation_results(tmp_path))
    at = _section("6.5")
    at.session_state["config"] = "servers6"
    at.session_state["level"] = "light"
    at.run()
    _ok(at)
    table = at.dataframe[0].value.set_index("Measure")
    a, b = ("Model A: Starts on arrival, planner without slowdown",
            "Model B: Flexible starts, planner without slowdown")
    carbon = "Total carbon emissions (kg CO2)"
    assert table.loc[carbon, a] == table.loc[carbon, "Base"] != "–"
    assert table.loc[carbon, b] == "–"                   # stuck: no full-day figures
    assert table.loc["Solver status", b] == \
        "Stuck at tick 288: work left after the last tick (deadlines)"
    note = next(i.value for i in at.info if "Stuck runs" in i.value)
    assert "**Model B** at tick 288 (work left after the last tick (deadlines))" in note
    assert "*Work left after the last tick* means every tick had a schedule" in note
    assert any("Left out of the chart and the tables below" in c.value and "Model B" in c.value
               for c in at.caption)
    # per server: the workloads each server ran, for the Base and Model A
    servers = at.dataframe[1].value
    assert list(servers.columns[-2:]) == ["Base", "Model A"]
    assert servers["Base"].sum() == servers["Model A"].sum() == 91
    assert at.get("plotly_chart")                        # completion time, Base and Model A

    at = _charts("servers6", "6.5", "Model B", level="light")
    _ok(at)
    text = next(w.value for w in at.warning if "No full-day result" in w.value)
    assert "Stuck after the last tick, 288 of 288" in text and "All 288 ticks" in text
    assert {m.label: m.value for m in at.metric}["Stuck at tick"] == "288 of 288"
    assert any("no bar marks the stop" in c.value for c in at.caption)
    assert any("still running after the last tick" in c.value for c in at.caption)
    assert not at.toggle

    at = _charts("servers6", "6.5", "Model A", level="light")
    _ok(at)
    assert not at.toggle(key="detail_base").disabled     # compared with the Base

    at = _page("from dashboard.views import chapter6\nchapter6.render()").run()
    _ok(at)
    grid = at.dataframe[0].value.set_index("Test")
    assert grid.loc["6.5 · Model B · Flexible starts, planner without slowdown", "6 · light"] \
        == "⛔ stuck at tick 288, work left after the last tick"
    assert grid.loc["6.5 · Model A · Starts on arrival, planner without slowdown",
                    "6 · light"] == "✅ every tick"

    at = _page("from dashboard.views import files\nfiles.render()")
    at.session_state["config"] = "servers6"
    at.session_state["level"] = "light"
    at.run()
    _ok(at)
