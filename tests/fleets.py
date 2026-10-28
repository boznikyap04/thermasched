"""The fleet tables of the shipped scenarios and a small cleaned-data fixture to build them on.

``tests/fixtures/clean/`` holds a servers.csv with both models: eight eligible R840 hosts and
one ineligible (rows of the cleaned UniMelb D1 table), four eligible C6320 hosts and one
ineligible (made-up values near the D2 medians, not measurements), and the first 40 workloads
of the cleaned UFCG catalogue that run 3 to 36 periods.
"""

from __future__ import annotations

import json
from pathlib import Path

FIXTURE_CLEAN = Path(__file__).parent / "fixtures" / "clean"


def row(model: str, f_mhz: float, zone: int, cold_plate: int = 0) -> dict:
    return {"model": model, "f_MHz": f_mhz, "zone": zone, "cold_plate": cold_plate}


FLEET6 = [row("R840", 2100, 1), row("R840", 2100, 2), row("R840", 2400, 1), row("R840", 2400, 2),
          row("C6320", 2600, 1, 1), row("C6320", 2600, 2, 1)]
FLEET10 = [row("R840", 2100, z) for z in (1, 2, 1)] + [row("R840", 2400, z) for z in (2, 1, 2, 1)] + \
          [row("C6320", 2600, z, 1) for z in (2, 1, 2)]
FLEET_SMALL = [row("R840", 2100, 1), row("R840", 2400, 2), row("C6320", 2600, 1, 1)]

# The settings of `small` with the fleet table.
SMALL_SETTINGS = {
    "seed": 42, "dt_seconds": 300, "periods": 96, "start_hour_local": 12, "fleet": FLEET_SMALL,
    "target_peak_load": 0.6, "top_up_by_repeats": True, "min_et_periods": 3, "max_et_periods": 36,
    "rt_share": 0.3, "rt_slack_frac": 0.25, "dt_slack_mult": 2.0, "dt_slack_min": 12,
    "dt_slack_max": 36, "ci_mean_g_per_kwh": 621.73, "ci_amplitude": 0.25,
}


def small_inputs() -> tuple[dict, dict, float]:
    """Constants, cold-plate table and f_ref of the shipped `small` scenario."""
    p = json.loads(Path("scenarios/small/params.json").read_text())
    return p["constants_as_printed"], p["cold_plate"], p["f_ref_MHz"]
