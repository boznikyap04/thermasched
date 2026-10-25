"""Chapter 5 charts: the graphs the thesis asks for, for the run picked in the sidebar.

One section at a time: servers (one line per server), cooling (one line per zone, and the cold
plates), energy and carbon, and workloads (Gantt). The optimized schedule is shown; a toggle
adds the baseline, dashed.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from dashboard import charts, data, state

# In the order of the thesis's list of graphs.
SECTIONS = ("Servers", "Cooling", "Energy and carbon", "Workloads")
# Server charts in the order of the thesis's list: column -> (heading, caption).
SERVER_CHARTS = {
    "utilization": ("Server CPU utilization", "How busy each server is: the share of its "
                    "cores in use, Eq. (16)."),
    "temperature_C": ("Predicted server temperature", "Each server against the DVFS "
                      "temperature, where it starts to slow down, and the thermal cap "
                      "T_max − H_min it must stay under."),
    "headroom_C": ("Thermal headroom", "T_max − temperature, Eq. (31): how much temperature "
                   "allowance each server has left. It must stay at or above H_min."),
    "PC_eff_MHz": ("Effective processing capability", "N_cores × f_s × DPF, Eq. (38). It "
                   "drops below a server's full speed only while the server is slowed by "
                   "temperature."),
    "P_IT_W": ("IT power", "P_idle + (P_max − P_idle) × utilization, Eq. (20). An idle "
               "server still draws its idle power."),
}


def _variants(run: data.Run, with_baseline: bool) -> list[str]:
    if not run.has_optimized:
        return ["baseline"]
    return ["optimized", "baseline"] if with_baseline else ["optimized"]


# -- Workloads ---------------------------------------------------------------------------

def _gantt_filters(run: data.Run) -> dict:
    with st.container(horizontal=True, gap="medium", vertical_alignment="bottom"):
        types = st.pills("Workload type", list(data.WORKLOAD_TYPES), selection_mode="multi",
                         default=list(data.WORKLOAD_TYPES),
                         format_func=data.WORKLOAD_TYPES.get)
        servers = st.multiselect(
            "Servers", run.servers["s"].tolist(), default=[], placeholder="All servers",
            format_func=lambda s: run.servers.set_index("s").loc[s, "label"], width=360)
        query = st.text_input("Workload ID contains", placeholder="e.g. w02", width=200)
        only_moved = st.toggle("Only moved workloads", disabled=not run.has_optimized)
        windows = st.toggle("Arrival → deadline windows", value=False)
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


def _workloads(run: data.Run, variants: list[str]) -> None:
    sch = run.schedule.copy()
    if sch.empty:
        st.info("This run has no schedule.csv.")
        return
    st.subheader("Workload schedule")
    opt = sch[sch["variant"] == "optimized"]
    moved_ids = set(opt.loc[opt["reassigned"] == 1, "i"])
    f = _gantt_filters(run)
    sch["lane"] = data.gantt_lanes(sch)
    sch["y"], blocks = charts.gantt_layout(run, sch)
    shown = _apply(sch, f, moved_ids)
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
               "completion, deadline and wait. The *Chapter 5 tables* page lists the same "
               "schedule as a table.")
    for v in variants:
        title = data.VARIANT_LABELS[v]
        if v == "optimized":
            title += f" · {len(moved_ids)} moved"
        state.chart(charts.gantt(run, shown[shown["variant"] == v], blocks, state.pal(), title,
                                 show_windows=f["windows"], x_range=x_range), key=f"gantt_{v}")


# -- Servers -----------------------------------------------------------------------------

def _servers(run: data.Run, variants: list[str]) -> None:
    sp = run.server_period
    if sp.empty:
        st.info("This run has no server_period.csv.")
        return
    pal = state.pal()
    servers = run.servers["s"].tolist()
    picked = st.multiselect("Servers", servers, default=servers,
                            format_func=lambda s: run.servers.set_index("s").loc[s, "label"],
                            help="Applies to every chart on this section. Click a server in a "
                                 "legend to hide it; double-click to show only that server.")
    if not picked:
        st.caption("Pick at least one server.")
        return
    for column, (heading, caption) in SERVER_CHARTS.items():
        st.subheader(heading)
        st.caption(caption)
        state.chart(charts.server_lines(run, pal, picked, column, variants), key=f"srv_{column}")

    st.subheader("Throttling (DPF)")
    shown = sp[sp["variant"].isin(variants)]
    if (shown["DPF"] < 1 - 1e-9).any():
        st.caption(f"DPF is the clock-speed factor: below 1 a server runs slower because it is "
                   f"above {run.T_dvfs_C:g} °C.")
        state.chart(charts.server_lines(run, pal, picked, "DPF", variants), key="srv_DPF")
    else:
        st.success(f"No server slows down: DPF = 1 for every server and period, since none "
                   f"passes {run.T_dvfs_C:g} °C. The *Validation* page shows a case where one "
                   "does.", icon="✅")

    st.subheader("Temperature heatmap")
    st.caption(f"Every server over the day on one colour scale. Blue shades stay below "
               f"{min(run.T_dvfs_C, run.thermal_cap_C):g} °C; amber is above the DVFS "
               "temperature and red above the cap, where cells are also marked ×.")
    state.chart(charts.temperature_heatmap(run, pal, variants), key="srv_heatmap")


# -- Cooling -----------------------------------------------------------------------------

def _cooling(run: data.Run, variants: list[str]) -> None:
    if run.zone_period.empty:
        st.info("This run has no zone_period.csv.")
        return
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
        st.caption("Cold plates are off in this run. Pick *6.2 · Base · Both cooling "
                   "systems optimized* in the sidebar to see them.")
        return
    st.caption("The cold-plate decisions of the servers that have one: coolant inlet "
               "temperature and flow, chosen from the allowed settings.")
    state.chart(charts.server_lines(run, pal, cp, "cp_coolant_C", variants), key="cp_coolant")
    state.chart(charts.server_lines(run, pal, cp, "cp_flow_Lmin", variants), key="cp_flow")


# -- Energy and carbon -------------------------------------------------------------------

def _energy(run: data.Run) -> None:
    pal = state.pal()
    st.caption("Both schedules are always shown here: these charts compare them.")
    st.subheader("Energy by component")
    st.caption("Energy over the whole horizon. Cold-plate pumps use so little (a fraction of "
               "a watt-hour) that their slice does not show; the *Energy* table on the "
               "*Chapter 5 tables* page has the numbers.")
    state.chart(charts.energy_bars(run, pal), key="energy_bars")
    st.subheader("Carbon emissions per period")
    st.caption("Carbon is the energy of IT, CRAC and cold plates times the grid's carbon "
               "intensity in that period (lower panel).")
    state.chart(charts.carbon_and_ci(run, pal), key="carbon")


def render() -> None:
    run = state.current_run()
    state.page_header("Chapter 5 charts", run)
    if not run.has_optimized:
        state.no_optimized_note(run)
    with st.container(horizontal=True, gap="medium", vertical_alignment="center"):
        # One section at a time: a chart inside a hidden st.tabs pane can stall the browser.
        section = st.segmented_control("Section", SECTIONS, default=SECTIONS[0],
                                       key="graphs_section",
                                       label_visibility="collapsed") or SECTIONS[0]
        with_baseline = st.toggle("Compare with baseline", key="graphs_baseline",
                                  disabled=not run.has_optimized
                                  or section == "Energy and carbon",
                                  help="Adds the baseline schedule as dashed lines.")
    variants = _variants(run, with_baseline)
    if section == "Workloads":
        _workloads(run, variants)
    elif section == "Servers":
        _servers(run, variants)
    elif section == "Cooling":
        _cooling(run, variants)
    else:
        _energy(run)
    state.model_note(run)
