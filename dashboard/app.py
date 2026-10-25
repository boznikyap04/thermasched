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
from scheduler import experiments as ex  # noqa: E402
from scheduler.version import VERSION  # noqa: E402
from dashboard.views import (  # noqa: E402
    chapter6, graphs, inputs, new_run, overview, section, upload, validation,
)
from dashboard.views import tables as tables_view  # noqa: E402

st.set_page_config(page_title="ThermaSched results", page_icon="🌡️", layout="wide")

NEW_RUN_FLAG = "enable_new_run"
# The New run page needs the solver (HiGHS). A deployment with only dashboard/requirements.txt
# installed has no solver, so the page is not offered there.
SOLVER_INSTALLED = importlib.util.find_spec("highspy") is not None


SIZE_KEY = "config_size"
PAIR_KEY = "config_pair"
OTHER_RUNS = "Other"
SIZE_LABELS = [f"{n} servers" for n in ex.SIZES]


def _pick_config(config_key: str) -> None:
    """Point the configuration widgets at one configuration (before they are drawn)."""
    st.session_state[state.CONFIG_KEY] = config_key
    config = ex.CONFIGURATION_BY_KEY.get(config_key)
    if config is None:
        st.session_state[SIZE_KEY] = OTHER_RUNS
        return
    st.session_state[SIZE_KEY] = config.size_label
    if config.pair_label:
        st.session_state[PAIR_KEY] = config.key


def _scenario_name(ref: data.RunRef) -> str:
    """The scenario a run was solved on (results/servers10/ holds thesis10 runs)."""
    try:
        return (data.load_summary(ref.path).get("scenario") or {}).get("name") or ref.scenario
    except (OSError, ValueError):
        return ref.scenario


def _sidebar() -> None:
    groups = state.config_runs()
    infos = state.run_infos()
    keys = {r.key for refs in groups.values() for r in refs}
    uploaded = {r.key for r in state.discover_runs() if state.is_uploaded(r)}
    statuses = state.run_statuses()
    used = {ref.key for ref, _ in state.chapter6()[1].values() if ref is not None}

    # A run just uploaded (or solved), or named in ?run=<folder>/<run>, picks its
    # configuration. The first visit opens 10 servers.
    wanted = st.session_state.pop(state.PENDING_RUN, None)
    if wanted not in keys and st.session_state.get(state.RUN_KEY) not in keys:
        wanted = st.query_params.get("run")
    if wanted in keys:
        st.session_state[state.RUN_KEY] = wanted
        _pick_config(infos[wanted].config_key)
    elif st.session_state.get(SIZE_KEY) is None:
        _pick_config("servers10")

    sizes = SIZE_LABELS + ([OTHER_RUNS] if data.OTHER in groups else [])
    if st.session_state.get(SIZE_KEY) not in sizes:
        st.session_state[SIZE_KEY] = sizes[-1 if data.OTHER not in groups else -2]
    size = st.sidebar.segmented_control(
        "Configuration", sizes, key=SIZE_KEY, required=True,
        help="Each configuration goes through every Chapter 6 test. *Other* holds runs of "
             "another scenario.")
    if size == OTHER_RUNS:
        config_key = data.OTHER
    else:
        configs = [c for c in ex.CONFIGURATIONS if c.size_label == size]
        if len(configs) > 1:
            pairs = [c.key for c in configs]
            if st.session_state.get(PAIR_KEY) not in pairs:
                st.session_state[PAIR_KEY] = next((k for k in pairs if k in groups), pairs[0])
            config_key = st.sidebar.selectbox(
                "Server pair", pairs, key=PAIR_KEY,
                format_func=lambda k: ex.CONFIGURATION_BY_KEY[k].pair_label
                + ("" if k in groups else " · no runs yet"))
        else:
            config_key = configs[0].key
    st.session_state[state.CONFIG_KEY] = config_key

    options = [r.key for r in groups.get(config_key, [])]
    if not options:
        st.session_state[state.RUN_KEY] = None
        st.sidebar.caption("No runs of this configuration yet. The Chapter 6 pages show which "
                           "tests are still to run.")
        return
    if st.session_state.get(state.RUN_KEY) not in options:
        st.session_state[state.RUN_KEY] = options[0]
    refs = {r.key: r for r in groups[config_key]}

    def name(k: str) -> str:
        ref = refs[k]
        text = k if config_key == data.OTHER else state.run_title(ref)
        if infos[k].tests and k not in used:
            text += f" · older solve ({ref.name})"
        elif not infos[k].tests and config_key != data.OTHER:
            text = f"{ref.name} (validation)" if ref.name.startswith("v_") else ref.name
        return ("📤 " if k in uploaded else "") + text + (f" · {statuses[k]}" if k in statuses
                                                         else "")
    st.sidebar.selectbox("Run", options, key=state.RUN_KEY, format_func=name,
                         help="The pages under *This run* show this run.")
    st.query_params["run"] = st.session_state[state.RUN_KEY]
    st.session_state["scenario"] = _scenario_name(refs[st.session_state[state.RUN_KEY]])

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
        st.markdown("**ThermaSched** · Chapter 6 results")
        st.caption(f"Release {VERSION}")
    if runs:
        _sidebar()

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
        state.OVERVIEW_PAGE = st.Page(overview.render, title="Run summary",
                                      icon=":material/dashboard:", url_path="overview")
        pages["Chapter 6"] = [
            st.Page(chapter6.render, title="Overview", icon=":material/grid_view:",
                    url_path="chapter6", default=True),
            *(st.Page(section.page(s.key), title=f"{s.key} {section.SHORT_TITLES[s.key]}",
                      icon=section.ICONS[s.key], url_path=f"section-{s.key.replace('.', '-')}")
              for s in ex.SECTIONS),
        ]
        pages["This run"] = [
            state.OVERVIEW_PAGE,
            st.Page(graphs.render, title="Charts", icon=":material/show_chart:",
                    url_path="charts"),
            st.Page(tables_view.render, title="Tables", icon=":material/table_view:",
                    url_path="tables"),
        ]
        pages["More"] = [
            st.Page(validation.render, title="Validation", icon=":material/fact_check:",
                    url_path="validation"),
            st.Page(inputs.render, title="Inputs", icon=":material/input:", url_path="inputs"),
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
