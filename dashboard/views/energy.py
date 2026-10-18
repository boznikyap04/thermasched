"""Energy & Carbon: per-period carbon with grid intensity, energy by component, savings."""

from __future__ import annotations

import streamlit as st

from dashboard import charts, data, state


def render() -> None:
    run = state.current_run()
    pal = state.pal()
    state.page_header("Energy & Carbon", run)
    if not run.has_optimized:
        state.no_optimized_note(run)
    if run.comparison_period.empty:
        st.info("This run has no comparison_period.csv.")
        return

    st.subheader("Carbon per period and grid carbon intensity")
    st.caption("Carbon is energy × grid intensity per period. The lower panel shares the "
               "time axis, so cleaner periods line up with the carbon above them.")
    state.chart(charts.carbon_and_ci(run, pal))

    st.subheader("Energy by component")
    hidden = [data.ENERGY_COMPONENTS[c] for c in data.ENERGY_COMPONENTS
              if c not in data.active_energy_components(run)]
    if hidden:
        st.caption(f"Not shown (zero in every period): {', '.join(hidden)}.")
    state.chart(charts.energy_stack(run, pal))

    if not run.has_optimized:
        state.model_note(run)
        return

    sb = data.savings_breakdown(run)
    cum = data.cumulative_savings(run)
    left, right = st.columns([3, 2])
    with left:
        st.subheader("Cumulative carbon saved")
        st.caption("Running total of baseline minus optimized carbon; a falling line means "
                   "the optimized schedule emitted more in those periods.")
        state.chart(charts.cumulative_savings(cum, run, pal))
    with right:
        st.subheader("Where the savings came from")
        st.caption("Carbon saved per component. The *energy effect* is the kWh saved at the "
                   "mean grid intensity; the *timing effect* is the rest, from moving energy "
                   "to cleaner or dirtier periods.")
        state.chart(charts.savings_bars(sb, pal))
    total = sb[["energy_saved_kWh", "carbon_saved_kg", "energy_effect_kg",
                "timing_effect_kg"]].sum()
    table = sb.drop(columns="component").copy()
    table.loc[len(table)] = ["Total", *total]
    st.dataframe(
        table, hide_index=True,
        column_config={
            "label": "Component",
            "energy_saved_kWh": st.column_config.NumberColumn("Energy saved (kWh)",
                                                              format="%.4f"),
            "carbon_saved_kg": st.column_config.NumberColumn("Carbon saved (kg CO₂)",
                                                             format="%.4f"),
            "energy_effect_kg": st.column_config.NumberColumn("Energy effect (kg CO₂)",
                                                              format="%.4f"),
            "timing_effect_kg": st.column_config.NumberColumn("Timing effect (kg CO₂)",
                                                              format="%.4f"),
        })

    with st.expander("Per-period data"):
        st.dataframe(run.comparison_period.drop(columns=["time"]), hide_index=True)
    state.model_note(run)
