"""Copy the package code into the notebooks, so that each notebook runs on its own (Colab).

    uv run python tools/sync_notebooks.py           # rewrite the generated cells
    uv run python tools/sync_notebooks.py --check   # exit 1 if a notebook is out of date

The code lives in scheduler/ and dashboard/; the notebooks hold generated copies of it.
Edit the package, then run this script. tests/test_notebooks.py runs the check.

- notebooks/data_prep.ipynb: a "release" cell with the version (scheduler/version.py) and the
  fingerprint of every scenario in scenarios/, after the cell with anchor "release"; and one
  cell with scheduler/build.py up to SOLVER_ONLY_MARKER, after the cell with anchor
  "build_code". Section 4 of the notebook compares the scenarios it wrote with those
  fingerprints, so after re-running the notebook with changed rules, run this script again.
- notebooks/solver.ipynb and notebooks/batch.ipynb: one ``%%writefile {LIB}/<module>`` cell per
  module in SOLVER_MODULES, after the cell with anchor "model_code". The notebook writes them
  to a folder LIB and imports them from there.

An anchor is a cell whose metadata has {"thermasched": {"anchor": "<name>"}}.

Generated cells carry {"thermasched": {"generated_from": "<path>"}} in their metadata; they
are replaced as a block, and their outputs are cleared.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOLVER_ONLY_MARKER = "# --- Only notebooks/solver.ipynb uses what follows"
SOLVER_MODULES = (
    "scheduler/version.py", "scheduler/types.py", "scheduler/io.py", "scheduler/baseline.py", "scheduler/build.py",
    "scheduler/optimize.py", "scheduler/evaluate.py", "scheduler/report.py", "scheduler/pertick.py",
    "scheduler/run.py", "scheduler/validate.py", "scheduler/experiments.py",
    "dashboard/data.py", "dashboard/theme.py", "dashboard/uploads.py",
)


def _lines(text: str) -> list[str]:
    ls = text.split("\n")
    return [line + "\n" for line in ls[:-1]] + ([ls[-1]] if ls[-1] else [])


def _cell(rel: str, source: str, cell_id: str | None = None) -> dict:
    return {"cell_type": "code", "execution_count": None,
            "id": "gen-" + (cell_id or rel.removesuffix(".py").replace("/", "-").replace("_", "-")),
            "metadata": {"thermasched": {"generated_from": rel}},
            "outputs": [], "source": _lines(source)}


VERSION_IMPORT = "from scheduler.version import VERSION\n"


def _version() -> str:
    ns: dict = {}
    exec((ROOT / "scheduler/version.py").read_text(), ns)
    return ns["VERSION"]


def release_cell_for_data_prep() -> list[dict]:
    sys.path.insert(0, str(ROOT))
    from scheduler.build import scenario_fingerprint
    fps = {d.name: scenario_fingerprint(d) for d in sorted((ROOT / "scenarios").iterdir())
           if (d / "params.json").is_file()}
    lines = "".join(f"    {name!r}: {fp!r},\n" for name, fp in fps.items())
    source = (
        "# The release this notebook belongs to, and the fingerprint of each scenario it writes\n"
        "# when the settings are left as shipped. Section 4 compares the scenarios written\n"
        "# below with these. This cell is generated; don't edit it.\n"
        f"VERSION = {_version()!r}\n"
        f"REFERENCE_FINGERPRINTS = {{\n{lines}}}\n"
        'print(f"ThermaSched {VERSION}")\n')
    return [_cell("scheduler/version.py", source, "release")]


def build_cell_for_data_prep() -> list[dict]:
    text = (ROOT / "scheduler/build.py").read_text()
    body = text.split(SOLVER_ONLY_MARKER)[0]
    # drop the module docstring and the __future__ import; a cell starts at the imports.
    # VERSION comes from the release cell instead of scheduler/version.py.
    if VERSION_IMPORT not in body:
        raise SystemExit(f"scheduler/build.py no longer has {VERSION_IMPORT.strip()!r}")
    body = body[body.index("import csv"):].replace("\n" + VERSION_IMPORT, "").rstrip() + "\n"
    # data_prep.ipynb is read on its own, so its copy names no file outside the notebook
    head = "# Scenario construction rules: servers, workloads, carbon profile, baseline schedule.\n"
    return [_cell("scheduler/build.py", head + body)]


def module_cells_for_solver() -> list[dict]:
    return [_cell(rel, f"%%writefile {{LIB}}/{rel}\n" + (ROOT / rel).read_text())
            for rel in SOLVER_MODULES]


# notebook -> [(anchor, function returning the generated cells that follow it)]
NOTEBOOKS = {
    "notebooks/data_prep.ipynb": [("release", release_cell_for_data_prep),
                                  ("build_code", build_cell_for_data_prep)],
    "notebooks/solver.ipynb": [("model_code", module_cells_for_solver)],
    "notebooks/batch.ipynb": [("model_code", module_cells_for_solver)],
}


def _meta(cell: dict) -> dict:
    return cell.get("metadata", {}).get("thermasched", {})


def sync(nb: dict, blocks: list[tuple[str, list[dict]]]) -> tuple[dict, bool]:
    """Return the notebook with each generated block replaced, and whether it changed."""
    old = nb["cells"]
    new = [c for c in old if "generated_from" not in _meta(c)]
    for anchor, cells in blocks:
        at = [i for i, c in enumerate(new) if _meta(c).get("anchor") == anchor]
        if len(at) != 1:
            raise SystemExit(f"expected one cell with anchor {anchor!r}, found {len(at)}")
        new = new[:at[0] + 1] + cells + new[at[0] + 1:]

    def generated(cells):
        return [(c["id"], "".join(c["source"])) for c in cells if "generated_from" in _meta(c)]

    changed = generated(old) != generated(new) or [c["id"] for c in old] != [c["id"] for c in new]
    return {**nb, "cells": new}, changed


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--check", action="store_true", help="only report out-of-date notebooks")
    a = p.parse_args(argv)
    stale = []
    for rel, blocks in NOTEBOOKS.items():
        path = ROOT / rel
        nb, changed = sync(json.loads(path.read_text()),
                           [(anchor, make()) for anchor, make in blocks])
        if not changed:
            continue
        stale.append(rel)
        if not a.check:
            path.write_text(json.dumps(nb, indent=1, ensure_ascii=False) + "\n")
            print(f"updated {rel}")
    if a.check and stale:
        print("out of date (run: uv run python tools/sync_notebooks.py): " + ", ".join(stale))
        return 1
    if not stale:
        print("notebooks up to date")
    return 0


if __name__ == "__main__":
    sys.exit(main())
