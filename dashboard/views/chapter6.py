"""Chapter 6 overview: which test has a run in each configuration (a server count on a load
level), and every result in one table that downloads as a CSV."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from dashboard import data, state
from scheduler import experiments as ex

# Display format per column; the CSV keeps full precision. "percent" shows a fraction as %.
FORMATS = {
    "wait_mean_min": "%.1f", "wait_max_min": "%.0f", "exec_mean_min": "%.1f",
    "turnaround_mean_min": "%.1f", "turnaround_max_min": "%.0f", "util_mean_pct": "%.2f",
    "E_crac_zone1_kWh": "%.3f", "E_crac_zone2_kWh": "%.3f", "E_crac_kWh": "%.3f",
    "E_IT_kWh": "%.3f", "E_cp_Wh": "%.3f", "E_cooling_kWh": "%.3f", "E_total_kWh": "%.3f",
    "carbon_kg": "%.3f", "T_mean_C": "%.1f", "T_max_C": "%.1f", "H_mean_C": "%.1f",
    "n_moved_server": "%d", "n_moved_zone": "%d", "n_late": "%d", "pct_late": "%.2f",
    "n_throttled_servers": "%d", "DPF_min": "%.3f", "n_unplaced": "%d",
    "mip_gap": "percent", "solve_time_s": "%.0f", "time_limit_s": "%d",
    "n_ticks": "%d", "n_ticks_at_cap": "%d", "tick_time_limit_s": "%d", "stuck_tick": "%d",
}
PINNED = ("configuration", "section", "tag", "label")
COUNTS = [k for k in FORMATS if k.startswith("n_")] + ["stuck_tick"]
# Above this MIP gap, a run stopped at its time limit may be far from its best schedule; for a
# per-tick run, a tick stopped at the cap may be far from the best decision for what it saw.
GAP_WARN = 0.05
NOTES = (
    "Airflow is not modelled, so in 6.2 the CRAC changes only its supply air temperature. "
    "Cold-plate pump electricity is in Wh because it is tiny. Waiting time is start minus "
    "arrival; execution time is completion minus start; completion time runs from arrival to "
    "the end of the last period; all three leave out unplaced workloads. Average headroom, "
    "utilization and lowest DPF are over every server and period. The temperatures are the "
    "model's predicted server temperatures (T_pred).")


def fmt_value(key: str, v) -> str:
    """One value as the tables show it."""
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return "–"
    f = FORMATS.get(key)
    if f == "percent":
        return f"{float(v) * 100:.2f} %"
    if f == "%d":
        return f"{int(round(float(v))):,}"
    if f:
        return f % float(v)
    return str(v)


def row_ticks(row) -> dict | None:
    """The per-tick figures of a table row (a Series or an itertuples row); None for a
    whole-day run."""
    n = getattr(row, "n_ticks", None) if not isinstance(row, pd.Series) else row.get("n_ticks")
    if n is None or pd.isna(n):
        return None
    get = (lambda k: row.get(k)) if isinstance(row, pd.Series) else (lambda k: getattr(row, k))
    ticks = {"n_ticks": int(n), "n_ticks_time_limit": int(get("n_ticks_at_cap") or 0),
             "tick_time_limit_s": get("tick_time_limit_s")}
    tick = get("stuck_tick")
    if tick is not None and pd.notna(tick):
        ticks["stuck"] = {"tick": int(tick), "reason": get("stuck_reason")}
    return ticks


def status_cell(row: pd.Series) -> str:
    """The solver outcome of a table row, in a few words."""
    status = row["status"]
    if status in data.NO_RUN:
        return status
    return data.solver_short({"status": status, "mip_gap": row.get("mip_gap")}, row_ticks(row))


def status_words(df: pd.DataFrame) -> pd.DataFrame:
    """The table with its solver status in plain words; a stuck run says at which tick."""
    df = df.copy()
    ran, stuck = data.has_result(df), data.is_stuck(df)
    df.loc[ran, "status"] = df.loc[ran, "status"].map(data.status_text)
    df.loc[stuck, "status"] = ("Stuck at tick "
                               + df.loc[stuck, "stuck_tick"].astype(int).astype(str))
    return df


def csv_bytes(df: pd.DataFrame, headers: dict[str, str]) -> bytes:
    # utf-8-sig: Excel then reads the °C and other non-ASCII headers correctly.
    df = status_words(df)
    df = df.astype({k: "Int64" for k in COUNTS if k in df})     # 3, not 3.0
    return df.rename(columns=headers).to_csv(index=False).encode("utf-8-sig")


def gap_warning(table: pd.DataFrame, where: str = "") -> None:
    gap = pd.to_numeric(table["mip_gap"], errors="coerce")
    unproven = table[(table["status"] == "time_limit") & (gap > GAP_WARN)]
    per_tick = pd.to_numeric(unproven["n_ticks"], errors="coerce").notna()

    def names(rows: pd.DataFrame) -> str:
        return ", ".join(dict.fromkeys(f"{r.configuration} {r.section} {r.tag}"
                                       for r in rows.itertuples()))
    if (~per_tick).any():
        st.warning(f"Not proven best{where}: {names(unproven[~per_tick])} stopped at the time "
                   f"limit with a MIP gap above {GAP_WARN:.0%}. Differences against these runs "
                   "may be the solver's, not the model's.", icon=":material/hourglass_bottom:")
    if per_tick.any():
        st.warning(f"Ticks stopped at the per-tick cap{where}: in {names(unproven[per_tick])}, "
                   f"some ticks stopped at the cap with a MIP gap above {GAP_WARN:.0%}. The "
                   "decisions of those ticks may not be the best for what they saw, so small "
                   "differences against these runs may be the solver's, not the model's. Each "
                   "test's page charts every tick.", icon=":material/hourglass_bottom:")


def _run_names(rows: pd.DataFrame) -> list[str]:
    """'6 servers · heavy day 6.1 Base', once per run (the Base sits in three sections)."""
    rows = rows.drop_duplicates(["configuration", "run"])
    return [f"{r.configuration} {r.section} {r.tag}" for r in rows.itertuples()]


def stuck_notice(table: pd.DataFrame, where: str = "", each: bool = False) -> None:
    """Say which runs stopped at a stuck tick and why: a stuck run is a result of the
    release, not a missing one. ``each`` names every run with its tick; otherwise the runs
    are counted per configuration and only those with no valid schedule are named."""
    stuck = table[data.is_stuck(table)].drop_duplicates(["configuration", "run"])
    if stuck.empty:
        return
    over_cap = stuck["stuck_reason"].str.startswith("no schedule within")
    if each:
        runs = "; ".join(f"**{r.tag}** at tick {int(r.stuck_tick)} ({r.stuck_reason})"
                         for r in stuck.itertuples())
        head = f"{'One run' if len(stuck) == 1 else f'{len(stuck)} runs'} got stuck{where}: {runs}."
    else:
        per = stuck.groupby("configuration", sort=False).size()
        head = (f"{len(stuck)} runs got stuck{where}: "
                + ", ".join(f"{n} on {c}" for c, n in per.items()) + ". "
                + (f"{int(over_cap.sum())} found no schedule for a tick within the per-tick cap"
                   if over_cap.any() else ""))
        invalid = stuck[~over_cap]
        if not invalid.empty:
            head += ("; " if over_cap.any() else "") + "; ".join(
                f"{n} (tick {int(r.stuck_tick)}) has {r.stuck_reason}"
                for n, r in zip(_run_names(invalid), invalid.itertuples()))
        head += "."
    st.info(f"**Stuck runs.** {head} A run stops at the first tick it cannot plan: it keeps "
            "the ticks before it (a partial schedule) but has no full-day schedule, so its "
            "measures are blank. *No schedule within the cap* means the solver ran out of time "
            "for that tick and a schedule may exist; *no valid schedule* means none exists "
            "within the limits named. Each test's *Test charts* page shows where it stopped.",
            icon=":material/block:")


def _status_grid(table: pd.DataFrame) -> pd.DataFrame:
    """One row per test (the base once), one column per configuration: servers · load level."""
    rows = {}
    for r in table.itertuples():
        test = f"{r.section} · {r.tag} · {r.label}" if r.tag != "Base" or r.section == "6.2" \
            else "Base (6.1, 6.3, 6.4)"
        ticks = row_ticks(r) if r.status not in data.NO_RUN else None
        if r.status in data.NO_RUN:
            icon = {data.NOT_RUN_YET: "·", data.NOT_APPLICABLE: "n/a",
                    data.NOT_IN_RELEASE: "–"}[r.status]
        elif ticks is not None and ticks.get("stuck"):
            short = ("no schedule in cap" if str(r.stuck_reason).startswith("no schedule within")
                     else "no valid schedule")
            icon = f"⛔ stuck at tick {ticks['stuck']['tick']}, {short}"
        elif ticks is not None and r.status in ("optimal", "time_limit"):
            cap = ticks["n_ticks_time_limit"]
            icon = ("✅ every tick" if not cap else
                    f"⏱ {cap} at cap, gap {(r.mip_gap or 0) * 100:.2f} %")
        elif r.status == "optimal":
            icon = "✅ proven best"
        elif r.status == "time_limit" and pd.notna(r.mip_gap):
            icon = f"⏱ gap {r.mip_gap * 100:.2f} %"
        else:
            icon = "❌ " + data.status_text(r.status)
        # "10 · light": the server count and load level, short enough for nine columns
        column = f"{r.servers.split()[0]} · {r.level.split()[0].lower()}"
        rows.setdefault(test, {})[column] = icon
    grid = pd.DataFrame.from_dict(rows, orient="index")
    grid.index.name = "Test"
    return grid.reset_index()


def _counts(cat) -> tuple[int, int]:
    """Tests with a run, and tests to run in this release (not counting the not-applicable
    ones and the configurations it does not run)."""
    in_release = data.configs_with_runs(cat)
    cells = [(config, test, cat[(config.key, test.id)][0])
             for config in ex.CONFIGURATIONS for test in ex.TESTS]
    todo = [c for c in cells if ex.applicable(c[1], c[0]) and c[0].key in in_release]
    return sum(used is not None for _, _, used in todo), len(todo)


def _not_in_release(cat) -> str:
    """'10 servers · heavy day, 2 servers (every load level)': the configurations without a
    run in this release."""
    in_release = data.configs_with_runs(cat)
    out = []
    for fleet in ex.FLEETS.values():
        missing = [c for c in ex.CONFIGURATIONS
                   if c.fleet_key == fleet.fleet_key and c.key not in in_release]
        if len(missing) == len(ex.LEVELS):
            out.append(f"{fleet.size_label} (every load level)")
        else:
            out += [c.label for c in missing]
    return ", ".join(out)


def render() -> None:
    st.title("Chapter 6")
    table, cat = state.chapter6()
    done, total = _counts(cat)
    n_stuck = len(table[data.is_stuck(table)].drop_duplicates(["configuration", "run"]))
    left_out = _not_in_release(cat)
    st.caption(
        f"Every configuration goes through the tests of the four Chapter 6 scenarios. A "
        f"configuration is a server count (10, 6 or 2 servers) on a load level: "
        + ", ".join(f"a {lv.label.lower()} ({lv.target:.0%})" for lv in ex.LEVELS)
        + ", the share of the fleet's cores or memory, whichever fills first, that the day's "
        f"workloads reach at their peak. **{done} of {total} runs are on the site**"
        + (f", {n_stuck} of them stuck at a tick" if n_stuck else "") + ". "
        + (f"Not run in this release: {left_out}. " if left_out else "")
        + "A run is matched to its test by its "
        "settings, not its folder name, so runs made in the batch notebook are recognized "
        "too. When several runs match one test, the newest is used.")

    st.subheader("Runs by configuration")
    grid = _status_grid(table)
    st.dataframe(grid, hide_index=True, column_config={
        "Test": st.column_config.TextColumn("Test", pinned=True)})
    st.caption("Columns: number of servers · load level. Runs re-planned every period (per "
               "tick): ✅ every tick solved to the requested gap · ⏱ ticks stopped at the "
               "per-tick cap (how many, and the worst tick's MIP gap). Runs planned for the "
               "whole day at once: ✅ proven best · ⏱ stopped at the time limit (with its MIP "
               "gap). ⛔ stuck: the run stopped at that tick, with no schedule found within the "
               "per-tick cap (one may exist) or no valid schedule, and has no full-day result. "
               "❌ no valid schedule · **·** not run yet · **–** not run in this release · "
               "**n/a** not applicable: 6.1 Test 1 needs two "
               "servers of the same tier, 6.2 needs a server with a cold plate "
               f"({data.cold_plate_server_text()}).")

    st.subheader("All results")
    with st.container(horizontal=True, gap="medium", vertical_alignment="bottom"):
        with_runs = list(dict.fromkeys(table.loc[data.has_result(table), "configuration"]))
        picked = st.multiselect("Configurations", [c.label for c in ex.CONFIGURATIONS],
                                default=with_runs, key="ch6_configs", width=520)
        changes = st.toggle("Change against each section's Base (%)", key="ch6_changes",
                            help="Each result against the Base of its configuration and "
                                 "section. Blank where either has no value or the Base is 0.")
    shown_all = data.chapter6_changes(table) if changes else table
    shown = status_words(shown_all[shown_all["configuration"].isin(picked)])
    config = {}
    for key, header in data.CHAPTER6_COLUMNS.items():
        if changes and key in data.CHAPTER6_METRICS:
            config[key] = st.column_config.NumberColumn(
                header.rsplit(" (", 1)[0] + " (% change)", format="%+.2f%%")
        elif FORMATS.get(key) == "percent":
            config[key] = st.column_config.NumberColumn(header, format="percent")
        elif key in FORMATS:
            config[key] = st.column_config.NumberColumn(header, format=FORMATS[key])
        else:
            config[key] = st.column_config.TextColumn(header, pinned=key in PINNED)
    config.update(servers=None, level=None)     # in the Configuration column; kept in the CSV
    st.dataframe(shown, hide_index=True, column_config=config)
    gap_warning(table[table["configuration"].isin(picked)])
    stuck_notice(table[table["configuration"].isin(picked)])

    st.download_button("Download every result (CSV)",
                       csv_bytes(table, data.CHAPTER6_COLUMNS),
                       file_name="chapter6_results.csv", mime="text/csv",
                       icon=":material/download:",
                       help="Every configuration and test at full precision, with the units "
                            "in the headers.")
    st.caption(NOTES)
