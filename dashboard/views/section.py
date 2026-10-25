"""One page per Chapter 6 scenario (6.1-6.4): the Base next to its tests for the configuration
picked in the sidebar, with what the scenario measures, per-server figures and moved
workloads; and the same measures across every configuration."""

from __future__ import annotations

from typing import Callable

import pandas as pd
import streamlit as st

from dashboard import charts, data, state, tables
from dashboard.views.chapter6 import (
    FORMATS, NOTES, csv_bytes, fmt_value, gap_warning, status_cell)
from scheduler import experiments as ex

SHORT_TITLES = {"6.1": "Cooling zones", "6.2": "Cooling systems", "6.3": "Thermal headroom",
                "6.4": "Reassignment"}
ICONS = {"6.1": ":material/grid_on:", "6.2": ":material/ac_unit:",
         "6.3": ":material/thermostat:", "6.4": ":material/swap_horiz:"}
VIEWS = ("This configuration", "Across configurations")
# Rows under the measures in the comparison table: key -> label.
RUN_ROWS = {"run": "Run folder", "status": "Solver status", "time_limit_s": "Time limit (s)",
            "release": "Release"}
# Sections that list every workload's original and new server.
MOVES = {"6.1", "6.4"}


def _heading(tag: str, name: str) -> str:
    """'Test 1: Same-type servers ...'; the Base is just 'Base'."""
    return tag if name == "Base" else f"{tag}: {name}"


def _rows(table: pd.DataFrame, config: ex.Configuration, section: str) -> pd.DataFrame:
    rows = table[(table["configuration"] == config.label) & (table["section"] == section)]
    return rows.reset_index(drop=True)


def _comparison(rows: pd.DataFrame, section: str, changes: bool) -> pd.DataFrame:
    """Measures down, tests across (Base first), as display text."""
    measures = data.SECTION_MEASURES[section]
    pct = data.chapter6_changes(rows) if changes else None
    out = {"Measure": [data.CHAPTER6_COLUMNS[k] for k in measures] + list(RUN_ROWS.values())}
    for i, r in rows.iterrows():
        col = _heading(r["tag"], r["label"])
        ran = data.has_result(rows.iloc[[i]]).iloc[0]
        values = []
        for k in measures:
            text = fmt_value(k, r[k]) if ran else "–"
            if changes and ran and i > 0 and pd.notna(pct.at[i, k]):
                text += f" ({pct.at[i, k]:+.1f} %)"
            values.append(text)
        values += [r["run"] if ran else "–", status_cell(r),
                   fmt_value("time_limit_s", r["time_limit_s"]) if ran else "–",
                   r["release"] if ran else "–"]
        out[col] = values
    return pd.DataFrame(out)


def _loaded(rows: pd.DataFrame, cat, config: ex.Configuration, section: ex.Section
            ) -> list[tuple[str, data.Run]]:
    """(tag, loaded run) for each test of the section that has a run."""
    out = []
    for tag, tid in section.tests:
        ref, _ = cat[(config.key, tid)]
        if ref is not None and ex.applicable(ex.TEST_BY_ID[tid], config):
            out.append((tag, state.load_run(ref)))
    return out


def _chart(rows: pd.DataFrame, section: str) -> None:
    ran = rows[data.has_result(rows)]
    if ran.empty:
        return
    tags = ran["tag"].tolist()
    pal = state.pal()

    def col(k):
        return pd.to_numeric(ran[k], errors="coerce").tolist()

    if section == "6.1":
        fig = charts.grouped_bars(tags, {"Zone 1": col("E_crac_zone1_kWh"),
                                         "Zone 2": col("E_crac_zone2_kWh")}, pal,
                                  y_title="CRAC electricity (kWh)")
        title = "CRAC electricity per zone"
    elif section == "6.2":
        fig = charts.grouped_bars(tags, {"Average": col("T_mean_C"),
                                         "Highest": col("T_max_C")}, pal,
                                  y_title="Server temperature (°C)", fmt=",.1f")
        title = "Predicted server temperature"
    elif section == "6.3":
        fig = charts.grouped_bars(tags, {"Waiting": col("wait_mean_min"),
                                         "Execution": col("exec_mean_min")}, pal,
                                  y_title="Average time per workload (min)", stacked=True,
                                  fmt=",.1f")
        title = "Completion time from arrival: waiting, then execution"
    else:
        fig = charts.grouped_bars(
            tags, {"IT": col("E_IT_kWh"), "CRAC": col("E_crac_kWh"),
                   "Cold-plate pumps": [v / 1000 for v in col("E_cp_Wh")]}, pal,
            y_title="Electricity (kWh)", stacked=True,
            colors={"IT": pal.components["E_IT_kWh"], "CRAC": pal.components["E_crac_kWh"],
                    "Cold-plate pumps": pal.components["E_cp_kWh"]})
        title = "Electricity by component (carbon follows it, weighted by the hour)"
    st.markdown(f"**{title}**")
    state.chart(fig, key=f"section-chart-{section}")


