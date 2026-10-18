"""Compliance: violations from summary.json and the server, zone, cold-plate, workload and
reassignment tables."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from dashboard import data, state

TOL = 1e-6
FLAG_LABELS = {
    "cpu_ok": "CPU capacity", "mem_ok": "Memory capacity", "thermal_cap_ok": "Thermal cap",
    "workloads_ok": "Workloads (SLA)", "supply_range_ok": "Supply range",
    "zone_temp_ok": "Zone temperature", "ramp_ok": "Supply ramps",
    "crac_capacity_ok": "CRAC capacity", "cold_plate_ok": "Cold plates",
    "cold_plate_coolant_ok": "Coolant range", "cold_plate_flow_ok": "Coolant flow",
    "availability_ok": "Server availability", "priority_ok": "Priority order",
}
WORKLOAD_FLAGS = ["placed", "starts_on_or_after_arrival", "wait_within_allowed", "on_time",
                  "work_complete", "within_horizon"]


def _bad_style(pal) -> str:
    from dashboard.theme import rgba
    return f"background-color: {rgba(pal.status['critical'], 0.22)}"


def _server_table(run: data.Run, v: str, pal) -> None:
    cs = run.compliance_servers[run.compliance_servers["variant"] == v].drop(columns="variant")
    if cs.empty:
        st.caption("No compliance_servers.csv.")
        return
    cap, dvfs = run.thermal_cap_C, run.T_dvfs_C
    bad = pd.DataFrame(False, index=cs.index, columns=cs.columns)
    bad["cpu_peak_cores"] = cs["cpu_peak_cores"] > cs["cpu_capacity_cores"] + TOL
    bad["mem_peak_MB"] = cs["mem_peak_MB"] > cs["mem_capacity_MB"] + TOL
    bad["hottest_T_C"] = cs["hottest_T_C"] > cap + TOL
    bad["periods_above_cap"] = cs["periods_above_cap"] > 0
    if run.H_min_C is not None:
        bad["min_headroom_C"] = cs["min_headroom_C"] < run.H_min_C - TOL
    warn = cs["periods_above_dvfs"] > 0
    status = bad.any(axis=1).map({True: "❌ limit broken", False: "✅ ok"})
    status[~bad.any(axis=1) & warn] = "⚠️ throttled (DVFS)"
    cs = cs.copy()
    cs.insert(0, "Status", status)
    bad.insert(0, "Status", bad.any(axis=1))
    styled = cs.style.apply(lambda _: bad.loc[:, cs.columns].replace(
        {True: _bad_style(pal), False: ""}), axis=None).format(precision=2)
    st.dataframe(styled, hide_index=True, column_config={
        "s": None, "name": "Server", "zone": "Zone", "cold_plate": "Cold plate",
        "cpu_peak_cores": "Peak CPU (cores)", "cpu_capacity_cores": "CPU capacity (cores)",
        "max_utilization": st.column_config.NumberColumn("Max utilization", format="percent"),
        "min_PC_eff_MHz": st.column_config.NumberColumn("Min PC_eff (MHz)", format="%,.0f"),
        "periods_unavailable": "Periods unavailable",
        "mem_peak_MB": "Peak memory (MB)", "mem_capacity_MB": "Memory capacity (MB)",
        "hottest_T_C": f"Hottest (°C, cap {cap:g})", "min_headroom_C": "Min headroom (°C)",
        "periods_above_dvfs": f"Periods > DVFS {dvfs:g} °C",
        "periods_above_cap": f"Periods > cap {cap:g} °C", "min_DPF": "Min DPF",
    })


def _zone_table(run: data.Run, v: str, pal) -> None:
    cz = run.compliance_zones[run.compliance_zones["variant"] == v].drop(columns="variant")
    if cz.empty:
        st.caption("No compliance_zones.csv.")
        return
    bad = pd.DataFrame(False, index=cz.index, columns=cz.columns)
    bad["supply_min_C"] = cz["supply_min_C"] < cz["supply_allowed_min_C"] - TOL
    bad["supply_max_C"] = cz["supply_max_C"] > cz["supply_allowed_max_C"] + TOL
    bad["max_ramp_short_C"] = cz["max_ramp_short_C"] > cz["ramp_short_limit_C"] + TOL
    bad["max_ramp_long_C"] = cz["max_ramp_long_C"] > cz["ramp_long_limit_C"] + TOL
    bad["Q_crac_peak_kW"] = cz["Q_crac_peak_kW"] > cz["Q_crac_capacity_kW"] + TOL
    cz = cz.copy()
    cz.insert(0, "Status", bad.any(axis=1).map({True: "❌ limit broken", False: "✅ ok"}))
    bad.insert(0, "Status", bad.any(axis=1))
    styled = cz.style.apply(lambda _: bad.loc[:, cz.columns].replace(
        {True: _bad_style(pal), False: ""}), axis=None).format(precision=3)
    st.dataframe(styled, hide_index=True, column_config={
        "z": "Zone", "supply_min_C": "Supply min (°C)", "supply_max_C": "Supply max (°C)",
        "supply_allowed_min_C": "Allowed min (°C)", "supply_allowed_max_C": "Allowed max (°C)",
        "zone_limit_C": "Zone limit (°C)", "max_ramp_short_C": "Max 15-min ramp (°C)",
        "ramp_short_limit_C": "15-min limit (°C)", "max_ramp_long_C": "Max 1-h ramp (°C)",
        "ramp_long_limit_C": "1-h limit (°C)", "Q_crac_peak_kW": "Peak Q_crac (kW)",
        "Q_crac_capacity_kW": "Capacity (kW)",
    })


def _workload_table(run: data.Run, v: str, key: str) -> None:
    cw = run.compliance_workloads[run.compliance_workloads["variant"] == v]
    if cw.empty:
        st.caption("No compliance_workloads.csv.")
        return
    n_bad = int((cw["compliant"] == 0).sum())
    only_bad = st.toggle(f"Only non-compliant ({n_bad})", value=n_bad > 0, key=key,
                         disabled=n_bad == 0)
    cw = cw[cw["compliant"] == 0] if only_bad else cw
    cw = cw.drop(columns="variant").copy()
    flags = [c for c in WORKLOAD_FLAGS + ["compliant"] if c in cw]
    for c in flags:
        cw[c] = cw[c].astype(bool)
    cw["work_ratio"] = cw["work_delivered_MHz_s"] / cw["work_required_MHz_s"]
    st.dataframe(cw, hide_index=True, height=320, column_config={
        "i": None, "workload_id": "Workload", "compliant": "Compliant",
        "placed": "Placed", "starts_on_or_after_arrival": "After arrival",
        "wait_within_allowed": "Wait OK", "on_time": "On time", "work_complete": "Work done",
        "within_horizon": "In horizon",
        "min_DPF": st.column_config.NumberColumn("Min DPF while running", format="%.4f"),
        "work_delivered_MHz_s": st.column_config.NumberColumn("Work delivered (MHz·s)",
                                                              format="%.3e"),
        "work_required_MHz_s": st.column_config.NumberColumn("Work required (MHz·s)",
                                                             format="%.3e"),
        "work_ratio": st.column_config.ProgressColumn(
            "Delivered / required", format="%.3f", min_value=0.0, max_value=1.2),
    })


def _cold_plate_table(run: data.Run, v: str) -> None:
    ccp = run.compliance_cold_plates
    ccp = ccp[ccp["variant"] == v].drop(columns="variant") if not ccp.empty else ccp
    if ccp.empty:
        st.caption("No cold plates in this run.")
        return
    st.dataframe(ccp, hide_index=True, column_config={
        "s": None, "name": "Server", "n_cold_plates": "Plates",
        "coolant_min_C": "Coolant min (°C)", "coolant_max_C": "Coolant max (°C)",
        "coolant_allowed_min_C": "Allowed min (°C)", "coolant_allowed_max_C": "Allowed max (°C)",
        "flow_min_Lmin": "Flow min (L/min)", "flow_max_Lmin": "Flow max (L/min)",
        "flow_allowed_min_Lmin": "Allowed min (L/min)", "flow_allowed_max_Lmin": "Allowed max (L/min)",
        "Q_cp_peak_W": st.column_config.NumberColumn("Peak Q_cp (W)", format="%.1f"),
        "Q_cp_capacity_W": "Capacity (W)",
    })


def _reassignment_table(run: data.Run) -> None:
    ra = run.reassignment
    if ra.empty:
        st.caption("No reassignment.csv (the run has no optimized schedule, or predates it).")
        return
    moved = ra[ra["reassigned"] == 1]
    running_moved = int(((ra["B_running"] == 1) & (ra["reassigned"] == 1)).sum())
    st.caption(f"{len(moved)} of {len(ra)} workloads moved, {int(ra['cross_zone'].sum())} to "
               f"another zone. Running workloads (B_i = 1) moved: {running_moved} (must be 0, "
               "Eq. 29). Reasons are a reading of the scored schedule; the solver itself only "
               "minimises carbon.")
    only = st.toggle("Only reassigned", value=len(moved) > 0, key="only_moved_compliance",
                     disabled=moved.empty)
    show = moved if only else ra
    st.dataframe(show, hide_index=True, height=320, column_config={
        "i": None, "original_server": None, "final_server": None, "workload_id": "Workload",
        "type": "Type", "B_running": st.column_config.CheckboxColumn("Running (B_i)"),
        "original_server_name": "Original server", "original_zone": "Original zone",
        "final_server_name": "Final server", "final_zone": "Final zone",
        "reassigned": st.column_config.CheckboxColumn("Moved"),
        "cross_zone": st.column_config.CheckboxColumn("Cross-zone"), "reason": "Reason",
    }, column_order=["workload_id", "type", "B_running", "original_server_name",
                     "original_zone", "final_server_name", "final_zone", "reassigned",
                     "cross_zone", "reason"])


def render() -> None:
    run = state.current_run()
    pal = state.pal()
    state.page_header("Compliance", run)
    if not run.has_optimized:
        state.no_optimized_note(run)

    cols = st.columns(len(run.variants))
    for col, v in zip(cols, run.variants):
        block = run.summary.get(v) or {}
        with col, st.container(border=True):
            ok = block.get("valid")
            st.markdown(f"**{data.VARIANT_LABELS[v]}** · "
                        + ("✅ valid" if ok else "❌ breaks limits"))
            flags = block.get("compliance_flags") or {}
            with st.container(horizontal=True, gap="small"):
                for k, val in flags.items():
                    if k == "all_ok":
                        continue
                    st.badge(FLAG_LABELS.get(k, k), icon="✅" if val else "❌",
                             color="green" if val else "red")
            if block.get("violations"):
                for x in block["violations"]:
                    st.markdown(f"- ❌ {x}")
            else:
                st.caption("No violations.")

    tabs = st.tabs([data.VARIANT_LABELS[v] for v in run.variants])
    for tab, v in zip(tabs, run.variants):
        with tab:
            st.markdown("##### Servers")
            _server_table(run, v, pal)
            st.markdown("##### Zones")
            _zone_table(run, v, pal)
            st.markdown("##### Cold plates")
            _cold_plate_table(run, v)
            st.markdown("##### Workloads")
            _workload_table(run, v, key=f"only_bad_{v}")
            if v == "optimized":
                st.markdown("##### Reassignment")
                _reassignment_table(run)
    st.caption("Cells shaded red break a limit. ⚠️ marks servers that ran above the DVFS "
               "temperature (allowed, but they slow down).")
