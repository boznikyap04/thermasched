"""The Chapter 6 configurations and tests (scheduler/experiments.py) and how runs match them."""

from __future__ import annotations

import pytest

from scheduler import experiments as ex


def _ids(settings: dict, scenario: str) -> list[str]:
    return [t.id for t in ex.identify(settings, scenario)[1]]


def test_configurations():
    assert list(ex.FLEETS) == ["servers10", "servers6", "servers2"]
    assert [c.key for c in ex.CONFIGURATIONS] == [
        f"servers{n}{suffix}" for n in (10, 6, 2) for suffix in ("_light", "", "_heavy")]
    assert ex.configuration("servers10").label == "10 servers · normal day"
    assert ex.configuration("servers2", "heavy").label == "2 servers · heavy day"
    assert [lv.target for lv in ex.LEVELS] == [0.30, 0.60, 0.85]
    assert ex.FLEETS["servers2"].fleet == "2 mid"
    ten = ex.FLEETS["servers10"]
    assert ten.tiers.count("slow") == 4 and ten.tiers.count("fast") == 3
    assert len(ten.regroup_zone_map) == ten.n_servers
    assert all(len(c.regroup_zone_map or c.tiers) == c.n_servers for c in ex.CONFIGURATIONS)


def test_a_scenario_name_gives_the_load_level():
    assert ex.identify({}, "servers10_light")[0].key == "servers10_light"
    assert ex.identify({}, "servers6_heavy_swing") == (
        ex.configuration("servers6", "heavy"), [ex.TEST_BY_ID["s4_t3b_ci_swing"]])
    # The earlier names are the normal day.
    assert ex.identify({}, "thesis10")[0].key == "servers10"
    assert ex.identify({}, "consolidated6_swing")[0].key == "servers6"
    assert ex.identify({}, "thesis10_light") == (None, [])


def test_sections_list_known_tests_with_the_reference_first():
    for section in ex.SECTIONS:
        assert section.tests[0][0] == "Base"
        assert all(tid in ex.TEST_BY_ID for _, tid in section.tests)
    used = {tid for s in ex.SECTIONS for _, tid in s.tests}
    assert used == set(ex.TEST_BY_ID)
    assert [s.key for s, _ in ex.sections_of("base")] == ["6.1", "6.3", "6.4"]


def test_not_applicable_tests():
    config = ex.FLEETS
    regroup, cold = ex.TEST_BY_ID["s1_t1_zones"], ex.TEST_BY_ID["s2_base"]
    assert ex.applicable(regroup, config["servers2"])
    assert not ex.applicable(cold, config["servers2"])
    assert all(ex.applicable(t, config["servers10"]) for t in ex.TESTS)


def test_matching_by_settings():
    assert _ids({}, "thesis10") == ["base"]
    assert _ids({}, "servers10") == ["base"]
    assert _ids({}, "consolidated6") == ["base"]
    assert _ids({"reassignment": "none"}, "thesis10") == ["s4_t1_no_moves"]
    assert _ids({"zone_map": [1, 1, 1, 1, 2, 2, 2, 2, 2, 2]}, "thesis10") == ["s1_t1_zones"]
    assert _ids({"zone_map": [1, 1, 2, 2, 2, 2]}, "consolidated6") == ["s1_t1_zones"]
    assert _ids({"cold_plates": True, "cp_mode": "fixed"}, "thesis10") == ["s2_t1_crac"]
    assert _ids({"H_min_C": 19}, "thesis10") == ["s3_t1_hmin_high"]
    assert _ids({"placement": "thermal_blind"}, "servers6") == ["s4_t2_blind"]
    # Names, time limits and gaps never decide a test.
    assert _ids({"run_name": "x", "time_limit_s": 60, "mip_rel_gap": 0.1}, "thesis10") == ["base"]
    # Two switches at once: no test.
    assert _ids({"reassignment": "none", "H_min_C": 5}, "thesis10") == []
    # A random baseline, another scenario, an unknown carbon file: no test.
    assert _ids({"baseline_rule": "random"}, "thesis10") == []
    assert ex.identify({}, "thesis10_tight") == (None, [])
    assert _ids({"carbon_file": "x.csv"}, "thesis10") == []


def test_carbon_intensity_is_one_switch():
    """Flat carbon (the old ci_flat switch), the swing scenario and a future ci_amplitude
    switch all map to ci_amplitude."""
    assert _ids({"ci_flat": True}, "thesis10") == ["s4_t3a_ci_flat"]
    assert _ids({"ci_amplitude": 0.0}, "servers10") == ["s4_t3a_ci_flat"]
    assert _ids({}, "thesis10_swing") == ["s4_t3b_ci_swing"]
    assert _ids({"ci_amplitude": 0.5}, "servers10") == ["s4_t3b_ci_swing"]
    assert _ids({"ci_flat": True}, "thesis10_swing") == ["s4_t3a_ci_flat"]
    config, _ = ex.identify({}, "thesis10_swing")
    assert config.key == "servers10"


def test_a_not_applicable_test_never_matches():
    # Two mid servers have no cold plate, so 6.2's switches are no test there.
    assert _ids({"zone_map": [1, 1]}, "servers2") == ["s1_t1_zones"]
    assert _ids({"cold_plates": True}, "servers2") == []


@pytest.mark.parametrize("test", ex.TESTS, ids=lambda t: t.id)
def test_titles(test):
    title = ex.title_of(test)
    if test.id == "base":
        assert title == "Base"
    else:
        section, tag = ex.sections_of(test.id)[0]
        assert title == f"{section.key} · {tag} · {test.name}"