def _servers(loaded: list[tuple[str, data.Run]], section: str) -> None:
    st.markdown("**Per server**")
    stat = st.selectbox("Figure", list(data.SERVER_STATS), key=f"server-stat-{section}",
                        index=list(data.SERVER_STATS).index(data.SECTION_SERVER_STATS[section]),
                        format_func=data.SERVER_STATS.get, width=320)
    long = pd.concat([data.server_stats(run).assign(run=tag) for tag, run in loaded],
                     ignore_index=True)
    first = loaded[0][1]
    pivot = (long.pivot_table(index="s", columns="run", values=stat, sort=False)
             .reindex(columns=[tag for tag, _ in loaded]))
    names = first.servers.set_index("s")
    pivot.insert(0, "Zone", names["zone"])
    pivot.insert(0, "Server", names["name"])
    pivot = pivot.loc[first.servers["s"]].reset_index(drop=True)
    fmt = "%d" if stat == "periods_throttled" else \
        "%.3f" if stat in ("DPF_min", "DPF_mean", "E_IT_kWh") else "%.1f"
    st.dataframe(pivot, hide_index=True, column_config={
        tag: st.column_config.NumberColumn(tag, format=fmt) for tag, _ in loaded})
    zone_runs = [tag for tag, run in loaded
                 if not run.servers.set_index("s")["zone"].equals(names["zone"])]
    if zone_runs:
        st.caption(f"Zones are those of the Base; {', '.join(zone_runs)} regroups them.")
    st.download_button("Download per-server figures (CSV)",
                       long.rename(columns={"name": "Server", "zone": "Zone", "run": "Test",
                                            **data.SERVER_STATS}).drop(columns="s")
                       .to_csv(index=False).encode("utf-8-sig"),
                       file_name=f"chapter6_{section}_servers.csv", mime="text/csv",
                       icon=":material/download:", key=f"dl-servers-{section}")


def _moves(loaded: list[tuple[str, data.Run]], section: str) -> None:
    st.markdown("**Workloads: original and new server and zone**")
    frames = []
    for tag, run in loaded:
        t = tables.reassignment(run)
        if not t.empty:
            frames.append(t.assign(Test=tag))
    if not frames:
        st.caption("These runs record no reassignment table.")
        return
    every = pd.concat(frames, ignore_index=True)
    every = every[["Test", *[c for c in every.columns if c != "Test"]]]
    counts = every.groupby("Test", sort=False).agg(
        moved=("Moved", lambda m: int((m == "yes").sum())),
        cross=("Cross-zone", lambda m: int((m == "yes").sum())))
    st.caption(" · ".join(f"{tag}: {r.moved} moved, {r.cross} to another zone"
                          for tag, r in counts.iterrows()))
    only = st.toggle("Only moved workloads", value=bool(counts["moved"].sum()),
                     key=f"only-moved-{section}")
    shown = every[every["Moved"] == "yes"] if only else every
    if shown.empty:
        st.caption("No run of this section moves a workload; every workload stays on the "
                   "server it starts on. The *Validation* page (Moves) explains why.")
    else:
        st.dataframe(shown, hide_index=True)
    st.download_button("Download the workload table (CSV)",
                       every.to_csv(index=False).encode("utf-8-sig"),
                       file_name=f"chapter6_{section}_workloads.csv", mime="text/csv",
                       icon=":material/download:", key=f"dl-moves-{section}")


