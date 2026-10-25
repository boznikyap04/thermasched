"""Zip export of run folders, to send runs to the project owner.

The zip mirrors ``results/``: ``<scenario>/<run>/summary.json`` plus the run's CSVs, and the
scenario's ``servers.csv`` / ``carbon.csv`` next to the run folders
(``<scenario>/servers.csv``). Unzipped into ``results/``, the runs show on the site with their
server names and clock times.
"""

from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

from dashboard.data import RunRef

# The only scenario inputs the site reads (server names and the clock).
SCENARIO_FILES = ("servers.csv", "carbon.csv")


def _inputs_scenario(ref: RunRef) -> str:
    """The scenario whose files a run uses: the name in its summary.json, which differs
    from its folder for an archived run (``archive-<scenario>``)."""
    try:
        name = (json.loads((ref.path / "summary.json").read_text()).get("scenario") or {}).get("name")
    except (OSError, ValueError, AttributeError):
        name = None
    return name or ref.scenario


def runs_zip(runs: list[tuple[RunRef, Path]]) -> bytes:
    """Zip of ``(run, scenarios_dir)`` pairs laid out as ``<scenario>/<run>/...``.

    ``<scenario>`` is the scenario named in the run's summary.json, so an archived run
    (``archive-<scenario>/``) is zipped under its real scenario.
    The scenario's servers.csv and carbon.csv are added as ``<scenario>/<file>`` so the
    zip shows server names and clock times on a machine without that scenario.
    """
    buf = io.BytesIO()
    added: set[str] = set()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for ref, scenarios_dir in runs:
            scenario = _inputs_scenario(ref)
            if f"{scenario}/{ref.name}/" in added:      # an archived and a current run share a name
                scenario = ref.scenario
            added.add(f"{scenario}/{ref.name}/")
            for f in sorted(ref.path.rglob("*")):
                if f.is_file() and not f.name.startswith("."):
                    rel = f.relative_to(ref.path).as_posix()
                    zf.write(f, f"{scenario}/{ref.name}/{rel}")
            for fname in SCENARIO_FILES:
                arc = f"{scenario}/{fname}"
                src = Path(scenarios_dir) / _inputs_scenario(ref) / fname
                if arc not in added and src.is_file():
                    zf.write(src, arc)
                    added.add(arc)
    return buf.getvalue()
