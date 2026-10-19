"""Compare runs: settings and key metrics across every run of a scenario."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from dashboard import charts, data, state


def render() -> None:
    pal = state.pal()
    runs = state.discover_runs()
    scenarios = sorted({r.scenario for r in runs}, key=data.scenario_order)
    current = st.session_state.get("scenario", scenarios[0])
    st.title("Compare runs")
    st.caption("Sensitivity analysis: how the switches of a run change what the optimizer "
               "saves. Each run is compared with its own baseline.")
    scenario = st.segmented_control("Scenario", scenarios, required=True,
                                    default=current if current in scenarios else scenarios[0])
    refs = [r for r in runs if r.scenario == scenario]
    df = state.runs_frame(refs)
    if df.empty:
        st.info("No runs for this scenario.")
        return

    builds = sorted(df["scenario_build"].dropna().unique())
    if len(builds) > 1:
        st.warning(
            f"These runs were solved on {len(builds)} different builds of `{scenario}` "
            f"({', '.join(f'`{b}`' for b in builds)}). A build is made by one release from "
            "one set of settings and data; savings are comparable only between runs of the "
            "same build. See the *Scenario build* column.", icon=":material/difference:")

    st.subheader("Carbon saved")
    state.chart(charts.compare_saved(df, pal))
    st.subheader("Total carbon, baseline vs optimized")
    state.chart(charts.compare_carbon(df, pal))

    st.subheader("Runs")
    shown = df.drop(columns="scenario").copy()
    shown["H_min_C"] = shown["H_min_C"].map(lambda h: "default" if pd.isna(h) else f"{h:g}")
    st.dataframe(shown, hide_index=True, column_config={
        "run": st.column_config.TextColumn("Run", pinned=True),
        "scenario_build": st.column_config.TextColumn(
            "Scenario build", help="Fingerprint of the scenario inputs the run was solved on; "
                                   f"`{data.UNKNOWN_BUILD}` for runs made {data.UNVERSIONED}."),
        "version": "Release", "made_with": "Made with",
        "baseline_rule": "Baseline rule",
        "baseline_supply_C": st.column_config.NumberColumn("Baseline supply (°C)", format="%g"),
        "reassignment": "Reassignment", "supply_temp": "Supply temp.",
        "H_min_C": "H_min (°C)",
        "cold_plates": "Cold plates", "status": "Solver status",
        "solve_time_s": st.column_config.NumberColumn("Solve time (s)", format="%.1f"),
        "mip_gap": st.column_config.NumberColumn("MIP gap", format="percent"),
        "baseline_valid": "Baseline valid", "optimized_valid": "Optimized valid",
        "baseline_carbon_kg": st.column_config.NumberColumn("Baseline carbon (kg)",
                                                            format="%.3f"),
        "optimized_carbon_kg": st.column_config.NumberColumn("Optimized carbon (kg)",
                                                             format="%.3f"),
        "carbon_saved_kg": st.column_config.NumberColumn("Carbon saved (kg)", format="%.3f"),
        "carbon_saved_pct": st.column_config.NumberColumn("Carbon saved (%)", format="%.2f%%"),
        "baseline_E_total_kWh": st.column_config.NumberColumn("Baseline energy (kWh)",
                                                              format="%.3f"),
        "optimized_E_total_kWh": st.column_config.NumberColumn("Optimized energy (kWh)",
                                                               format="%.3f"),
        "energy_saved_pct": st.column_config.NumberColumn("Energy saved (%)", format="%.2f%%"),
        "baseline_hottest_C": st.column_config.NumberColumn("Baseline hottest (°C)",
                                                            format="%.1f"),
        "optimized_hottest_C": st.column_config.NumberColumn("Optimized hottest (°C)",
                                                             format="%.1f"),
        "n_reassigned": st.column_config.NumberColumn("Reassigned", format="%d"),
        "optimized_n_noncompliant": st.column_config.NumberColumn("Non-compliant (opt)",
                                                                  format="%d"),
    })
    st.download_button("Download table (CSV)", df.to_csv(index=False).encode(),
                       file_name=f"{scenario}_runs.csv", mime="text/csv",
                       icon=":material/download:")
    st.download_button("Download all these runs (.zip)", data=lambda: state.run_zip(refs),
                       file_name=f"{scenario}_runs.zip", mime="application/zip",
                       on_click="ignore", icon=":material/folder_zip:",
                       help="Every run of this scenario in one zip, to open on the "
                            "Upload results page.")
    st.caption("Runs differ in more than one switch at once (e.g. baseline rule and supply "
               "temperature), so read differences against the settings columns. A run "
               "without an optimized schedule has no saving.")
