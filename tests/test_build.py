import json
import shutil

import pytest

from scheduler.build import build_scenario, derive_scenario
from scheduler.io import load_scenario

FILES = ("servers.csv", "workloads.csv", "carbon.csv", "baseline_schedule.csv", "params.json")


@pytest.mark.parametrize("name", ["thesis10", "consolidated6", "small", "thesis10_tight", "thesis10_swing",
                                  "thesis10_warm"])
def test_build_reproduces_shipped_scenario(name, tmp_path):
    """The builder used by data_prep.ipynb writes the shipped scenarios byte for byte."""
    p = json.loads(open(f"scenarios/{name}/params.json").read())
    extra = {"variant_of": p["variant_of"]} if "variant_of" in p else None
    build_scenario(name, p["settings"], p["constants_as_printed"], p["cold_plate"],
                   clean_dir="data/clean", scenarios_dir=tmp_path, f_ref_mhz=p["f_ref_MHz"],
                   extra=extra)
    for f in FILES:
        assert (tmp_path / name / f).read_bytes() == open(f"scenarios/{name}/{f}", "rb").read(), f


def test_experiments_record_what_they_change_from_thesis10():
    """Every shipped experiment is thesis10 with only the values under variant_of changed."""
    main = json.loads(open("scenarios/thesis10/params.json").read())
    assert "variant_of" not in main
    for name in ("consolidated6", "small", "thesis10_tight", "thesis10_swing", "thesis10_warm"):
        p = json.loads(open(f"scenarios/{name}/params.json").read())
        assert p["variant_of"]["scenario"] == "thesis10"
        changed = p["variant_of"]["changed"]
        assert changed, name
        assert p["settings"] == main["settings"] | changed.get("settings", {}), name
        assert p["constants_as_printed"] == main["constants_as_printed"] | changed.get("constants", {}), name
        assert p["cold_plate"] == main["cold_plate"], name


def test_derive_from_an_experiment(tmp_path):
    """An experiment written by data_prep.ipynb is a valid starting point in solver.ipynb."""
    for name in ("thesis10_warm",):
        shutil.copytree(f"scenarios/{name}", tmp_path / name)
    out = derive_scenario("nb_warm_six", "thesis10_warm", {"n_servers": 6, "freq_split": [2, 2, 2]},
                          scenarios_dir=tmp_path, clean_dir="data/clean")
    assert out["params"]["constants_as_printed"]["T_crac_max_C"] == 32.0
    assert load_scenario("nb_warm_six", tmp_path).S == 6


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
