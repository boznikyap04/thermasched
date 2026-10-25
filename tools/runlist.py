"""The per-tick batch runs, from the experiment list in scheduler/experiments.py.

    uv run python tools/runlist.py                    # the 39 runs, one per line
    uv run python tools/runlist.py --fleet servers10  # the 39 runs of the 10-server fleet
    uv run python tools/runlist.py --sections 6.1,6.2 # the 18 runs of the first batch
    uv run python tools/runlist.py --format json      # the same, with every field
    uv run python tools/runlist.py --format matrix    # {"include": [...]} for the Actions matrix
    uv run python tools/runlist.py --only servers6_heavy__base --format matrix
    uv run python tools/runlist.py --timing --format matrix   # the same: the timing run only

The runs (docs/PLAN.md §3): a fleet (servers6, or ``--fleet servers10``) on the light, normal
and heavy day, every test of sections 6.1 to 6.4 that applies to the fleet (the first batch
was 6.1 and 6.2 on servers6), each as one per-tick run in
``<results-dir>/<scenario>/<test id>/``. 6.4 Test 3a (flat carbon) runs with ``--ci-flat``;
6.4 Test 3b (deeper carbon swing) runs on the configuration's ``_swing`` scenario, so its
folder is ``<scenario>_swing/s4_t3b_ci_swing/`` and is filed under the configuration's folder
when the results are installed. A run's switches are the test's (``switches_for``), the same
the batch notebook sets for that test, so the site recognizes the run as that test.

Each run's command is ``python -m scheduler.run <args> <per_tick_args>``: ``args`` are the
usual flags, ``per_tick_args`` the per-tick mode's. A resumed run re-runs the identical
command, so the per-tick flags must not change between a run and its resume.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scheduler.experiments import (  # noqa: E402
    LEVELS, SECTION_BY_KEY, SWING, TEST_BY_ID, applicable, configuration, switches_for,
)

FLEET = "servers6"
LEVEL_KEYS = tuple(lv.key for lv in LEVELS)            # light, normal, heavy
SECTIONS = ("6.1", "6.2", "6.3", "6.4")
# The run of the timing confirmation (docs/PLAN.md §5 item 3): heavy day, 6.1 Base.
TIMING_RUN = "servers6_heavy__base"


def timing_run(fleet: str = FLEET) -> str:
    """The fleet's timing run: its heavy day, 6.1 Base (TIMING_RUN for servers6)."""
    return f"{fleet}_heavy__base"

# Per-tick solve-time cap, seconds; None leaves the per-tick mode's default of 60 s, the cap
# chosen after the timing run (docs/PLAN.md §5 item 3).
TICK_TIME_LIMIT_S: float | None = None
# Stop after the current tick and save the checkpoint once this much time has passed, so a
# job saves its state before GitHub's 6-hour limit stops it: 5 h 30 min.
WALL_TIME_LIMIT_S = 5.5 * 3600

# Each switch of a test as run.py flags. A switch not listed here makes the run list fail, so
# a new test cannot be run with a switch silently left out.
_FLAGS = {
    "zone_map": lambda v: ["--zone-map", ",".join(str(z) for z in v)],
    "reassignment": lambda v: ["--reassignment", v],
    "cold_plates": lambda v: ["--cold-plates"] if v else [],
    "cp_mode": lambda v: ["--cp-mode", v],
    "supply_temp_mode": lambda v: ["--supply-temp-mode", v],
    "H_min_C": lambda v: ["--h-min", f"{v:g}"],
    "placement": lambda v: ["--thermal-blind"] if v == "thermal_blind" else [],
    # Only the flat profile is a flag; the swing is a scenario (see _scenario_for).
    "ci_amplitude": lambda v: ["--ci-flat"] if v == 0 else _no_flag("ci_amplitude", v),
}


def _no_flag(key, value):
    raise ValueError(f"no run.py flag for switch {key}={value!r}")


def _scenario_for(config, switches: dict) -> tuple[str, dict]:
    """The scenario a test runs on, and the switches left for flags: the deeper carbon swing
    is the configuration's ``_swing`` twin, whose name implies it (experiments.SWING)."""
    implied = dict(SWING)
    if all(switches.get(k) == v for k, v in implied.items()):
        return f"{config.key}_swing", {k: v for k, v in switches.items() if k not in implied}
    return config.key, switches


def switch_args(switches: dict) -> list[str]:
    out = []
    for key, value in switches.items():
        if key not in _FLAGS:
            _no_flag(key, value)
        out += _FLAGS[key](value)
    return out


