"""New run (optional): build RunSettings, solve in a background thread, refresh the list.

This is the only page that writes: scheduler.run.run() writes
results/<scenario>/<run_name>/. It is hidden unless switched on in the sidebar.
"""

from __future__ import annotations

import threading
import time
import traceback
from dataclasses import dataclass, field

import streamlit as st

from dashboard import data, state


@dataclass
class Job:
    settings: object
    started: float = field(default_factory=time.time)
    finished: float | None = None
    summary: dict | None = None
    error: str | None = None
    thread: threading.Thread | None = None

    @property
    def done(self) -> bool:
        return self.finished is not None

    @property
    def key(self) -> str:
        return f"{self.settings.scenario}/{self.settings.run_name}"


@st.cache_resource
def _jobs() -> dict[str, Job]:
    """Jobs shared across reruns and sessions (one solve at a time: HiGHS uses all cores)."""
    return {}


def _work(job: Job, diagnosis_s: float) -> None:
    from scheduler.run import run
    try:
        job.summary = run(job.settings, scenarios_dir=str(data.SCENARIOS_DIR),
                          results_dir=str(data.RESULTS_DIR), quiet=True,
                          diagnosis_time_limit_s=diagnosis_s, made_with="dashboard")
    except Exception:  # noqa: BLE001 - reported on the page
        job.error = traceback.format_exc()
    finally:
        job.finished = time.time()


def _scenarios() -> list[str]:
    root = data.SCENARIOS_DIR
    return sorted(p.parent.name for p in root.glob("*/params.json")) if root.is_dir() else []


def _form():
    from scheduler.run import parse_args
    from scheduler.types import (
        BASELINE_RULES, COLD_PLATE_MODES, REASSIGNMENT_MODES, SUPPLY_TEMP_MODES)

    scenarios = _scenarios()
    if not scenarios:
        st.error(f"No scenarios found under `{data.SCENARIOS_DIR}`.")
        return None
    c1, c2, c3 = st.columns(3)
    with c1:
        st.markdown("**Scenario and baseline**")
        scenario = st.selectbox("Scenario", scenarios,
                                index=scenarios.index("small") if "small" in scenarios else 0)
        rule = st.selectbox("Baseline rule", BASELINE_RULES)
        seed = st.number_input("Seed (random rule)", value=42, step=1,
                               disabled=rule != "random")
        base_temp = st.number_input("Baseline supply temperature (°C)", 18.0, 27.0, 18.0, 1.0)
    with c2:
        st.markdown("**Optimized model**")
        reassign = st.selectbox("Reassignment", REASSIGNMENT_MODES)
        mode = st.selectbox("Supply temperature", SUPPLY_TEMP_MODES)
        fixed = st.number_input("Fixed supply temperature (°C)", 18.0, 27.0, base_temp, 1.0,
                                disabled=mode != "fixed")
        h_override = st.checkbox("Override H_min")
        h_min = st.number_input("H_min (°C)", 0.0, 40.0, 10.0, 1.0, disabled=not h_override)
        priority = st.toggle("Priority rules, Eq. (56)-(57)", value=True)
        zone_map = st.text_input("Zone map (blank: servers.csv)", placeholder="e.g. 1,1,1,2,2,2",
                                 help="Zone of each server in order (S1 T1).")
        ci = st.selectbox("Carbon intensity", ["scenario", "flat (mean)"],
                          help="Flat holds CI at the scenario's mean (S4 T3).")
    with c3:
        st.markdown("**Solver and hardware**")
        limit = st.number_input("Time limit (s)", 5.0, 7200.0, 120.0, 30.0)
        gap = st.number_input("Relative MIP gap", 0.0, 0.5, 0.001, 0.001, format="%.4f")
        diag = st.number_input("Diagnosis time per family (s)", 5.0, 600.0, 60.0, 10.0,
                               help="Only used when the model is infeasible.")
        cold = st.toggle("Cold plates")
        count = st.number_input("Cold plates per server (blank: servers.csv)", 0, 8, value=None,
                                disabled=not cold)
        cp_mode = st.selectbox("Cold plates in the optimized run", COLD_PLATE_MODES,
                               disabled=not cold,
                               help="fixed: hold the baseline's flow and coolant (S2 T2).")

    argv = ["--scenario", scenario, "--baseline-rule", rule, "--seed", str(int(seed)),
            "--baseline-supply-temp", f"{base_temp:g}", "--reassignment", reassign,
            "--supply-temp-mode", mode, "--time-limit", f"{limit:g}", "--mip-gap", f"{gap:g}"]
    if mode == "fixed":
        argv += ["--fixed-supply-temp", f"{fixed:g}"]
    if h_override:
        argv += ["--h-min", f"{h_min:g}"]
    if cold:
        argv += ["--cold-plates"] + (["--cold-plate-count", str(int(count))]
                                     if count is not None else [])
        argv += ["--cp-mode", cp_mode]
    if not priority:
        argv += ["--no-priority"]
    if zone_map.strip():
        argv += ["--zone-map", zone_map.strip().replace(" ", "")]
    if ci == "flat (mean)":
        argv += ["--ci-flat"]
    try:
        default_name = parse_args(argv)[0].run_name
    except SystemExit:
        st.error("Zone map must be comma-separated zone numbers, one per server.")
        return None
    name = st.text_input("Run name", value=default_name,
                         help="Folder under results/<scenario>/. Default built from the switches.")
    name = name.strip() or default_name
    if "/" in name or name.startswith("."):
        st.error("The run name must be a plain folder name.")
        return None
    settings = parse_args(argv + ["--run-name", name])[0]
    return settings, diag


