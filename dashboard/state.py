"""Streamlit glue: cached loaders, the configuration and run pickers, the active palette."""

from __future__ import annotations

from pathlib import Path

import streamlit as st

from dashboard import data
from scheduler import experiments as ex
from dashboard.theme import PLOTLY_CONFIG, Palette, palette

# The configuration picked on any page. Streamlit drops a widget's state when its page is
# left, so the choice lives here and every page's picker starts from it (and from ?config=).
CONFIG_KEY = "config"
ACROSS = "across"
ACROSS_LABEL = "Across configurations"


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


def _keep_config(widget: str) -> None:
    st.session_state[CONFIG_KEY] = st.session_state[widget]


def pick_config(page: str, across: bool = False) -> ex.Configuration | None:
    """The 10 / 6 / 2 servers picker of a page; with ``across``, also *Across
    configurations* (returned as None). Every page starts from the last choice."""
    keys = [c.key for c in ex.CONFIGURATIONS] + ([ACROSS] if across else [])
    current = st.session_state.get(CONFIG_KEY)
    if current not in keys:
        query = st.query_params.get("config")
        current = query if query in keys else keys[0]
        # A page without *Across configurations* leaves that choice for the next page.
        if st.session_state.get(CONFIG_KEY) is None:
            st.session_state[CONFIG_KEY] = current
    widget = f"config-{page}"
    st.session_state[widget] = current
    st.segmented_control("Configuration", keys, key=widget, required=True,
                         format_func=lambda k: ACROSS_LABEL if k == ACROSS
                         else ex.CONFIGURATION_BY_KEY[k].label,
                         on_change=_keep_config, args=(widget,))
    st.query_params["config"] = current
    return ex.CONFIGURATION_BY_KEY.get(current)


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
