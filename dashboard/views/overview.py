"""Run summary: what was run, how complete the solver's answer is, the headline numbers
optimized vs baseline, and whether the self-checks passed."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from dashboard import data, state

DIGITS = {"kg CO₂": 2, "kWh": 2, "Wh": 3, "°C": 1, "": 0}
DELTA_COLOR = {"lower": "inverse", "higher": "normal", "neutral": "off"}
STATUS_COLOR = {"optimal": "green", "time_limit": "orange", "infeasible": "red",
                "no_solution": "red"}


def _settings_row(run: data.Run) -> None:
    with st.container(horizontal=True, gap="small"):
        for label, value in data.settings_badges(run.summary):
            st.badge(f"{label}: {value}", color="gray")


def _tile(row: pd.Series, run: data.Run) -> None:
    digits = DIGITS.get(row["unit"], 2)
    unit = row["unit"]
    has_opt = run.has_optimized and not pd.isna(row["optimized"])
    value = row["optimized"] if has_opt else row["baseline"]
    help_text = None
    if row["key"] == "hottest_T_C":
        m = (run.summary.get("optimized" if has_opt else "baseline") or {}).get("metrics", {})
        help_text = (f"On {run.server_name(m.get('hottest_server'))}, "
                     f"period t={m.get('hottest_period')}.")
    label = row["label"]
    if not has_opt:
        st.metric(label, state.fmt_num(value, digits, unit), border=True, help=help_text)
        return
    diff, pct = row["diff"], row["pct"]
    arrow = "auto"
    if abs(diff) < 10 ** -(digits + 1):
        delta, color, arrow = "no change", "off", "off"
    else:
        # The unit is on the value; keep the delta short so it is not truncated.
        delta = f"{diff:+,.{digits}f}"
        if not pd.isna(pct):
            delta += f" ({pct:+.1f}%)"
        color = DELTA_COLOR[row["better"]]
    st.metric(label, state.fmt_num(value, digits, unit), delta=delta, delta_color=color,
              delta_arrow=arrow, border=True, help=help_text,
              delta_description=f"baseline {state.fmt_num(row['baseline'], digits)}")


def _kpis(run: data.Run) -> None:
    kpis = data.kpi_frame(run.summary)
    energy = kpis[kpis["key"].str.startswith(("carbon", "E_"))]
    rest = kpis.drop(energy.index)
    for group in (energy, rest):
        cols = st.columns(5)
        for col, (_, row) in zip(cols, group.iterrows()):
            with col:
                _tile(row, run)


def _solver(run: data.Run) -> None:
    sol = run.solver
    status = sol.get("status", "unknown")
    with st.container(border=True):
        with st.container(horizontal=True, gap="small", vertical_alignment="center"):
            st.markdown("**Solver**")
            st.badge(data.solver_short(sol) if status != "unknown" else "unknown",
                     color=STATUS_COLOR.get(status, "gray"))
        st.caption(data.solver_sentence(sol))
        c1, c2, c3 = st.columns(3)
        c1.metric("Solve time", state.fmt_num(sol.get("solve_time_s"), 0, "s"))
        gap = sol.get("mip_gap")
        c2.metric("MIP gap", "–" if gap is None else f"{gap * 100:.2f}%",
                  help=f"Requested: {run.settings.get('mip_rel_gap', 0) * 100:g}%")
        bound = sol.get("best_bound_g")
        c3.metric("Best bound", state.fmt_num(None if bound is None else bound / 1000, 3, "kg"),
                  help="Lower bound on the optimum: no schedule can emit less.")
        with st.expander("Solver details"):
            obj = sol.get("objective_g")
            st.caption(f"Objective (carbon) {state.fmt_num(None if obj is None else obj / 1000, 3, 'kg')}"
                       f" · {state.fmt_num(sol.get('n_variables'), 0)} variables "
                       f"({state.fmt_num(sol.get('n_binaries'), 0)} binary) · "
                       f"{state.fmt_num(sol.get('n_constraints'), 0)} constraints"
                       + (f" · {sol['solver_status_text']}" if sol.get("solver_status_text")
                          else ""))
            if sol.get("relaxed"):
                st.caption(f"Relaxed families: {', '.join(sol['relaxed'])}")
            for n in sol.get("notes") or []:
                st.markdown(f"- {n}")


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


def _infeasibility(run: data.Run) -> None:
    diag = data.infeasibility_frame(run.summary)
    status = run.solver.get("status", "unknown")
    st.error(f"**No optimized schedule.** The solver ended with status **{status}**. "
             "The baseline is shown on every page.", icon="⛔")
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
    for v in run.variants:
        block = run.summary.get(v) or {}
        if block.get("violations"):
            items = "\n".join(f"- {x}" for x in block["violations"])
            st.warning(f"**{data.VARIANT_LABELS[v]} breaks limits:**\n{items}", icon="⚠️")


def render() -> None:
    run = state.current_run()
    sc = run.summary.get("scenario", {})
    hours = sc.get("T", 0) * run.dt_seconds / 3600
    state.page_header("Run summary", run,
                      f"{sc.get('I', '?')} workloads · {sc.get('S', '?')} servers · "
                      f"{sc.get('Z', '?')} zones · {sc.get('T', '?')} periods of "
                      f"{run.dt_seconds / 60:g} min ({hours:g} h)")
    _settings_row(run)
    st.caption(data.provenance_caption(run.summary))
    for warning in data.provenance_warnings(run.summary):
        st.warning(warning, icon=":material/difference:")
    if not run.has_optimized:
        _infeasibility(run)
    _violations(run)
    _solver(run)

    st.subheader("Key results: optimized vs baseline" if run.has_optimized
                 else "Key results: baseline only")
    _kpis(run)
    _checks(run)
    state.model_note(run)
