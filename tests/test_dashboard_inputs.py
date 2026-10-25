"""Inputs page tables (dashboard/inputs.py) against the real scenarios/ folders."""

from __future__ import annotations

import pandas as pd
import pytest

from dashboard import data, inputs

SCENARIOS = inputs.scenarios()
VALIDATION_TABLE = data.VALIDATION_DIR / "thesis10" / "workload_inputs.csv"

pytestmark = pytest.mark.skipif("thesis10" not in SCENARIOS, reason="no scenarios/thesis10")


def test_lists_built_scenarios_without_archives():
    assert "thesis10" in SCENARIOS
    assert not any(data.is_archive(s) for s in SCENARIOS)
    assert SCENARIOS == sorted(SCENARIOS)


@pytest.mark.parametrize("scenario", SCENARIOS)
def test_every_table_builds_for_every_scenario(scenario):
    servers = pd.read_csv(data.SCENARIOS_DIR / scenario / "servers.csv")
    workloads = pd.read_csv(data.SCENARIOS_DIR / scenario / "workloads.csv")
    assert len(inputs.server_table(scenario)) == len(servers)
    assert len(inputs.workload_table(scenario)) == len(workloads)
    assert len(inputs.carbon_table(scenario)) > 0
    assert not inputs.parameter_table(scenario).empty


@pytest.mark.skipif(not VALIDATION_TABLE.is_file(), reason="no thesis10 validation tables")
def test_workload_table_matches_the_release_validation_table():
    built = inputs.workload_table("thesis10")
    released = pd.read_csv(VALIDATION_TABLE)
    assert list(built.columns) == list(released.columns)
    pd.testing.assert_frame_equal(built, released, check_dtype=False)


def test_server_table_units_and_thesis_values():
    t = inputs.server_table("thesis10").set_index("Server")
    rcc165 = t.loc["qh2-rcc165"]
    assert rcc165["Idle power (W)"] == pytest.approx(164.82)
    assert rcc165["Maximum power (W)"] == pytest.approx(328.27)
    assert rcc165["Frequency (MHz per core)"] == 2100
    assert rcc165["Processing capability (MHz)"] == pytest.approx(64 * 2100)
    assert rcc165["RAM (GB)"] == pytest.approx(528286 / 1024, abs=0.05)
    # 2.1 / 2.4 / 3.0 GHz split 4 / 3 / 3, the three cold plates on the 3.0 GHz servers.
    assert t["Frequency (MHz per core)"].value_counts().to_dict() == {2100: 4, 2400: 3, 3000: 3}
    assert set(t.index[t["Cold plates"] > 0]) <= set(t.index[t["Frequency (MHz per core)"] == 3000])


def test_carbon_table_clock_starts_at_period_one():
    c = inputs.carbon_table("thesis10")
    assert c["Period"].iloc[0] == 1 and c["Time"].iloc[0] == "06:00"
    assert c["Time"].iloc[1] == "06:05"
    assert len(c) == 288


def test_parameter_table_reads_params_json():
    p = inputs.parameter_table("thesis10").set_index("Parameter")["Value"]
    assert p["DVFS onset temperature"] == "75"
    assert p["Thermal throttling temperature"] == "100"
    assert p["Remaining performance fraction"] == "0.622"
    assert p["Thermal cap (T_max − H_min)"] == "80"
    assert p["CRAC supply-air temperature range"] == "18–27"
    assert p["Coolant (inlet water) temperature range"] == "20.00–39.95"
    assert p["Delay-tolerant workloads: extra time"] == "2 × runtime, within 2–8 h"
    assert p["Time-sensitive workloads: extra time"] == "25% of runtime, at least 5 min"
    assert p["Planning horizon"] == "288 periods (24 h)"


def test_clock_wraps_past_midnight_and_needs_a_start_hour():
    assert inputs.clock(1, 23.5, 300) == "23:30"
    assert inputs.clock(7, 23.5, 300) == "00:00"
    assert inputs.clock(1, None, 300) is None