def _open(key: str) -> None:
    st.cache_data.clear()
    st.session_state["scenario"] = key.split("/")[0]
    st.session_state[state.RUN_KEY] = key


@st.fragment(run_every=1.0)
def _progress(job: Job) -> None:
    if job.done:
        st.rerun()  # full rerun: the result is drawn outside the fragment
    elapsed = time.time() - job.started
    limit = float(job.settings.time_limit_s)
    st.progress(min(elapsed / limit, 0.99),
                text=f"Solving `{job.key}` · {elapsed:,.0f} s of up to {limit:g} s "
                     "(plus model build, and the diagnosis if infeasible)")


def _result(job: Job) -> None:
    elapsed = job.finished - job.started
    if job.error:
        st.error(f"`{job.key}` failed after {elapsed:,.0f} s.")
        st.code(job.error)
        return
    status = (job.summary.get("solver") or {}).get("status", "baseline only")
    st.success(f"`{job.key}` finished in {elapsed:,.0f} s · solver status **{status}**.",
               icon="✅")
    if st.button("Open in Overview", on_click=_open, args=(job.key,), type="primary",
                 key=f"open_{job.key}_{job.finished}") and state.OVERVIEW_PAGE is not None:
        st.switch_page(state.OVERVIEW_PAGE)


def render() -> None:
    st.title("New run")
    st.caption("Solves the baseline and the optimized model with `scheduler.run.run()` and "
               "writes `results/<scenario>/<run>/`. Solves can take up to the time limit.")
    jobs = _jobs()
    active = next((j for j in jobs.values() if not j.done), None)

    with st.container(border=True):
        out = _form()
    if out is None:
        return
    settings, diag = out
    target = data.RESULTS_DIR / settings.scenario / settings.run_name
    overwrite = True
    if target.exists():
        overwrite = st.checkbox(f"`{settings.scenario}/{settings.run_name}` exists. "
                                "Overwrite it?")
    if st.button("Solve", type="primary", icon=":material/play_arrow:",
                 disabled=active is not None or not overwrite):
        try:
            settings.validate()
        except Exception as e:  # noqa: BLE001
            st.error(str(e))
        else:
            job = Job(settings)
            job.thread = threading.Thread(target=_work, args=(job, diag), daemon=True,
                                          name=f"solve-{job.key}")
            jobs[job.key] = job
            job.thread.start()
            active = job

    if active is not None and active.done is False:
        _progress(active)
    finished = [j for j in jobs.values() if j.done]
    for job in sorted(finished, key=lambda j: j.finished, reverse=True)[:3]:
        _result(job)
