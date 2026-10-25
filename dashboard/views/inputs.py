"""Inputs: the scenario's servers, workloads, carbon intensity and fixed parameters, ready to
cite in Chapter 5. Read from scenarios/<scenario>/, not from a run."""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from dashboard import inputs, state
from dashboard.theme import style

SECTIONS = ("Servers", "Workloads", "Carbon intensity", "Parameters")


def _csv(df: pd.DataFrame) -> bytes:
    # utf-8-sig: Excel then reads the °C and other non-ASCII headers correctly.
    return df.to_csv(index=False).encode("utf-8-sig")


def _download(df: pd.DataFrame, scenario: str, key: str) -> None:
    st.download_button(f"Download {key}.csv", _csv(df), file_name=f"{scenario}_{key}.csv",
                       mime="text/csv", icon=":material/download:", key=f"dl-inputs-{key}")


def _servers(scenario: str) -> None:
    df = inputs.server_table(scenario)
    st.dataframe(df, hide_index=True, column_config={
        "Processing capability (MHz)": st.column_config.NumberColumn(format="%,.0f"),
        "Thermal persistence α_s (–)": st.column_config.NumberColumn(format="%.4f"),
        "Thermal resistance R_s (°C/W)": st.column_config.NumberColumn(format="%.4f"),
    })
    _download(df, scenario, "servers")
    st.caption(
        "CPU cores, RAM, idle and maximum power, the starting temperature and the thermal "
        "parameters (a_s, R_s, α_s of the server temperature equation) come from the UniMelb "
        "measurements. UniMelb records no CPU frequency, so the frequencies are literature "
        "values (2.1 / 2.4 / 3.0 GHz, Li et al. 2026) split 4 / 3 / 3 (Marahatta et al. 2021) "
        "and assigned by maximum power: the servers with the highest maximum power get the "
        "highest frequency. Processing capability = cores × frequency. RAM is in GB of 1,024 MB.")


def _workloads(scenario: str) -> None:
    df = inputs.workload_table(scenario)
    n_ts = int((df["Type"] == "time-sensitive").sum())
    st.caption(f"{len(df)} workloads: {n_ts} time-sensitive, {len(df) - n_ts} delay-tolerant. "
               "What each asks for (CPU cores and RAM) and when (arrival, deadline, allowed "
               "delay), with units in the headers. Clock times are the local time at the start "
               "of the period.")
    st.dataframe(df, hide_index=True, height=420, column_config={
        "Work required (MHz·s)": st.column_config.NumberColumn(format="%.4e"),
    })
    _download(df, scenario, "workload_inputs")


def _carbon(scenario: str) -> None:
    df = inputs.carbon_table(scenario)
    params = inputs.load_params(scenario)
    dt = inputs.dt_seconds(params)
    ci = df["Grid carbon intensity (g CO2/kWh)"]
    pal = state.pal()
    # Plot against the period index, labelled with the clock (the day may cross midnight).
    fig = go.Figure(go.Scatter(
        x=df["Period"], y=ci, mode="lines", line=dict(color=pal.ink2, width=1.75),
        customdata=df["Time"], hovertemplate="%{y:,.2f} g CO₂/kWh at %{customdata} "
                                             "(t=%{x})<extra></extra>"))
    style(fig, pal, height=320, legend=False, time_axis=False)
    step = max(1, round(3 * 3600 / dt))          # a tick every 3 hours
    ticks = df["Period"].iloc[::step]
    fig.update_xaxes(title_text="Local time (start of period)", tickvals=ticks,
                     ticktext=df["Time"].iloc[::step])
    fig.update_yaxes(title_text="Grid carbon intensity (g CO₂/kWh)")
    state.chart(fig, key="inputs-ci")
    st.caption(f"Mean {ci.mean():,.2f}, lowest {ci.min():,.2f}, highest {ci.max():,.2f} g CO₂/kWh "
               f"over {len(df)} periods of {dt / 60:g} min.")
    st.dataframe(df, hide_index=True, height=320)
    _download(df, scenario, "carbon_intensity")


def _parameters(scenario: str) -> None:
    df = inputs.parameter_table(scenario)
    st.dataframe(df, hide_index=True, height=min(38 + 35 * len(df), 940))
    _download(df, scenario, "parameters")
    st.caption("From the scenario's params.json. The thermal cap is the highest temperature a "
               "server may reach: T_max minus the safety margin H_min. Runs may override H_min, "
               "the CRAC supply and the cold-plate settings; the run's *Summary* lists them.")


def render() -> None:
    st.title("Inputs")
    names = inputs.scenarios()
    if not names:
        st.info("No scenarios found under scenarios/.")
        return
    current = st.session_state.get("scenario")
    current = current if current in names else ("thesis10" if "thesis10" in names else names[0])
    with st.container(horizontal=True, gap="medium", vertical_alignment="bottom"):
        scenario = st.selectbox("Scenario", names, index=names.index(current),
                                key="inputs_scenario", width=260)
        section = st.segmented_control("Inputs", SECTIONS, default=SECTIONS[0],
                                       key="inputs_section") or SECTIONS[0]
    st.caption(f"The inputs of `{scenario}` for Chapter 5, as the model reads them. Every "
               "table downloads as CSV.")
    {
        "Servers": _servers, "Workloads": _workloads, "Carbon intensity": _carbon,
        "Parameters": _parameters,
    }[section](scenario)
