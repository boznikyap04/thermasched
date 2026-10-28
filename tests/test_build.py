import csv
import json
import shutil

import pytest

from scheduler.build import (
    CPU_BY_MHZ, build_running_variant, build_scenario, check_settings, derive_scenario, draw_hosts,
    eligible_hosts, pick_servers, read_csv_rows, scenario_fingerprint,
)
from scheduler.io import load_scenario
from tests.fleets import FIXTURE_CLEAN, FLEET6, FLEET10, FLEET_SMALL, SMALL_SETTINGS, row, small_inputs

FILES = ("servers.csv", "workloads.csv", "carbon.csv", "baseline_schedule.csv", "params.json")


# The scenarios data_prep.ipynb builds from data/clean/ (small_running is made from small).
BUILT = ("servers10_light", "servers10", "servers10_heavy", "servers10_light_swing",
         "servers10_swing", "servers10_heavy_swing",
         "servers6_light", "servers6", "servers6_heavy", "servers6_light_swing", "servers6_swing",
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
    variant_of changed: two scenarios differ only in values one of them lists as changed.
    servers10 is the reference settings as they are, so it has no variant_of."""
    params = {name: json.loads(open(f"scenarios/{name}/params.json").read()) for name in BUILT}
    assert "variant_of" not in params["servers10"]

    def changed_settings(p):
        return p["variant_of"]["changed"]["settings"] if "variant_of" in p else {}

    for name, p in params.items():
        if name == "servers10":
            continue
        assert p["variant_of"]["scenario"] == "servers10", name
        changed = changed_settings(p)
        assert changed, name
        assert all(p["settings"][k] == v for k, v in changed.items()), name
    for name, p in params.items():
        for other, q in params.items():
            listed = set(changed_settings(p)) | set(changed_settings(q))
            assert {k: v for k, v in p["settings"].items() if k not in listed} == \
                {k: v for k, v in q["settings"].items() if k not in listed}, (name, other)
            assert p["constants_as_printed"] == q["constants_as_printed"], (name, other)
            assert p["cold_plate"] == q["cold_plate"], (name, other)


def test_derive_from_a_shipped_scenario(tmp_path):
    """A scenario written by data_prep.ipynb is a valid starting point in solver.ipynb."""
    shutil.copytree("scenarios/servers6", tmp_path / "servers6")
    out = derive_scenario("nb_warm_three", "servers6", {"fleet": FLEET_SMALL},
                          {"T_crac_max_C": 32.0}, scenarios_dir=tmp_path, clean_dir="data/clean")
    assert out["params"]["constants_as_printed"]["T_crac_max_C"] == 32.0
    assert out["params"]["built_from"]["scenario"] == "servers6"
    assert load_scenario("nb_warm_three", tmp_path).S == 3


def build_small(scenarios_dir, name="small", settings=None, clean_dir=FIXTURE_CLEAN):
    const, cp, f_ref = small_inputs()
    return build_scenario(name, settings or SMALL_SETTINGS, const, cp, clean_dir=clean_dir,
                          scenarios_dir=scenarios_dir, f_ref_mhz=f_ref)


@pytest.fixture
def scen_dir(tmp_path):
    """small and small_running, built on the fixture's cleaned tables."""
    build_small(tmp_path)
    build_running_variant("small_running", "small", [3, 5], {"server": 3, "periods": [37, 48]},
                          scenarios_dir=tmp_path)
    return tmp_path


FOUR = FLEET_SMALL + [row("R840", 2400, 2)]


def test_derive_applies_changes(scen_dir):
    out = derive_scenario("nb_four", "small", {"fleet": FOUR}, {"T_max_server_C": 85.0},
                          scenarios_dir=scen_dir, clean_dir=FIXTURE_CLEAN)
    assert out["changed"] == {"settings": {"fleet": FOUR}, "constants": {"T_max_server_C": 85.0}}
    sc = load_scenario("nb_four", scen_dir)
    assert sc.S == 4 and sc.constants.T_max_server_C == 85.0
    assert out["params"]["built_from"]["scenario"] == "small"
    # The first three servers keep their hosts: a fleet that grows draws further down the
    # same seeded order of each model.
    small = read_csv_rows(scen_dir / "small" / "servers.csv")
    four = read_csv_rows(scen_dir / "nb_four" / "servers.csv")
    assert [r["server"] for r in four[:3]] == [r["server"] for r in small]
    assert four[3]["model"] == "R840" and four[3]["server"] not in {r["server"] for r in small}
    # a scenario built here can be rebuilt under the same name
    derive_scenario("nb_four", "small", {"fleet": FOUR}, scenarios_dir=scen_dir, clean_dir=FIXTURE_CLEAN)


def test_derive_with_another_seed_draws_other_hosts(scen_dir):
    hosts = {}
    for seed in range(5):
        name = f"nb_seed{seed}"
        derive_scenario(name, "small", {"seed": seed}, scenarios_dir=scen_dir, clean_dir=FIXTURE_CLEAN)
        hosts[seed] = tuple(r["server"] for r in read_csv_rows(scen_dir / name / "servers.csv"))
    assert len(set(hosts.values())) > 1


@pytest.mark.parametrize("name, start, settings, match", [
    ("small", "small", None, "shipped"),
    ("nb_x", "small_running", None, "edited by hand"),
    ("nb_x", "small", {"n_servers": 4}, "unknown scenario setting"),
    ("nb_x", "small", {"freq_split": [1, 1, 1]}, "unknown scenario setting"),
    ("nb_x", "small", {"fleet": []}, "non-empty"),
    ("nb_x", "small", {"fleet": [row("R840", 2100, 1)] * 9}, "only 8 R840 hosts"),
    ("nb_x", "small", {"dt_seconds": 600}, "slot length"),
])
def test_derive_refuses(scen_dir, name, start, settings, match):
    with pytest.raises(ValueError, match=match):
        derive_scenario(name, start, settings, scenarios_dir=scen_dir, clean_dir=FIXTURE_CLEAN)
    assert not (scen_dir / "nb_x").exists()


def test_derive_does_not_overwrite_other_folders(scen_dir):
    (scen_dir / "mine").mkdir()
    with pytest.raises(ValueError, match="not built by derive_scenario"):
        derive_scenario("mine", "small", scenarios_dir=scen_dir, clean_dir=FIXTURE_CLEAN)


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


# --- The fleet table and the seeded host draw, on the fixture's cleaned servers.csv


def settings(fleet, seed=42):
    return SMALL_SETTINGS | {"fleet": fleet, "seed": seed}


def _hosts(fleet, seed=42, clean_dir=FIXTURE_CLEAN):
    return [s["server"] for s in pick_servers(settings(fleet, seed), clean_dir)]


def test_draw_is_deterministic_per_model_and_never_repeats_a_host():
    pool = {s["server"]: s for s in read_csv_rows(FIXTURE_CLEAN / "servers.csv")}
    for fleet in (FLEET6, FLEET10, FLEET_SMALL):
        for seed in (0, 1, 42):
            hosts = _hosts(fleet, seed)
            assert hosts == _hosts(fleet, seed)
            assert len(set(hosts)) == len(hosts)
            assert [pool[h]["model"] for h in hosts] == [r["model"] for r in fleet]
            assert all(pool[h]["eligible"] == "1" for h in hosts)
    # every eligible host of a model can be drawn: the 10-server fleet takes 7 of the 8 R840s
    # and 3 of the 4 C6320s; the ineligible ones never
    assert "qh2-rcc121" not in _hosts(FLEET10) and "qh2-rcc263" not in _hosts(FLEET10)


def test_draw_depends_on_the_seed():
    assert len({tuple(_hosts(FLEET6, seed)) for seed in range(10)}) > 1


def test_draw_ignores_power_and_row_order(tmp_path):
    """Swapping the power figures between hosts, or shuffling the table, leaves the draw as is;
    so does dropping a host that was not drawn."""
    rows = read_csv_rows(FIXTURE_CLEAN / "servers.csv")
    fields = list(rows[0])
    drawn = _hosts(FLEET6)

    def write(name, records):
        d = tmp_path / name
        d.mkdir()
        with open(d / "servers.csv", "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=fields)
            w.writeheader()
            w.writerows(records)
        return d

    power = ("P_idle_W", "P_max_W", "P_fit_full_load_W")
    rotated = [r | {k: rows[(i + 3) % len(rows)][k] for k in power} for i, r in enumerate(rows)]
    assert _hosts(FLEET6, clean_dir=write("rotated", rotated)) == drawn
    assert _hosts(FLEET6, clean_dir=write("reversed", rows[::-1])) == drawn
    not_drawn = next(r["server"] for r in rows if r["server"] not in drawn and r["eligible"] == "1")
    assert _hosts(FLEET6, clean_dir=write("fewer", [r for r in rows if r["server"] != not_drawn])) == drawn


def test_servers_take_model_frequency_zone_and_cold_plate_from_the_fleet_rows():
    servers = pick_servers(settings(FLEET10), FIXTURE_CLEAN)
    assert list(servers[0])[:5] == ["s", "server", "model", "cpu", "zone"]
    for i, (s, r) in enumerate(zip(servers, FLEET10), 1):
        assert s["s"] == i and s["model"] == r["model"] and s["zone"] == r["zone"]
        assert s["f_s_MHz"] == r["f_MHz"] and s["cpu"] == CPU_BY_MHZ[r["f_MHz"]]
        assert s["CT_s_cold_plate"] == s["n_cold_plates"] == r["cold_plate"]
        assert s["PC_s_MHz"] == s["N_cores"] * s["f_s_MHz"]
        assert s["W_per_MHz"] == round((s["P_max_W"] - s["P_idle_W"]) / s["PC_s_MHz"], 6)
        assert s["N_cores"] == (80 if r["model"] == "C6320" else 64)
    assert [s["cpu"] for s in servers[:3]] == ["Xeon Gold 6130"] * 3
    assert servers[-1]["cpu"] == "Xeon E5-2690 v4" and servers[3]["cpu"] == "Xeon Gold 6148"
    # a cold plate can go on any row the table says, and off the C6320s
    moved = [r | {"cold_plate": int(r["model"] == "R840" and r["f_MHz"] == 2100)} for r in FLEET6]
    assert [s["CT_s_cold_plate"] for s in pick_servers(settings(moved), FIXTURE_CLEAN)] == [1, 1, 0, 0, 0, 0]


@pytest.mark.parametrize("change, match", [
    ({"fleet": []}, "non-empty"),
    ({"fleet": None}, "non-empty"),
    ({"n_servers": 6}, "replaced by the fleet table"),
    ({"freq_mhz": [2100.0], "freq_split": [3]}, "replaced by the fleet table"),
    ({"n_zones": 2}, "replaced by the fleet table"),
    ({"fleet": [row("R740", 2100, 1)]}, "model 'R740'"),
    ({"fleet": [{"model": "R840", "f_MHz": 2100, "zone": 1}]}, "exactly the keys"),
    ({"fleet": [row("R840", 2100, 1) | {"cpu": "x"}]}, "exactly the keys"),
    ({"fleet": [row("R840", 0, 1)]}, "f_MHz"),
    ({"fleet": [row("R840", 2100, 0)]}, "zone = 0"),
    ({"fleet": [row("R840", 2100, 1.0)]}, "zone = 1.0"),
    ({"fleet": [row("R840", 2100, 1), row("R840", 2100, 3)]}, "every zone from 1 to 3"),
    ({"fleet": [row("R840", 2100, 1, 2)]}, "cold_plate = 2"),
    ({"fleet": [row("R840", 2100, 1, True)]}, "cold_plate = True"),
    ({"periods": 0}, "periods"),
])
def test_check_settings_refuses(change, match):
    with pytest.raises(ValueError, match=match):
        check_settings(SMALL_SETTINGS | change)


def test_check_settings_counts_eligible_hosts_per_model():
    hosts = eligible_hosts(FIXTURE_CLEAN)
    check_settings(settings(FLEET10), hosts)
    check_settings(settings([row("C6320", 2600, 1, 1)] * 4), hosts)
    with pytest.raises(ValueError, match="5 C6320 servers, but only 4 C6320 hosts"):
        check_settings(settings([row("C6320", 2600, 1, 1)] * 5), hosts)
    with pytest.raises(ValueError, match="9 R840 servers, but only 8 R840 hosts"):
        check_settings(settings(FLEET10 + [row("R840", 2100, 1)] * 2), hosts)
    with pytest.raises(IndexError):    # what check_settings guards against
        draw_hosts(settings([row("C6320", 2600, 1, 1)] * 5), hosts)


def test_cleaned_table_without_models_is_refused(tmp_path):
    (tmp_path / "servers.csv").write_text("server,eligible\nqh2-rcc120,1\n")
    with pytest.raises(ValueError, match="no `model` column"):
        eligible_hosts(tmp_path)


def test_build_on_the_fleet_table(tmp_path):
    servers, diag = build_small(tmp_path, "six", settings(FLEET6) | {"periods": 48})
    params = json.loads((tmp_path / "six" / "params.json").read_text())
    assert params["settings"]["fleet"] == FLEET6
    assert diag["S_servers"] == 6 and diag["Z_zones"] == 2
    fast = sum(s["C_s_cores"] for s in servers if s["f_s_MHz"] == 2600)
    assert fast == 160
    assert diag["peak_load_share_of_fastest_tier"] == round(diag["peak_requested_vcpus"] / fast, 3)
    assumed = params["assumed_not_from_data"]
    assert "f_s_MHz assignment" not in assumed
    spec = next(a for a in assumed if a.startswith("f_s_MHz"))
    for part in ("SPEC", "R840 2100 MHz, Xeon Gold 6130", "R840 2400 MHz, Xeon Gold 6148",
                 "C6320 2600 MHz, Xeon E5-2690 v4"):
        assert part in spec
    assert any("C6320" in a and "March 2019" in a for a in assumed)
    assert any("C6320" in a and "inlet" in a and "R840 room" in a for a in assumed)
    sc = load_scenario("six", tmp_path)
    assert sc.S == 6 and sc.n_zones == 2
    assert [sv.zone for sv in sc.servers] == [1, 2, 1, 2, 1, 2]
    # An R840-only fleet lists no C6320 assumption.
    build_small(tmp_path, "r840", settings(FLEET6[:4]))
    assumed = json.loads((tmp_path / "r840" / "params.json").read_text())["assumed_not_from_data"]
    assert not any("C6320" in a for a in assumed)


def test_running_variant_on_the_fleet_table(scen_dir):
    small = scen_dir / "small"
    assert (scen_dir / "small_running" / "servers.csv").read_bytes() == (small / "servers.csv").read_bytes()
    params = json.loads((scen_dir / "small_running" / "params.json").read_text())
    assert params["settings"]["fleet"] == FLEET_SMALL
    assert "AV_st (availability.csv)" in params["assumed_not_from_data"]
    sc = load_scenario("small_running", scen_dir)
    assert sc.S == 3 and sum(w.B for w in sc.workloads) > 0
