"""Chapter 6 results: every Chapter 6 run of the thesis in one table, in section order."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from dashboard import data, state

# Display format per column (st.column_config.NumberColumn); the CSV keeps full precision.
FORMATS = {
    "wait_mean_min": "%.1f", "wait_max_min": "%.0f",
    "turnaround_mean_min": "%.1f", "turnaround_max_min": "%.0f",
    "E_crac_zone1_kWh": "%.3f", "E_crac_zone2_kWh": "%.3f", "E_IT_kWh": "%.3f",
    "E_cp_Wh": "%.3f", "E_total_kWh": "%.3f", "carbon_kg": "%.3f",
    "T_mean_C": "%.1f", "T_max_C": "%.1f",
    "n_moved_server": "%d", "n_moved_zone": "%d", "n_late": "%d", "pct_late": "%.2f%%",
    "n_throttled_servers": "%d", "n_unplaced": "%d",
    "mip_gap": "percent", "time_limit_s": "%d",
}
PINNED = ("section", "label", "run")
COUNTS = [k for k in FORMATS if k.startswith("n_")]
# Above this MIP gap, a run stopped at its time limit may be far from its best schedule.
GAP_WARN = 0.05


def _change_header(key: str) -> str:
    """'Average waiting time (min)' -> 'Average waiting time (% change)'."""
    if key == "pct_late":       # "Missed deadlines" is taken by the count
        return "Share of missed deadlines (% change)"
    return data.CHAPTER6_COLUMNS[key].rsplit(" (", 1)[0] + " (% change)"


def _column_config(changes: bool) -> dict:
    config = {}
    for key, header in data.CHAPTER6_COLUMNS.items():
        if changes and key in data.CHAPTER6_METRICS:
            config[key] = st.column_config.NumberColumn(_change_header(key), format="%+.2f%%")
        elif key in FORMATS:
            config[key] = st.column_config.NumberColumn(header, format=FORMATS[key])
        else:
            config[key] = st.column_config.TextColumn(header, pinned=key in PINNED)
    return config


def _titles(rows: pd.DataFrame) -> str:
    return ", ".join(f"{s} {lab}" for s, lab in rows[["section", "label"]].values)


def _csv(df: pd.DataFrame, headers: dict[str, str]) -> bytes:
    # utf-8-sig: Excel then reads the °C and other non-ASCII headers correctly.
    return df.rename(columns=headers).to_csv(index=False).encode("utf-8-sig")


def _matches(entries) -> None:
    uploaded = {r.key for r in state.discover_runs() if state.is_uploaded(r)}

    def name(ref: data.RunRef) -> str:
        return ("📤 " if ref.key in uploaded else "") + f"`{ref.name}`"

    lines = []
    for tr, used, found in entries:
        if len(found) > 1:
            others = ", ".join(name(r) for r in found if r != used)
            lines.append(f"- **{tr.title}**: {name(used)} (newest, shown); also {others}")
    with st.expander("Runs matching each label"):
        if lines:
            st.markdown("\n".join(lines))
        else:
            st.caption("Every label matches one run at most.")


def render() -> None:
    runs = state.discover_runs()
    st.title("Chapter 6 results")
    st.caption(
        "One row per run of Chapter 6, in section order. Values are the **optimized** result "
        "of each run. The base run appears in 6.1, 6.3 and 6.4, so every test sits right "
        "below its section's reference (the first row of the section). Runs are matched to "
        "labels by their settings, not their folder name; when several runs match a label, "
        "the newest is used.")
    table, entries = state.chapter6(runs)

    changes = st.toggle("Show change against each section's reference (%)",
                        help="Each result against the first row of its section. Blank where "
                             "either row has no value, or the reference is zero.")
    shown = data.chapter6_changes(table) if changes else table.copy()
    not_run = shown["status"] == data.NOT_RUN_YET
    shown.loc[not_run, "run"] = f"— {data.NOT_RUN_YET} —"
    shown["status"] = shown["status"].str.replace("_", " ")
    st.dataframe(shown, hide_index=True, column_config=_column_config(changes))

    if not_run.any():
        st.caption(f"Not run yet: {_titles(table[not_run])}.")
    gap = pd.to_numeric(table["mip_gap"], errors="coerce")
    unproven = table[(table["status"] == "time_limit") & (gap > GAP_WARN)]
    if not unproven.empty:
        st.warning(
            f"Not proven optimal: {_titles(unproven)} stopped at the time limit with a MIP gap "
            f"above {GAP_WARN:.0%}. Differences between these rows may be the solver's, not "
            "the model's.", icon=":material/hourglass_bottom:")
    unplaced = pd.to_numeric(table["n_unplaced"], errors="coerce").fillna(0)
    if (unplaced > 0).any():
        st.caption("Unplaced workloads, left out of the time columns: " + ", ".join(
            f"{s} {lab}: {int(n)}" for s, lab, n in
            table.loc[unplaced > 0, ["section", "label", "n_unplaced"]].values) + ".")

    with st.container(horizontal=True):
        absolute = table.astype({k: "Int64" for k in COUNTS})    # 3, not 3.0, in the CSV
        st.download_button("Download table (CSV)", _csv(absolute, data.CHAPTER6_COLUMNS),
                           file_name="chapter6_results.csv", mime="text/csv",
                           icon=":material/download:",
                           help="Every value at full precision, with the units in the headers.")
        if changes:
            headers = {**data.CHAPTER6_COLUMNS,
                       **{k: _change_header(k) for k in data.CHAPTER6_METRICS}}
            st.download_button("Download changes (CSV)",
                               _csv(data.chapter6_changes(table), headers),
                               file_name="chapter6_changes.csv", mime="text/csv",
                               icon=":material/download:")
    _matches(entries)
    st.caption(
        "Airflow is not modelled, so in 6.2 *CRAC changed* means the supply air temperature "
        "only, optimized per zone and period. Cold-plate pump electricity is in Wh because it "
        "is tiny (it would show as 0.000 kWh). Waiting time is start minus arrival; arrival "
        "to completion runs to the end of the last period; both leave out unplaced workloads.")
