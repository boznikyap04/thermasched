"""Zip import/export of run folders, so results can be shared without touching results/.

A shared zip mirrors ``results/``: ``<scenario>/<run>/summary.json`` plus the run's CSVs,
and optionally the scenario's ``servers.csv`` / ``carbon.csv`` next to the run folders
(``<scenario>/servers.csv``). Import is forgiving about the layout: any folder with a
``summary.json`` is a run, wherever it sits in the zip (zipping a single run folder, a
scenario folder or the whole ``results/`` folder all work).

There is no Streamlit here so the import can be tested directly; the upload page keeps
imported runs in a per-session folder (see ``dashboard/views/upload.py``).
"""

from __future__ import annotations

import io
import json
import re
import shutil
import zipfile
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from dashboard.data import RunRef

# The only scenario inputs the dashboard reads (server names and the clock).
SCENARIO_FILES = ("servers.csv", "carbon.csv")
UPLOADED_SUFFIX = " (uploaded)"

# Guards against a zip that expands far beyond what a run folder needs.
MAX_MEMBERS = 20_000
MAX_UNCOMPRESSED_BYTES = 2 * 1024 ** 3


@dataclass
class ImportResult:
    runs: list[RunRef] = field(default_factory=list)
    scenarios: list[str] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)


def _safe_name(name: str, fallback: str) -> str:
    """A single folder name: no separators, no leading dot, nothing empty."""
    name = re.sub(r"[\\/:\x00]", "_", str(name)).strip().lstrip(".").strip()
    return name or fallback


def _members(zf: zipfile.ZipFile) -> list[tuple[PurePosixPath, zipfile.ZipInfo]]:
    """Regular files with a safe relative path; macOS/Windows clutter is skipped."""
    out = []
    for info in zf.infolist():
        if info.is_dir():
            continue
        p = PurePosixPath(info.filename.replace("\\", "/"))
        if p.is_absolute() or ".." in p.parts or not p.parts:
            continue
        if p.parts[0] == "__MACOSX" or any(part.startswith(".") for part in p.parts):
            continue
        if p.name in ("Thumbs.db", "desktop.ini"):
            continue
        out.append((p, info))
    return out


def _owner(path: PurePosixPath, roots: list[PurePosixPath]) -> PurePosixPath | None:
    """The deepest run root that contains ``path``."""
    best = None
    for r in roots:
        if not r.parts or path.is_relative_to(r):
            if best is None or len(r.parts) > len(best.parts):
                best = r
    return best


def import_zip(source, results_dir: str | Path, scenarios_dir: str | Path, *,
               reserved: set[str] = frozenset(), fallback_name: str = "uploaded_run",
               fallback_scenarios_dir: str | Path | None = None) -> ImportResult:
    """Unpack every run in the zip into ``results_dir/<scenario>/<run>/``.

    ``reserved`` holds run keys that must not be replaced (runs already on disk); an
    upload with such a key is renamed ``<run> (uploaded)``. Any other run with the same
    key is replaced, so uploading a newer zip of a run updates it.

    Scenario files found in the zip go to ``scenarios_dir/<scenario>/``; files missing
    there are filled in from ``fallback_scenarios_dir`` when it has them.
    """
    results_dir, scenarios_dir = Path(results_dir), Path(scenarios_dir)
    result = ImportResult()
    try:
        zf = zipfile.ZipFile(source)
    except zipfile.BadZipFile:
        result.problems.append("This file is not a valid .zip archive.")
        return result

    with zf:
        members = _members(zf)
        if len(members) > MAX_MEMBERS or \
                sum(i.file_size for _, i in members) > MAX_UNCOMPRESSED_BYTES:
            result.problems.append("The zip is too large to be a set of run folders.")
            return result

        summaries = {p.parent: info for p, info in members if p.name == "summary.json"}
        roots = sorted(summaries, key=lambda r: len(r.parts))
        if not roots:
            result.problems.append(
                "No `summary.json` found. Zip the run folder itself (the folder that "
                "contains `summary.json`, `baseline/` and `optimized/`).")
            return result

        by_root: dict[PurePosixPath, list[tuple[PurePosixPath, zipfile.ZipInfo]]] = {}
        loose = []
        for p, info in members:
            owner = _owner(p, roots)
            if owner is None:
                loose.append((p, info))
            else:
                by_root.setdefault(owner, []).append((p, info))

        written: set[str] = set()
        run_scenarios: set[str] = set()
        for root in roots:
            try:
                summary = json.loads(zf.read(summaries[root]))
            except (KeyError, ValueError, UnicodeDecodeError):
                result.problems.append(f"`{root / 'summary.json'}` could not be read; "
                                       "that run was skipped.")
                continue
            sc = summary.get("scenario") if isinstance(summary, dict) else None
            sc_name = sc.get("name") if isinstance(sc, dict) else None
            parent = root.parent.name if len(root.parts) > 1 else ""
            scenario = _safe_name(sc_name or parent, "uploaded")
            name = _safe_name(root.name if root.parts else "", fallback_name)

            if f"{scenario}/{name}" in reserved:
                name += UPLOADED_SUFFIX
            base, n = name, 2
            while f"{scenario}/{name}" in written:      # two runs with one name in a zip
                name, n = f"{base} {n}", n + 1
            key = f"{scenario}/{name}"
            written.add(key)
            run_scenarios.add(scenario)

            dest = results_dir / scenario / name
            if dest.exists():
                shutil.rmtree(dest)
            for p, info in by_root[root]:
                _extract(zf, info, dest / (p.relative_to(root) if root.parts else p))
            result.runs.append(RunRef(scenario, name, dest))

        # Scenario inputs: servers.csv / carbon.csv outside the run folders.
        for p, info in loose:
            if p.name not in SCENARIO_FILES:
                continue
            folder = p.parent.name if len(p.parts) > 1 else ""
            if not folder and len(run_scenarios) == 1:
                folder = next(iter(run_scenarios))
            if not folder:
                continue
            scenario = _safe_name(folder, "uploaded")
            _extract(zf, info, scenarios_dir / scenario / p.name)
            if scenario not in result.scenarios:
                result.scenarios.append(scenario)

    if fallback_scenarios_dir is not None:
        for scenario in result.scenarios:
            for fname in SCENARIO_FILES:
                target = scenarios_dir / scenario / fname
                src = Path(fallback_scenarios_dir) / scenario / fname
                if not target.exists() and src.is_file():
                    shutil.copyfile(src, target)
    return result


def _extract(zf: zipfile.ZipFile, info: zipfile.ZipInfo, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    with zf.open(info) as src, open(target, "wb") as dst:
        shutil.copyfileobj(src, dst)


def runs_zip(runs: list[tuple[RunRef, Path]]) -> bytes:
    """Zip of ``(run, scenarios_dir)`` pairs laid out as ``<scenario>/<run>/...``.

    The scenario's servers.csv and carbon.csv are added as ``<scenario>/<file>`` so the
    zip shows server names and clock times on a machine without that scenario.
    """
    buf = io.BytesIO()
    added: set[str] = set()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for ref, scenarios_dir in runs:
            for f in sorted(ref.path.rglob("*")):
                if f.is_file() and not f.name.startswith("."):
                    rel = f.relative_to(ref.path).as_posix()
                    zf.write(f, f"{ref.scenario}/{ref.name}/{rel}")
            for fname in SCENARIO_FILES:
                arc = f"{ref.scenario}/{fname}"
                src = Path(scenarios_dir) / ref.scenario / fname
                if arc not in added and src.is_file():
                    zf.write(src, arc)
                    added.add(arc)
    return buf.getvalue()
