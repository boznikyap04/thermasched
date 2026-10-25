"""Colours and shared Plotly styling.

Categorical colours come from a validated colour-blind-safe palette with a light and a
dark step per hue. Baseline and optimized keep the same hue everywhere (orange and blue).
Other dimensions (energy component, workload type) use hues distinct from those two.
Charts with one line per server or zone use ``series``; there a schedule is told apart by
the dash (baseline dashed), not the hue.
Thresholds are drawn in neutral ink with a text label, never in a series colour.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import plotly.graph_objects as go


@dataclass(frozen=True)
class Palette:
    mode: str
    baseline: str
    optimized: str
    components: dict[str, str]
    types: dict[str, str]
    ink: str
    ink2: str
    muted: str
    grid: str
    axis: str
    surface: str
    seq: tuple[str, ...]           # sequential ramp, low -> high (low recedes into surface)
    series: tuple[str, ...] = ()   # one hue per server or zone, in display order
    status: dict[str, str] = field(default_factory=lambda: dict(STATUS))

    def variant(self, v: str) -> str:
        return self.baseline if v == "baseline" else self.optimized

    def nth(self, k: int) -> str:
        """The k-th series colour (servers, zones), cycling past the end."""
        return self.series[k % len(self.series)]


STATUS = {"good": "#0ca30c", "warning": "#fab219", "serious": "#ec835a", "critical": "#d03b3b"}

_BLUE_RAMP = ("#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95", "#0d366b")

LIGHT = Palette(
    mode="light", baseline="#eb6834", optimized="#2a78d6",
    components={"E_IT_kWh": "#1baf7a", "E_crac_kWh": "#6250d6",
                "E_cp_kWh": "#e87ba4", "E_fan_kWh": "#eda100"},
    types={"time_sensitive": "#e87ba4", "delay_tolerant": "#008300"},
    ink="#0b0b0b", ink2="#52514e", muted="#898781", grid="#e1e0d9", axis="#c3c2b7",
    surface="#fcfcfb", seq=_BLUE_RAMP,
    series=("#2a78d6", "#eb6834", "#1baf7a", "#6250d6", "#e87ba4", "#c98500", "#0f8f8f",
            "#8c564b", "#7a7974", "#b8336a"),
)
DARK = Palette(
    mode="dark", baseline="#d95926", optimized="#3987e5",
    components={"E_IT_kWh": "#199e70", "E_crac_kWh": "#9085e9",
                "E_cp_kWh": "#d55181", "E_fan_kWh": "#c98500"},
    types={"time_sensitive": "#d55181", "delay_tolerant": "#008300"},
    ink="#f0efec", ink2="#c3c2b7", muted="#898781", grid="#2c2c2a", axis="#383835",
    surface="#1a1a19", seq=tuple(reversed(_BLUE_RAMP)),
    series=("#3987e5", "#d95926", "#199e70", "#9085e9", "#d55181", "#eda100", "#2bb5b5",
            "#b07a6a", "#a8a7a1", "#e0628f"),
)


def palette(mode: str | None) -> Palette:
    return DARK if mode == "dark" else LIGHT


def rgba(hex_color: str, alpha: float) -> str:
    h = hex_color.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    return f"rgba({r},{g},{b},{alpha})"


FONT = 'system-ui, -apple-system, "Segoe UI", sans-serif'
TIME_FORMAT = "%H:%M"


def style(fig: go.Figure, pal: Palette, *, height: int = 360, legend: bool = True,
          time_axis: bool = True, hovermode: str | bool = "x unified",
          titled: bool = False) -> go.Figure:
    """Recessive grid and axes, transparent background, legend above the plot.

    ``titled``: the figure has subplot titles, so the legend sits one row higher.
    Charts are drawn with Streamlit's theme off (it replaces colour scales), so every
    colour here comes from the palette for the active light or dark mode.
    """
    lift = 30 if titled and legend else 0
    top = (36 if legend else 16) + lift
    plot_h = max(height - top - 60, 100)
    fig.update_layout(
        template="none", height=height, font=dict(family=FONT, color=pal.ink2, size=13),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        margin=dict(l=8, r=8, t=top, b=8),
        hovermode=hovermode, showlegend=legend,
        legend=dict(orientation="h", yanchor="bottom", y=1.0 + lift / plot_h, xanchor="left",
                    x=0, title_text="", font=dict(color=pal.ink2), bgcolor="rgba(0,0,0,0)"),
        hoverlabel=dict(font=dict(family=FONT, color=pal.ink), bgcolor=pal.surface,
                        bordercolor=pal.axis),
    )
    fig.update_xaxes(gridcolor=pal.grid, linecolor=pal.axis, zeroline=False, showgrid=False,
                     tickfont=dict(color=pal.muted), title_font=dict(color=pal.ink2),
                     showline=True, ticks="outside", tickcolor=pal.axis, ticklen=4,
                     automargin=True)
    fig.update_yaxes(gridcolor=pal.grid, linecolor=pal.axis, zerolinecolor=pal.axis,
                     showgrid=True, zeroline=False, tickfont=dict(color=pal.muted),
                     title_font=dict(color=pal.ink2), automargin=True)
    if time_axis:
        fig.update_xaxes(tickformat=TIME_FORMAT, hoverformat=TIME_FORMAT,
                         showspikes=True, spikemode="across", spikethickness=1,
                         spikecolor=pal.muted, spikedash="solid")
    for ann in fig.layout.annotations or ():
        ann.font = dict(family=FONT, color=pal.ink2, size=13)
    return fig


def threshold(fig: go.Figure, pal: Palette, y: float, label: str, *, dash: str = "dash",
              row: int | str | None = None, col: int | str | None = None) -> None:
    """A horizontal limit line in neutral ink with its label at the right end."""
    kw = {} if row is None else dict(row=row, col=col)
    fig.add_hline(y=y, line=dict(color=pal.ink2, width=1, dash=dash),
                  annotation=dict(text=label, font=dict(color=pal.ink2, size=11),
                                  bgcolor=rgba(pal.surface, 0.7)),
                  annotation_position="top right", **kw)


PLOTLY_CONFIG = {"displaylogo": False, "modeBarButtonsToRemove": ["lasso2d", "select2d"]}
