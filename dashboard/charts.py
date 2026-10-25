"""Plotly figure builders. Each takes a loaded Run (or frames from dashboard.data) and a
Palette and returns a styled figure; no Streamlit calls here."""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from dashboard.data import (
    ENERGY_COMPONENTS, VARIANT_LABELS, WORKLOAD_TYPES, Run, active_energy_components,
    period_bounds,
)
from dashboard.theme import Palette, rgba, style, threshold

TIME_TITLE = "Local time (HH:MM)"


def _period_label(run: Run) -> str:
    return f"{run.dt_seconds / 60:g}-min period"


def _variant_line(pal: Palette, v: str, width: float = 2.0) -> dict:
    return dict(color=pal.variant(v), width=width)


def _empty(pal: Palette, message: str, height: int = 240) -> go.Figure:
    fig = go.Figure()
    fig.add_annotation(text=message, showarrow=False, font=dict(color=pal.muted, size=14),
                       xref="paper", yref="paper", x=0.5, y=0.5)
    fig.update_xaxes(visible=False)
    fig.update_yaxes(visible=False)
    return style(fig, pal, height=height, legend=False, time_axis=False)


# ---------------------------------------------------------------------------
# Energy and carbon
# ---------------------------------------------------------------------------

def carbon_and_ci(run: Run, pal: Palette) -> go.Figure:
    """Carbon per period, baseline vs optimized, with grid CI in an aligned panel below."""
    cp = run.comparison_period
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, row_heights=[0.62, 0.38],
                        vertical_spacing=0.08)
    for v in run.variants:
        col = f"{v}_carbon_g"
        if col not in cp or cp[col].isna().all():
            continue
        fig.add_scatter(
            x=cp["time"], y=cp[col], name=VARIANT_LABELS[v], mode="lines",
            line=_variant_line(pal, v), customdata=cp["t"],
            hovertemplate="%{y:,.2f} g CO₂ (t=%{customdata})", row=1, col=1)
    fig.add_scatter(
        x=cp["time"], y=cp["CI_g_per_kWh"], name="Grid carbon intensity", mode="lines",
        line=dict(color=pal.ink2, width=1.5), showlegend=False, customdata=cp["t"],
        hovertemplate="%{y:,.2f} g CO₂/kWh (t=%{customdata})", row=2, col=1)
    style(fig, pal, height=540)
    fig.update_yaxes(title_text=f"Carbon per {_period_label(run)} (g CO₂)", row=1, col=1)
    fig.update_yaxes(title_text="Grid CI (g CO₂/kWh)", row=2, col=1)
    fig.update_xaxes(title_text=TIME_TITLE, row=2, col=1)
    return fig


def energy_bars(run: Run, pal: Palette) -> go.Figure:
    """Energy over the horizon by component, one stacked bar per schedule."""
    comps = active_energy_components(run)
    variants = [v for v in run.variants if (run.period["variant"] == v).any()]
    totals = run.period.groupby("variant")[comps].sum()
    fig = go.Figure()
    for comp in comps:
        y = [float(totals.loc[v, comp]) for v in variants]
        grand = [float(totals.loc[v].sum()) for v in variants]
        fig.add_bar(
            x=[VARIANT_LABELS[v] for v in variants], y=y, name=ENERGY_COMPONENTS[comp],
            marker=dict(color=pal.components[comp], line_width=0),
            customdata=np.c_[[100 * a / g if g else 0 for a, g in zip(y, grand)]],
            hovertemplate=(f"{ENERGY_COMPONENTS[comp]}: %{{y:,.4f}} kWh "
                           "(%{customdata[0]:.1f}% of total)<extra></extra>"))
    for v in variants:
        total = float(totals.loc[v].sum())
        fig.add_annotation(x=VARIANT_LABELS[v], y=total, text=f"{total:,.2f} kWh",
                           showarrow=False, yanchor="bottom", font=dict(color=pal.ink2))
    style(fig, pal, height=380, time_axis=False, hovermode="closest")
    fig.update_layout(barmode="stack", bargap=0.55)
    fig.update_yaxes(title_text="Energy over the horizon (kWh)", rangemode="tozero")
    return fig


# ---------------------------------------------------------------------------
# Thermal
# ---------------------------------------------------------------------------

