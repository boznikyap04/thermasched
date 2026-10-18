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
from dashboard.theme import Palette, rgba, style

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


def energy_stack(run: Run, pal: Palette) -> go.Figure:
    """Stacked energy by component, one panel per variant, shared y scale."""
    comps = active_energy_components(run)
    variants = [v for v in run.variants if (run.period["variant"] == v).any()]
    fig = make_subplots(rows=1, cols=len(variants), shared_yaxes=True,
                        subplot_titles=[VARIANT_LABELS[v] for v in variants],
                        horizontal_spacing=0.03)
    for k, v in enumerate(variants, start=1):
        p = run.period[run.period["variant"] == v]
        for comp in comps:
            fig.add_scatter(
                x=p["time"], y=p[comp], name=ENERGY_COMPONENTS[comp], mode="lines",
                stackgroup=v, legendgroup=comp, showlegend=k == 1,
                line=dict(color=pal.surface, width=0.75),
                fillcolor=pal.components[comp], customdata=p["t"],
                hovertemplate=f"%{{y:,.4f}} kWh (t=%{{customdata}})", row=1, col=k)
    style(fig, pal, height=380, titled=True)
    fig.update_yaxes(title_text=f"Energy per {_period_label(run)} (kWh)", row=1, col=1)
    fig.update_xaxes(title_text=TIME_TITLE)
    return fig


def cumulative_savings(cum: pd.DataFrame, run: Run, pal: Palette) -> go.Figure:
    """Running total of carbon saved (optimized vs baseline), split by component."""
    fig = go.Figure()
    for comp in active_energy_components(run):
        col = f"{comp}_carbon_saved_kg"
        if col in cum:
            fig.add_scatter(x=cum["time"], y=cum[col], name=f"{ENERGY_COMPONENTS[comp]}",
                            mode="lines", line=dict(color=pal.components[comp], width=1.5),
                            customdata=cum["t"],
                            hovertemplate="%{y:,.3f} kg CO₂ (t=%{customdata})")
    fig.add_scatter(x=cum["time"], y=cum["carbon_saved_kg"], name="Total", mode="lines",
                    line=dict(color=pal.ink, width=2.5), customdata=cum["t"],
                    hovertemplate="%{y:,.3f} kg CO₂ (t=%{customdata})")
    last = cum.iloc[-1]
    fig.add_annotation(x=last["time"], y=last["carbon_saved_kg"],
                       text=f"{last['carbon_saved_kg']:,.2f} kg", showarrow=False,
                       xanchor="right", yanchor="bottom", font=dict(color=pal.ink, size=12))
    style(fig, pal, height=340)
    fig.update_yaxes(title_text="Cumulative carbon saved (kg CO₂)", zeroline=True)
    fig.update_xaxes(title_text=TIME_TITLE)
    return fig


def savings_bars(sb: pd.DataFrame, pal: Palette) -> go.Figure:
    """Carbon saved per energy component (kg); positive = optimized emitted less."""
    sb = sb.iloc[::-1]
    fig = go.Figure(go.Bar(
        x=sb["carbon_saved_kg"], y=sb["label"], orientation="h",
        marker=dict(color=[pal.components[c] for c in sb["component"]], line_width=0,
                    cornerradius=4),
        text=[f"{v:,.3f} kg" for v in sb["carbon_saved_kg"]], textposition="outside",
        textfont=dict(color=pal.ink2), cliponaxis=False,
        customdata=np.c_[sb["energy_saved_kWh"], sb["energy_effect_kg"], sb["timing_effect_kg"]],
        hovertemplate=("<b>%{y}</b><br>Carbon saved %{x:,.4f} kg CO₂<br>"
                       "Energy saved %{customdata[0]:,.4f} kWh<br>"
                       "Energy effect %{customdata[1]:,.4f} kg<br>"
                       "Timing effect %{customdata[2]:,.4f} kg<extra></extra>")))
    style(fig, pal, height=110 + 48 * len(sb), legend=False, time_axis=False, hovermode="closest")
    fig.update_xaxes(title_text="Carbon saved vs baseline (kg CO₂)", zeroline=True,
                     zerolinecolor=pal.axis)
    fig.update_yaxes(showgrid=False)
    fig.update_layout(bargap=0.45, margin=dict(r=60))
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


def temperature_heatmap(run: Run, pal: Palette) -> go.Figure:
    """Server x time temperature for each variant on one shared colour scale."""
    sp = run.server_period
    variants = [v for v in run.variants if (sp["variant"] == v).any()]
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


