"""Test charts: the key results and charts of one test's optimized schedule, for the
configuration, scenario and test picked at the top, with the Base of its scenario dashed.

One topic at a time: servers (one line per server), cooling (one line per zone, and the cold
plates), energy and carbon, and workloads (Gantt). The heuristic baseline is not shown; the
comparison is always with the Base test.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from dashboard import charts, data, state
from dashboard.views.section import NOT_APPLICABLE, SHORT_TITLES, _heading
from scheduler import experiments as ex

PAGE = "detail"
TOPICS = ("Servers", "Cooling", "Energy and carbon", "Workloads")
# Three a row leave room for the value, its change and the Base's value.
TILES_PER_ROW = 3
DIGITS = {"kg CO₂": 2, "kWh": 2, "Wh": 3, "°C": 1, "": 0}
DELTA_COLOR = {"lower": "inverse", "higher": "normal", "neutral": "off"}
STATUS_COLOR = {"optimal": "green", "time_limit": "orange", "infeasible": "red",
                "no_solution": "red"}
# Server charts in the order of the thesis's list: column -> (heading, caption).
SERVER_CHARTS = {
    "utilization": ("Server CPU utilization", "How busy each server is: the share of its "
                    "cores in use, Eq. (16)."),
    "temperature_C": ("Predicted server temperature", "Each server against the DVFS "
                      "temperature, where it starts to slow down, and this test's thermal cap "
                      "T_max − H_min it must stay under."),
    "headroom_C": ("Thermal headroom", "T_max − temperature, Eq. (31): how much temperature "
                   "allowance each server has left. It must stay at or above this test's "
                   "H_min."),
    "PC_eff_MHz": ("Effective processing capability", "N_cores × f_s × DPF, Eq. (38). It "
                   "drops below a server's full speed only while the server is slowed by "
                   "temperature."),
    "P_IT_W": ("IT power", "P_idle + (P_max − P_idle) × utilization, Eq. (20). An idle "
               "server still draws its idle power."),
}


# -- What was run --------------------------------------------------------------------------

def _header(run: data.Run) -> None:
    release = run.provenance.get("thermasched_version") or data.UNVERSIONED
    st.caption(f"Run `results/{run.ref.key}` · release {release}")
    with st.container(horizontal=True, gap="small"):
        for label, value in data.settings_badges(run.summary):
            st.badge(f"{label}: {value}", color="gray")
    st.caption(data.provenance_caption(run.summary))
    for warning in data.provenance_warnings(run.summary):
        st.warning(warning, icon=":material/difference:")


def _same_schedule_note(run: data.Run, base: data.Run, tag: str) -> None:
    # whole-day runs only: a per-tick run's status says only whether some tick hit its cap
    stopped = all(r.solver.get("status") == "time_limit" and data.per_tick_info(r.summary) is None
                  for r in (run, base))
    st.info(f"**{tag} has the same optimized schedule as the Base:** every workload runs on "
            "the same server and starts in the same period, so the server and workload "
            "charts match the Base's. Cooling, energy and carbon still differ where this test "
            "changes them (zones, cooling, carbon intensity)."
            + (" Both runs stopped at their time limit, so the solver did not find a "
               "different schedule for this test in the time it had." if stopped else ""),
            icon=":material/content_copy:")


def _infeasibility(run: data.Run) -> None:
    status = run.solver.get("status", "unknown")
    st.error(f"**No optimized schedule.** The solver ended with status **{status}**, so this "
             "test has no charts.", icon="⛔")
    _diagnosis(run)


def _stuck(run: data.Run, stuck: dict) -> None:
    """A per-tick run that stopped at a tick: where, why, what it keeps. It is a result of
    the release, so a warning, not an error."""
    clock = run.clock.set_index("t")["clock"].get(stuck.get("tick"))
    st.warning(f"**No full-day result.** {data.stuck_sentence(run.summary, clock)}",
               icon=":material/block:")
    path = run.ref.path / "partial_schedule.csv"
    if path.is_file():
        part = pd.read_csv(path)
        running = int(part["end"].isna().sum()) if "end" in part else 0
        st.caption(f"Partial schedule: {len(part):,} workloads started before tick "
                   f"{stuck.get('tick')}, {running:,} of them still running there "
                   "(`partial_schedule.csv` on *Output files*). The key results, the "
                   "comparison with the Base and the charts need a full day, so this page "
                   "shows the solver's figures up to the stuck tick.")
    _diagnosis(run)
    _solver(run)
    _checks(run)


def _diagnosis(run: data.Run) -> None:
    diag = data.infeasibility_frame(run.summary)
    if diag.empty:
        return
    with st.container(border=True):
        st.markdown("**Infeasibility diagnosis**")
        st.caption("The model was re-solved with one constraint family relaxed at a time. "
                   "*Feasible* means that dropping this family alone makes a valid schedule "
                   "possible, so it is a cause of the infeasibility.")
        icons = {"feasible": "🟢 feasible when relaxed: cause",
                 "infeasible": "🔴 still infeasible"}
        st.dataframe(pd.DataFrame({
            "Relaxed constraint family": diag["label"],
            "Result": diag["result"].map(lambda r: icons.get(r, f"❔ {r}")),
        }), hide_index=True)
        causes = diag.loc[diag["result"] == "feasible", "label"].tolist()
        if causes:
            st.markdown("Likely cause: " + "; ".join(f"**{c}**" for c in causes) + ".")
            if any("Thermal cap" in c for c in causes):
                st.caption(f"Thermal cap for this run: {run.thermal_cap_C:g} °C "
                           f"(T_max − H_min, H_min = {state.fmt_num(run.H_min_C, 0)} °C).")


def _violations(run: data.Run) -> None:
    block = run.summary.get("optimized") or {}
    if block.get("violations"):
        items = "\n".join(f"- {x}" for x in block["violations"])
        st.warning(f"**The optimized schedule breaks limits:**\n{items}", icon="⚠️")


def _per_tick(run: data.Run, sol: dict, ticks: dict) -> None:
    """The solver figures of a run re-planned at every tick, and its solve time per tick."""
    n, cap, limit = ticks.get("n_ticks"), data.ticks_at_cap(ticks), ticks.get("tick_time_limit_s")
    stuck = ticks.get("stuck") if ticks.get("outcome") == "stuck" else None
    if stuck:
        n = int(ticks.get("n_ticks_optimal") or 0) + cap       # the ticks solved before it
        c1, c2, c3, c4 = st.columns(4)
        T = (run.summary.get("scenario") or {}).get("T")
        c4.metric("Stuck at tick", f"{stuck.get('tick')}" + (f" of {T}" if T else ""),
                  help=data.stuck_reason(stuck, limit).capitalize() + ".")
    else:
        c1, c2, c3 = st.columns(3)
    c1.metric("Solve time, all ticks", state.fmt_num(sol.get("solve_time_s"), 0, "s"))
    gap = ticks.get("max_mip_gap") if stuck else sol.get("mip_gap")
    c2.metric("Worst tick's MIP gap", "–" if gap is None else f"{gap * 100:.2f}%",
              help=f"Requested for every tick: {run.settings.get('mip_rel_gap', 0) * 100:g}%")
    c3.metric("Ticks at the cap", f"{cap} of {n}" + (" solved" if stuck else ""),
              help=f"Each tick's solve stops after {limit:g} s with the best plan found so far.")
    frame = data.load_ticks(run.ref.path)
    if frame is not None:
        state.chart(charts.tick_solve_times(frame, run.clock, state.pal(), limit), key="ticks")
        st.caption("Solve time of each tick, at the time of its period. A tick sees the "
                   "workloads that have arrived and plans to the end of the day; only its own "
                   "period's decisions are kept. Hover a bar for its MIP gap and how many "
                   "workloads were waiting."
                   + (" The last bar is the stuck tick." if stuck else ""))


def _solver(run: data.Run) -> None:
    sol = run.solver
    status = sol.get("status", "unknown")
    ticks = data.per_tick_info(run.summary)
    with st.container(border=True):
        with st.container(horizontal=True, gap="small", vertical_alignment="center"):
            st.markdown("**Solver**")
            st.badge(data.solver_short(sol, ticks) if status != "unknown" else "unknown",
                     color=STATUS_COLOR.get(status, "gray"))
        if data.stuck_info(run.summary) is None:      # a stuck run says it above
            st.caption(data.solver_sentence(sol, ticks))
        if ticks is not None:
            _per_tick(run, sol, ticks)
        else:
            c1, c2, c3 = st.columns(3)
            c1.metric("Solve time", state.fmt_num(sol.get("solve_time_s"), 0, "s"))
            gap = sol.get("mip_gap")
            c2.metric("MIP gap", "–" if gap is None else f"{gap * 100:.2f}%",
                      help=f"Requested: {run.settings.get('mip_rel_gap', 0) * 100:g}%")
            bound = sol.get("best_bound_g")
            c3.metric("Best bound",
                      state.fmt_num(None if bound is None else bound / 1000, 3, "kg"),
                      help="Lower bound on the optimum: no schedule can emit less.")
        with st.expander("Solver details"):
            obj = sol.get("objective_g")
            size = (f" · {state.fmt_num(sol.get('n_variables'), 0)} variables "
                    f"({state.fmt_num(sol.get('n_binaries'), 0)} binary) · "
                    f"{state.fmt_num(sol.get('n_constraints'), 0)} constraints"
                    if sol.get("n_variables") else "")     # a stuck run has no model to count
            st.caption(f"Objective (carbon) {state.fmt_num(None if obj is None else obj / 1000, 3, 'kg')}"
                       + size + (f" · {sol['solver_status_text']}" if sol.get("solver_status_text")
                                 else ""))
            if sol.get("relaxed"):
                st.caption(f"Relaxed families: {', '.join(sol['relaxed'])}")
            for n in sol.get("notes") or []:
                st.markdown(f"- {n}")


def _tile(row: pd.Series, run: data.Run, with_base: bool) -> None:
    digits = DIGITS.get(row["unit"], 2)
    unit = row["unit"]
    m = (run.summary.get("optimized") or {}).get("metrics", {})
    help_text = (f"On {run.server_name(m.get('hottest_server'))}, period "
                 f"t={m.get('hottest_period')}." if row["key"] == "hottest_T_C" else None)
    # The unit goes in the label, so the value and the Base's value stay short.
    label = f"{row['label']} ({unit})" if unit else row["label"]
    value = state.fmt_num(row["value"], digits)
    if not with_base or pd.isna(row["base"]):
        st.metric(label, value, border=True, help=help_text)
        return
    diff, pct = row["diff"], row["pct"]
    arrow = "auto"
    if abs(diff) < 10 ** -(digits + 1):
        delta, color, arrow = "no change", "off", "off"
    else:
        delta = f"{diff:+,.{digits}f}"
        if not pd.isna(pct):
            delta += f" ({pct:+.1f}%)"
        color = DELTA_COLOR[row["better"]]
    st.metric(label, value, delta=delta, delta_color=color, delta_arrow=arrow, border=True,
              help=help_text,
              delta_description=f"Base {state.fmt_num(row['base'], digits)}")


def _kpis(run: data.Run, base: data.Run | None) -> None:
    kpis = data.kpi_frame(run.summary, base.summary if base is not None else None)
    for start in range(0, len(kpis), TILES_PER_ROW):
        cols = st.columns(TILES_PER_ROW)
        for col, (_, row) in zip(cols, kpis.iloc[start:start + TILES_PER_ROW].iterrows()):
            with col:
                _tile(row, run, base is not None)


def _checks(run: data.Run) -> None:
    checks = data.checks_frame(run.summary)
    if checks.empty:
        st.caption("No self-checks recorded for this run.")
        return
    failed = checks[checks["passed"] == False]  # noqa: E712 - None means not applicable
    n = len(checks)
    title = (f"✅ All {n} self-checks passed" if failed.empty
             else f"❌ {len(failed)} of {n} self-checks failed: " + ", ".join(failed["label"]))
    with st.expander(title, expanded=not failed.empty):
        for _, c in checks.iterrows():
            icon, word = {True: ("✅", "pass"), False: ("❌", "FAIL")}.get(c["passed"], ("➖", "n/a"))
            st.markdown(f"{icon} **{word}** · {c['label']}")
            if c["detail"]:
                st.caption(c["detail"])


# -- Workloads -----------------------------------------------------------------------------

def _gantt_filters(run: data.Run) -> dict:
    with st.container(horizontal=True, gap="medium", vertical_alignment="bottom"):
        types = st.pills("Workload type", list(data.WORKLOAD_TYPES), selection_mode="multi",
                         default=list(data.WORKLOAD_TYPES),
                         format_func=data.WORKLOAD_TYPES.get, key="detail_types")
        servers = st.multiselect(
            "Servers", run.servers["s"].tolist(), default=[], placeholder="All servers",
            format_func=lambda s: run.servers.set_index("s").loc[s, "label"], width=360,
            key="detail_gantt_servers")
        query = st.text_input("Workload ID contains", placeholder="e.g. w02", width=200,
                              key="detail_query")
        only_moved = st.toggle("Only moved workloads", key="detail_only_moved")
        windows = st.toggle("Arrival → deadline windows", value=False, key="detail_windows")
    return dict(types=types or [], servers=servers, query=query.strip(),
                only_moved=only_moved, windows=windows)


def _apply(df: pd.DataFrame, f: dict, moved_ids: set) -> pd.DataFrame:
    keep = df["type"].isin(f["types"])
    if f["servers"]:
        keep &= df["server"].isin(f["servers"]) | df["original_server"].isin(f["servers"])
    if f["query"]:
        keep &= df["workload_id"].str.contains(f["query"], case=False, regex=False)
    if f["only_moved"]:
        keep &= df["i"].isin(moved_ids)
    return df[keep]


def _workloads(run: data.Run) -> None:
    sch = run.schedule.copy()
    if sch.empty:
        st.info("This run has no schedule.csv.")
        return
    variants = list(run.variants)
    st.subheader("Workload schedule")
    moved = {v: set(sch.loc[(sch["variant"] == v) & (sch["reassigned"] == 1), "i"])
             for v in variants}
    f = _gantt_filters(run)
    sch["lane"] = data.gantt_lanes(sch)
    sch["y"], blocks = charts.gantt_layout(run, sch)
    shown = _apply(sch, f, set().union(*moved.values()))
    bound = data.period_bounds(run.clock, run.dt_seconds)
    span = ([sch["arrival"].min(), max(sch["finish"].max(), sch["deadline"].max())]
            if f["windows"] else [sch["start"].min(), sch["finish"].max()])
    x_range = list(bound(span))
    x_range = [x_range[0] - pd.Timedelta(minutes=10), x_range[1] + pd.Timedelta(minutes=10)]
    first = variants[0]
    st.caption(f"Showing {shown[shown['variant'] == first]['i'].nunique()} of "
               f"{sch[sch['variant'] == first]['i'].nunique()} workloads. Each bar runs from "
               "the workload's start to its completion on its server; workloads running at "
               "once on a server get their own row. Hover a bar for its arrival, start, "
               "completion, deadline and wait. The scenario page lists every workload's "
               "original and new server."
               + (" The Base's schedule is below this test's." if len(variants) > 1 else ""))
    for v in variants:
        state.chart(charts.gantt(run, shown[shown["variant"] == v], blocks, state.pal(),
                                 f"{v} · {len(moved[v])} moved", show_windows=f["windows"],
                                 x_range=x_range), key=f"gantt_{v}")


# -- Servers -------------------------------------------------------------------------------

def _servers(run: data.Run) -> None:
    sp = run.server_period
    if sp.empty:
        st.info("This run has no server_period.csv.")
        return
    variants = list(run.variants)
    pal = state.pal()
    servers = run.servers["s"].tolist()
    picked = st.multiselect("Servers", servers, default=servers, key="detail_servers",
                            format_func=lambda s: run.servers.set_index("s").loc[s, "label"],
                            help="Applies to every chart on this topic. Click a server in a "
                                 "legend to hide it; double-click to show only that server.")
    if not picked:
        st.caption("Pick at least one server.")
        return
    for column, (heading, caption) in SERVER_CHARTS.items():
        st.subheader(heading)
        st.caption(caption)
        state.chart(charts.server_lines(run, pal, picked, column, variants), key=f"srv_{column}")

    st.subheader("Throttling (DPF)")
    if (sp["DPF"] < 1 - 1e-9).any():
        st.caption(f"DPF is the clock-speed factor: below 1 a server runs slower because it is "
                   f"above {run.T_dvfs_C:g} °C.")
        state.chart(charts.server_lines(run, pal, picked, "DPF", variants), key="srv_DPF")
    else:
        st.success(f"No server slows down: DPF = 1 for every server and period, since none "
                   f"passes {run.T_dvfs_C:g} °C.", icon="✅")

    st.subheader("Temperature heatmap")
    st.caption(f"Every server over the day on one colour scale. Blue shades stay below "
               f"{min(run.T_dvfs_C, run.thermal_cap_C):g} °C; amber is above the DVFS "
               "temperature and red above the cap, where cells are also marked ×.")
    state.chart(charts.temperature_heatmap(run, pal, variants), key="srv_heatmap")


# -- Cooling -------------------------------------------------------------------------------

def _cooling(run: data.Run) -> None:
    if run.zone_period.empty:
        st.info("This run has no zone_period.csv.")
        return
    variants = list(run.variants)
    pal = state.pal()
    st.caption("Airflow is not modelled: the CRAC's decision is its supply-air temperature, "
               "and its electricity is the heat it removes divided by its COP at that "
               "temperature.")
    st.subheader("CRAC supply-air temperature")
    st.caption("The cooling decision per zone and period (whole degrees). Grey band: the "
               "allowed range. A warmer supply raises the COP, so the same heat costs less "
               "electricity.")
    state.chart(charts.zone_lines(run, pal, "supply_temp_C", variants), key="zone_supply")
    st.subheader("CRAC energy")
    st.caption(f"Electricity each zone's CRAC uses per {run.dt_seconds / 60:g}-minute period.")
    state.chart(charts.zone_lines(run, pal, "E_crac_kWh", variants), key="zone_energy")

    cp = charts.cold_plate_servers(run)
    st.subheader("Cold plates")
    if not cp:
        st.caption("Cold plates are off in this run. The tests of 6.2 have them on.")
        return
    st.caption("The cold-plate decisions of the servers that have one: coolant inlet "
               "temperature and flow, chosen from the allowed settings.")
    state.chart(charts.server_lines(run, pal, cp, "cp_coolant_C", variants), key="cp_coolant")
    state.chart(charts.server_lines(run, pal, cp, "cp_flow_Lmin", variants), key="cp_flow")


# -- Energy and carbon ---------------------------------------------------------------------

def _energy(run: data.Run) -> None:
    pal = state.pal()
    st.subheader("Energy by component")
    st.caption("Energy over the horizon. Cold-plate pumps use so little (a fraction of a "
               "watt-hour) that their slice does not show; the key results above have the "
               "number.")
    state.chart(charts.energy_bars(run, pal), key="energy_bars")
    st.subheader("Carbon emissions per period")
    st.caption("Carbon is the energy of IT, CRAC and cold plates times the grid's carbon "
               "intensity in that period (lower panel).")
    state.chart(charts.carbon_and_ci(run, pal), key="carbon")


# -- Page ----------------------------------------------------------------------------------

def _pick() -> tuple[ex.Configuration, ex.Section, str]:
    config = state.pick_config(PAGE)
    key = state.pick_kept("section", "Scenario", [s.key for s in ex.SECTIONS], PAGE,
                          format_func=lambda k: f"{k} {SHORT_TITLES[k]}")
    section = ex.SECTION_BY_KEY[key]
    tag = state.pick_kept("test", "Test", [t for t, _ in section.tests], PAGE)
    return config, section, tag


def render() -> None:
    st.title("Test charts")
    st.caption("The key results and charts of one test's optimized schedule. Every test is "
               "compared with the Base of its scenario, drawn dashed.")
    config, section, tag = _pick()
    tests = dict(section.tests)
    test = ex.TEST_BY_ID[tests[tag]]
    base_tag, base_id = section.tests[0]
    st.subheader(f"{section.key} {_heading(tag, test.name)}")
    if not ex.applicable(test, config):
        st.info(f"{section.key} {tag} does not apply to {config.label}: "
                f"{NOT_APPLICABLE[test.needs]}.")
        return
    cat = state.chapter6()[1]
    ref, _ = cat[(config.key, test.id)]
    if ref is None:
        if config.key not in data.configs_with_runs(cat):
            st.info(f"No run: {config.label} is not run in this release.",
                    icon=":material/do_not_disturb_on:")
        else:
            st.info(f"No run of {section.key} {tag} for {config.label} yet.")
        return
    run = state.load_run(ref)
    _header(run)
    if not run.has_optimized:
        stuck = data.stuck_info(run.summary)
        if stuck is not None:
            _stuck(run, stuck)
        else:
            _infeasibility(run)
        return
    base = None
    if tag != base_tag:
        base_ref, _ = cat[(config.key, base_id)]
        base = state.load_run(base_ref) if base_ref is not None else None
        if base is None:
            st.caption(f"The {section.key} Base has no run for {config.label}, so there is "
                       "nothing to compare with.")
        elif not base.has_optimized:
            base_stuck = data.stuck_info(base.summary)
            why = (f"got stuck at tick {base_stuck.get('tick')} "
                   f"({data.stuck_reason(base_stuck, base.settings.get('tick_time_limit_s'))})"
                   if base_stuck else f"ended with status {base.solver.get('status')}")
            st.caption(f"The {section.key} Base {why} and has no full-day schedule, so there "
                       "is nothing to compare with.")
            base = None
    _violations(run)
    if base is not None and data.same_schedule(run, base):
        _same_schedule_note(run, base, tag)

    st.markdown("**Key results**" + (" · this test, and its change against the Base"
                                     if base is not None else ""))
    _kpis(run, base)
    _solver(run)
    _checks(run)

    with st.container(horizontal=True, gap="medium", vertical_alignment="center"):
        # One topic at a time: a chart inside a hidden st.tabs pane can stall the browser.
        topic = state.pick_kept("topic", "Topic", list(TOPICS), PAGE)
        with_base = st.toggle("Base dashed", value=True, key="detail_base",
                              disabled=base is None,
                              help="Adds the Base's optimized schedule as dashed lines.")
    shown = data.against_base(run, tag, base if with_base else None)
    if topic == "Servers":
        _servers(shown)
    elif topic == "Cooling":
        _cooling(shown)
    elif topic == "Energy and carbon":
        _energy(shown)
    else:
        _workloads(shown)
    note = run.summary.get("model_note")
    if note:
        st.caption(f"ℹ️ Model note: {note}")