def run_id(scenario: str, run_name: str) -> str:
    """Unique over the batch, for job and artifact names: servers6_heavy__base."""
    return f"{scenario}__{run_name}"


def per_tick_args(tick_time_limit_s: float | None = TICK_TIME_LIMIT_S,
                  wall_time_limit_s: float | None = WALL_TIME_LIMIT_S) -> list[str]:
    out = ["--per-tick"]
    if tick_time_limit_s is not None:
        out += ["--tick-time-limit", f"{tick_time_limit_s:g}"]
    if wall_time_limit_s is not None:
        out += ["--wall-time-limit", f"{wall_time_limit_s:g}"]
    return out


def runs(fleet: str = FLEET, levels=LEVEL_KEYS, sections=SECTIONS, *,
         results_dir: str = "results", tick_time_limit_s: float | None = TICK_TIME_LIMIT_S,
         wall_time_limit_s: float | None = WALL_TIME_LIMIT_S) -> list[dict]:
    """The runs, ordered by section, test and level as in docs/PLAN.md §3. A test in more
    than one of the sections is run once."""
    out, seen = [], set()
    tail = per_tick_args(tick_time_limit_s, wall_time_limit_s)
    for key in sections:
        section = SECTION_BY_KEY[key]
        for tag, test_id in section.tests:
            test = TEST_BY_ID[test_id]
            for level in levels:
                config = configuration(fleet, level)
                if not applicable(test, config) or (config.key, test.id) in seen:
                    continue
                seen.add((config.key, test.id))
                scenario, switches = _scenario_for(config, switches_for(test, config))
                args = (["--scenario", scenario, "--run-name", test.id]
                        + switch_args(switches)
                        + ["--results-dir", results_dir])
                out.append({
                    "id": run_id(scenario, test.id), "scenario": scenario,
                    "configuration": config.key,
                    "run_name": test.id, "level": level, "section": key, "tag": tag,
                    "test": test.name, "args": args, "per_tick_args": tail,
                })
    return out


def select(all_runs: list[dict], only: list[str]) -> list[dict]:
    """The runs named in ``only`` (run ids), in batch order; an unknown id is an error."""
    ids = {r["id"] for r in all_runs}
    unknown = [i for i in only if i not in ids]
    if unknown:
        raise SystemExit(f"unknown run ids {unknown}; known: {sorted(ids)}")
    return [r for r in all_runs if r["id"] in set(only)]


def matrix(selected: list[dict]) -> dict:
    """The Actions matrix: one entry per run, its full argv as a JSON string."""
    return {"include": [
        {"id": r["id"], "scenario": r["scenario"], "run_name": r["run_name"],
         "argv": json.dumps(r["args"] + r["per_tick_args"])} for r in selected]}


def _ids(text: str) -> list[str]:
    return [s for s in text.replace(",", " ").split() if s]


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="tools/runlist.py", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--fleet", default=FLEET)
    p.add_argument("--levels", default=",".join(LEVEL_KEYS))
    p.add_argument("--sections", default=",".join(SECTIONS))
    p.add_argument("--only", default="",
                   help="run ids to keep, comma- or space-separated (default: every run)")
    p.add_argument("--timing", action="store_true",
                   help="keep only the fleet's timing run, its heavy-day base, e.g. "
                        f"{TIMING_RUN} (ignored with --only)")
    p.add_argument("--results-dir", default="results")
    p.add_argument("--tick-time-limit", type=float, default=TICK_TIME_LIMIT_S)
    p.add_argument("--wall-time-limit", type=float, default=WALL_TIME_LIMIT_S)
    p.add_argument("--format", choices=("lines", "json", "matrix"), default="lines")
    a = p.parse_args(argv)
    found = runs(a.fleet, _ids(a.levels), _ids(a.sections), results_dir=a.results_dir,
                 tick_time_limit_s=a.tick_time_limit, wall_time_limit_s=a.wall_time_limit)
    if a.only.strip():
        found = select(found, _ids(a.only))
    elif a.timing:
        found = select(found, [timing_run(a.fleet)])
    if a.format == "matrix":
        print(json.dumps(matrix(found)))
    elif a.format == "json":
        print(json.dumps(found, indent=2))
    else:
        for r in found:
            print(f"{r['id']:<36} python -m scheduler.run "
                  + " ".join(r["args"] + r["per_tick_args"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