def _threshold_traces(fig: go.Figure, pal: Palette, run: Run, rows: int, cols: int,
                      n_panels: int) -> None:
    dvfs, cap = run.T_dvfs_C, run.thermal_cap_C
    for k in range(n_panels):
        r, c = k // cols + 1, k % cols + 1
        fig.add_hline(y=dvfs, line=dict(color=pal.ink2, width=1, dash="dash"), row=r, col=c)
        fig.add_hline(y=cap, line=dict(color=pal.ink2, width=1, dash="dot"), row=r, col=c)
    # Legend entries for the two limit lines.
    for name, dash in ((f"DVFS {dvfs:g} °C", "dash"), (f"Thermal cap {cap:g} °C", "dot")):
        fig.add_scatter(x=[None], y=[None], mode="lines", name=name, hoverinfo="skip",
                        line=dict(color=pal.ink2, width=1, dash=dash), row=1, col=1)


def server_temperatures(run: Run, pal: Palette, servers: list[int], cols: int = 2) -> go.Figure:
    """Small multiples: one panel per server, baseline vs optimized, with limit lines."""
    sp = run.server_period
    info = run.servers.set_index("s").loc[servers]
    rows = math.ceil(len(servers) / cols)
    cols = min(cols, len(servers))
    fig = make_subplots(rows=rows, cols=cols, shared_xaxes=True, shared_yaxes=True,
                        subplot_titles=info["label"].tolist(),
                        vertical_spacing=0.32 / rows if rows > 1 else 0.05,
                        horizontal_spacing=0.04)
    for k, s in enumerate(servers):
        r, c = k // cols + 1, k % cols + 1
        for v in run.variants:
            d = sp[(sp["variant"] == v) & (sp["s"] == s)]
            if d.empty:
                continue
            fig.add_scatter(
                x=d["time"], y=d["temperature_C"], name=VARIANT_LABELS[v], mode="lines",
                line=_variant_line(pal, v, 1.5), legendgroup=v, showlegend=k == 0,
                customdata=np.c_[d["t"], d["headroom_C"]],
                hovertemplate="%{y:.2f} °C, headroom %{customdata[1]:.2f} °C (t=%{customdata[0]})",
                row=r, col=c)
    _threshold_traces(fig, pal, run, rows, cols, len(servers))
    style(fig, pal, height=110 + 210 * rows, titled=True)
    lo = math.floor(sp["temperature_C"].min() / 5) * 5
    hi = max(sp["temperature_C"].max(), run.thermal_cap_C, run.T_dvfs_C) + 3
    fig.update_yaxes(range=[lo, hi])
    fig.update_xaxes(showticklabels=True)
    for r in range(1, rows + 1):
        fig.update_yaxes(title_text="Temperature (°C)", row=r, col=1)
    for c in range(1, cols + 1):
        fig.update_xaxes(title_text=TIME_TITLE, row=rows, col=c)
    return fig


def min_headroom(run: Run, pal: Palette) -> go.Figure:
    """Smallest headroom across servers per period, with the required H_min."""
    sp = run.server_period
    fig = go.Figure()
    for v in run.variants:
        d = sp[sp["variant"] == v]
        if d.empty:
            continue
        idx = d.groupby("t")["headroom_C"].idxmin()
        m = d.loc[idx].sort_values("t")
        fig.add_scatter(
            x=m["time"], y=m["headroom_C"], name=VARIANT_LABELS[v], mode="lines",
            line=_variant_line(pal, v), customdata=np.c_[m["t"], m["name"]],
            hovertemplate="%{y:.2f} °C on %{customdata[1]} (t=%{customdata[0]})")
    style(fig, pal, height=320)
    if run.H_min_C is not None:
        fig.add_hline(y=run.H_min_C, line=dict(color=pal.ink2, width=1, dash="dot"),
                      annotation=dict(text=f"Required H_min {run.H_min_C:g} °C",
                                      font=dict(color=pal.ink2, size=11)),
                      annotation_position="bottom right")
    lo = min(0.0, sp["headroom_C"].min() - 2) if len(sp) else 0
    fig.update_yaxes(title_text="Min. headroom across servers (°C)",
                     range=[lo, sp["headroom_C"].max() + 2])
    fig.update_xaxes(title_text=TIME_TITLE)
    return fig


