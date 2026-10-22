"""ThermaSched results dashboard.

    uv run streamlit run dashboard/app.py

Reads run outputs under results/<scenario>/<run>/ (read-only unless the optional
New run page is switched on in the sidebar), plus zipped runs uploaded in the browser.
"""

from __future__ import annotations

import importlib.util
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

from dashboard import data, state  # noqa: E402
from scheduler.version import VERSION  # noqa: E402
from dashboard.views import (  # noqa: E402
    chapter6, compare, compliance, cooling, energy, new_run, overview, schedule, thermal, upload,
    validation,
)

st.set_page_config(page_title="ThermaSched results", page_icon="🌡️", layout="wide")

NEW_RUN_FLAG = "enable_new_run"
# The New run page needs the solver (HiGHS). A deployment with only dashboard/requirements.txt
# installed has no solver, so the page is not offered there.
SOLVER_INSTALLED = importlib.util.find_spec("highspy") is not None


def _sidebar(runs: list[data.RunRef]) -> None:
    by_scenario: dict[str, list[str]] = {}
    for r in runs:
        by_scenario.setdefault(r.scenario, []).append(r.key)
    uploaded = {r.key for r in runs if state.is_uploaded(r)}
    labels = state.thesis_labels()
    statuses = state.run_statuses()

    # A run just uploaded (or solved) asks to be selected before the widgets draw.
    pending = st.session_state.pop(state.PENDING_RUN, None)
    if pending in {r.key for r in runs}:
        st.session_state[state.RUN_KEY] = pending
        st.session_state["scenario"] = pending.split("/")[0]

    # First visit: honour ?run=<scenario>/<run> so a view can be linked.
    if state.RUN_KEY not in st.session_state:
        wanted = st.query_params.get("run")
        st.session_state[state.RUN_KEY] = wanted if wanted in {r.key for r in runs} else runs[0].key
    if "scenario" not in st.session_state or st.session_state["scenario"] not in by_scenario:
        st.session_state["scenario"] = st.session_state[state.RUN_KEY].split("/")[0]
        if st.session_state["scenario"] not in by_scenario:
            st.session_state["scenario"] = runs[0].scenario

    scenario = st.sidebar.selectbox("Scenario", list(by_scenario), key="scenario")
    options = by_scenario[scenario]
    if st.session_state.get(state.RUN_KEY) not in options:
        st.session_state[state.RUN_KEY] = options[0]
    # A Chapter 6 run shows its thesis label first, then its own name.
    st.sidebar.selectbox("Run", options, key=state.RUN_KEY,
                         format_func=lambda k: ("📤 " if k in uploaded else "")
                         + (f"{labels[k]} · " if k in labels else "") + k.split("/", 1)[1]
                         + (f" · {statuses[k]}" if k in statuses else ""))
    st.query_params["run"] = st.session_state[state.RUN_KEY]

    ref = state.selected_ref()
    if ref is not None:
        try:
            summary = data.load_summary(ref.path)
            status = (summary.get("solver") or {}).get("status", "unknown")
            color = {"optimal": "green", "time_limit": "orange", "infeasible": "red",
                     "no_solution": "red"}.get(status, "gray")
            st.sidebar.badge(data.solver_short(summary.get("solver") or {})
                             if status != "unknown" else "solver: unknown", color=color)
        except (OSError, ValueError):
            st.sidebar.badge("summary.json unreadable", color="red")
        if ref.key in uploaded:
            st.sidebar.caption("📤 Uploaded in this session")
        if data.is_archive(ref.scenario):
            st.sidebar.caption("🗄️ Archived run, made before release 1.0.0")
        st.sidebar.download_button(
            "Download run (.zip)", data=lambda: state.run_zip([ref]),
            file_name=f"{ref.scenario}__{ref.name}.zip", mime="application/zip",
            on_click="ignore", icon=":material/download:", width="stretch",
            help="The run folder plus its scenario's server names and clock, ready to "
                 "send. The other person opens it on the Upload results page.")


def main() -> None:
    runs = state.discover_runs()
    with st.sidebar:
        st.markdown("**ThermaSched** · pick a run")
        st.caption(f"Release {VERSION}")
    if runs:
        _sidebar(runs)

    with st.sidebar:
        st.divider()
        if st.button("Reload results", icon=":material/refresh:", width="stretch",
                     help="Re-scan results/ and drop cached data"):
            st.cache_data.clear()
            st.rerun()
        if SOLVER_INSTALLED:
            st.toggle("Enable *New run* page", key=NEW_RUN_FLAG,
                      help="Adds a page that solves a new run and writes it under results/.")

    upload_page = st.Page(upload.render, title="Upload results", icon=":material/upload:",
                          url_path="upload", default=not runs)
    pages = {}
    if runs:
        state.OVERVIEW_PAGE = st.Page(overview.render, title="Overview",
                                      icon=":material/dashboard:", url_path="overview",
                                      default=True)
        pages["Results"] = [
            state.OVERVIEW_PAGE,
            st.Page(energy.render, title="Energy & Carbon", icon=":material/bolt:",
                    url_path="energy"),
            st.Page(thermal.render, title="Thermal", icon=":material/device_thermostat:",
                    url_path="thermal"),
            st.Page(cooling.render, title="Cooling", icon=":material/ac_unit:",
                    url_path="cooling"),
            st.Page(schedule.render, title="Schedule", icon=":material/view_timeline:",
                    url_path="schedule"),
            st.Page(compliance.render, title="Compliance", icon=":material/rule:",
                    url_path="compliance"),
        ]
        pages["Across runs"] = [
            st.Page(compare.render, title="Compare runs", icon=":material/compare_arrows:",
                    url_path="compare"),
            st.Page(chapter6.render, title="Chapter 6 results", icon=":material/table_view:",
                    url_path="chapter6"),
            st.Page(validation.render, title="Validation", icon=":material/fact_check:",
                    url_path="validation"),
        ]
    else:
        state.OVERVIEW_PAGE = None
    pages["Files"] = [upload_page]
    if SOLVER_INSTALLED and st.session_state.get(NEW_RUN_FLAG):
        pages.setdefault("Solve", []).append(
            st.Page(new_run.render, title="New run", icon=":material/play_circle:",
                    url_path="new-run"))

    st.navigation(pages).run()


main()
