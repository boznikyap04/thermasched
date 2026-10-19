"""Release version, written into every scenario (params.json) and run (summary.json).

VERSION must equal ``version`` in pyproject.toml and have an entry in CHANGELOG.md
(tests/test_release.py checks both). The notebooks carry a copy of it, so a run made with
an old notebook shows its version on the dashboard.

SCHEMA_VERSION is the layout of summary.json. Raise it when a field is renamed or removed,
and keep the dashboard able to read every earlier layout.
"""

VERSION = "1.0.1"
SCHEMA_VERSION = 1
