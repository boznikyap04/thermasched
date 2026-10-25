"""ThermaSched results dashboard.

    uv run streamlit run dashboard/app.py

Reads the run outputs under results/<configuration>/<run>/ and shows the four Chapter 6
scenarios (6.1 to 6.4) for 10, 6 and 2 servers, the charts and key results of each test
against its Base, and every output CSV as it is. Read-only.
"""

from __future__ import annotations

import sys
from pathlib import Path

# `streamlit run` puts dashboard/ on sys.path, not the repository root.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import streamlit as st  # noqa: E402

PROJECT_PACKAGES = ("dashboard", "scheduler")


def _drop_stale_modules() -> None:
    """Load the project's code afresh when it changed on disk.

    Streamlit runs this script again on every rerun, but modules it imported stay cached in
    the process. Community Cloud pulls a new commit into the running process, so without
    this the new app.py would run against the old dashboard and scheduler modules (an
    AttributeError for anything the release added). The first run of a process, or the first
    after the source changed, drops those modules and the data cached from them."""
    stamp = tuple(sorted((str(p), p.stat().st_mtime_ns)
                         for pkg in PROJECT_PACKAGES for p in (ROOT / pkg).rglob("*.py")))
    if getattr(sys, "_thermasched_code_stamp", None) == stamp:
        return
    stale = [m for m in sys.modules if m.split(".")[0] in PROJECT_PACKAGES]
    for name in stale:
        del sys.modules[name]
    if stale:
        st.cache_data.clear()
    sys._thermasched_code_stamp = stamp


_drop_stale_modules()

from dashboard.views import chapter6, detail, files, section  # noqa: E402
from scheduler import experiments as ex  # noqa: E402
from scheduler.version import VERSION  # noqa: E402

st.set_page_config(page_title="ThermaSched results", page_icon="🌡️", layout="wide")


def main() -> None:
    with st.sidebar:
        st.markdown("**ThermaSched** · Chapter 6 results")
        st.caption(f"Release {VERSION}")
    # dashboard/views/validation.py (the model checks) is kept off the site; add its page
    # here to bring it back.
    pages = {
        "Chapter 6": [
            st.Page(chapter6.render, title="Overview", icon=":material/grid_view:",
                    url_path="chapter6", default=True),
            *(st.Page(section.page(s.key), title=f"{s.key} {section.SHORT_TITLES[s.key]}",
                      icon=section.ICONS[s.key], url_path=f"section-{s.key.replace('.', '-')}")
              for s in ex.SECTIONS),
        ],
        "Test charts": [
            st.Page(detail.render, title="Charts and key results", icon=":material/monitoring:",
                    url_path="test-charts"),
        ],
        "Outputs": [
            st.Page(files.render, title="Output files", icon=":material/table_view:",
                    url_path="files"),
        ],
    }
    st.navigation(pages).run()


main()
