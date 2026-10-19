"""Copy the package code into the notebooks, so that each notebook runs on its own (Colab).

    uv run python tools/sync_notebooks.py           # rewrite the generated cells
    uv run python tools/sync_notebooks.py --check   # exit 1 if a notebook is out of date

The code lives in scheduler/ and dashboard/; the notebooks hold generated copies of it.
Edit the package, then run this script. tests/test_notebooks.py runs the check.

- notebooks/data_prep.ipynb: one cell with scheduler/build.py up to SOLVER_ONLY_MARKER, right
  after the cell whose metadata has {"thermasched": {"anchor": "build_code"}}.
- notebooks/solver.ipynb: one ``%%writefile {LIB}/<module>`` cell per module in SOLVER_MODULES,
  after the cell whose metadata has {"thermasched": {"anchor": "model_code"}}. The notebook
  writes them to a folder LIB and imports them from there.

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
    "scheduler/types.py", "scheduler/io.py", "scheduler/baseline.py", "scheduler/build.py",
    "scheduler/optimize.py", "scheduler/evaluate.py", "scheduler/report.py", "scheduler/run.py",
    "dashboard/data.py", "dashboard/theme.py", "dashboard/uploads.py",
)


def _lines(text: str) -> list[str]:
    ls = text.split("\n")
    return [line + "\n" for line in ls[:-1]] + ([ls[-1]] if ls[-1] else [])


def _cell(rel: str, source: str) -> dict:
    return {"cell_type": "code", "execution_count": None,
            "id": "gen-" + rel.removesuffix(".py").replace("/", "-").replace("_", "-"),
            "metadata": {"thermasched": {"generated_from": rel}},
            "outputs": [], "source": _lines(source)}


def build_cell_for_data_prep() -> list[dict]:
    text = (ROOT / "scheduler/build.py").read_text()
    body = text.split(SOLVER_ONLY_MARKER)[0]
    # drop the module docstring and the __future__ import; a cell starts at the imports
    body = body[body.index("import csv"):].rstrip() + "\n"
    head = ("# Generated from scheduler/build.py by tools/sync_notebooks.py. Edit that file, then\n"
            "# run the script; changes made here are overwritten.\n")
    return [_cell("scheduler/build.py", head + body)]


def module_cells_for_solver() -> list[dict]:
    return [_cell(rel, f"%%writefile {{LIB}}/{rel}\n" + (ROOT / rel).read_text())
            for rel in SOLVER_MODULES]


NOTEBOOKS = {
    "notebooks/data_prep.ipynb": ("build_code", build_cell_for_data_prep),
    "notebooks/solver.ipynb": ("model_code", module_cells_for_solver),
}


def _meta(cell: dict) -> dict:
    return cell.get("metadata", {}).get("thermasched", {})


def sync(nb: dict, anchor: str, cells: list[dict]) -> tuple[dict, bool]:
    """Return the notebook with the generated block replaced, and whether it changed."""
    old = nb["cells"]
    kept = [c for c in old if "generated_from" not in _meta(c)]
    at = [i for i, c in enumerate(kept) if _meta(c).get("anchor") == anchor]
    if len(at) != 1:
        raise SystemExit(f"expected one cell with anchor {anchor!r}, found {len(at)}")
    new = kept[:at[0] + 1] + cells + kept[at[0] + 1:]
    changed = [(c["id"], "".join(c["source"])) for c in old if "generated_from" in _meta(c)] != \
              [(c["id"], "".join(c["source"])) for c in cells] or \
              [c["id"] for c in old] != [c["id"] for c in new]
    return {**nb, "cells": new}, changed


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--check", action="store_true", help="only report out-of-date notebooks")
    a = p.parse_args(argv)
    stale = []
    for rel, (anchor, make) in NOTEBOOKS.items():
        path = ROOT / rel
        nb, changed = sync(json.loads(path.read_text()), anchor, make())
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
