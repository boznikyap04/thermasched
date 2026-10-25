import json
import shutil

import pytest

from scheduler.build import build_running_variant, build_scenario, derive_scenario, scenario_fingerprint
from scheduler.io import load_scenario

FILES = ("servers.csv", "workloads.csv", "carbon.csv", "baseline_schedule.csv", "params.json")


# The scenarios data_prep.ipynb builds from data/clean/ (small_running is made from small).
BUILT = ("servers6_light", "servers6", "servers6_heavy", "servers6_light_swing", "servers6_swing",
         "servers6_heavy_swing", "small")


@pytest.mark.parametrize("name", BUILT)
def test_build_reproduces_shipped_scenario(name, tmp_path):
    """The builder used by data_prep.ipynb writes the shipped scenarios byte for byte."""
    p = json.loads(open(f"scenarios/{name}/params.json").read())
    extra = {"variant_of": p["variant_of"]} if "variant_of" in p else None
    build_scenario(name, p["settings"], p["constants_as_printed"], p["cold_plate"],
                   clean_dir="data/clean", scenarios_dir=tmp_path, f_ref_mhz=p["f_ref_MHz"],
                   extra=extra)
    for f in FILES:
        assert (tmp_path / name / f).read_bytes() == open(f"scenarios/{name}/{f}", "rb").read(), f


def test_scenarios_record_what_they_change_from_the_reference_settings():
    """Every shipped scenario is the reference settings (servers10) with only the values under
    variant_of changed: two scenarios differ only in values one of them lists as changed."""
    params = {name: json.loads(open(f"scenarios/{name}/params.json").read()) for name in BUILT}
    for name, p in params.items():
        assert p["variant_of"]["scenario"] == "servers10", name
        changed = p["variant_of"]["changed"]
        assert changed["settings"], name
        assert all(p["settings"][k] == v for k, v in changed["settings"].items()), name
        for other, q in params.items():
            listed = set(changed["settings"]) | set(q["variant_of"]["changed"]["settings"])
            assert {k: v for k, v in p["settings"].items() if k not in listed} == \
                {k: v for k, v in q["settings"].items() if k not in listed}, (name, other)
            assert p["constants_as_printed"] == q["constants_as_printed"], (name, other)
            assert p["cold_plate"] == q["cold_plate"], (name, other)


def test_derive_from_a_shipped_scenario(tmp_path):
    """A scenario written by data_prep.ipynb is a valid starting point in solver.ipynb."""
    shutil.copytree("scenarios/servers6", tmp_path / "servers6")
    out = derive_scenario("nb_warm_three", "servers6", {"n_servers": 3, "freq_split": [1, 1, 1]},
                          {"T_crac_max_C": 32.0}, scenarios_dir=tmp_path, clean_dir="data/clean")
    assert out["params"]["constants_as_printed"]["T_crac_max_C"] == 32.0
    assert out["params"]["built_from"]["scenario"] == "servers6"
    assert load_scenario("nb_warm_three", tmp_path).S == 3


@pytest.fixture
def scen_dir(tmp_path):
    for name in ("small", "small_running"):
        shutil.copytree(f"scenarios/{name}", tmp_path / name)
    return tmp_path


def test_derive_applies_changes(scen_dir):
    out = derive_scenario("nb_four", "small", {"n_servers": 4, "freq_split": [2, 1, 1]},
                          {"T_max_server_C": 85.0}, scenarios_dir=scen_dir, clean_dir="data/clean")
    assert out["changed"] == {"settings": {"n_servers": 4, "freq_split": [2, 1, 1]},
                              "constants": {"T_max_server_C": 85.0}}
    sc = load_scenario("nb_four", scen_dir)
    assert sc.S == 4 and sc.constants.T_max_server_C == 85.0
    assert out["params"]["built_from"]["scenario"] == "small"
    # a scenario built here can be rebuilt under the same name
    derive_scenario("nb_four", "small", {"n_servers": 4, "freq_split": [2, 1, 1]},
                    scenarios_dir=scen_dir, clean_dir="data/clean")


@pytest.mark.parametrize("name, start, settings, match", [
    ("small", "small", None, "shipped"),
    ("nb_x", "small_running", None, "edited by hand"),
    ("nb_x", "small", {"n_server": 4}, "unknown scenario setting"),
    ("nb_x", "small", {"n_servers": 4}, "adds up to"),
    ("nb_x", "small", {"dt_seconds": 600}, "slot length"),
])
def test_derive_refuses(scen_dir, name, start, settings, match):
    with pytest.raises(ValueError, match=match):
        derive_scenario(name, start, settings, scenarios_dir=scen_dir, clean_dir="data/clean")
    assert not (scen_dir / "nb_x").exists()


def test_derive_does_not_overwrite_other_folders(scen_dir):
    (scen_dir / "mine").mkdir()
    with pytest.raises(ValueError, match="not built by derive_scenario"):
        derive_scenario("mine", "small", scenarios_dir=scen_dir, clean_dir="data/clean")


def test_build_running_variant_reproduces_small_running(tmp_path):
    """data_prep.ipynb makes small_running from small by rule, as shipped."""
    shutil.copytree("scenarios/small", tmp_path / "small")
    build_running_variant("small_running", "small", [3, 5], {"server": 3, "periods": [37, 48]},
                          scenarios_dir=tmp_path)
    for f in FILES + ("availability.csv",):
        assert (tmp_path / "small_running" / f).read_bytes() == \
            open(f"scenarios/small_running/{f}", "rb").read(), f


def test_fingerprint_follows_content_not_release_or_line_endings(tmp_path):
    shutil.copytree("scenarios/small", tmp_path / "a")
    fp = scenario_fingerprint(tmp_path / "a")
    assert fp == scenario_fingerprint("scenarios/small") == load_scenario("small").fingerprint
    params = json.loads((tmp_path / "a" / "params.json").read_text())
    params["built_with"] = {"thermasched": "9.9.9"}
    (tmp_path / "a" / "params.json").write_text(json.dumps(params))
    carbon = tmp_path / "a" / "carbon.csv"
    carbon.write_bytes(carbon.read_bytes().replace(b"\r\n", b"\n"))
    assert scenario_fingerprint(tmp_path / "a") == fp
    carbon.write_bytes(carbon.read_bytes().replace(b"621", b"622", 1))
    assert scenario_fingerprint(tmp_path / "a") != fp
    assert scenario_fingerprint(tmp_path / "missing") is None