def temperature_colorscale(pal: Palette, zmin: float, zmax: float,
                           dvfs: float, cap: float) -> list:
    """Sequential ramp up to the first limit, then warning (above DVFS) and critical
    (above the cap) bands, as hard steps."""
    def pos(v):
        return min(max((v - zmin) / (zmax - zmin), 0.0), 1.0)
    low = min(dvfs, cap)
    p_low = pos(low)
    n = len(pal.seq)
    scale = [[p_low * k / (n - 1), c] for k, c in enumerate(pal.seq)]
    if dvfs < cap:
        scale += [[p_low, pal.status["warning"]], [pos(cap), pal.status["warning"]]]
    scale += [[pos(cap), pal.status["critical"]], [1.0, pal.status["critical"]]]
    return scale


def temperature_heatmap(run: Run, pal: Palette, variants: list[str]) -> go.Figure:
    """Server x time temperature for each variant on one shared colour scale."""
    sp = run.server_period
    variants = [v for v in variants if (sp["variant"] == v).any()]
    dvfs, cap = run.T_dvfs_C, run.thermal_cap_C
    zmin = math.floor(sp["temperature_C"].min())
    zmax = max(math.ceil(sp["temperature_C"].max()), max(dvfs, cap) + 2)
    order = run.servers["label"].tolist()
    fig = make_subplots(rows=len(variants), cols=1, shared_xaxes=True,
                        subplot_titles=[VARIANT_LABELS[v] for v in variants],
                        vertical_spacing=0.12 if len(variants) > 1 else 0.05)
    for k, v in enumerate(variants, start=1):
        d = sp[sp["variant"] == v]
        z = d.pivot(index="label", columns="t", values="temperature_C").reindex(order)
        h = d.pivot(index="label", columns="t", values="headroom_C").reindex(order)
        times = run.clock.set_index("t").loc[z.columns, "time"]
        tt = np.broadcast_to(z.columns.to_numpy(), z.shape)
        fig.add_heatmap(
            x=times, y=z.index, z=z.to_numpy(), coloraxis="coloraxis", ygap=2,
            customdata=np.dstack([tt, h.to_numpy()]),
            hovertemplate=("<b>%{y}</b><br>%{x|%H:%M} (t=%{customdata[0]})<br>"
                           "%{z:.2f} °C, headroom %{customdata[1]:.2f} °C<extra>"
                           f"{VARIANT_LABELS[v]}</extra>"),
            row=k, col=1)
        over = d[d["temperature_C"] > cap + 1e-6]
        if len(over):
            fig.add_scatter(
                x=over["time"], y=over["label"], mode="markers", name=f"Above cap {cap:g} °C",
                marker=dict(symbol="x-thin", size=7, line=dict(width=1.5, color=pal.ink)),
                legendgroup="over", showlegend=k == 1 or not fig.data[0].showlegend,
                customdata=np.c_[over["t"], over["temperature_C"]],
                hovertemplate=("<b>%{y}</b><br>%{x|%H:%M} (t=%{customdata[0]})<br>"
                               "%{customdata[1]:.2f} °C, above cap<extra></extra>"),
                row=k, col=1)
    ticks = sorted({dvfs, cap} | set(np.linspace(zmin, min(dvfs, cap), 4).round()))
    ticks = [t for t in ticks if zmin <= t <= zmax and
             (t in (dvfs, cap) or min(abs(t - dvfs), abs(t - cap)) > (zmax - zmin) * 0.06)]
    labels = [f"{t:g} DVFS" if t == dvfs and t != cap else
              f"{t:g} cap" if t == cap and t != dvfs else
              f"{t:g} DVFS = cap" if t == dvfs == cap else f"{t:g}" for t in ticks]
    style(fig, pal, height=170 + 34 * len(order) * len(variants), legend=True,
          hovermode="closest", titled=True)
    fig.update_layout(coloraxis=dict(
        colorscale=temperature_colorscale(pal, zmin, zmax, dvfs, cap), cmin=zmin, cmax=zmax,
        colorbar=dict(title=dict(text="Server temp. (°C)", side="right"), tickvals=ticks,
                      ticktext=labels, thickness=12, outlinewidth=0,
                      tickfont=dict(color=pal.ink2))))
    fig.update_xaxes(showspikes=False, showgrid=False)
    fig.update_xaxes(title_text=TIME_TITLE, row=len(variants), col=1)
    fig.update_yaxes(showgrid=False, autorange="reversed", title_text="Server (zone)")
    return fig


