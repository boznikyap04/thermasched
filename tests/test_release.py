"""A release is one version, in pyproject.toml, scheduler/version.py and CHANGELOG.md."""

import re
import tomllib
from pathlib import Path

from scheduler.version import VERSION


def test_version_matches_pyproject():
    assert tomllib.loads(Path("pyproject.toml").read_text())["project"]["version"] == VERSION


def test_changelog_has_an_entry_for_this_version():
    """Each release says what changed and what the group must re-run."""
    log = Path("CHANGELOG.md").read_text()
    entry = re.search(rf"^## {re.escape(VERSION)}\b.*?(?=^## |\Z)", log, re.M | re.S)
    assert entry, f"CHANGELOG.md has no '## {VERSION}' section"
    assert "Re-run" in entry.group(0), "say what has to be re-run (or 'nothing')"
