"""The site's pages draw for every configuration, and the configuration picked on one page is
the one the next page opens with."""

from __future__ import annotations

import pytest
from streamlit.testing.v1 import AppTest

from dashboard import data
from scheduler import experiments as ex

ROOT = data.REPO_ROOT
CONFIGS = [c.key for c in ex.CONFIGURATIONS]

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


@pytest.mark.parametrize("config", CONFIGS + ["across"])
@pytest.mark.parametrize("key", [s.key for s in ex.SECTIONS])
def test_section_pages(key, config):
    at = _section(key)
    at.session_state["config"] = config
    at.run()
    _ok(at)
    assert at.segmented_control(key=f"config-{key}").value == config
    if config == "servers2" and key == "6.2":
        assert "does not apply" in at.info[0].value
    elif config == "servers10":
        assert at.dataframe                 # every 10-server section has runs


def test_picking_a_configuration_carries_to_the_next_page():
    at = _section("6.1").run()
    assert at.segmented_control(key="config-6.1").value == "servers10"   # first visit
    at.segmented_control(key="config-6.1").set_value("servers6").run()
    _ok(at)
    assert at.session_state["config"] == "servers6"
    assert at.query_params["config"] == "servers6"

    other = _section("6.4")
    other.session_state["config"] = at.session_state["config"]
    other.run()
    assert other.segmented_control(key="config-6.4").value == "servers6"


def test_the_link_picks_the_configuration():
    at = _section("6.3")
    at.query_params["config"] = "servers6"
    at.run()
    assert at.segmented_control(key="config-6.3").value == "servers6"


@pytest.mark.parametrize("config", CONFIGS)
def test_output_files(config):
    at = _page("from dashboard.views import files\nfiles.render()")
    at.session_state["config"] = config
    at.run()
    _ok(at)
    if config == "servers2":
        assert "No runs" in at.info[0].value
        return
    assert at.session_state[f"run-files-{config}"].startswith(f"{config}/")
    assert at.dataframe and len(at.dataframe[0].value) > 0


def test_output_files_keeps_the_file_across_runs():
    at = _page("from dashboard.views import files\nfiles.render()").run()
    first = at.session_state["run-files-servers10"]
    at.selectbox(key=f"file-{first}").set_value("optimized/server_period.csv").run()
    at.selectbox(key="run-files-servers10").select_index(1).run()
    _ok(at)
    second = at.session_state["run-files-servers10"]
    assert second != first
    assert at.selectbox(key=f"file-{second}").value == "optimized/server_period.csv"