def _dash_key(fig: go.Figure, pal: Palette, variants: list[str]) -> None:
    """Legend entries saying which schedule is solid and which dashed (two schedules only)."""
    if len(variants) < 2:
        return
    for v in variants:
        fig.add_scatter(x=[None], y=[None], mode="lines", hoverinfo="skip",
                        name=f"{VARIANT_LABELS[v]} ({'solid' if v == 'optimized' else 'dashed'})",
                        line=dict(color=pal.ink2, width=1.4,
                                  dash="solid" if v == "optimized" else "dash"))


# server_period column -> (axis title, hover format, scale, unit); scale converts the value.
SERVER_LINES = {
    "utilization": ("CPU utilization (%)", ".1f", 100.0, "%"),
    "temperature_C": ("Predicted temperature (°C)", ".2f", 1.0, "°C"),
    "headroom_C": ("Thermal headroom (°C)", ".2f", 1.0, "°C"),
    "PC_eff_MHz": ("Effective processing capability (GHz)", ",.2f", 1e-3, "GHz"),
    "P_IT_W": ("IT power (W)", ",.1f", 1.0, "W"),
    "DPF": ("DPF (1 = full speed)", ".4f", 1.0, ""),
    "cp_coolant_C": ("Coolant inlet temperature (°C)", ".2f", 1.0, "°C"),
    "cp_flow_Lmin": ("Coolant flow (L/min)", ".3f", 1.0, "L/min"),
}


def server_lines(run: Run, pal: Palette, servers: list[int], column: str,
                 variants: list[str]) -> go.Figure:
    """One line per server over the day; a second schedule is drawn dashed in the same
    colour. Temperature carries the DVFS and cap lines, headroom the required H_min."""
    title, fmt, scale, unit = SERVER_LINES[column]
    sp = run.server_period
    info = run.servers.reset_index(drop=True)
    fig = go.Figure()
    for k, srv in info.iterrows():
        if srv["s"] not in servers:
            continue
        for v in variants:
            d = sp[(sp["variant"] == v) & (sp["s"] == srv["s"])]
            if d.empty or d[column].isna().all():
                continue
            tag = "" if len(variants) == 1 else f" ({VARIANT_LABELS[v].lower()})"
            fig.add_scatter(
                x=d["time"], y=d[column] * scale, name=srv["label"], mode="lines",
                legendgroup=str(srv["s"]), showlegend=v == variants[0],
                line=dict(color=pal.nth(k), width=1.6 if v == "optimized" else 1.2,
                          dash="solid" if v == "optimized" else "dash",
                          shape="hv" if column in ("utilization", "cp_flow_Lmin",
                                                   "cp_coolant_C") else "linear"),
                customdata=d["t"],
                hovertemplate=f"{srv['name']}{tag}: %{{y:{fmt}}} {unit}<extra></extra>")
    _dash_key(fig, pal, variants)
    style(fig, pal, height=440)
    if column == "temperature_C":
        threshold(fig, pal, run.T_dvfs_C, f"DVFS {run.T_dvfs_C:g} °C", dash="dash")
        threshold(fig, pal, run.thermal_cap_C, f"Thermal cap {run.thermal_cap_C:g} °C",
                  dash="dot")
        fig.update_yaxes(range=[None, max(run.thermal_cap_C, run.T_dvfs_C) + 3])
    elif column == "headroom_C" and run.H_min_C is not None:
        threshold(fig, pal, run.H_min_C, f"Required H_min {run.H_min_C:g} °C", dash="dot")
        fig.update_yaxes(rangemode="tozero")
    elif column == "utilization":
        fig.update_yaxes(range=[0, 103])
    elif column == "DPF":
        fig.update_yaxes(range=[min(0.9, float(sp["DPF"].min()) - 0.02), 1.02])
    fig.update_yaxes(title_text=title)
    fig.update_xaxes(title_text=TIME_TITLE)
    return fig


# zone_period column -> (axis title, hover format, scale, unit).
ZONE_LINES = {
    "supply_temp_C": ("CRAC supply-air temperature (°C)", ".1f", 1.0, "°C"),
    "E_crac_kWh": ("CRAC energy per period (kWh)", ",.4f", 1.0, "kWh"),
}


