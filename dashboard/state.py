"""Streamlit glue: cached loaders, the selected run, the active palette, small widgets."""

from __future__ import annotations

import shutil
import tempfile
import time
import uuid
from pathlib import Path

import pandas as pd
import streamlit as st

from dashboard import data, uploads
from dashboard.theme import PLOTLY_CONFIG, Palette, palette

RUN_KEY = "run_key"
PENDING_RUN = "pending_run"   # run to select on the next rerun (set before the sidebar draws)
OVERVIEW_PAGE = None   # set by app.py each run, for st.switch_page

# Uploaded runs live in a temporary folder per browser session, never in results/.
UPLOAD_ROOT = Path(tempfile.gettempdir()) / "thermasched-uploads"
UPLOAD_MAX_AGE_S = 3 * 24 * 3600


def _mtime(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


@st.cache_data(show_spinner=False)
def _discover(results_dir: str, stamp: float) -> list[data.RunRef]:
    return data.discover_runs(results_dir)


def _discover_in(root: Path) -> list[data.RunRef]:
    # A new run folder changes the scenario directory's mtime, which busts the cache.
    stamp = sum(_mtime(p) for p in [root, *root.glob("*")]) if root.is_dir() else 0.0
    return _discover(str(root), stamp)


def upload_dir(create: bool = False) -> Path | None:
    """This session's upload folder (``results/`` and ``scenarios/`` inside), or None."""
    path = st.session_state.get("upload_dir")
    if path is None and create:
        _prune_old_uploads()
        path = UPLOAD_ROOT / uuid.uuid4().hex
        (path / "results").mkdir(parents=True)
        (path / "scenarios").mkdir()
        st.session_state["upload_dir"] = path
    return path


def _prune_old_uploads() -> None:
    if not UPLOAD_ROOT.is_dir():
        return
    for d in UPLOAD_ROOT.iterdir():
        if d.is_dir() and time.time() - _mtime(d) > UPLOAD_MAX_AGE_S:
            shutil.rmtree(d, ignore_errors=True)


def disk_runs() -> list[data.RunRef]:
    return _discover_in(data.RESULTS_DIR)


def uploaded_runs() -> list[data.RunRef]:
    root = upload_dir()
    return _discover_in(root / "results") if root is not None else []


def discover_runs() -> list[data.RunRef]:
    """Runs under results/ plus the runs uploaded in this session."""
    return sorted(disk_runs() + uploaded_runs(), key=data.run_order)


def is_uploaded(ref: data.RunRef) -> bool:
    root = upload_dir()
    return root is not None and ref.path.is_relative_to(root)


def scenarios_dir_for(ref: data.RunRef) -> Path:
    """Uploaded scenario files win for an uploaded run; otherwise scenarios/."""
    root = upload_dir()
    if root is not None and is_uploaded(ref) and (root / "scenarios" / ref.scenario).is_dir():
        return root / "scenarios"
    return data.SCENARIOS_DIR


def import_upload(file) -> uploads.ImportResult:
    root = upload_dir(create=True)
    return uploads.import_zip(
        file, root / "results", root / "scenarios",
        reserved={r.key for r in disk_runs()},
        fallback_name=Path(getattr(file, "name", "")).stem or "uploaded_run",
        fallback_scenarios_dir=data.SCENARIOS_DIR)


def remove_upload(ref: data.RunRef | None = None) -> None:
    """Delete one uploaded run, or every upload of this session."""
    root = upload_dir()
    if root is None:
        return
    if ref is None:
        shutil.rmtree(root, ignore_errors=True)
        del st.session_state["upload_dir"]
        return
    if is_uploaded(ref):
        shutil.rmtree(ref.path, ignore_errors=True)
        scenario_dir = ref.path.parent
        if scenario_dir.is_dir() and not any(scenario_dir.iterdir()):
            scenario_dir.rmdir()


def run_zip(refs: list[data.RunRef]) -> bytes:
    return uploads.runs_zip([(r, scenarios_dir_for(r)) for r in refs])


@st.cache_data(show_spinner="Loading run…")
def _load_run(run_dir: str, scenarios_dir: str, stamp: float) -> data.Run:
    return data.load_run(run_dir, scenarios_dir)


def load_run(ref: data.RunRef) -> data.Run:
    return _load_run(str(ref.path), str(scenarios_dir_for(ref)),
                     _mtime(ref.path / "summary.json"))


@st.cache_data(show_spinner=False)
def compare_runs(keys: tuple[str, ...], _refs: tuple[data.RunRef, ...], stamp: float):
    return data.compare_runs(list(_refs))


def runs_frame(refs: list[data.RunRef]) -> pd.DataFrame:
    stamp = sum(_mtime(r.path / "summary.json") for r in refs)
    # Paths, not keys: two sessions can upload different runs under the same key.
    return compare_runs(tuple(str(r.path) for r in refs), tuple(refs), stamp)


def selected_ref() -> data.RunRef | None:
    runs = {r.key: r for r in discover_runs()}
    return runs.get(st.session_state.get(RUN_KEY))


def current_run() -> data.Run | None:
    """The run picked in the sidebar, or a friendly stop when none can be loaded."""
    ref = selected_ref()
    if ref is None:
        st.info("Pick a run in the sidebar.")
        st.stop()
    try:
        return load_run(ref)
    except Exception as e:  # noqa: BLE001 - shown to the user, the app keeps running
        st.error(f"Could not load **{ref.key}**: {e}")
        st.stop()


def pal() -> Palette:
    theme = getattr(st.context, "theme", None)
    return palette(getattr(theme, "type", None))


def chart(fig, key: str | None = None) -> None:
    st.plotly_chart(fig, config=PLOTLY_CONFIG, key=key, theme=None)


def page_header(title: str, run: data.Run, caption: str | None = None) -> None:
    st.title(title)
    st.caption(f"`{run.ref.scenario}` / `{run.ref.name}`" + (f" · {caption}" if caption else ""))


def no_optimized_note(run: data.Run) -> None:
    status = run.solver.get("status", "unknown")
    st.warning(f"This run has no optimized schedule (solver status **{status}**), so only the "
               "baseline is shown. See *Overview* for the infeasibility diagnosis.", icon="⚠️")


def model_note(run: data.Run) -> None:
    note = run.summary.get("model_note")
    if note:
        st.caption(f"ℹ️ Model note: {note}")


def fmt_num(v, digits: int = 2, unit: str = "") -> str:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return "–"
    if isinstance(v, (int,)) or float(v).is_integer() and digits == 0:
        s = f"{int(round(float(v))):,}"
    else:
        s = f"{float(v):,.{digits}f}"
    return f"{s} {unit}".strip()