def _this_configuration(table, cat, config: ex.Configuration, section: ex.Section) -> None:
    rows = _rows(table, config, section.key)
    changes = st.toggle("Show change against the Base (%)", key=f"changes-{section.key}")
    st.dataframe(_comparison(rows, section.key, changes), hide_index=True,
                 column_config={"Measure": st.column_config.TextColumn(pinned=True)})
    missing = rows[~data.has_result(rows)]
    if not missing.empty:
        st.caption(" · ".join(f"{r.tag}: {r.status}" for r in missing.itertuples()) + ".")
    gap_warning(rows)
    st.download_button("Download this comparison (CSV)",
                       csv_bytes(rows, data.CHAPTER6_COLUMNS),
                       file_name=f"chapter6_{section.key}_{config.key}.csv", mime="text/csv",
                       icon=":material/download:", key=f"dl-section-{section.key}",
                       help="Every column of the results table for these runs, full precision.")

    loaded = _loaded(rows, cat, config, section)
    if not loaded:
        st.info(f"No run of {section.key} for {config.label} yet.")
        return
    _chart(rows, section.key)
    _servers(loaded, section.key)
    if section.key in MOVES:
        _moves(loaded, section.key)
    with st.expander("Open a run"):
        for tag, run in loaded:
            state.run_link(run.ref, f"{tag}: {run.ref.key}")


def _across(table: pd.DataFrame, section: ex.Section) -> None:
    measures = data.SECTION_MEASURES[section.key]
    measure = st.selectbox("Measure", measures, format_func=data.CHAPTER6_COLUMNS.get,
                           key=f"across-measure-{section.key}", width=420)
    rows = table[table["section"] == section.key]
    grid = (rows.assign(value=pd.to_numeric(rows[measure], errors="coerce"))
            .pivot_table(index="configuration", columns="tag", values="value", sort=False,
                         dropna=False))
    order = [t for t, _ in section.tests]
    grid = grid.reindex(columns=order)
    grid = grid.dropna(how="all")
    if grid.empty:
        st.info("No configuration has a run of this section yet.")
        return
    shown = grid.map(lambda v: fmt_value(measure, v)).reset_index()
    st.dataframe(shown.rename(columns={"configuration": "Configuration"}), hide_index=True)
    names = dict(section.tests)
    st.caption(" · ".join(f"**{tag}** {ex.TEST_BY_ID[names[tag]].name}" for tag in order
                          if ex.TEST_BY_ID[names[tag]].name != "Base"))
    fmt = ",.0f" if FORMATS.get(measure) == "%d" else ",.3f"
    fig = charts.grouped_bars(list(grid.index), {t: grid[t].tolist() for t in grid.columns},
                              state.pal(), y_title=data.CHAPTER6_COLUMNS[measure], fmt=fmt)
    state.chart(fig, key=f"across-chart-{section.key}")
    st.download_button("Download (CSV)",
                       grid.reset_index().to_csv(index=False).encode("utf-8-sig"),
                       file_name=f"chapter6_{section.key}_{measure}_by_configuration.csv",
                       mime="text/csv", icon=":material/download:",
                       key=f"dl-across-{section.key}")


def page(key: str) -> Callable[[], None]:
    section = ex.SECTION_BY_KEY[key]

    def render() -> None:
        st.title(f"{section.key} {section.title}")
        st.markdown(f"*{section.question}*")
        st.caption(f"**Goal:** {section.goal} {section.note}")
        table, cat = state.chapter6()
        view = st.segmented_control("View", VIEWS, default=VIEWS[0], key=f"view-{key}",
                                    label_visibility="collapsed") or VIEWS[0]
        if view == VIEWS[1]:
            _across(table, section)
        else:
            config = state.selected_config()
            if config is None:
                st.info("Pick a configuration (2, 6 or 10 servers) in the sidebar.")
                return
            st.caption(f"Configuration: **{config.label}** (change it in the sidebar).")
            _this_configuration(table, cat, config, section)
        st.caption(NOTES)

    render.__name__ = f"section_{key.replace('.', '_')}"     # Streamlit names pages by it
    return render
