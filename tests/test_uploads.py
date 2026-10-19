"""Zip import/export of run folders (dashboard/uploads.py)."""

from __future__ import annotations

import io
import json
import zipfile

import pytest

from dashboard import data, uploads

RUNS = {r.key: r for r in data.discover_runs()}
KEY = "small/least_loaded_base18_free_optimize"          # as named by its summary.json
SOURCE = "archive-small/least_loaded_base18_free_optimize"  # where it sits under results/

pytestmark = pytest.mark.skipif(SOURCE not in RUNS, reason="no run outputs under results/")


def _zip(files: dict[str, bytes | str]) -> io.BytesIO:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, content in files.items():
            zf.writestr(name, content)
    buf.seek(0)
    return buf


def _run_files(prefix: str) -> dict[str, bytes]:
    ref = RUNS[SOURCE]
    return {f"{prefix}{f.relative_to(ref.path).as_posix()}": f.read_bytes()
            for f in ref.path.rglob("*") if f.is_file()}


def _import(tmp_path, source, **kw):
    return uploads.import_zip(source, tmp_path / "results", tmp_path / "scenarios", **kw)


def test_round_trip_keeps_names_and_clock(tmp_path):
    ref = RUNS[SOURCE]
    blob = uploads.runs_zip([(ref, data.SCENARIOS_DIR)])
    names = zipfile.ZipFile(io.BytesIO(blob)).namelist()
    assert f"{KEY}/summary.json" in names and "small/servers.csv" in names

    res = _import(tmp_path, io.BytesIO(blob))
    assert not res.problems
    assert [r.key for r in res.runs] == [KEY]
    assert res.scenarios == ["small"]
    assert data.discover_runs(tmp_path / "results") == res.runs

    got = data.load_run(res.runs[0].path, tmp_path / "scenarios")
    want = data.load_run(ref.path)
    assert got.summary == want.summary
    assert got.variants == want.variants
    assert got.servers["name"].tolist() == want.servers["name"].tolist()
    assert got.clock["clock"].tolist() == want.clock["clock"].tolist()


def test_zip_of_folder_contents_uses_zip_name_and_summary_scenario(tmp_path):
    res = _import(tmp_path, _zip(_run_files("")), fallback_name="my_run")
    assert [r.key for r in res.runs] == ["small/my_run"]
    assert (tmp_path / "results/small/my_run/baseline/period.csv").is_file()


def test_extra_folder_level_and_mac_clutter(tmp_path):
    files = _run_files("Archive/least_loaded/") | {
        "__MACOSX/Archive/._summary.json": b"junk",
        "Archive/least_loaded/.DS_Store": b"junk",
    }
    res = _import(tmp_path, _zip(files))
    assert [r.key for r in res.runs] == ["small/least_loaded"]
    run_dir = tmp_path / "results/small/least_loaded"
    assert not (run_dir / ".DS_Store").exists()
    assert data.load_run(run_dir, tmp_path / "scenarios").variants == ("baseline", "optimized")


def test_reserved_key_is_renamed_and_reupload_replaces(tmp_path):
    files = _run_files("small/least_loaded_base18_free_optimize/")
    res = _import(tmp_path, _zip(files), reserved={KEY})
    assert [r.name for r in res.runs] == ["least_loaded_base18_free_optimize (uploaded)"]

    stale = res.runs[0].path / "stale.csv"
    stale.write_text("x")
    again = _import(tmp_path, _zip(files), reserved={KEY})
    assert [r.key for r in again.runs] == [r.key for r in res.runs]
    assert not stale.exists()
    assert len(data.discover_runs(tmp_path / "results")) == 1


def test_several_runs_and_missing_scenario_files_filled_in(tmp_path):
    summary = json.dumps({"scenario": {"name": "small"}})
    files = {"results/small/a/summary.json": summary, "results/small/b/summary.json": summary,
             "results/small/servers.csv": "s,server,zone\n1,x,1\n"}
    res = _import(tmp_path, _zip(files), fallback_scenarios_dir=data.SCENARIOS_DIR)
    assert sorted(r.key for r in res.runs) == ["small/a", "small/b"]
    assert (tmp_path / "scenarios/small/servers.csv").read_text().startswith("s,server")
    assert (tmp_path / "scenarios/small/carbon.csv").is_file()   # from scenarios/small


def test_unsafe_paths_are_skipped(tmp_path):
    files = _run_files("run/") | {"run/../../evil.csv": b"x", "/abs.csv": b"x"}
    res = _import(tmp_path, _zip(files))
    assert [r.name for r in res.runs] == ["run"]
    assert not (tmp_path / "evil.csv").exists()
    assert not list(tmp_path.parent.glob("evil.csv"))


def test_bad_inputs_report_problems(tmp_path):
    assert _import(tmp_path, io.BytesIO(b"not a zip")).problems
    no_summary = _import(tmp_path, _zip({"run/baseline/period.csv": "t\n1\n"}))
    assert not no_summary.runs and "summary.json" in no_summary.problems[0]
    broken = _import(tmp_path, _zip({"run/summary.json": "{oops"}))
    assert not broken.runs and broken.problems
