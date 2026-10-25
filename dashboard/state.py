"""Streamlit glue: cached loaders, the server-count, load-level, run and kept pickers, the
active palette."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd
import streamlit as st

from dashboard import data
from scheduler import experiments as ex
from dashboard.theme import PLOTLY_CONFIG, Palette, palette

# The server count and load level picked on any page. Streamlit drops a widget's state when
# its page is left, so the choices live here and every page's pickers start from them (and
# from ?config= and ?level=). CONFIG_KEY holds the fleet: servers10, servers6 or servers2.
CONFIG_KEY = "config"
LEVEL_KEY = "level"
ACROSS = "across"
ACROSS_FLEETS_LABEL = "Across server counts"
ACROSS_LEVELS_LABEL = "Across load levels"


def _mtime(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


@st.cache_data(show_spinner=False)
def _discover(results_dir: str, stamp: float) -> list[data.RunRef]:
    return data.discover_runs(results_dir)


def discover_runs() -> list[data.RunRef]:
    """Every run under results/."""
    root = data.RESULTS_DIR
    # A new run folder changes the scenario directory's mtime, which busts the cache.
    stamp = sum(_mtime(p) for p in [root, *root.glob("*")]) if root.is_dir() else 0.0
    return _discover(str(root), stamp)


@st.cache_data(show_spinner="Loading run…")
def _load_run(run_dir: str, scenarios_dir: str, stamp: float) -> data.Run:
    return data.load_run(run_dir, scenarios_dir)


def load_run(ref: data.RunRef) -> data.Run:
    return _load_run(str(ref.path), str(data.SCENARIOS_DIR), _mtime(ref.path / "summary.json"))


def _summaries_stamp(refs: list[data.RunRef]) -> float:
    return sum(_mtime(r.path / "summary.json") for r in refs)


def _cache_args(refs: list[data.RunRef]):
    return tuple(str(r.path) for r in refs), tuple(refs), _summaries_stamp(refs)


@st.cache_data(show_spinner=False)
def _run_infos(keys: tuple[str, ...], _refs: tuple[data.RunRef, ...],
               stamp: float) -> dict[str, data.RunInfo]:
    return data.run_infos(list(_refs))


def run_infos() -> dict[str, data.RunInfo]:
    """Run key -> its configuration and tests, for every run."""
    return _run_infos(*_cache_args(discover_runs()))


@st.cache_data(show_spinner="Reading the Chapter 6 runs…")
def _chapter6(keys: tuple[str, ...], _refs: tuple[data.RunRef, ...], stamp: float):
    refs = list(_refs)
    infos = data.run_infos(refs)
    return data.chapter6_table(refs, infos), data.catalogue(refs, infos)


def chapter6():
    """The Chapter 6 table (every configuration) and the catalogue: (configuration, test)
    -> (run used, every matching run)."""
    return _chapter6(*_cache_args(discover_runs()))


def config_runs() -> dict[str, list[data.RunRef]]:
    """Configuration key (or data.OTHER) -> its runs, in run-picker order."""
    refs = discover_runs()
    return data.config_runs(refs, run_infos())


@dataclass(frozen=True)
class Scope:
    """What a page shows: a fleet key and a load level key, one of which may be ACROSS."""
    fleet: str
    level: str

    @property
    def config(self) -> ex.Configuration | None:
        """The configuration, or None when the page compares across one of the two."""
        return None if ACROSS in (self.fleet, self.level) else ex.configuration(self.fleet, self.level)


def _picker(name: str, label: str, keys: list[str], page: str, default: str,
            format_func) -> str:
    """A segmented control kept in st.session_state[name] and ?<name>=. A page that does not
    offer the kept choice (*Across ...*) shows ``default`` and leaves the choice for the next
    page that offers it."""
    current = st.session_state.get(name)
    if current not in keys:
        query = st.query_params.get(name)
        current = query if query in keys else default
        if st.session_state.get(name) is None:
            st.session_state[name] = current
    widget = f"{name}-{page}"
    st.session_state[widget] = current
    st.segmented_control(label, keys, key=widget, required=True, format_func=format_func,
                         on_change=_keep, args=(name, widget))
    st.query_params[name] = current
    return current


def pick_scope(page: str, across: bool = False) -> Scope:
    """The server-count picker (10 / 6 / 2 servers) and the load-level picker (light / normal /
    heavy day) of a page. With ``across``, one of them may be set to *Across ...*, never
    both. Every page starts from the last choice."""
    fleets, levels = list(ex.FLEETS), [lv.key for lv in ex.LEVELS]
    with st.container(horizontal=True, gap="large"):
        fleet = _picker(CONFIG_KEY, "Servers",
                        fleets + ([ACROSS] if across and st.session_state.get(LEVEL_KEY) != ACROSS
                                  else []),
                        page, first_fleet_with_runs(),
                        lambda k: ACROSS_FLEETS_LABEL if k == ACROSS else ex.FLEETS[k].size_label)
        level = _picker(LEVEL_KEY, "Load level",
                        levels + ([ACROSS] if across and fleet != ACROSS else []),
                        page, ex.NORMAL,
                        lambda k: ACROSS_LEVELS_LABEL if k == ACROSS else ex.LEVEL_BY_KEY[k].label)
    return Scope(fleet, level)


def first_fleet_with_runs() -> str:
    """The fleet a first visit opens on: the first (10, 6, 2 servers) with a run under
    results/, so the site never opens on an empty page; the first fleet when none has."""
    with_runs = {ex.CONFIGURATION_BY_KEY[k].fleet_key
                 for k in data.config_runs(discover_runs()) if k in ex.CONFIGURATION_BY_KEY}
    return next((f for f in ex.FLEETS if f in with_runs), next(iter(ex.FLEETS)))


def pick_config(page: str) -> ex.Configuration:
    """The configuration (a fleet on a load level) picked at the top of a page."""
    return pick_scope(page).config


def _keep(name: str, widget: str) -> None:
    st.session_state[name] = st.session_state[widget]


def pick_kept(name: str, label: str, options: list[str], page: str,
              format_func=str) -> str:
    """A segmented control whose choice is kept across pages and reruns, in
    st.session_state[name] and ?<name>=, like the configuration picker. When the kept choice
    is not among ``options`` (another section's test), the first option is shown and the
    kept choice is left for the next page that offers it."""
    current = st.session_state.get(name)
    if current not in options:
        query = st.query_params.get(name)
        current = query if query in options else options[0]
    widget = f"{name}-{page}"
    st.session_state[widget] = current
    st.segmented_control(label, options, key=widget, required=True, format_func=format_func,
                         on_change=_keep, args=(name, widget))
    st.query_params[name] = current
    return current


def run_label(ref: data.RunRef, used: set[str]) -> str:
    """'6.1 · Test 1 · …' for the run a test uses, else its folder name with what it is."""
    info = run_infos().get(ref.key)
    if info and info.tests:
        title = data.run_title(info, ref)
        return title if ref.key in used else f"{title} · older solve ({ref.name})"
    return f"{ref.name} (validation)" if ref.name.startswith("v_") else ref.name


def pick_run(config: ex.Configuration, page: str) -> data.RunRef | None:
    """A run of the configuration: the run of each test in test order, then the others."""
    refs = config_runs().get(config.key, [])
    if not refs:
        return None
    used = {ref.key for ref, _ in chapter6()[1].values() if ref is not None}
    by_key = {r.key: r for r in refs}
    key = st.selectbox("Run", list(by_key), key=f"run-{page}-{config.key}",
                       format_func=lambda k: run_label(by_key[k], used))
    return by_key[key]


def pal() -> Palette:
    theme = getattr(st.context, "theme", None)
    return palette(getattr(theme, "type", None))


def chart(fig, key: str | None = None) -> None:
    st.plotly_chart(fig, config=PLOTLY_CONFIG, key=key, theme=None)


def fmt_num(v, digits: int = 2, unit: str = "") -> str:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return "–"
    if isinstance(v, (int,)) or float(v).is_integer() and digits == 0:
        s = f"{int(round(float(v))):,}"
    else:
        s = f"{float(v):,.{digits}f}"
    return f"{s} {unit}".strip()