def zone_lines(run: Run, pal: Palette, column: str, variants: list[str]) -> go.Figure:
    """One line per cooling zone over the day; the supply chart shades the allowed range.
    ``E_crac_kWh`` is the CRAC power times the period length."""
    title, fmt, scale, unit = ZONE_LINES[column]
    zp = run.zone_period.copy()
    zp["E_crac_kWh"] = zp["P_crac_kW"] * run.dt_seconds / 3600
    fig = go.Figure()
    for k, z in enumerate(sorted(zp["z"].unique())):
        for v in variants:
            d = zp[(zp["variant"] == v) & (zp["z"] == z)]
            if d.empty:
                continue
            tag = "" if len(variants) == 1 else f" ({VARIANT_LABELS[v].lower()})"
            fig.add_scatter(
                x=d["time"], y=d[column] * scale, mode="lines", name=f"Zone {z}",
                legendgroup=str(z), showlegend=v == variants[0],
                line=dict(color=pal.nth(k), width=1.8 if v == "optimized" else 1.3,
                          dash="solid" if v == "optimized" else "dash", shape="hv"),
                customdata=d["t"],
                hovertemplate=f"Zone {z}{tag}: %{{y:{fmt}}} {unit}<extra></extra>")
    _dash_key(fig, pal, variants)
    style(fig, pal, height=360)
    cz = run.compliance_zones
    if column == "supply_temp_C" and not cz.empty:
        lo, hi = cz["supply_allowed_min_C"].min(), cz["supply_allowed_max_C"].max()
        fig.add_hrect(y0=lo, y1=hi, fillcolor=rgba(pal.muted, 0.12), line_width=0,
                      layer="below")
        fig.add_annotation(text=f"allowed {lo:g}–{hi:g} °C", xref="x domain", x=0.01, y=hi,
                           xanchor="left", yanchor="top", showarrow=False,
                           font=dict(color=pal.ink2, size=11))
        fig.update_yaxes(range=[min(lo, zp["supply_temp_C"].min()) - 1,
                                max(hi, zp["supply_temp_C"].max()) + 1])
    else:
        fig.update_yaxes(rangemode="tozero")
    fig.update_yaxes(title_text=title)
    fig.update_xaxes(title_text=TIME_TITLE)
    return fig


def cold_plate_servers(run: Run) -> list[int]:
    """Servers with cold-plate settings in any variant, in display order."""
    sp = run.server_period
    if sp.empty or "cp_flow_Lmin" not in sp:
        return []
    has = set(sp.loc[pd.to_numeric(sp["cp_flow_Lmin"], errors="coerce").notna(), "s"])
    return [s for s in run.servers["s"] if s in has]


# ---------------------------------------------------------------------------
# Schedule
# ---------------------------------------------------------------------------

def gantt_layout(run: Run, schedule: pd.DataFrame) -> tuple[pd.Series, pd.DataFrame]:
    """y position per schedule row and the server blocks (s, label, offset, lanes).

    Each server gets as many lanes as either variant needs, so baseline and optimized
    charts line up row for row.
    """
    lanes = schedule["lane"]
    need = (schedule[lanes >= 0].groupby("server")["lane"].max() + 1).to_dict()
    blocks, offset = [], 0
    for _, srv in run.servers.iterrows():
        n = int(need.get(srv["s"], 1))
        blocks.append(dict(s=srv["s"], label=srv["label"], offset=offset, lanes=n))
        offset += n + 1
    blocks = pd.DataFrame(blocks)
    off = blocks.set_index("s")["offset"]
    y = schedule["server"].map(off) + lanes
    return y, blocks


