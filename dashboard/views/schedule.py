"""Schedule: Gantt of workloads per server for both schedules, and the table of moves."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from dashboard import charts, data, state


def _filters(run: data.Run) -> dict:
    with st.container(horizontal=True, gap="medium", vertical_alignment="bottom"):
        types = st.pills("Workload type", list(data.WORKLOAD_TYPES), selection_mode="multi",
                         default=list(data.WORKLOAD_TYPES),
                         format_func=data.WORKLOAD_TYPES.get)
        servers = st.multiselect(
            "Servers", run.servers["s"].tolist(), default=[], placeholder="All servers",
            format_func=lambda s: run.servers.set_index("s").loc[s, "label"], width=360)
        query = st.text_input("Workload ID contains", placeholder="e.g. w02", width=200)
        only_moved = st.toggle("Only reassigned", disabled=not run.has_optimized)
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


def render() -> None:
    run = state.current_run()
    pal = state.pal()
    state.page_header("Schedule", run, f"reassignment: {run.settings.get('reassignment', '?')}")
    if not run.has_optimized:
        state.no_optimized_note(run)
    sch = run.schedule.copy()
    if sch.empty:
        st.info("This run has no schedule.csv.")
        return

    moves = data.workload_moves(run)
    moved_ids = set(moves.loc[moves["reassigned"], "i"])
    f = _filters(run)

    sch["lane"] = data.gantt_lanes(sch)
    sch["y"], blocks = charts.gantt_layout(run, sch)
    shown = _apply(sch, f, moved_ids)
    bound = data.period_bounds(run.clock, run.dt_seconds)
    span = [sch["arrival"].min(), max(sch["finish"].max(), sch["deadline"].max())]
    x_range = list(bound(span)) if f["windows"] else list(bound(
        [sch["start"].min(), sch["finish"].max()]))
    x_range = [x_range[0] - pd.Timedelta(minutes=10), x_range[1] + pd.Timedelta(minutes=10)]

    n_total = sch[sch["variant"] == "baseline"]["i"].nunique()
    n_shown = shown[shown["variant"] == "baseline"]["i"].nunique()
    st.caption(f"Showing {n_shown} of {n_total} workloads. Each bar runs from the start of "
               "its first period to the end of its last; concurrent workloads on a server "
               "get their own row. Hover a bar for exact periods.")
    for v in run.variants:
        d = shown[shown["variant"] == v]
        title = data.VARIANT_LABELS[v]
        if v == "optimized":
            title += f" · {len(moved_ids)} reassigned"
        state.chart(charts.gantt(run, d, blocks, pal, title, show_windows=f["windows"],
                                 x_range=x_range), key=f"gantt_{v}")

    st.subheader("Moves and waits")
    m = moves[moves["i"].isin(_apply(sch[sch["variant"] == "baseline"], f, moved_ids)["i"])]
    if run.has_optimized:
        st.caption(f"{len(moved_ids)} workloads changed server. Wait is in periods of "
                   f"{run.dt_seconds / 60:g} min; Δ wait > 0 means the optimizer delayed the start.")
    cols = {
        "workload_id": "Workload", "type_label": "Type",
        "original_server_name": "Original server", "server_name_optimized": "Optimized server",
        "reassigned": "Moved", "original_zone": "Zone (orig)", "final_zone": "Zone (opt)",
        "cross_zone": "Cross-zone", "reason": "Reason",
        "arrival": "Arrival t", "deadline": "Deadline t",
        "start_baseline": "Start t (base)", "start_optimized": "Start t (opt)",
        "wait_baseline": "Wait (base)", "wait_optimized": "Wait (opt)",
        "wait_change": "Δ wait", "compliant_optimized": "Compliant (opt)",
    }
    if not run.has_optimized:
        cols = {k: v for k, v in cols.items() if "optimized" not in k and k not in
                ("reassigned", "wait_change", "original_server_name")}
        cols |= {"server_name_baseline": "Server", "compliant_baseline": "Compliant"}
    cols = {k: v for k, v in cols.items() if k in m}   # zone/reason only in newer runs
    table = m[list(cols)].rename(columns=cols)
    for c in ("Compliant (opt)", "Compliant"):
        if c in table:
            table[c] = table[c].map({1: True, 0: False})
    st.dataframe(table, hide_index=True, height=380, column_config={
        "Δ wait": st.column_config.NumberColumn(format="%+d"),
        "Moved": st.column_config.CheckboxColumn(),
        "Cross-zone": st.column_config.CheckboxColumn(),
    })
    st.download_button("Download moves (CSV)", table.to_csv(index=False).encode(),
                       file_name=f"{run.ref.name}_moves.csv", mime="text/csv",
                       icon=":material/download:")
