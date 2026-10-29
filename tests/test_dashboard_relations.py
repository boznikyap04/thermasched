"""Relationship checks of the Validation page (dashboard/relations.py) on real servers10 runs."""

from __future__ import annotations

import numpy as np
import pytest

from dashboard import data, relations
from dashboard.theme import palette

BASE = data.RESULTS_DIR / "servers10" / "base"
COLD = BASE                 # cold plates are on in every run
FLAT = data.RESULTS_DIR / "servers10" / "s4_t3a_ci_flat"

pytestmark = pytest.mark.skipif(
    not all((p / "summary.json").is_file() for p in (BASE, COLD, FLAT)),
    reason="servers10 runs not under results/")


@pytest.fixture(scope="module")
def runs():
    return {k: data.load_run(p) for k, p in (("base", BASE), ("cold", COLD), ("flat", FLAT))}


def test_every_relationship_has_a_reading_and_a_figure(runs):
    pal = palette("light")
    for rel in relations.RELATIONS:
        run = runs["cold"] if rel.cold_plates else runs["base"]
        other = runs["flat"] if rel.two_runs else None
        for v in run.variants:
            text = relations.reading(rel.key, run, v, other)
            assert text and text[0].isupper() and text.endswith("."), (rel.key, text)
            assert "nan" not in text, (rel.key, text)
            fig = relations.figure(rel.key, run, v, pal, other)
            assert len(fig.data) > 0, rel.key


def test_cold_plates_are_detected(runs):
    assert relations.has_cold_plates(runs["cold"])
    cp = relations.cold_plate_rows(runs["cold"], "optimized")
    assert cp["s"].nunique() == 3 and cp["cp_flow_Lmin"].notna().all()


def test_utilization_drives_power_and_idle_is_not_zero(runs):
    sp = runs["base"].server_period
    sp = sp[sp["variant"] == "optimized"]
    for _, g in sp.groupby("s"):
        if g["utilization"].nunique() == 1:     # idle all day: power stays at P_idle
            assert g["P_IT_W"].nunique() == 1 and g["P_IT_W"].iloc[0] > 0
            continue
        assert relations.pearson(g["utilization"], g["P_IT_W"]) > 0.99
    assert "not 0 W" in relations.reading("util_power", runs["base"], "optimized")


def test_running_count_matches_the_schedule(runs):
    run = runs["base"]
    n = relations.running_per_period(run, "optimized")
    sch = run.schedule[run.schedule["variant"] == "optimized"].dropna(subset=["start"])
    assert len(n) == len(run.clock)
    assert n.sum() == int((sch["finish"].clip(upper=len(run.clock) + 1) - sch["start"]).sum())


def test_crac_removes_the_heat_the_cold_plates_leave(runs):
    zh = relations.zone_heat(runs["cold"], "optimized")
    assert np.allclose(zh["Q_crac_kW"], zh["heat_kW"], rtol=1e-3, atol=1e-6)
    assert np.allclose(zh["P_crac_kW"], zh["Q_crac_kW"] / zh["COP"], rtol=1e-3)


def test_pearson_is_undefined_for_a_constant_side():
    assert np.isnan(relations.pearson([1, 1, 1], [1, 2, 3]))
    assert relations.pearson([1, 2, 3], [2, 4, 6]) == pytest.approx(1.0)


def test_shifting_compares_delay_tolerant_work_in_both_runs(runs):
    df = relations.shifting(runs["base"], runs["flat"])
    assert {"running_base", "running_flat", "CI_g_per_kWh", "CI_flat"} <= set(df.columns)
    assert df["CI_flat"].nunique() == 1 and df["CI_g_per_kWh"].nunique() > 1
