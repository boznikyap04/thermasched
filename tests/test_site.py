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
    at.selectbox(key=f"file-{first}").set_value("optimized/server_period.csv").run()
    at.selectbox(key="run-files-servers6").select_index(1).run()
    _ok(at)
    second = at.session_state["run-files-servers6"]
    assert second != first
    assert at.selectbox(key=f"file-{second}").value == "optimized/server_period.csv"


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
    assert at.metric                                        # the key results
    assert at.get("plotly_chart")
    toggle = at.toggle(key="detail_base")
    assert toggle.disabled == (test == "Base")


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
    at = _section("6.1")
    at.session_state["config"] = "servers6"
    at.session_state["level"] = "light"
    at.run()
    assert any("same optimized schedule" in c.value for c in at.caption)


def test_per_tick_run_shows_its_ticks():
    """A per-tick run's solver block counts the ticks at the cap and charts every tick, and
    says nothing of a whole-day time limit or best bound."""
    at = _charts("servers6", "6.1", "Test 1", level="heavy")
    _ok(at)
    labels = {m.label for m in at.metric}
    assert {"Ticks at the cap", "Worst tick's MIP gap"} <= labels
    assert "Best bound" not in labels
    assert next(m.value for m in at.metric if m.label == "Ticks at the cap").endswith("of 288")
    assert any("Re-planned at each of 288 ticks" in c.value for c in at.caption)
    assert not any("Time limit:" in md.value for md in at.markdown)
