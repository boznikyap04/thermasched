"""Cooling: per-zone supply temperature, Q_crac, P_crac and COP; limits and ramps; cold-plate
coolant temperature and flow next to the CRAC supply air."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from dashboard import charts, data, state

TOL = 1e-6


def _zone_table(cz: pd.DataFrame) -> pd.DataFrame:
    t = pd.DataFrame({
        "Schedule": cz["variant"].map(data.VARIANT_LABELS),
        "Zone": "Zone " + cz["z"].astype(str),
        "Supply used (°C)": cz["supply_min_C"].map("{:g}".format) + "–"
        + cz["supply_max_C"].map("{:g}".format),
        "Supply allowed (°C)": cz["supply_allowed_min_C"].map("{:g}".format) + "–"
        + cz["supply_allowed_max_C"].map("{:g}".format),
        "Max 15-min ramp (°C)": cz["max_ramp_short_C"],
        "15-min limit (°C)": cz["ramp_short_limit_C"],
        "Max 1-h ramp (°C)": cz["max_ramp_long_C"],
        "1-h limit (°C)": cz["ramp_long_limit_C"],
        "Peak Q_crac (kW)": cz["Q_crac_peak_kW"],
        "Capacity (kW)": cz["Q_crac_capacity_kW"],
        "15-min ramp used": 100 * cz["max_ramp_short_C"] / cz["ramp_short_limit_C"],
        "1-h ramp used": 100 * cz["max_ramp_long_C"] / cz["ramp_long_limit_C"],
        "Capacity used": 100 * cz["Q_crac_peak_kW"] / cz["Q_crac_capacity_kW"],
    })
    ok = ((cz["supply_min_C"] >= cz["supply_allowed_min_C"] - TOL)
          & (cz["supply_max_C"] <= cz["supply_allowed_max_C"] + TOL)
          & (cz["max_ramp_short_C"] <= cz["ramp_short_limit_C"] + TOL)
          & (cz["max_ramp_long_C"] <= cz["ramp_long_limit_C"] + TOL)
          & (cz["Q_crac_peak_kW"] <= cz["Q_crac_capacity_kW"] + TOL))
    t.insert(2, "Status", ok.map({True: "✅ within limits", False: "❌ limit broken"}))
    return t


def _cold_plate_table(ccp: pd.DataFrame) -> pd.DataFrame:
    def rng(lo, hi, fmt):
        return ccp[lo].map(fmt.format) + "–" + ccp[hi].map(fmt.format)
    t = pd.DataFrame({
        "Schedule": ccp["variant"].map(data.VARIANT_LABELS),
        "Server": ccp["name"],
        "Plates": ccp["n_cold_plates"],
        "Coolant used (°C)": rng("coolant_min_C", "coolant_max_C", "{:.2f}"),
        "Coolant allowed (°C)": rng("coolant_allowed_min_C", "coolant_allowed_max_C", "{:g}"),
        "Flow used (L/min)": rng("flow_min_Lmin", "flow_max_Lmin", "{:g}"),
        "Flow allowed (L/min)": rng("flow_allowed_min_Lmin", "flow_allowed_max_Lmin", "{:g}"),
        "Peak Q_cp (W)": ccp["Q_cp_peak_W"].round(1),
        "Capacity (W)": ccp["Q_cp_capacity_W"],
    })
    ok = ((ccp["coolant_min_C"] >= ccp["coolant_allowed_min_C"] - TOL)
          & (ccp["coolant_max_C"] <= ccp["coolant_allowed_max_C"] + TOL)
          & (ccp["flow_min_Lmin"] >= ccp["flow_allowed_min_Lmin"] - TOL)
          & (ccp["flow_max_Lmin"] <= ccp["flow_allowed_max_Lmin"] + TOL)
          & (ccp["Q_cp_peak_W"] <= ccp["Q_cp_capacity_W"] + TOL))
    t.insert(2, "Status", ok.map({True: "✅ within limits", False: "❌ limit broken"}))
    return t


def render() -> None:
    run = state.current_run()
    pal = state.pal()
    state.page_header("Cooling", run, "CRAC units, one per zone")
    if not run.has_optimized:
        state.no_optimized_note(run)
    zp = run.zone_period
    if zp.empty:
        st.info("This run has no zone_period.csv.")
        return

    metrics = ["supply_temp_C", "Q_crac_kW", "P_crac_kW", "COP"]
    metrics += data.nonzero_columns(zp, ["P_fan_kW", "airflow"])
    hidden = [charts.ZONE_METRICS[m] for m in ("P_fan_kW", "airflow")
              if m in zp and m not in metrics]
    st.subheader("Zone cooling over time")
    cap = ""
    if hidden:
        cap = f"Not shown (not modelled or zero throughout): {', '.join(hidden)}. "
    st.caption(cap + "Grey band: allowed supply-air range. Higher supply air raises COP, "
               "so the same heat is removed with less CRAC power.")
    state.chart(charts.zone_grid(run, pal, metrics))

    cz = run.compliance_zones
    if not cz.empty:
        st.subheader("Limits: supply range, ramps and capacity")
        share = st.column_config.ProgressColumn(format="%.1f%%", min_value=0, max_value=100)
        st.dataframe(_zone_table(cz), hide_index=True, column_config={
            **{c: st.column_config.NumberColumn(format="%.3f")
               for c in ("Max 15-min ramp (°C)", "Max 1-h ramp (°C)", "Peak Q_crac (kW)")},
            "15-min ramp used": share, "1-h ramp used": share, "Capacity used": share})
        st.caption("Ramp limits: supply temperature may change by at most the 15-min limit "
                   "over 3 periods and the 1-h limit over 12 periods. *Used* columns show the "
                   "peak as a share of each limit.")

    cp_servers = charts.cold_plate_servers(run)
    if cp_servers:
        st.subheader("Cooling decisions: CRAC supply air and cold plates")
        st.caption("Top: coolant temperature (solid) and the CRAC supply air of the server's "
                   "zone (dotted), both in °C. Bottom: coolant flow in L/min. CRAC airflow is "
                   "not modelled, so it has no line.")
        state.chart(charts.cooling_decisions(run, pal, cp_servers))
        ccp = run.compliance_cold_plates
        if not ccp.empty:
            st.subheader("Cold-plate limits")
            st.dataframe(_cold_plate_table(ccp), hide_index=True)
    state.model_note(run)
