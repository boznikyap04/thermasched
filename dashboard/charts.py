"""Plotly figure builders for the Chapter 6 pages (and the validation tables); no Streamlit
calls here."""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from dashboard.theme import Palette, style

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