def gantt(run: Run, sched: pd.DataFrame, blocks: pd.DataFrame, pal: Palette, title: str,
          *, show_windows: bool, x_range) -> go.Figure:
    """Workloads per server: bars from start to finish, coloured by type, hatched when
    reassigned, red-outlined when non-compliant, optional arrival -> deadline window."""
    bound = period_bounds(run.clock, run.dt_seconds)
    fig = go.Figure()
    d = sched[sched["y"].notna()].copy()
    start, end = bound(d["start"]), bound(d["finish"])
    d["start_ts"], d["dur_ms"] = start, (end - start) / pd.Timedelta(milliseconds=1)
    d["start_clock"], d["finish_clock"] = start.strftime("%H:%M"), end.strftime("%H:%M")
    d["server_label"] = d["server_name"].fillna("–")
    bad = pal.status["critical"]

    if show_windows and len(d):
        a, dl = bound(d["arrival"]), bound(d["deadline"])
        xs, ys = [], []
        for x0, x1, yy in zip(a, dl, d["y"]):
            xs += [x0, x1, None]
            ys += [yy, yy, None]
        fig.add_scatter(x=xs, y=ys, mode="lines", name="Allowed window (arrival → deadline)",
                        line=dict(color=pal.muted, width=1), hoverinfo="skip")
        fig.add_scatter(x=a, y=d["y"], mode="markers", name="Arrival",
                        marker=dict(symbol="triangle-right", size=7, color=pal.muted),
                        hoverinfo="skip")
        fig.add_scatter(x=dl, y=d["y"], mode="markers", name="Deadline",
                        marker=dict(symbol="line-ns", size=10, line=dict(width=2, color=pal.ink2)),
                        hoverinfo="skip")

    for typ, label in WORKLOAD_TYPES.items():
        # Reassigned bars are a separate, legend-less trace so the legend swatch stays solid.
        has_solid = ((d["type"] == typ) & (d["reassigned"] != 1)).any()
        for moved in (False, True):
            g = d[(d["type"] == typ) & ((d["reassigned"] == 1) == moved)]
            if g.empty:
                continue
            noncompliant = g["compliant"] == 0
            fig.add_bar(
                base=g["start_ts"], x=g["dur_ms"], y=g["y"], orientation="h", name=label,
                legendgroup=typ, showlegend=not moved or not has_solid,
                width=0.8,
                marker=dict(color=pal.types[typ],
                            pattern=dict(shape="/" if moved else "", fillmode="overlay",
                                         fgcolor=pal.surface, size=5, solidity=0.4),
                            line=dict(color=np.where(noncompliant, bad, pal.types[typ]),
                                      width=np.where(noncompliant, 2, 0))),
                customdata=np.c_[g["workload_id"], g["start_clock"], g["finish_clock"],
                                 g["start"], g["finish"], g["arrival"], g["deadline"],
                                 g["wait"], g["original_server_name"], g["server_label"],
                                 np.where(g["reassigned"] == 1, "yes", "no"),
                                 np.where(noncompliant, "no", "yes")],
                hovertemplate=("<b>%{customdata[0]}</b> " + label +
                               "<br>%{customdata[1]} → %{customdata[2]} "
                               "(t=%{customdata[3]} → %{customdata[4]})"
                               "<br>arrival t=%{customdata[5]}, deadline t=%{customdata[6]}, "
                               "wait %{customdata[7]} periods"
                               "<br>server %{customdata[9]} (original %{customdata[8]}), "
                               "reassigned %{customdata[10]}<br>compliant %{customdata[11]}"
                               "<extra></extra>"))
    # Legend keys for the two secondary encodings.
    if (d["reassigned"] == 1).any():
        fig.add_bar(x=[None], y=[None], name="Reassigned (hatched)", orientation="h",
                    marker=dict(color=pal.muted, pattern=dict(shape="/", fgcolor=pal.surface,
                                                              fillmode="overlay", size=5,
                                                              solidity=0.4)))
    if (d["compliant"] == 0).any():
        fig.add_bar(x=[None], y=[None], name="Non-compliant (red outline)", orientation="h",
                    marker=dict(color="rgba(0,0,0,0)", line=dict(color=bad, width=2)))

    total = int(blocks["offset"].iloc[-1] + blocks["lanes"].iloc[-1]) if len(blocks) else 1
    style(fig, pal, height=max(300, 130 + 9 * total), hovermode="closest")
    fig.update_layout(barmode="overlay", title=dict(text=title, font=dict(color=pal.ink, size=15),
                                                    x=0, y=0.995, yanchor="top"),
                      margin=dict(t=70))
    fig.update_layout(legend=dict(y=1.0, yanchor="bottom"))
    for _, b in blocks.iloc[1:].iterrows():
        fig.add_hline(y=b["offset"] - 1, line=dict(color=pal.grid, width=1))
    fig.update_yaxes(tickvals=(blocks["offset"] + (blocks["lanes"] - 1) / 2).tolist(),
                     ticktext=blocks["label"].tolist(), showgrid=False, zeroline=False,
                     range=[total, -1.5], title_text="Server (zone)")
    fig.update_xaxes(type="date", title_text=TIME_TITLE, range=x_range, showspikes=False)
    return fig


