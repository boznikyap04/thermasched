"""Output files: every CSV a run wrote, shown as it is, with its download."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import streamlit as st

from dashboard import data, state

FILE_KEY = "output_file"        # the file picked last, kept when another run is picked
# What each file holds, by file name.
FILE_NOTES = {
    "comparison_period.csv": "One row per period: energy and carbon of the baseline and the "
                             "optimized schedule side by side, and their difference.",
    "schedule.csv": "One row per workload: its server, start, finish, waiting time, deadline "
                    "and work delivered.",
    "reassignment.csv": "One row per workload: its original and final server and zone, and "
                        "why it moved or stayed.",
    "server_period.csv": "One row per server and period: CPU and memory used, utilization, IT "
                         "power, cold plate, temperature, headroom, DPF and effective speed.",
    "zone_period.csv": "One row per zone and period: CRAC supply temperature, heat removed, "
                       "COP and electricity.",
    "period.csv": "One row per period: electricity by component, carbon intensity and "
                  "carbon.",
    "compliance_servers.csv": "One row per server: the peaks of each limit next to the limit.",
    "compliance_zones.csv": "One row per zone: supply temperature range, ramps and CRAC heat "
                            "next to their limits.",
    "compliance_cold_plates.csv": "One row per cold-plate server: coolant, flow and heat "
                                  "removed next to their limits.",
    "compliance_workloads.csv": "One row per workload: whether it met each of its "
                                "requirements.",
    "ticks.csv": "One row per tick of a run re-planned every period: solver status, solve "
                 "time, MIP gap, and the workloads waiting, started and running.",
    "partial_schedule.csv": "A stuck run's schedule up to the tick it stopped at: each "
                            "workload started before it, its server, start and end (blank "
                            "while still running).",
}
SCHEDULES = {"baseline": "Baseline schedule", "optimized": "Optimized schedule"}


def _files(ref: data.RunRef) -> list[str]:
    """The run's CSVs, relative to its folder: the run's own first, then per schedule."""
    paths = [p.relative_to(ref.path).as_posix() for p in ref.path.rglob("*.csv")]
    return sorted(paths, key=lambda p: (p.count("/"), p))


def _describe(rel: str) -> str:
    folder, _, name = rel.rpartition("/")
    note = FILE_NOTES.get(name, "")
    return f"{SCHEDULES[folder]}. {note}" if folder in SCHEDULES else note


def _keep_file(widget: str) -> None:
    st.session_state[FILE_KEY] = st.session_state[widget]


def render() -> None:
    st.title("Output files")
    st.caption("Every CSV a run wrote, as it wrote it. Pick a configuration, a run and a file.")
    config = state.pick_config("files")
    ref = state.pick_run(config, "files")
    if ref is None:
        st.info(f"No runs of {config.label}: it is not run in this release.")
        return
    try:
        for warning in data.provenance_warnings(data.load_summary(ref.path)):
            st.warning(warning, icon=":material/warning:")
    except (OSError, ValueError):
        st.warning("This run's summary.json could not be read.", icon=":material/warning:")
    files = _files(ref)
    if not files:
        st.info("This run has no CSV files.")
        return
    widget = f"file-{ref.key}"
    if st.session_state.get(FILE_KEY) not in files:
        st.session_state[FILE_KEY] = next(
            (f for f in ("optimized/schedule.csv", "partial_schedule.csv") if f in files),
            files[0])
    st.session_state[widget] = st.session_state[FILE_KEY]
    rel = st.selectbox("File", files, key=widget, on_change=_keep_file, args=(widget,))

    path = Path(ref.path) / rel
    try:
        df = pd.read_csv(path)
    except pd.errors.EmptyDataError:
        df = pd.DataFrame()
    st.caption(" ".join(filter(None, [
        _describe(rel), f"{len(df):,} rows, {len(df.columns)} columns ·",
        f"`results/{ref.key}/{rel}`"])))
    st.dataframe(df, hide_index=True)
    st.download_button(f"Download {Path(rel).name}", path.read_bytes(),
                       file_name=f"{ref.scenario}_{ref.name}_{rel.replace('/', '_')}",
                       mime="text/csv", icon=":material/download:")
