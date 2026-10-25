"""Chapter 5 tables: the nine tables of the base-run results, one at a time, each a CSV."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from dashboard import data, state, tables

TABLES = ("Schedule", "Deadlines and waiting", "Reassignment", "CPU and memory",
          "Temperature and headroom", "Cooling limits", "Work completion", "Energy",
          "Carbon per period")
COLUMN_FORMATS = {
    "Execution time (min)": "%.0f", "Waiting time (min)": "%.0f", "Allowed delay (min)": "%.0f",
    "Peak CPU utilization (%)": "%.1f", "Memory capacity (GB)": "%.1f",
    "Peak memory used (GB)": "%.1f",
    "Hottest predicted temperature (°C)": "%.2f", "Lowest headroom (°C)": "%.2f",
    "Thermal cap (°C)": "%g", "Required H_min (°C)": "%g", "Lowest DPF": "%.4f",
    "Lowest effective capability (MHz)": "%,.0f",
    "Peak heat removed (kW)": "%.3f", "Peak heat removed (W)": "%.1f",
    "Largest 15-min change (°C)": "%.2f", "Largest 1-h change (°C)": "%.2f",
    "Lowest coolant used (°C)": "%.2f", "Highest coolant used (°C)": "%.2f",
    "Work required W_i (MHz·s)": "%.4e", "Work delivered (MHz·s)": "%.4e",
    "Delivered / required": "%.3f", "Lowest server PC_eff while running (MHz)": "%,.0f",
    "Lowest DPF while running": "%.4f",
    "Energy (kWh)": "%.6g", "Share of total (%)": "%.4g",
    "IT (kWh)": "%.5f", "CRAC (kWh)": "%.5f", "Cold-plate pumps (kWh)": "%.3e",
    "Total energy (kWh)": "%.5f", "Grid carbon intensity (g CO2/kWh)": "%.2f",
    "Carbon (g CO2)": "%.3f",
}


def _csv(df: pd.DataFrame) -> bytes:
    # utf-8-sig: Excel then reads the °C and other non-ASCII headers correctly.
    return df.to_csv(index=False).encode("utf-8-sig")


def _show(df: pd.DataFrame, run: data.Run, key: str, *, height: int | None = None) -> None:
    config = {c: st.column_config.NumberColumn(format=f) for c, f in COLUMN_FORMATS.items()
              if c in df}
    kw = {} if height is None else {"height": height}
    st.dataframe(df, hide_index=True, column_config=config, **kw)
    st.download_button(f"Download {key}.csv", _csv(df), file_name=f"{run.ref.name}_{key}.csv",
                       mime="text/csv", icon=":material/download:", key=f"dl-{key}")


def _missing(df: pd.DataFrame) -> bool:
    if df.empty:
        st.info("This run has no data for this table in the selected schedule.")
    return df.empty


def _count_bad(df: pd.DataFrame, column: str) -> int:
    return int((df[column] == tables.BAD).sum()) if column in df else 0


def _schedule(run, v) -> None:
    df = tables.workload_schedule(run, v)
    if _missing(df):
        return
    placed = int(df["Server"].notna().sum())
    st.caption(f"Which server runs each workload, when it starts, how long it runs and when it "
               f"finishes. {placed} of {len(df)} workloads are placed. Times are local; a "
               f"completion is the end of the workload's last {run.dt_seconds / 60:g}-min "
               "period.")
    _show(df, run, "schedule", height=420)


def _deadlines(run, v) -> None:
    df = tables.deadlines_and_waiting(run, v)
    if _missing(df):
        return
    late, over = _count_bad(df, "On time"), _count_bad(df, "Wait within allowed")
    verdict = (f"All {len(df)} workloads finish by their deadline and wait no longer than "
               "allowed." if late == over == 0 else
               f"{late} workloads miss their deadline and {over} wait longer than allowed.")
    st.caption("Each workload's wait against its allowed delay and its completion against its "
               f"deadline. {verdict}")
    _show(df, run, "deadlines_and_waiting", height=420)


def _reassignment(run, v) -> None:
    if v != "optimized":
        st.info("Reassignment is a decision of the optimized schedule; the baseline keeps "
                "every workload on its original server. Pick *Optimized* above.")
        return
    df = tables.reassignment(run)
    if df.empty:
        st.info("This run has no reassignment table (no optimized schedule, or made before it "
                "was recorded).")
        return
    moved = int((df["Moved"] == "yes").sum())
    running_moved = int(((df["Moved"] == "yes") & (df["Running at start (B_i)"] == "yes")).sum())
    st.caption(f"Each workload's original and final server. {moved} of {len(df)} workloads "
               f"moved, {int((df['Cross-zone'] == 'yes').sum())} of them to another zone. "
               f"Workloads already running at the start may not move: {running_moved} did. "
               "The reason is a reading of the scored schedule; the solver itself only "
               "minimises carbon.")
    _show(df, run, "reassignment", height=420)


def _cpu_memory(run, v) -> None:
    df = tables.cpu_and_memory(run, v)
    if _missing(df):
        return
    bad = _count_bad(df, "Within capacity")
    st.caption("The most CPU cores and memory each server's workloads used at once, against "
               "the server's capacity. " + ("Every server stays within capacity." if bad == 0
                                            else f"{bad} servers exceed their capacity."))
    _show(df, run, "cpu_and_memory")


def _temperature(run, v) -> None:
    df = tables.temperature_and_headroom(run, v)
    if _missing(df):
        return
    bad = _count_bad(df, "Within limits")
    throttled = int((df["Lowest DPF"] < 1 - 1e-9).sum())
    st.caption(
        f"Each server's hottest predicted temperature against the thermal cap "
        f"({run.thermal_cap_C:g} °C), and its smallest headroom against H_min. DPF below 1 "
        f"means the server ran slower (above {run.T_dvfs_C:g} °C). "
        + ("Every server stays within its limits" if bad == 0
           else f"{bad} servers break a limit")
        + (", and none slows down." if throttled == 0 else f"; {throttled} slow down."))
    _show(df, run, "temperature_and_headroom")


def _cooling(run, v) -> None:
    crac = tables.crac_limits(run, v)
    st.markdown("**CRAC, per zone**")
    if _missing(crac):
        return
    bad = _count_bad(crac, "Within limits")
    st.caption("Supply air temperatures used, how fast they changed, and the most heat removed, "
               "against the CRAC's limits. "
               + ("Every zone stays within them." if bad == 0
                  else f"{bad} zones break a limit.")
               + " Airflow is not modelled, so it has no columns.")
    _show(crac, run, "crac_limits")
    st.markdown("**Cold plates, per server**")
    cp = tables.cold_plate_limits(run, v)
    if cp.empty:
        st.caption("This run has cold plates off. Pick *6.2 · Base · Both cooling "
                   "systems optimized* in the sidebar to see them.")
        return
    bad = _count_bad(cp, "Within limits")
    st.caption("Coolant temperature and flow used, and the most heat removed, against each "
               "plate's limits. " + ("Every plate stays within them." if bad == 0
                                    else f"{bad} plates break a limit."))
    _show(cp, run, "cold_plate_limits")


def _work(run, v) -> None:
    df = tables.work_completion(run, v)
    if _missing(df):
        return
    short = _count_bad(df, "Work complete")
    slowed = int((df["Lowest DPF while running"] < 1 - 1e-9).sum())
    st.caption(
        "Whether each workload receives all the processing it needs, and the slowest its "
        "server ran meanwhile (DPF below 1 is thermal throttling). Delivered work is above "
        "the requirement because run time is rounded up to whole periods. "
        + ("Every workload gets its full work" if short == 0
           else f"{short} workloads fall short of their work")
        + (", and none runs on a slowed server." if slowed == 0
           else f"; {slowed} run on a slowed server for part of their run."))
    _show(df, run, "work_completion", height=420)


def _energy(run, v) -> None:
    df = tables.energy_breakdown(run, v)
    if _missing(df):
        return
    parts = df[df["Component"] != "Total"].sort_values("Energy (kWh)", ascending=False)
    top = parts.iloc[0]
    st.caption(f"Energy of each component over the horizon. {top['Component']} uses the most: "
               f"{top['Share of total (%)']:.1f} % of {df['Energy (kWh)'].iloc[-1]:.2f} kWh. "
               "Fans are not modelled.")
    _show(df, run, "energy_breakdown")


def _carbon(run, v) -> None:
    df = tables.carbon_per_period(run, v)
    if _missing(df):
        return
    energy, carbon = tables.carbon_totals(run, v)
    st.caption(f"Energy, grid carbon intensity and carbon in every {run.dt_seconds / 60:g}-min "
               f"period: carbon = total energy × carbon intensity. Over the horizon: "
               f"**{energy:.3f} kWh** and **{carbon:.3f} kg CO2**.")
    _show(df, run, "carbon_per_period", height=420)


def render() -> None:
    run = state.current_run()
    state.page_header("Chapter 5 tables", run)
    if not run.has_optimized:
        state.no_optimized_note(run)
    with st.container(horizontal=True, gap="medium", vertical_alignment="bottom"):
        variants = list(reversed(run.variants))      # optimized first when there is one
        v = st.segmented_control("Schedule", variants, default=variants[0], required=True,
                                 format_func=data.VARIANT_LABELS.get, key="tables_variant")
    # One table at a time, like the Validation page.
    table = st.segmented_control("Table", TABLES, default=TABLES[0], key="tables_section",
                                 label_visibility="collapsed") or TABLES[0]
    {
        "Schedule": _schedule, "Deadlines and waiting": _deadlines,
        "Reassignment": _reassignment, "CPU and memory": _cpu_memory,
        "Temperature and headroom": _temperature, "Cooling limits": _cooling,
        "Work completion": _work, "Energy": _energy, "Carbon per period": _carbon,
    }[table](run, v)
