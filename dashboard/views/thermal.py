"""Thermal: temperature heatmap, per-server temperature, headroom, utilization, IT power and
effective capability, and DPF throttling."""

from __future__ import annotations

import streamlit as st

from dashboard import charts, data, state

METRICS = {
    "temperature_C": "Temperature",
    "headroom_C": "Headroom",
    "utilization": "CPU utilization",
    "P_IT_W": "IT power",
    "PC_eff_MHz": "Effective capability",
}
CAPTIONS = {
    "temperature_C": "Predicted server temperature with the DVFS and thermal-cap lines.",
    "headroom_C": "Thermal headroom T_max − temperature, Eq. (31); it must stay at or above H_min.",
    "utilization": "Share of the server's cores in use, Eq. (16).",
    "P_IT_W": "IT power P_idle + (P_max − P_idle) × utilization, Eq. (20); all of it becomes heat.",
    "PC_eff_MHz": "Effective processing capability N_cores × f_s × DPF, Eq. (38); it falls below "
                  "the full-speed line only while the server is throttled.",
}


def render() -> None:
    run = state.current_run()
    pal = state.pal()
    state.page_header("Thermal", run, f"DVFS throttling above {run.T_dvfs_C:g} °C · "
                      f"thermal cap {run.thermal_cap_C:g} °C")
    if not run.has_optimized:
        state.no_optimized_note(run)
    sp = run.server_period
    if sp.empty:
        st.info("This run has no server_period.csv.")
        return

    st.subheader("Server temperature over time")
    st.caption(f"One shared colour scale for both schedules. Blue shades stay below "
               f"{min(run.T_dvfs_C, run.thermal_cap_C):g} °C; amber is above the DVFS "
               f"temperature and red above the cap, where cells are also marked ×.")
    state.chart(charts.temperature_heatmap(run, pal))

    st.subheader("Per server over time")
    servers = run.servers["s"].tolist()
    with st.container(horizontal=True, gap="medium", vertical_alignment="bottom"):
        metric = st.pills("Metric", list(METRICS), default="temperature_C",
                          format_func=METRICS.get, key="server_metric") or "temperature_C"
        picked = st.multiselect("Servers", servers, default=servers,
                                format_func=lambda s: run.servers.set_index("s").loc[s, "label"])
    st.caption(CAPTIONS[metric])
    if picked:
        picked = [s for s in servers if s in picked]
        if metric == "temperature_C":
            state.chart(charts.server_temperatures(run, pal, picked))
        else:
            state.chart(charts.server_metric(run, pal, picked, metric))
    else:
        st.caption("Pick at least one server.")

    left, right = st.columns(2)
    with left:
        st.subheader("Thermal headroom")
        st.caption("Smallest headroom (T_max − temperature) across all servers in each "
                   "period; the hover names the tightest server.")
        state.chart(charts.min_headroom(run, pal))
    with right:
        st.subheader("Throttling (DPF)")
        throttled = data.throttled_servers(run)
        if throttled.empty:
            st.success("No throttling: DPF = 1 for every server and period in "
                       + ("both schedules." if len(run.variants) > 1 else "the baseline."),
                       icon="✅")
        else:
            st.caption("DPF is the clock-speed factor: below 1 the server runs slower "
                       f"because it is above {run.T_dvfs_C:g} °C.")
            table = throttled.assign(variant=throttled["variant"].map(data.VARIANT_LABELS))
            st.dataframe(table.drop(columns="s"), hide_index=True, column_config={
                "variant": "Schedule", "name": "Server",
                "periods_throttled": st.column_config.NumberColumn("Periods with DPF < 1"),
                "min_DPF": st.column_config.NumberColumn("Lowest DPF", format="%.4f")})
    if not throttled.empty:
        s_list = [s for s in servers if s in set(throttled["s"])]
        state.chart(charts.dpf_lines(run, pal, s_list))

    with st.expander("Per-server summary (compliance_servers.csv)"):
        st.dataframe(run.compliance_servers, hide_index=True)
