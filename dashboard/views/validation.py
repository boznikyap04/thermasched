"""Validation: small, controlled checks of the model, and the relationships between the
model's outputs that the thesis's literature predicts.

The model-check tables are written by the validation checks of the release
(results/validation/<scenario>/); the solver notebook's last section computes the same tables.
The relationship plots read the run picked on the page. The page is kept off the site
(dashboard/app.py lists the pages); add it there to bring it back.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from scheduler import experiments as ex
from dashboard import charts, data, relations, state

GROUPS = ("Model checks", "Relationships")
TABS = ("Moves", "Reassignment test", "CRAC", "Speed", "Server A vs B", "Slowdown",
        "Cold plates", "Power")


def _csv(df: pd.DataFrame) -> bytes:
    # utf-8-sig: Excel then reads the °C and other non-ASCII headers correctly.
    return df.to_csv(index=False).encode("utf-8-sig")


def _table(tables: dict, key: str, scenario: str, *, height: int | None = None) -> pd.DataFrame | None:
    df = tables.get(key)
    if df is None:
        st.info(f"No `{key}` table: the run it reads was not in results/ when the checks ran.")
        return None
    kw = {} if height is None else {"height": height}
    st.dataframe(df, hide_index=True, **kw)
    st.download_button(f"Download {key}.csv", _csv(df), file_name=f"{scenario}_{key}.csv",
                       mime="text/csv", icon=":material/download:", key=f"dl-{key}")
    return df


def _verdict(meta: dict, key: str) -> None:
    passed = (meta.get("checks") or {}).get(key, {}).get("passed")
    if passed is True:
        st.badge("Passed", icon=":material/check:", color="green")
    elif passed is False:
        st.badge("Failed", icon=":material/close:", color="red")


def _row(df: pd.DataFrame | None, run: str) -> pd.Series | None:
    if df is None or "Run" not in df:
        return None
    hit = df[df["Run"] == run]
    return None if hit.empty else hit.iloc[0]


def _moves(tables: dict, scenario: str) -> None:
    st.markdown(
        "**Why does no run move a workload?** Every run that allows moves first solves the same "
        "model with moves off (a quick solve that is proven best), then looks for a better "
        "schedule that moves workloads, starting from that one. *0 moves* means it found no "
        "better schedule in its time limit. Nothing in the model blocks moves: with "
        "reassignment *free* every workload may use every server.")
    solver = tables.get("solver")
    free, none = _row(solver, "least_loaded_base18_free_optimize_tl1800"), \
        _row(solver, "least_loaded_base18_none_optimize_tl1800")
    f27, z27, n27 = (_row(solver, f"least_loaded_base18_{m}_fixed27_tl1800")
                     for m in ("free", "same_zone", "none"))
    lines = []
    if free is not None and none is not None:
        lines.append(
            f"- **Base, reassignment allowed, 1800 s:** {free['Solver status'].lower()}, "
            f"{free['Carbon (kg CO2)']:.3f} kg, gap {free['MIP gap (%)']:.2f} %. No schedule can "
            f"emit less than {free['Lower bound (kg CO2)']:.3f} kg, so moving workloads could save "
            f"at most **{free['Most a better schedule could save (kg CO2)']:.3f} kg**. Without "
            f"moves: {none['Solver status'].lower()}, {none['Carbon (kg CO2)']:.3f} kg.")
    for r, what in ((f27, "reassignment allowed"), (z27, "same-zone moves only")):
        if r is not None and n27 is not None:
            lines.append(
                f"- **CRAC fixed at 27 °C, {what}, {r['Time limit (s)']:.0f} s:** "
                f"{r['Solver status'].lower()}, {r['Carbon (kg CO2)']:.3f} kg, "
                f"gap {r['MIP gap (%)']:.2f} %, {int(r['Workloads moved'])} moved; at most "
                f"{r['Most a better schedule could save (kg CO2)']:.3f} kg left to find.")
    if lines:
        st.markdown("\n".join(lines))
    if f27 is not None or z27 is not None:
        st.markdown(
            "The optimized runs all keep the CRAC at 27 °C, so the runs with it fixed there leave "
            "the solver only the timing and the moves to decide. They stop at the time limit "
            "too, still with no move: a better schedule with moves is not ruled out, but it "
            "could save at most the amount above.")
    st.markdown(
        "Moves can only save a little here: every server draws its idle power all day whatever "
        "runs on it, and idle power is most of the IT electricity (see *Server A vs B*). Only the "
        "power a workload adds depends on where it runs. The *Reassignment test* section shows the "
        "model does move workloads when a move is needed or helps.")
    st.markdown("**Every run of this scenario**: how complete each solver result is.")
    _table(tables, "solver", scenario)
    st.caption("*Proven best*: no valid schedule emits less carbon. *Stopped at time limit*: the "
               "best schedule found in the time allowed; the lower bound is what no schedule can "
               "beat, so carbon minus bound is the most a better schedule could still save.")


def _reassignment(meta: dict, tables: dict, scenario: str) -> None:
    _verdict(meta, "reassignment")
    st.markdown(
        "Two small cases built from real servers of the scenario, each solved with reassignment "
        "*none* and *free*. **Move needed:** a time-sensitive workload starts on a slow server "
        "where it cannot meet its deadline. With *none* there is no valid schedule; with *free* "
        "it moves to the fast server and finishes on time. **Move helps:** a delay-tolerant "
        "workload starts on the server that uses the most electricity per unit of work. With "
        "*free* it moves to the most efficient server and emits less carbon.")
    _table(tables, "reassignment", scenario)


def _crac(meta: dict, tables: dict, scenario: str) -> None:
    st.markdown(
        "The CRAC supply temperature is a decision of the model: in each zone and 5-minute "
        "period the solver picks a whole degree in the CRAC's range, limited only by how fast "
        "it may change. A higher supply temperature gives the CRAC a higher COP, so it uses "
        "less electricity for the same heat. The scenario is solved below with moves off "
        "(proven best in seconds) at four safety margins H_min:")
    crac = _table(tables, "crac", scenario)
    if crac is not None:
        st.markdown("\n".join(_crac_line(r) for _, r in crac.iterrows()))
    supply = tables.get("crac_supply")
    if supply is not None and not supply.empty:
        clock = data.load_clock(scenario, int(supply["Period"].max()), float(meta.get("dt_seconds", 300)))
        state.chart(charts.validation_supply(supply, clock, state.pal()), key="val-supply")
        st.download_button("Download crac_supply.csv", _csv(supply),
                           file_name=f"{scenario}_crac_supply.csv", mime="text/csv",
                           icon=":material/download:", key="dl-crac_supply")
    st.markdown("**COP of the CRAC at each supply temperature**")
    _table(tables, "crac_cop", scenario)


def _crac_line(r: pd.Series) -> str:
    head = f"- **H_min {r['H_min (°C)']:g} °C** (cap {r['Thermal cap (°C)']:g} °C): "
    lows = {c: r[c] for c in r.index if c.startswith("Zone") and "periods below" in c}
    if pd.isna(r.get("Hottest server (°C)")):
        return head + f"{str(r['Solver status']).lower()}; {r['Lower supply in']}."
    hot = f"hottest server {r['Hottest server (°C)']:.1f} °C"
    if all(v == 0 for v in lows.values()):
        return head + f"the supply stays at the top of its range all day; {hot}."
    return head + f"the solver lowers the supply in {r['Lower supply in']}, and keeps the top of its range otherwise; {hot}."


def _speed(meta: dict, tables: dict, scenario: str) -> None:
    _verdict(meta, "execution_time")
    st.markdown(
        "The run length of a workload is its required work divided by what its cores deliver "
        "per period: ⌈work ÷ (cores × MHz × DPF × 300 s)⌉ periods, rounded **up** to whole "
        "5-minute periods. Below, each workload keeps its work, cores, start (its arrival) and "
        "DPF, and runs alone on each server. *Pass* means the evaluator agrees this is the "
        "shortest run that delivers the work. A run past the end of the day is evaluated "
        "beyond it so its work is still counted.")
    _table(tables, "execution_time", scenario)
    eq = (meta.get("checks") or {}).get("execution_time", {}).get("equal_periods")
    if eq:
        st.markdown(
            f"**Equal execution times** come from the rounding: work that needs, say, 2.03 periods "
            f"on the fast server and 2.90 on the slow one takes 3 periods on both. "
            f"{eq['same_periods']} of the {eq['workloads']} workloads take the same number of "
            f"periods on {' and '.join(eq['servers'])}.")


def _choice(tables: dict, scenario: str) -> None:
    st.markdown(
        "The same workload on server A or B. The model has no switch to turn a server off, so "
        "**every server draws its idle power all day**, whatever runs on it: the fleet's idle "
        "electricity is the same in every option. Placing a workload only adds the power its "
        "cores draw above idle, for as long as it runs. That added electricity is what a move "
        "can change. It is small next to the idle part, which is why the servers' electricity "
        "hardly changes between runs.")
    _table(tables, "server_choice", scenario)
    st.caption("A faster server is not always cheaper: when the rounding gives both servers "
               "the same number of periods, the one with the larger gap between maximum and "
               "idle power adds more.")


def _slowdown(meta: dict, tables: dict, scenario: str) -> None:
    _verdict(meta, "slowdown")
    st.markdown(
        "A server slows down (DPF below 1) only above T_dvfs = 75 °C, and in the base run no "
        "server gets there, so DPF stays 1. **Controlled case:** one workload that needs a "
        "whole number of periods at full speed, run alone on the server that heats fastest, "
        "with the supply temperature fixed first cool, then warm, and H_min 5 °C so the cap "
        "leaves room above 75 °C.")
    slow = _table(tables, "slowdown", scenario)
    if slow is not None and "Periods run" in slow:
        st.markdown("\n".join(
            f"- Supply {r['Supply temperature (°C)']:g} °C: hottest "
            f"{r['Hottest temperature during the run (°C)']:.1f} °C, lowest DPF "
            f"{r['Lowest DPF during the run']:.3f}, **{int(r['Periods run'])} periods** "
            f"({r['Execution time (min)']:g} min) for work that takes "
            f"{int(r['Periods at full speed'])} at full speed."
            for _, r in slow.iterrows() if not pd.isna(r.get("Periods run"))))
    note = (meta.get("checks") or {}).get("throttled_servers", {}).get("note")
    if note:
        st.markdown(
            f"**In a full run:** `{note}` (CRAC allowed up to 32 °C) is the run where a server "
            "does slow down. Every workload it slowed still finished in the same number of "
            "periods, because rounding up to whole periods had left it spare work; none missed "
            "its deadline.")
        _table(tables, "throttled_servers", scenario)
        _table(tables, "throttled_workloads", scenario)


def _cold_plates(meta: dict, tables: dict, scenario: str) -> None:
    _verdict(meta, "cold_plates")
    note = (meta.get("checks") or {}).get("cold_plates", {}).get("note")
    st.markdown(
        "The base run has cold plates off, so these checks use the run with them on"
        + (f" (`{note}`, 6.2 Base, both cooling systems optimized)" if note else "")
        + ". For each server with a plate: the heat removed never exceeds the server's own heat "
        "or the plate's limit, the flow is one of the settings, and the coolant stays within its "
        "limits. *Hottest without cold plates* is the same server in the base run.")
    _table(tables, "cold_plates", scenario)


def _power(meta: dict, tables: dict, scenario: str) -> None:
    _verdict(meta, "power")
    st.markdown(
        "Server power is linear in CPU use: P = P_idle + (P_max − P_idle) × CPU share. Each "
        "server is solved alone with a workload that fills 50 % or 100 % of its cores for one "
        "period and nothing in the next (0 %). *Optimizer* is the model's own power variable, "
        "*Evaluator* the independent checker's. *Pass*: both within 0.01 W of the expected value.")
    _table(tables, "power", scenario)


AIRFLOW_NOTE = (
    "**Airflow is not modelled** (decided with the thesis group on 2026-10-22): the CRAC's "
    "electricity is the heat it removes divided by its COP at the chosen supply temperature, and "
    "fan power is fixed at 0, so every run reports 0 kWh for fans. In 6.2, *CRAC changed* means "
    "the supply air temperature only.")


def _model_checks() -> None:
    scenarios = data.validation_scenarios()
    if not scenarios:
        st.info("No validation tables yet. They are written to results/validation/<scenario>/ "
                "by the validation checks (the last section of the solver notebook).")
        return
    scenario = (st.selectbox("Scenario", scenarios) if len(scenarios) > 1 else scenarios[0])
    meta, tables = data.load_validation(scenario)
    st.caption(
        f"Checks of `{scenario}` made by release {meta.get('thermasched_version')} on "
        f"{str(meta.get('created_utc', ''))[:10]} (scenario build "
        f"`{meta.get('scenario_fingerprint')}`). Each section answers one question with a table you "
        "can download. The checks that solve use small scenarios built from this scenario's own "
        "servers and constants, solved by the model and scored by the independent evaluator.")
    st.caption(AIRFLOW_NOTE)
    checks = meta.get("checks") or {}
    failed = [k for k, v in checks.items() if v.get("passed") is False]
    if failed:
        st.error(f"Failed checks: {', '.join(failed)}.", icon=":material/error:")
    # One section at a time: a chart inside a hidden st.tabs pane can stall the browser.
    section = st.segmented_control("Check", TABS, default=TABS[0], key="validation_section",
                                   label_visibility="collapsed") or TABS[0]
    {
        "Moves": lambda: _moves(tables, scenario),
        "Reassignment test": lambda: _reassignment(meta, tables, scenario),
        "CRAC": lambda: _crac(meta, tables, scenario),
        "Speed": lambda: _speed(meta, tables, scenario),
        "Server A vs B": lambda: _choice(tables, scenario),
        "Slowdown": lambda: _slowdown(meta, tables, scenario),
        "Cold plates": lambda: _cold_plates(meta, tables, scenario),
        "Power": lambda: _power(meta, tables, scenario),
    }[section]()


def _section64_runs(config: ex.Configuration) -> tuple[data.Run | None, data.Run | None]:
    """The Base and the 6.4 flat-carbon-intensity run of the configuration, as the Chapter 6
    pages use."""
    cat = state.chapter6()[1]
    base, flat = cat[(config.key, "base")][0], cat[(config.key, "s4_t3a_ci_flat")][0]
    return (state.load_run(base) if base else None, state.load_run(flat) if flat else None)


def _relationships() -> None:
    config = state.pick_config("validation")
    ref = state.pick_run(config, "validation")
    if ref is None:
        st.info(f"No runs of {config.label} yet.")
        return
    run = state.load_run(ref)
    info = state.run_infos().get(run.ref.key)
    label = data.run_long_title(info, run.ref) if info and info.config else None
    st.caption(
        "Does the model behave the way the papers behind the thesis say it should? Each plot "
        "pairs two outputs of the run picked above ("
        + (f"**{label}** · " if label else "") + f"`{run.ref.scenario}` / `{run.ref.name}`), "
        "names its source, what the source leads us to expect, and what this run shows.")
    with st.container(horizontal=True, gap="medium", vertical_alignment="bottom"):
        rel = st.selectbox("Relationship", relations.RELATIONS, key="relation",
                           format_func=lambda r: f"{relations.RELATIONS.index(r) + 1}. {r.title}",
                           width=480)
        variants = list(run.variants)
        default = relations.variant_of(run)
        variant = st.segmented_control(
            "Schedule", variants, default=default, key="relation_variant",
            format_func=data.VARIANT_LABELS.get, disabled=rel.two_runs or len(variants) < 2,
            help="The optimized schedule unless you pick the baseline (least-loaded, CRAC "
                 "fixed), which can show behaviour the optimizer never chooses.") or default

    st.subheader(rel.title)
    st.caption(f"**Source:** {rel.source}  \n**Expected:** {rel.expect}")
    other = None
    if rel.cold_plates and not relations.has_cold_plates(run):
        st.info(f"This run has cold plates off. Pick **{relations.COLD_PLATE_RUN}** above "
                "to see this relationship.", icon=":material/info:")
        return
    if rel.two_runs:
        run, other = _section64_runs(config)
        if run is None or other is None:
            missing = [n for n, r in (("Base", run),
                                      ("6.4 Test 3a Flat carbon intensity", other)) if r is None]
            st.info(f"Needs both 6.4 runs; not found: {', '.join(missing)}.",
                    icon=":material/info:")
            return
        st.caption("This plot always compares the **Base** and **6.4 Test 3a Flat carbon "
                   "intensity** runs of the configuration picked above (optimized "
                   "schedules), whatever run is picked.")
        variant = relations.variant_of(run)
    state.chart(relations.figure(rel.key, run, variant, state.pal(), other),
                key=f"relation-{rel.key}")
    st.markdown(f"**This run:** {relations.reading(rel.key, run, variant, other)}")


def render() -> None:
    st.title("Validation")
    group = st.segmented_control("Group", GROUPS, default=GROUPS[0], key="validation_group",
                                 label_visibility="collapsed") or GROUPS[0]
    if group == "Model checks":
        _model_checks()
    else:
        _relationships()