# ---------------------------------------------------------------------------
# Compare runs
# ---------------------------------------------------------------------------

def grouped_bars(categories: list[str], series: dict[str, list], pal: Palette, *,
                 y_title: str, stacked: bool = False, colors: dict[str, str] | None = None,
                 fmt: str = ",.3f", height: int = 340) -> go.Figure:
    """One bar per category and series, grouped (or stacked). Chapter 6 uses it with the
    tests of a section (Base, Test 1, ...) or the configurations as categories."""
    fig = go.Figure()
    for k, (name, values) in enumerate(series.items()):
        color = (colors or {}).get(name, pal.nth(k))
        fig.add_bar(x=categories, y=values, name=name,
                    marker=dict(color=color, cornerradius=4, line_width=0),
                    hovertemplate=f"%{{x}} · {name}: %{{y:{fmt}}}<extra></extra>")
    style(fig, pal, height=height, time_axis=False, hovermode="closest",
          legend=len(series) > 1)
    fig.update_layout(barmode="stack" if stacked else "group", bargap=0.3, bargroupgap=0.08)
    fig.update_yaxes(title_text=y_title, rangemode="tozero")
    return fig


def compare_carbon(df: pd.DataFrame, pal: Palette) -> go.Figure:
    """Total carbon per run, baseline vs optimized, with % saved at the bar end."""
    df = df.iloc[::-1]
    fig = go.Figure()
    labels = ["no optimized schedule" if pd.isna(o) else
              f"{p:.1f}% saved" if p >= 0 else f"{-p:.1f}% more"
              for o, p in zip(df["optimized_carbon_kg"], df["carbon_saved_pct"].fillna(0))]
    fig.add_bar(y=df["run"], x=df["optimized_carbon_kg"].fillna(0), name="Optimized",
                orientation="h", marker=dict(color=pal.optimized, cornerradius=4, line_width=0),
                text=labels, textposition="outside", textfont=dict(color=pal.ink2, size=12),
                cliponaxis=False, customdata=df["optimized_carbon_kg"],
                hovertemplate="%{customdata:,.3f} kg CO₂<extra>Optimized</extra>")
    fig.add_bar(y=df["run"], x=df["baseline_carbon_kg"], name="Baseline", orientation="h",
                marker=dict(color=pal.baseline, cornerradius=4, line_width=0),
                hovertemplate="%{x:,.3f} kg CO₂<extra>Baseline</extra>")
    style(fig, pal, height=120 + 64 * len(df), time_axis=False, hovermode="closest")
    # Horizontal groups stack the first trace at the bottom; keep the legend in group order.
    fig.update_layout(barmode="group", bargap=0.3, bargroupgap=0.08, margin=dict(r=150),
                      legend_traceorder="reversed")
    fig.update_xaxes(title_text="Total carbon over the horizon (kg CO₂)", rangemode="tozero")
    fig.update_yaxes(showgrid=False)
    return fig


def validation_supply(supply: pd.DataFrame, clock: pd.DataFrame, pal: Palette) -> go.Figure:
    """Validation: the optimized CRAC supply temperature per zone (one row each), one line per
    safety margin H_min. Columns of ``supply``: H_min (°C), Zone, Period, Supply temperature (°C)."""
    zones = sorted(supply["Zone"].unique())
    fig = make_subplots(rows=len(zones), cols=1, shared_xaxes=True, vertical_spacing=0.12,
                        subplot_titles=[f"Zone {z}" for z in zones])
    colors = [pal.optimized, pal.components["E_crac_kWh"], pal.baseline, pal.components["E_IT_kWh"]]
    times = clock.set_index("t")["time"]
    for k, (h, df) in enumerate(supply.groupby("H_min (°C)", sort=True)):
        for row, z in enumerate(zones, 1):
            part = df[df["Zone"] == z].sort_values("Period")
            fig.add_trace(go.Scatter(
                x=times.reindex(part["Period"]).values, y=part["Supply temperature (°C)"],
                mode="lines", name=f"H_min {h:g} °C", legendgroup=str(h), showlegend=row == 1,
                line=dict(color=colors[k % len(colors)], width=2, shape="hv"),
                hovertemplate=f"H_min {h:g} °C: %{{y:g}} °C<extra></extra>"), row=row, col=1)
    style(fig, pal, height=200 + 160 * len(zones), titled=True)
    fig.update_yaxes(title_text="Supply (°C)")
    return fig