# column -> (axis title, hover format, scale, unit); scale converts the stored value.
SERVER_METRICS = {
    "headroom_C": ("Headroom (°C)", ".2f", 1.0, "°C"),
    "utilization": ("CPU utilization (%)", ".1f", 100.0, "%"),
    "P_IT_W": ("IT power (W)", ",.1f", 1.0, "W"),
    "PC_eff_MHz": ("Effective capability (GHz)", ",.2f", 1e-3, "GHz"),
}


def server_metric(run: Run, pal: Palette, servers: list[int], column: str,
                  cols: int = 2) -> go.Figure:
    """Small multiples of one server_period column: one panel per server, baseline vs
    optimized. Headroom carries the H_min line; PC_eff the full-speed N_cores * f_s line."""
    title, fmt, scale, unit = SERVER_METRICS[column]
    sp = run.server_period
    info = run.servers.set_index("s").loc[servers]
    rows = math.ceil(len(servers) / cols)
    cols = min(cols, len(servers))
    fig = make_subplots(rows=rows, cols=cols, shared_xaxes=True, shared_yaxes=True,
                        subplot_titles=info["label"].tolist(),
                        vertical_spacing=0.32 / rows if rows > 1 else 0.05,
                        horizontal_spacing=0.04)
    for k, s in enumerate(servers):
        r, c = k // cols + 1, k % cols + 1
        for v in run.variants:
            d = sp[(sp["variant"] == v) & (sp["s"] == s)]
            if d.empty:
                continue
            fig.add_scatter(
                x=d["time"], y=d[column] * scale, name=VARIANT_LABELS[v], mode="lines",
                line=dict(color=pal.variant(v), width=1.5,
                          shape="hv" if column == "utilization" else "linear"),
                legendgroup=v, showlegend=k == 0, customdata=d["t"],
                hovertemplate=f"%{{y:{fmt}}} {unit} (t=%{{customdata}})", row=r, col=c)
        if column == "PC_eff_MHz":
            full = sp.loc[sp["s"] == s, column].max() * scale
            fig.add_hline(y=full, line=dict(color=pal.ink2, width=1, dash="dot"), row=r, col=c)
    if column == "headroom_C" and run.H_min_C is not None:
        for k in range(len(servers)):
            fig.add_hline(y=run.H_min_C, line=dict(color=pal.ink2, width=1, dash="dot"),
                          row=k // cols + 1, col=k % cols + 1)
        fig.add_scatter(x=[None], y=[None], mode="lines", name=f"Required H_min {run.H_min_C:g} °C",
                        hoverinfo="skip", line=dict(color=pal.ink2, width=1, dash="dot"),
                        row=1, col=1)
    if column == "PC_eff_MHz":
        fig.add_scatter(x=[None], y=[None], mode="lines", name="Full speed (DPF = 1)",
                        hoverinfo="skip", line=dict(color=pal.ink2, width=1, dash="dot"),
                        row=1, col=1)
    style(fig, pal, height=110 + 210 * rows, titled=True)
    vals = sp.loc[sp["s"].isin(servers), column] * scale
    if column == "utilization":
        fig.update_yaxes(range=[0, max(100.0, float(vals.max())) + 3])
    elif column == "headroom_C":
        lo = min(0.0 if run.H_min_C is None else run.H_min_C, float(vals.min()))
        fig.update_yaxes(range=[lo - 2, float(vals.max()) + 2])
    elif column == "PC_eff_MHz":
        fig.update_yaxes(range=[float(vals.min()) * 0.95, float(vals.max()) * 1.03])
    fig.update_xaxes(showticklabels=True)
    for r in range(1, rows + 1):
        fig.update_yaxes(title_text=title, row=r, col=1)
    for c in range(1, cols + 1):
        fig.update_xaxes(title_text=TIME_TITLE, row=rows, col=c)
    return fig


def dpf_lines(run: Run, pal: Palette, servers: list[int], cols: int = 2) -> go.Figure:
    """DPF (1 = full clock speed) per throttled server, baseline vs optimized."""
    sp = run.server_period
    info = run.servers.set_index("s").loc[servers]
    rows = math.ceil(len(servers) / cols)
    cols = min(cols, len(servers))
    fig = make_subplots(rows=rows, cols=cols, shared_xaxes=True, shared_yaxes=True,
                        subplot_titles=info["label"].tolist(),
                        vertical_spacing=0.3 / rows if rows > 1 else 0.05,
                        horizontal_spacing=0.04)
    for k, s in enumerate(servers):
        r, c = k // cols + 1, k % cols + 1
        for v in run.variants:
            d = sp[(sp["variant"] == v) & (sp["s"] == s)]
            if d.empty:
                continue
            fig.add_scatter(
                x=d["time"], y=d["DPF"], name=VARIANT_LABELS[v], mode="lines",
                line=_variant_line(pal, v, 1.5), legendgroup=v, showlegend=k == 0,
                customdata=np.c_[d["t"], d["PC_eff_MHz"], d["temperature_C"]],
                hovertemplate=("DPF %{y:.4f}, %{customdata[1]:,.0f} MHz effective, "
                               "%{customdata[2]:.2f} °C (t=%{customdata[0]})"),
                row=r, col=c)
    style(fig, pal, height=110 + 200 * rows, titled=True)
    lo = sp.loc[sp["s"].isin(servers), "DPF"].min()
    fig.update_yaxes(range=[max(0.0, lo - 0.03), 1.02])
    fig.update_xaxes(showticklabels=True)
    for r in range(1, rows + 1):
        fig.update_yaxes(title_text="DPF (1 = full speed, –)", row=r, col=1)
    for c in range(1, cols + 1):
        fig.update_xaxes(title_text=TIME_TITLE, row=rows, col=c)
    return fig


# ---------------------------------------------------------------------------
# Cooling
# ---------------------------------------------------------------------------

ZONE_METRICS = {
    "supply_temp_C": "Supply air (°C)",
    "Q_crac_kW": "Q_crac (kW)",
    "P_crac_kW": "P_crac (kW)",
    "COP": "COP (–)",
    "P_fan_kW": "Fan power (kW)",
    "airflow": "Airflow (m³/s)",
}
ZONE_FORMATS = {"supply_temp_C": ".2f", "Q_crac_kW": ",.4f", "P_crac_kW": ",.4f",
                "COP": ".4f", "P_fan_kW": ",.4f", "airflow": ",.4f"}


def zone_grid(run: Run, pal: Palette, metrics: list[str]) -> go.Figure:
    """Rows = metrics, columns = zones; baseline vs optimized lines.
    The supply panel shades the allowed supply band from compliance_zones.csv."""
    zp = run.zone_period
    zones = sorted(zp["z"].unique())
    fig = make_subplots(rows=len(metrics), cols=len(zones), shared_xaxes=True,
                        subplot_titles=[f"Zone {z}" for z in zones],
                        vertical_spacing=0.05, horizontal_spacing=0.06)
    cz = run.compliance_zones
    for c, z in enumerate(zones, start=1):
        for r, m in enumerate(metrics, start=1):
            for v in run.variants:
                d = zp[(zp["variant"] == v) & (zp["z"] == z)]
                if d.empty:
                    continue
                fig.add_scatter(
                    x=d["time"], y=d[m], name=VARIANT_LABELS[v], mode="lines",
                    line=dict(color=pal.variant(v), width=1.75, shape="hv"),
                    legendgroup=v, showlegend=(r == 1 and c == 1), customdata=d["t"],
                    hovertemplate=f"%{{y:{ZONE_FORMATS[m]}}} (t=%{{customdata}})",
                    row=r, col=c)
            if m == "supply_temp_C" and not cz.empty:
                lim = cz[(cz["z"] == z)].iloc[0]
                fig.add_hrect(y0=lim["supply_allowed_min_C"], y1=lim["supply_allowed_max_C"],
                              fillcolor=rgba(pal.muted, 0.12), line_width=0, layer="below",
                              row=r, col=c)
                fig.add_annotation(
                    text=f"allowed {lim['supply_allowed_min_C']:g}–"
                         f"{lim['supply_allowed_max_C']:g} °C",
                    xref="x domain", x=0.01, y=lim["supply_allowed_max_C"], xanchor="left",
                    yanchor="top", showarrow=False, font=dict(color=pal.ink2, size=11),
                    row=r, col=c)
    style(fig, pal, height=100 + 190 * len(metrics), titled=True)
    for r, m in enumerate(metrics, start=1):
        fig.update_yaxes(title_text=ZONE_METRICS[m], row=r, col=1)
    if "supply_temp_C" in metrics and not cz.empty:
        r = metrics.index("supply_temp_C") + 1
        lo = min(cz["supply_allowed_min_C"].min(), zp["supply_temp_C"].min()) - 1
        hi = max(cz["supply_allowed_max_C"].max(), zp["supply_temp_C"].max()) + 1
        fig.update_yaxes(range=[lo, hi], row=r)
    for c in range(1, len(zones) + 1):
        fig.update_xaxes(title_text=TIME_TITLE, row=len(metrics), col=c)
    return fig


def cold_plate_servers(run: Run) -> list[int]:
    """Servers with cold-plate settings in any variant, in display order."""
    sp = run.server_period
    if sp.empty or "cp_flow_Lmin" not in sp:
        return []
    has = set(sp.loc[pd.to_numeric(sp["cp_flow_Lmin"], errors="coerce").notna(), "s"])
    return [s for s in run.servers["s"] if s in has]


def cooling_decisions(run: Run, pal: Palette, servers: list[int]) -> go.Figure:
    """Per cold-plate server: CRAC supply air of its zone and coolant temperature in one
    panel (both °C), coolant flow in the panel below (L/min; CRAC airflow is not modelled)."""
    sp, zp = run.server_period, run.zone_period
    info = run.servers.set_index("s").loc[servers]
    n = len(servers)
    fig = make_subplots(rows=2, cols=n, shared_xaxes=True, shared_yaxes="rows",
                        subplot_titles=info["label"].tolist(), vertical_spacing=0.1,
                        horizontal_spacing=0.04, row_heights=[0.6, 0.4])
    for c, s in enumerate(servers, start=1):
        zone = int(info.loc[s, "zone"])
        for v in run.variants:
            d = sp[(sp["variant"] == v) & (sp["s"] == s)]
            z = zp[(zp["variant"] == v) & (zp["z"] == zone)] if not zp.empty else zp
            if d.empty:
                continue
            first = c == 1
            fig.add_scatter(
                x=d["time"], y=d["cp_coolant_C"], name=f"{VARIANT_LABELS[v]} · coolant",
                mode="lines", line=dict(color=pal.variant(v), width=1.75, shape="hv"),
                legendgroup=f"{v}cool", showlegend=first, customdata=d["t"],
                hovertemplate="coolant %{y:.2f} °C (t=%{customdata})", row=1, col=c)
            if not z.empty:
                fig.add_scatter(
                    x=z["time"], y=z["supply_temp_C"], name=f"{VARIANT_LABELS[v]} · CRAC supply air",
                    mode="lines", line=dict(color=pal.variant(v), width=1.25, dash="dot",
                                            shape="hv"),
                    legendgroup=f"{v}air", showlegend=first, customdata=z["t"],
                    hovertemplate=f"zone {zone} supply %{{y:.0f}} °C (t=%{{customdata}})",
                    row=1, col=c)
            fig.add_scatter(
                x=d["time"], y=d["cp_flow_Lmin"], name=f"{VARIANT_LABELS[v]} · coolant flow",
                mode="lines", line=dict(color=pal.variant(v), width=1.75, shape="hv"),
                legendgroup=f"{v}cool", showlegend=False, customdata=d["t"],
                hovertemplate="flow %{y:.3f} L/min (t=%{customdata})", row=2, col=c)
    style(fig, pal, height=520, titled=True)
    fig.update_yaxes(title_text="Temperature (°C)", row=1, col=1)
    fig.update_yaxes(title_text="Coolant flow (L/min)", row=2, col=1, rangemode="tozero")
    for c in range(1, n + 1):
        fig.update_xaxes(title_text=TIME_TITLE, row=2, col=c)
    return fig


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


def compare_saved(df: pd.DataFrame, pal: Palette) -> go.Figure:
    """% carbon saved per run (single series); labels sit right of the bar or of zero."""
    df = df.iloc[::-1]
    pct = df["carbon_saved_pct"]
    fig = go.Figure(go.Bar(
        y=df["run"], x=pct.fillna(0), orientation="h",
        marker=dict(color=pal.optimized, cornerradius=4, line_width=0),
        customdata=np.c_[df["carbon_saved_kg"].fillna(np.nan)],
        hovertemplate="%{x:.3f}% (%{customdata[0]:,.3f} kg CO₂)<extra></extra>"))
    for run, p in zip(df["run"], pct):
        text = ("no optimized schedule" if pd.isna(p) else
                f"{p:.2f}% saved" if p >= 0 else f"{-p:.2f}% more carbon")
        fig.add_annotation(x=0 if pd.isna(p) else max(p, 0), y=run, text=text, xanchor="left",
                           xshift=6, showarrow=False, font=dict(color=pal.ink2, size=12))
    style(fig, pal, height=120 + 44 * len(df), time_axis=False, legend=False,
          hovermode="closest")
    fig.update_layout(bargap=0.4, margin=dict(r=160))
    fig.update_xaxes(title_text="Carbon saved vs baseline (%)", zeroline=True,
                     zerolinecolor=pal.axis, zerolinewidth=1)
    fig.update_yaxes(showgrid=False)
    return fig
