"""Relationship checks from the thesis group's output plan: does the model behave the way the
cited papers say it should? Each check pairs two outputs of one run (or two runs) in a scatter,
line or box plot, with a one-sentence reading computed from the data.

No Streamlit here: frames, readings and Plotly figures only.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from dashboard.data import VARIANT_LABELS, WORKLOAD_TYPES, Run
from dashboard.theme import Palette, style

TIME_TITLE = "Local time (HH:MM)"
COLD_PLATE_RUN = "Base"      # cold plates are on in every run but --no-cold-plates ones


@dataclass(frozen=True)
class Relation:
    key: str
    title: str
    source: str
    expect: str
    cold_plates: bool = False    # needs a run with cold plates on
    two_runs: bool = False       # compares the 6.4 base run with the flat-CI run


RELATIONS = (
    Relation("util_power", "CPU utilization vs IT power",
             "Hsieh et al. (2020), Table 4, Section 6, p. 107; Arshad et al. (2022), Section 3.1, "
             "Eqs. (1)–(3), pp. 331–332",
             "Higher utilization gives higher server power, rising toward P_max at 100 %; at 0 % "
             "a server still draws its idle power, not 0 W."),
    Relation("running_energy", "Workloads running vs IT energy",
             "Koot & Wijnhoven (2021), Section 5.2, Fig. 3, p. 7",
             "Periods with more workloads running use more IT energy."),
    Relation("power_temp", "IT power vs predicted server temperature",
             "Yu et al. (2025), Section 5.1, Fig. 7(b), pp. 8–9",
             "Higher server power gives a higher predicted temperature."),
    Relation("headroom_dpf", "Thermal headroom vs DPF and effective capability",
             "Kim et al. (2021), Section 3.2, Fig. 2(a)–(b), p. 4",
             "Servers with enough headroom keep DPF = 1 and full capability; less headroom "
             "means a lower DPF and a lower effective processing capability."),
    Relation("supply_energy", "CRAC supply-air temperature and CRAC energy over time",
             "Zhao et al. (2025), Figs. 27–28 and Table 10, p. 23",
             "The supply-air temperature the model chooses, and the CRAC energy it costs, over "
             "the same periods: colder supply air costs more energy."),
    Relation("heat_crac", "IT heat vs CRAC heat removed",
             "Tang et al. (2022), Section 2.3.1, p. 5",
             "When the servers produce more heat, the CRAC removes more heat."),
    Relation("load_power", "CRAC cooling load vs CRAC power",
             "Ran et al. (2026), Section 2.3, Eqs. (14)–(16), p. 6",
             "More heat to remove needs more CRAC electrical power (P = Q / COP)."),
    Relation("cp_flow", "Cold-plate coolant flow vs server temperature",
             "Wang et al. (2024), Fig. 8(a–f), p. 11",
             "More coolant flow gives a lower server temperature, at similar IT power.",
             cold_plates=True),
    Relation("cp_inlet", "Cold-plate inlet-water temperature vs server temperature",
             "Zhou et al. (2026), Section 3.1, Fig. 6(a–c), p. 7",
             "Colder inlet water gives a lower predicted server temperature.", cold_plates=True),
    Relation("cp_heat", "Server heat vs cold-plate heat removed",
             "Yan et al. (2026), Section 3.1.2, Fig. 5(a–c), pp. 6–7",
             "The hotter a server works, the more heat its cold plate removes.",
             cold_plates=True),
    Relation("waits", "Waiting time by workload type",
             "Ali & Özkasap (2024), Section 6.1, Fig. 6, p. 367",
             "Time-sensitive workloads start sooner; delay-tolerant ones may wait longer, "
             "within their allowed delay."),
    Relation("shifting", "Workload shifting under changing vs flat carbon intensity",
             "Javadpour et al. (2023), Fig. 13, p. 9",
             "With a daily carbon-intensity curve, delay-tolerant work moves to cleaner periods; "
             "with a flat curve there is no reason to move it.", two_runs=True),
)
BY_KEY = {r.key: r for r in RELATIONS}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def variant_of(run: Run) -> str:
    """The schedule the checks read by default: optimized when there is one."""
    return "optimized" if run.has_optimized else "baseline"


def pearson(x, y) -> float:
    """Pearson r, NaN when either side is constant or there are fewer than 3 points."""
    x, y = np.asarray(x, float), np.asarray(y, float)
    ok = ~(np.isnan(x) | np.isnan(y))
    x, y = x[ok], y[ok]
    if len(x) < 3 or np.ptp(x) == 0 or np.ptp(y) == 0:
        return float("nan")
    return float(np.corrcoef(x, y)[0, 1])


def _r(r: float) -> str:
    return "r undefined (one side is constant)" if np.isnan(r) else f"r = {r:.2f}"


def _sp(run: Run, variant: str) -> pd.DataFrame:
    sp = run.server_period
    return sp[sp["variant"] == variant] if not sp.empty else sp


def _zp(run: Run, variant: str) -> pd.DataFrame:
    zp = run.zone_period
    return zp[zp["variant"] == variant] if not zp.empty else zp


def _per_server_r(sp: pd.DataFrame, x: str, y: str) -> pd.Series:
    return sp.groupby("name", sort=False).apply(lambda g: pearson(g[x], g[y]),
                                                include_groups=False)


def _sentence(text: str) -> str:
    """Upper-case the first letter only (str.capitalize would lower-case °C and kWh)."""
    return text[:1].upper() + text[1:]


def _span(lo: float, hi: float, fmt: str) -> str:
    """'a–b', or just 'a' when both ends print the same."""
    a, b = format(lo, fmt), format(hi, fmt)
    return a if a == b else f"{a}–{b}"


def _r_range(rs: pd.Series) -> str:
    rs = rs.dropna()
    if rs.empty:
        return "r undefined"
    lo, hi = rs.min(), rs.max()
    return f"r = {lo:.2f}" if abs(hi - lo) < 0.005 else f"r = {lo:.2f} to {hi:.2f}"


# ---------------------------------------------------------------------------
# Frames
# ---------------------------------------------------------------------------

def running_per_period(run: Run, variant: str, types: tuple[str, ...] | None = None) -> pd.Series:
    """Number of workloads running in each period t = 1..T (start <= t < finish)."""
    sch = run.schedule
    sch = sch[(sch["variant"] == variant) & sch["start"].notna() & sch["finish"].notna()]
    if types is not None:
        sch = sch[sch["type"].isin(types)]
    T = len(run.clock)
    count = np.zeros(T + 2, dtype=int)
    for s, f in zip(sch["start"].astype(int), sch["finish"].astype(int)):
        count[max(s, 1):min(f, T + 1)] += 1
    return pd.Series(count[1:T + 1], index=pd.RangeIndex(1, T + 1, name="t"))


def running_vs_energy(run: Run, variant: str) -> pd.DataFrame:
    """t, time, workloads running, IT energy (kWh) that period."""
    p = run.period[run.period["variant"] == variant][["t", "time", "E_IT_kWh"]]
    n = running_per_period(run, variant).rename("n_running").reset_index()
    return p.merge(n, on="t", how="left")


def zone_heat(run: Run, variant: str) -> pd.DataFrame:
    """Per zone and period: IT heat not taken by cold plates (kW), CRAC heat removed,
    CRAC power and energy, supply temperature, COP."""
    sp, zp = _sp(run, variant), _zp(run, variant)
    if sp.empty or zp.empty:
        return pd.DataFrame()
    q_cp = sp["Q_cp_W"].fillna(0.0) if "Q_cp_W" in sp else 0.0
    heat = (sp.assign(heat_kW=(sp["P_IT_W"] - q_cp) / 1000.0)
            .groupby(["zone", "t"], as_index=False)["heat_kW"].sum()
            .rename(columns={"zone": "z"}))
    out = zp.merge(heat, on=["z", "t"], how="left")
    out["E_crac_kWh"] = out["P_crac_kW"] * run.dt_seconds / 3600.0
    return out


def cold_plate_rows(run: Run, variant: str) -> pd.DataFrame:
    """server_period rows of servers with a cold plate (flow set) in this schedule."""
    sp = _sp(run, variant)
    if sp.empty or "cp_flow_Lmin" not in sp:
        return sp.iloc[0:0]
    flow = pd.to_numeric(sp["cp_flow_Lmin"], errors="coerce")
    out = sp[flow.notna()].copy()
    out["cp_flow_Lmin"] = flow[flow.notna()]
    return out


def has_cold_plates(run: Run) -> bool:
    return any(not cold_plate_rows(run, v).empty for v in run.variants)


def waits(run: Run, variant: str) -> pd.DataFrame:
    """Placed workloads with their type label and waiting time in minutes."""
    sch = run.schedule
    sch = sch[(sch["variant"] == variant) & sch["start"].notna()].copy()
    sch["wait_min"] = sch["wait"].astype(float) * run.dt_seconds / 60.0
    return sch


def shifting(base: Run, flat: Run) -> pd.DataFrame:
    """t, time, CI of the base run, delay-tolerant workloads running in each run."""
    v_b, v_f = variant_of(base), variant_of(flat)
    p = base.period[base.period["variant"] == v_b][["t", "time", "CI_g_per_kWh"]]
    pf = flat.period[flat.period["variant"] == v_f][["t", "CI_g_per_kWh"]].rename(
        columns={"CI_g_per_kWh": "CI_flat"})
    out = p.merge(pf, on="t", how="left")
    dt = ("delay_tolerant",)
    out["running_base"] = running_per_period(base, v_b, dt).reindex(out["t"]).to_numpy()
    out["running_flat"] = running_per_period(flat, v_f, dt).reindex(out["t"]).to_numpy()
    return out


# ---------------------------------------------------------------------------
# Readings: one sentence each, from the data
# ---------------------------------------------------------------------------

def reading(key: str, run: Run, variant: str, other: Run | None = None) -> str:
    return READINGS[key](run, variant, other)


def _read_util_power(run, v, _):
    sp = _sp(run, v)
    rs = _per_server_r(sp, "utilization", "P_IT_W")
    idle = []
    for _, g in sp.groupby("name", sort=False):
        if g["utilization"].nunique() > 1:
            idle.append(np.polyfit(g["utilization"], g["P_IT_W"], 1)[1])
        else:
            idle.append(g["P_IT_W"].iloc[0] if g["utilization"].iloc[0] == 0 else np.nan)
    idle = pd.Series(idle).dropna()
    rising = int((rs > 0).sum())
    text = (f"Higher utilization gives higher IT power on {rising} of {len(rs)} servers "
            f"({_r_range(rs)}).")
    if not idle.empty:
        text += (f" At 0 % utilization the servers draw {idle.min():,.0f}–{idle.max():,.0f} W, "
                 "not 0 W.")
    return text


def _read_running_energy(run, v, _):
    df = running_vs_energy(run, v)
    r = pearson(df["n_running"], df["E_IT_kWh"])
    trend = "more" if r > 0 else "less"
    return (f"Periods with more workloads running use {trend} IT energy ({_r(r)}), from "
            f"{df['E_IT_kWh'].min():.3f} kWh with {df['n_running'].min()} running to "
            f"{df['E_IT_kWh'].max():.3f} kWh with {df['n_running'].max()}.")


def _read_power_temp(run, v, _):
    sp = _sp(run, v)
    rs = _per_server_r(sp, "P_IT_W", "temperature_C")
    return (f"Higher IT power goes with a higher predicted temperature on {int((rs > 0).sum())} "
            f"of {len(rs)} servers ({_r_range(rs)}; overall "
            f"{_r(pearson(sp['P_IT_W'], sp['temperature_C']))}). The scatter is not a single "
            "line because temperature also follows the previous period and the supply air.")


def _read_headroom_dpf(run, v, _):
    sp = _sp(run, v)
    low = sp[sp["DPF"] < 1 - 1e-9]
    if low.empty:
        return (f"DPF is 1 in every period: no server passed {run.T_dvfs_C:g} °C (least "
                f"headroom {sp['headroom_C'].min():.1f} °C), so this run shows no slowdown. "
                "The Slowdown check under Model checks shows a case where one does.")
    return (f"DPF falls below 1 in {len(low)} server-periods on {low['name'].nunique()} "
            f"server(s), all with headroom of at most {low['headroom_C'].max():.1f} °C; the "
            f"lowest DPF, {low['DPF'].min():.3f}, comes with "
            f"{low.loc[low['DPF'].idxmin(), 'headroom_C']:.1f} °C of headroom. With more "
            "headroom DPF stays 1 and capability stays at full speed.")


def _read_supply_energy(run, v, _):
    zh = zone_heat(run, v)
    parts = []
    for z, g in zh.groupby("z"):
        lo, hi = g["supply_temp_C"].min(), g["supply_temp_C"].max()
        sup = f"{lo:g} °C all day" if lo == hi else f"{lo:g}–{hi:g} °C"
        parts.append(f"zone {z} supply {sup}, CRAC energy "
                     f"{_span(g['E_crac_kWh'].min(), g['E_crac_kWh'].max(), '.4f')} kWh per period")
    text = _sentence("; ".join(parts)) + "."
    per_heat = zh["P_crac_kW"] / zh["Q_crac_kW"].where(zh["Q_crac_kW"] > 0)
    r = pearson(zh["supply_temp_C"], per_heat)
    if not np.isnan(r):
        text += (f" Colder supply air costs more CRAC energy per kW of heat removed "
                 f"({_r(r)}).")
    else:
        text += " With the supply constant, CRAC energy follows only the heat to remove."
    return text


def _read_heat_crac(run, v, _):
    zh = zone_heat(run, v)
    r = pearson(zh["heat_kW"], zh["Q_crac_kW"])
    ratio = (zh["Q_crac_kW"] / zh["heat_kW"].where(zh["heat_kW"] > 0)).dropna()
    return (f"The CRAC removes more heat when the servers make more ({_r(r)}); it removes "
            f"{_span(ratio.min(), ratio.max(), '.0%')} of the heat the cold plates leave.")


def _read_load_power(run, v, _):
    zh = zone_heat(run, v)
    r = pearson(zh["Q_crac_kW"], zh["P_crac_kW"])
    cops = zh["COP"].dropna()
    return (f"More heat to remove needs more CRAC power ({_r(r)}); the slope is 1 / COP, with "
            f"COP {_span(cops.min(), cops.max(), '.2f')} at the supply temperatures used.")


def _single(series: pd.Series) -> float | None:
    vals = series.dropna().unique()
    return float(vals[0]) if len(vals) == 1 else None


def _read_cp_flow(run, v, _):
    cp = cold_plate_rows(run, v)
    if cp.empty:
        return f"This run has cold plates off. Pick {COLD_PLATE_RUN}."
    one = _single(cp["cp_flow_Lmin"])
    if one is not None:
        return (f"The flow is {one:g} L/min in every period on all {cp['name'].nunique()} "
                "cold-plate servers, so this run cannot show how flow changes temperature: the "
                "optimizer keeps the plates at full flow because the pumps use almost no "
                "electricity.")
    rs = _per_server_r(cp, "cp_flow_Lmin", "temperature_C")
    return f"More flow goes with a lower temperature on {int((rs < 0).sum())} of {len(rs)} servers ({_r_range(rs)})."


def _read_cp_inlet(run, v, _):
    cp = cold_plate_rows(run, v)
    if cp.empty:
        return f"This run has cold plates off. Pick {COLD_PLATE_RUN}."
    one = _single(cp["cp_coolant_C"])
    if one is not None:
        return (f"The inlet water is {one:g} °C in every period, the coldest allowed, so this "
                "run cannot show how inlet temperature changes server temperature.")
    rs = _per_server_r(cp, "cp_coolant_C", "temperature_C")
    return (f"Colder inlet water goes with a lower temperature on {int((rs > 0).sum())} of "
            f"{len(rs)} servers ({_r_range(rs)}).")


def _read_cp_heat(run, v, _):
    cp = cold_plate_rows(run, v)
    if cp.empty:
        return f"This run has cold plates off. Pick {COLD_PLATE_RUN}."
    rs = _per_server_r(cp, "P_IT_W", "Q_cp_W")
    over = int((cp["Q_cp_W"] > cp["P_IT_W"] + 1e-6).sum())
    return (f"The cold plate removes more heat when its server makes more on "
            f"{int((rs > 0).sum())} of {len(rs)} servers ({_r_range(rs)}); peak "
            f"{cp['Q_cp_W'].max():.1f} W. It never removes more than the server makes"
            + ("." if over == 0 else f", except in {over} server-periods."))


def _read_waits(run, v, _):
    w = waits(run, v)
    parts = []
    for typ, label in WORKLOAD_TYPES.items():
        g = w[w["type"] == typ]["wait_min"]
        if len(g):
            parts.append(f"{label.lower()} workloads wait a median {g.median():.0f} min "
                         f"(mean {g.mean():.0f}, longest {g.max():.0f})")
    return _sentence("; ".join(parts)) + "."


def _read_shifting(run, v, other):
    if other is None:
        return "Needs both 6.4 runs."
    df = shifting(run, other)
    r_b = pearson(df["running_base"], df["CI_g_per_kWh"])
    r_f = pearson(df["running_flat"], df["CI_g_per_kWh"])
    return (f"Against the daily carbon-intensity curve, delay-tolerant work running correlates "
            f"{_r(r_b)} in the base run and {_r(r_f)} in the flat-CI run; a more negative r "
            "means more work in the cleaner periods.")


READINGS = {
    "util_power": _read_util_power, "running_energy": _read_running_energy,
    "power_temp": _read_power_temp, "headroom_dpf": _read_headroom_dpf,
    "supply_energy": _read_supply_energy, "heat_crac": _read_heat_crac,
    "load_power": _read_load_power, "cp_flow": _read_cp_flow, "cp_inlet": _read_cp_inlet,
    "cp_heat": _read_cp_heat, "waits": _read_waits, "shifting": _read_shifting,
}


# ---------------------------------------------------------------------------
# Figures
# ---------------------------------------------------------------------------

def figure(key: str, run: Run, variant: str, pal: Palette, other: Run | None = None) -> go.Figure:
    return FIGURES[key](run, variant, pal, other)


def _by_server(sp: pd.DataFrame, run: Run, pal: Palette, x: str, y: str, xtitle: str,
               ytitle: str, xscale: float = 1.0, yscale: float = 1.0, height: int = 460,
               fig: go.Figure | None = None, row: int | None = None,
               legend: bool = True) -> go.Figure:
    """Scatter of server-periods, one colour per server in display order."""
    fig = fig or go.Figure()
    kw = {} if row is None else dict(row=row, col=1)
    for k, srv in enumerate(run.servers.itertuples()):
        d = sp[sp["s"] == srv.s]
        if d.empty:
            continue
        fig.add_scatter(
            x=d[x] * xscale, y=d[y] * yscale, mode="markers", name=srv.label,
            legendgroup=srv.label, showlegend=legend,
            marker=dict(color=pal.nth(k), size=5, opacity=0.6, line_width=0),
            customdata=np.c_[d["t"], d["clock"]],
            hovertemplate=(f"<b>{srv.label}</b><br>{xtitle} %{{x:,.2f}}<br>{ytitle} "
                           "%{y:,.2f}<br>t=%{customdata[0]} (%{customdata[1]})<extra></extra>"),
            **kw)
    if row is None:
        style(fig, pal, height=height, time_axis=False, hovermode="closest")
        fig.update_xaxes(title_text=xtitle)
        fig.update_yaxes(title_text=ytitle)
    return fig


def _fig_util_power(run, v, pal, _):
    return _by_server(_sp(run, v), run, pal, "utilization", "P_IT_W", "CPU utilization (%)",
                      "IT power (W)", xscale=100.0)


def _fig_running_energy(run, v, pal, _):
    df = running_vs_energy(run, v)
    fig = go.Figure(go.Scatter(
        x=df["n_running"], y=df["E_IT_kWh"], mode="markers", name="Period",
        marker=dict(color=pal.variant(v), size=6, opacity=0.6, line_width=0),
        customdata=np.c_[df["t"], df["time"].dt.strftime("%H:%M")],
        hovertemplate=("%{x} running, %{y:.4f} kWh<br>t=%{customdata[0]} "
                       "(%{customdata[1]})<extra></extra>")))
    style(fig, pal, height=420, legend=False, time_axis=False, hovermode="closest")
    fig.update_xaxes(title_text="Workloads running in the period")
    fig.update_yaxes(title_text=f"IT energy per {run.dt_seconds / 60:g}-min period (kWh)")
    return fig


def _fig_power_temp(run, v, pal, _):
    return _by_server(_sp(run, v), run, pal, "P_IT_W", "temperature_C", "IT power (W)",
                      "Predicted temperature (°C)")


def _fig_headroom_dpf(run, v, pal, _):
    sp = _sp(run, v)
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.08)
    _by_server(sp, run, pal, "headroom_C", "DPF", "Headroom (°C)", "DPF", fig=fig, row=1)
    _by_server(sp, run, pal, "headroom_C", "PC_eff_MHz", "Headroom (°C)",
               "Effective capability (GHz)", yscale=1e-3, fig=fig, row=2, legend=False)
    style(fig, pal, height=620, time_axis=False, hovermode="closest")
    fig.update_yaxes(title_text="DPF (1 = full speed)", row=1, col=1)
    fig.update_yaxes(title_text="Effective capability (GHz)", row=2, col=1)
    fig.update_xaxes(title_text="Thermal headroom T_max − T (°C)", row=2, col=1)
    lo = sp["DPF"].min()
    fig.update_yaxes(range=[min(lo, 0.95) - 0.01, 1.01], row=1, col=1)
    return fig


def _fig_supply_energy(run, v, pal, _):
    zh = zone_heat(run, v)
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.08)
    for k, (z, g) in enumerate(zh.groupby("z")):
        common = dict(legendgroup=f"z{z}", customdata=g["t"])
        fig.add_scatter(x=g["time"], y=g["supply_temp_C"], name=f"Zone {z}", mode="lines",
                        line=dict(color=pal.nth(k), width=2, shape="hv"),
                        hovertemplate=f"Zone {z}: %{{y:g}} °C (t=%{{customdata}})<extra></extra>",
                        row=1, col=1, **common)
        fig.add_scatter(x=g["time"], y=g["E_crac_kWh"], name=f"Zone {z}", mode="lines",
                        showlegend=False, line=dict(color=pal.nth(k), width=1.5),
                        hovertemplate=f"Zone {z}: %{{y:.4f}} kWh (t=%{{customdata}})<extra></extra>",
                        row=2, col=1, **common)
    style(fig, pal, height=560)
    fig.update_yaxes(title_text="Supply air (°C)", row=1, col=1)
    fig.update_yaxes(title_text=f"CRAC energy per {run.dt_seconds / 60:g} min (kWh)",
                     rangemode="tozero", row=2, col=1)
    fig.update_xaxes(title_text=TIME_TITLE, row=2, col=1)
    return fig


def _zone_scatter(zh, pal, x, y, xtitle, ytitle, color_by=None):
    fig = go.Figure()
    if color_by is None:
        for k, (z, g) in enumerate(zh.groupby("z")):
            fig.add_scatter(
                x=g[x], y=g[y], mode="markers", name=f"Zone {z}",
                marker=dict(color=pal.nth(k), size=6, opacity=0.6, line_width=0),
                customdata=np.c_[g["t"], g["clock"]],
                hovertemplate=(f"<b>Zone {z}</b><br>{xtitle} %{{x:.3f}}<br>{ytitle} %{{y:.3f}}"
                               "<br>t=%{customdata[0]} (%{customdata[1]})<extra></extra>"))
    else:
        fig.add_scatter(
            x=zh[x], y=zh[y], mode="markers", name="Zone-period",
            marker=dict(color=zh[color_by], colorscale=list(pal.seq), size=7, line_width=0,
                        colorbar=dict(title=dict(text="Supply (°C)", side="right"),
                                      thickness=12, outlinewidth=0)),
            customdata=np.c_[zh["z"], zh["t"], zh[color_by]],
            hovertemplate=(f"Zone %{{customdata[0]}}, t=%{{customdata[1]}}<br>{xtitle} %{{x:.3f}}"
                           f"<br>{ytitle} %{{y:.3f}}<br>supply %{{customdata[2]:g}} °C"
                           "<extra></extra>"))
    style(fig, pal, height=440, time_axis=False, hovermode="closest", legend=color_by is None)
    fig.update_xaxes(title_text=xtitle)
    fig.update_yaxes(title_text=ytitle)
    return fig


def _fig_heat_crac(run, v, pal, _):
    return _zone_scatter(zone_heat(run, v), pal, "heat_kW", "Q_crac_kW",
                         "IT heat left to the CRAC (kW)", "CRAC heat removed Q_crac (kW)")


def _fig_load_power(run, v, pal, _):
    return _zone_scatter(zone_heat(run, v), pal, "Q_crac_kW", "P_crac_kW",
                         "CRAC cooling load Q_crac (kW)", "CRAC power P_crac (kW)",
                         color_by="supply_temp_C")


def _fig_cp(x, y, xtitle, ytitle):
    def build(run, v, pal, _):
        return _by_server(cold_plate_rows(run, v), run, pal, x, y, xtitle, ytitle)
    return build


def _fig_waits(run, v, pal, _):
    w = waits(run, v)
    fig = go.Figure()
    for typ, label in WORKLOAD_TYPES.items():
        g = w[w["type"] == typ]
        if g.empty:
            continue
        fig.add_box(
            x=[label] * len(g), y=g["wait_min"], name=label, boxpoints="all", jitter=0.4,
            pointpos=0, marker=dict(color=pal.types[typ], size=5, opacity=0.6),
            line=dict(color=pal.types[typ]), fillcolor="rgba(0,0,0,0)",
            customdata=np.c_[g["workload_id"], g["allowed_delay"] * run.dt_seconds / 60],
            hovertemplate=("<b>%{customdata[0]}</b><br>wait %{y:.0f} min "
                           "(allowed %{customdata[1]:.0f})<extra></extra>"))
    style(fig, pal, height=440, legend=False, time_axis=False, hovermode="closest")
    fig.update_yaxes(title_text="Waiting time, start − arrival (min)", rangemode="tozero")
    return fig


def _fig_shifting(run, v, pal, other):
    df = shifting(run, other)
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, row_heights=[0.62, 0.38],
                        vertical_spacing=0.08)
    for col, name, color in (("running_base", "6.4 Base (daily CI)", pal.optimized),
                             ("running_flat", "6.4 Test 3a Flat carbon intensity", pal.baseline)):
        fig.add_scatter(x=df["time"], y=df[col], name=name, mode="lines",
                        line=dict(color=color, width=1.75, shape="hv"), customdata=df["t"],
                        hovertemplate="%{y} running (t=%{customdata})", row=1, col=1)
    fig.add_scatter(x=df["time"], y=df["CI_g_per_kWh"], name="Grid CI (base run)", mode="lines",
                    line=dict(color=pal.ink2, width=1.5), customdata=df["t"],
                    hovertemplate="%{y:,.1f} g CO₂/kWh (t=%{customdata})", row=2, col=1)
    fig.add_scatter(x=df["time"], y=df["CI_flat"], name="Grid CI (flat run)", mode="lines",
                    line=dict(color=pal.ink2, width=1.5, dash="dot"), customdata=df["t"],
                    hovertemplate="%{y:,.1f} g CO₂/kWh flat (t=%{customdata})", row=2, col=1)
    style(fig, pal, height=560)
    fig.update_yaxes(title_text="Delay-tolerant running", rangemode="tozero", row=1, col=1)
    fig.update_yaxes(title_text="Grid CI (g CO₂/kWh)", row=2, col=1)
    fig.update_xaxes(title_text=TIME_TITLE, row=2, col=1)
    return fig


FIGURES = {
    "util_power": _fig_util_power, "running_energy": _fig_running_energy,
    "power_temp": _fig_power_temp, "headroom_dpf": _fig_headroom_dpf,
    "supply_energy": _fig_supply_energy, "heat_crac": _fig_heat_crac,
    "load_power": _fig_load_power,
    "cp_flow": _fig_cp("cp_flow_Lmin", "temperature_C", "Coolant flow (L/min)",
                       "Predicted temperature (°C)"),
    "cp_inlet": _fig_cp("cp_coolant_C", "temperature_C", "Inlet water (°C)",
                        "Predicted temperature (°C)"),
    "cp_heat": _fig_cp("P_IT_W", "Q_cp_W", "Server heat = IT power (W)",
                       "Cold-plate heat removed Q_cp (W)"),
    "waits": _fig_waits, "shifting": _fig_shifting,
}


def schedule_label(variant: str) -> str:
    return VARIANT_LABELS[variant]
