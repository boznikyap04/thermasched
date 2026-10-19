import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import sync_notebooks  # noqa: E402

NOTEBOOKS = ("notebooks/data_prep.ipynb", "notebooks/solver.ipynb")


def test_notebooks_hold_the_current_package_code():
    """The notebooks carry copies of scheduler/ and dashboard/ so that they run on their own.
    If this fails, run: uv run python tools/sync_notebooks.py"""
    assert sync_notebooks.main(["--check"]) == 0


def test_notebooks_do_not_import_the_repository():
    """Outside the generated cells, a notebook imports only what it carries itself, so it
    runs without the repository (on Colab, say)."""
    for rel in NOTEBOOKS:
        nb = json.loads(Path(rel).read_text())
        for cell in nb["cells"]:
            if cell["cell_type"] != "code":
                continue
            src = "".join(cell["source"])
            assert "sys.path.insert(0, str(ROOT))" not in src, rel
            if rel.endswith("data_prep.ipynb"):
                assert not re.search(r"^\s*(from|import)\s+(scheduler|dashboard)\b", src, re.M), rel


def test_data_prep_names_nothing_outside_itself():
    """data_prep.ipynb is read on its own: its text and code point to no repository file,
    other notebook, tool or command. Its outputs (the files it writes) may be named."""
    outside = re.compile(r"README|\.md\b|\.py\b|solver\.ipynb|scheduler/|tools/|docs/|archive/|"
                         r"\buv (run|sync)\b|pytest|--[a-z]+(-[a-z]+)*\b")
    nb = json.loads(Path("notebooks/data_prep.ipynb").read_text())
    found = [(i, line) for i, cell in enumerate(nb["cells"])
             for line in "".join(cell["source"]).split("\n") if outside.search(line)]
    assert not found, found
