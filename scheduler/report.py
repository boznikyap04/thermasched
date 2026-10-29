"""Result writer: CSV tables, summary.json and the printed comparison table.

Computes no model numbers of its own: everything comes from EvalResult, SolveResult
and the inputs (apart from differences and percentages between the two columns, and
a count of workloads whose server differs from the original one).
"""

from __future__ import annotations

import csv
import json
import math
import platform
import subprocess
from datetime import datetime, timezone
from importlib import metadata
from pathlib import Path

import numpy as np

from .types import EvalResult, RunSettings, Scenario, Schedule, SolveResult
from .version import SCHEMA_VERSION, VERSION

AIRFLOW_TEXT = "not modelled"
AIRFLOW_NOTE = "Airflow and fan power are not modelled (fan power and airflow are zero)."
NO_COLD_PLATE_NOTE = ("Cold plates are off (cold-plate heat removal and pump power are zero; "
                      "--no-cold-plates was set).")
# Flagged with the thesis group: explain in the writeup, revisit after the first prototype.
COLD_PLATE_FLAG = ("FLAGGED: cold-plate flow and coolant temperature carry almost no cost (pump "
                   "power is at most about 1 mW per plate, and no equation charges energy for "
                   "cooling the water), so the optimizer runs them wherever they remove the most "
                   "heat. Where the 0.3 kW limit or the server's own heat is what limits removal, "
                   "the reported flow and coolant values are arbitrary.")


def model_note(settings: RunSettings) -> str:
    return AIRFLOW_NOTE + " " + (COLD_PLATE_FLAG if settings.cold_plates else NO_COLD_PLATE_NOTE)


def _cold_plate_block(scenario: Scenario, settings: RunSettings, ev: EvalResult) -> dict:
    cp = scenario.cold_plate
    return to_jsonable({
        "enabled": bool(settings.cold_plates),
        "plates_per_server": ev.n_cold_plates,
        "count_source": ("not modelled" if not settings.cold_plates else
                         "servers.csv" if settings.cold_plate_count is None else
                         f"--cold-plate-count {settings.cold_plate_count}"),
        "flow_settings_Lmin": list(cp.flow_settings_Lmin),
        "R_C_per_W": list(cp.R_C_per_W),
        "conductance_W_per_C": cp.conductance_W_per_C(),
        "pump_W_per_plate": cp.pump_W(),
        "flow_limits_Lmin": [cp.flow_min_Lmin, cp.flow_max_Lmin],
        "coolant_limits_C": [cp.coolant_min_C, cp.coolant_max_C],
        "Q_max_per_plate_W": cp.Q_max_per_plate_W,
        "baseline_flow_Lmin": settings.baseline_cp_flow_Lmin,
        "baseline_coolant_C": settings.baseline_cp_coolant_C,
        "optimized_mode": settings.cp_mode,
        "optimized_fixed_flow_Lmin": settings.optimized_fixed_cp()[0] if settings.cp_mode == "fixed" else None,
        "optimized_fixed_coolant_C": settings.optimized_fixed_cp()[1] if settings.cp_mode == "fixed" else None,
        "flag": COLD_PLATE_FLAG if settings.cold_plates else None,
    })


# ---------------------------------------------------------------------------
# JSON / CSV helpers
# ---------------------------------------------------------------------------

def to_jsonable(x):
    """Convert numpy scalars/arrays and tuples to plain Python; NaN and inf -> None."""
    if isinstance(x, dict):
        return {str(k): to_jsonable(v) for k, v in x.items()}
    if isinstance(x, (list, tuple, set)):
        return [to_jsonable(v) for v in x]
    if isinstance(x, np.ndarray):
        return to_jsonable(x.tolist())
    if isinstance(x, np.bool_):
        return bool(x)
    if isinstance(x, np.integer):
        return int(x)
    if isinstance(x, (float, np.floating)):
        v = float(x)
        return None if (math.isnan(v) or math.isinf(v)) else v
    return x


def _cell(v):
    if v is None:
        return ""
    if isinstance(v, (bool, np.bool_)):
        return int(bool(v))
    if isinstance(v, (float, np.floating)):
        return "" if math.isnan(float(v)) else repr(float(v))
    if isinstance(v, np.integer):
        return int(v)
    return v


def _write_csv(path: Path, header: list[str], rows) -> None:
    with open(path, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(header)
        for row in rows:
            w.writerow([_cell(v) for v in row])


def _type_name(RT: int) -> str:
    return "time_sensitive" if RT == 1 else "delay_tolerant"


# ---------------------------------------------------------------------------
# Per-schedule tables
# ---------------------------------------------------------------------------

def _count_reassigned(schedule: Schedule, original_server: dict) -> int:
    n = 0
    for p in schedule.placements:
        if p.server is not None and p.server != original_server.get(p.i):
            n += 1
    return n


def _count_cross_zone(scenario: Scenario, schedule: Schedule, original_server: dict) -> int:
    zone = {sv.s: sv.zone for sv in scenario.servers}
    return sum(1 for p in schedule.placements
               if p.server is not None and original_server.get(p.i) is not None
               and zone[p.server] != zone[original_server[p.i]])


def _move_reason(scenario: Scenario, ev: EvalResult, w, orig: int, final: int,
                 start: int, end: int) -> str:
    """Post-hoc reading of one move, from the scored schedule. The solver only minimises
    carbon; these are the local conditions that favoured the new server."""
    so, sf = scenario.servers[orig - 1], scenario.servers[final - 1]
    idx = np.arange(max(start, 1) - 1, min(end - 1, scenario.T))
    out = []
    if len(idx) and (np.any(ev.cpu_used_cores[orig - 1, idx] + w.C_req > so.C_cores + 1e-9)
                     or np.any(ev.mem_used_MB[orig - 1, idx] + w.M_req_MB > so.M_MB + 1e-9)):
        out.append("original server full at the chosen start")
    if sf.f_MHz > so.f_MHz:
        out.append("faster server")

    def it_energy(sv) -> float:   # extra IT energy of this workload on sv, W x periods
        n = max(1, math.ceil(w.W_MHz_s / (w.C_req * sv.f_MHz * scenario.dt_seconds) - 1e-9))
        return (sv.P_max_W - sv.P_idle_W) * w.C_req / sv.C_cores * n
    if it_energy(sf) < it_energy(so) - 1e-9:
        out.append("less IT energy for its work")
    if len(idx) and ev.T_C[final - 1, idx].mean() < ev.T_C[orig - 1, idx].mean() - 1e-9:
        out.append("cooler server")
    if len(idx) and sf.zone != so.zone and \
            ev.COP[sf.zone - 1, idx].mean() > ev.COP[so.zone - 1, idx].mean() + 1e-9:
        out.append("zone with higher CRAC COP")
    return "; ".join(out) or "carbon trade-off across the fleet (no single local cause)"


def _write_reassignment(path: Path, scenario: Scenario, settings: RunSettings,
                        schedule: Schedule, ev: EvalResult, original_server: dict) -> None:
    """One row per workload: original and final server and zone, and why it moved (or not)."""
    by_i = {p.i: p for p in schedule.placements}
    zone = {sv.s: sv.zone for sv in scenario.servers}
    rows = []
    for w in scenario.workloads:
        p = by_i.get(w.i)
        orig = original_server.get(w.i)
        placed = bool(ev.placed[w.i - 1]) and p is not None
        final = p.server if placed else None
        moved = placed and orig is not None and final != orig
        if not placed:
            reason = "not placed"
        elif moved:
            reason = _move_reason(scenario, ev, w, orig, final, p.start, p.end)
        elif w.B == 1:
            reason = "running at the start (B_i = 1): stays on its server, Eq. (29)"
        elif settings.reassignment == "none":
            reason = "reassignment off"
        else:
            reason = "kept"
        rows.append([
            w.i, w.workload_id, _type_name(w.RT), w.B, orig,
            zone.get(orig) if orig is not None else None, final,
            zone.get(final) if final is not None else None, moved,
            bool(moved and zone[orig] != zone[final]), reason])
    _write_csv(path, ["i", "workload_id", "type", "B_running", "original_server", "original_zone",
                      "final_server", "final_zone", "reassigned", "cross_zone", "reason"], rows)


def _write_schedule_tables(folder: Path, scenario: Scenario, schedule: Schedule,
                           ev: EvalResult, original_server: dict) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    by_i = {p.i: p for p in schedule.placements}

    rows = []
    for w in scenario.workloads:
        k = w.i - 1
        p = by_i.get(w.i)
        placed = bool(ev.placed[k])
        orig = original_server.get(w.i)
        server = p.server if (p is not None and placed) else None
        start = p.start if (p is not None and placed) else None
        end = p.end if (p is not None and placed) else None
        rows.append([
            w.i, w.workload_id, _type_name(w.RT), w.A, orig, server,
            (server != orig) if placed else None, start,
            (end - start) if placed else None, end,
            ev.wait_periods[k], w.AD, w.D,
            ev.work_required_MHz_s[k], ev.work_delivered_MHz_s[k],
            ev.compliant[k], ev.placed[k], ev.starts_on_or_after_arrival[k],
            ev.wait_within_allowed[k], ev.on_time[k], ev.work_complete[k], w.B,
        ])
    _write_csv(folder / "schedule.csv",
               ["i", "workload_id", "type", "arrival", "original_server", "server", "reassigned",
                "start", "periods_run", "finish", "wait", "allowed_delay", "deadline",
                "work_required_MHz_s", "work_delivered_MHz_s", "compliant", "placed",
                "starts_on_or_after_arrival", "wait_within_allowed", "on_time", "work_complete",
                "B_running"],
               rows)

    T = scenario.T
    _write_csv(folder / "server_period.csv",
               ["s", "t", "cpu_used_cores", "mem_used_MB", "utilization", "P_IT_W", "Q_cp_W",
                "cp_flow_Lmin", "cp_coolant_C", "P_cp_W",
                "temperature_C", "headroom_C", "DPF", "PC_eff_MHz"],
               ([s + 1, t + 1, ev.cpu_used_cores[s, t], ev.mem_used_MB[s, t], ev.util[s, t],
                 ev.P_IT_W[s, t], ev.Q_cp_W[s, t], ev.cp_flow_Lmin[s, t], ev.cp_coolant_C[s, t],
                 ev.P_cp_W[s, t], ev.T_C[s, t], ev.headroom_C[s, t],
                 ev.DPF[s, t], ev.PC_eff_MHz[s, t]]
                for s in range(scenario.S) for t in range(T)))
    _write_csv(folder / "zone_period.csv",
               ["z", "t", "supply_temp_C", "Q_crac_kW", "COP", "P_crac_kW", "P_fan_kW", "airflow"],
               ([z + 1, t + 1, ev.T_supply_C[z, t], ev.Q_crac_kW[z, t], ev.COP[z, t],
                 ev.P_crac_kW[z, t], ev.P_fan_kW[z, t], AIRFLOW_TEXT]
                for z in range(scenario.Z) for t in range(T)))
    _write_csv(folder / "period.csv",
               ["t", "E_IT_kWh", "E_crac_kWh", "E_cp_kWh", "E_fan_kWh", "E_total_kWh",
                "CI_g_per_kWh", "carbon_g"],
               ([t + 1, ev.E_IT_kWh[t], ev.E_crac_kWh[t], ev.E_cp_kWh[t], ev.E_fan_kWh[t],
                 ev.E_total_kWh[t], scenario.CI_g_per_kWh[t], ev.carbon_g[t]] for t in range(T)))

    comp = ev.compliance
    srv_cols = ["s", "name", "zone", "cold_plate", "n_cold_plates", "Q_cp_peak_W", "Q_cp_capacity_W",
                "cpu_peak_cores", "cpu_capacity_cores", "max_utilization",
                "mem_peak_MB", "mem_capacity_MB", "hottest_T_C", "min_headroom_C",
                "periods_above_dvfs", "periods_above_cap", "min_DPF", "min_PC_eff_MHz",
                "periods_unavailable"]
    _write_csv(folder / "compliance_servers.csv", srv_cols,
               ([d[c] for c in srv_cols] for d in comp["servers"]))
    zone_cols = ["z", "supply_min_C", "supply_max_C", "supply_allowed_min_C",
                 "supply_allowed_max_C", "zone_limit_C", "max_ramp_short_C", "ramp_short_limit_C",
                 "max_ramp_long_C", "ramp_long_limit_C", "Q_crac_peak_kW", "Q_crac_capacity_kW"]
    _write_csv(folder / "compliance_zones.csv", zone_cols,
               ([d[c] for c in zone_cols] for d in comp["zones"]))
    cp_cols = ["s", "name", "n_cold_plates", "coolant_min_C", "coolant_max_C",
               "coolant_allowed_min_C", "coolant_allowed_max_C", "flow_min_Lmin", "flow_max_Lmin",
               "flow_allowed_min_Lmin", "flow_allowed_max_Lmin", "Q_cp_peak_W", "Q_cp_capacity_W"]
    _write_csv(folder / "compliance_cold_plates.csv", cp_cols,
               ([d[c] for c in cp_cols] for d in comp.get("cold_plates", [])))
    horizon = comp.get("within_horizon", [None] * scenario.I)
    _write_csv(folder / "compliance_workloads.csv",
               ["i", "workload_id", "placed", "work_delivered_MHz_s", "work_required_MHz_s",
                "min_DPF", "starts_on_or_after_arrival", "wait_within_allowed", "on_time",
                "work_complete", "within_horizon", "compliant"],
               ([w.i, w.workload_id, ev.placed[w.i - 1], ev.work_delivered_MHz_s[w.i - 1],
                 ev.work_required_MHz_s[w.i - 1], ev.min_DPF_run[w.i - 1],
                 ev.starts_on_or_after_arrival[w.i - 1],
                 ev.wait_within_allowed[w.i - 1], ev.on_time[w.i - 1], ev.work_complete[w.i - 1],
                 horizon[w.i - 1], ev.compliant[w.i - 1]] for w in scenario.workloads))


def _write_comparison_period(path: Path, scenario: Scenario, base: EvalResult,
                             opt: EvalResult | None) -> None:
    comps = ["E_IT_kWh", "E_crac_kWh", "E_cp_kWh", "E_fan_kWh", "E_total_kWh", "carbon_g"]
    header = (["t", "CI_g_per_kWh"] + [f"baseline_{c}" for c in comps]
              + [f"optimized_{c}" for c in comps] + [f"diff_{c}" for c in comps])
    rows = []
    for t in range(scenario.T):
        b = [getattr(base, c)[t] for c in comps]
        if opt is None:
            o = [None] * len(comps)
            d = [None] * len(comps)
        else:
            o = [getattr(opt, c)[t] for c in comps]
            d = [ov - bv for ov, bv in zip(o, b)]
        rows.append([t + 1, scenario.CI_g_per_kWh[t]] + b + o + d)
    _write_csv(path, header, rows)


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

# (key, label, unit) in table order. Values come from EvalResult.totals.
METRICS = [
    ("carbon_kg", "Total carbon", "kg"),
    ("E_IT_kWh", "Energy, IT", "kWh"),
    ("E_crac_kWh", "Energy, CRAC", "kWh"),
    ("E_cp_kWh", "Energy, cold plate", "kWh"),
    ("Q_cp_kWh", "Heat removed by cold plates", "kWh"),
    ("E_fan_kWh", "Energy, fan", "kWh"),
    ("E_total_kWh", "Energy, total", "kWh"),
    ("n_late", "Workloads late", ""),
    ("n_noncompliant", "Non-compliant workloads", ""),
    ("mean_wait_RT", "Mean wait, time-sensitive", "periods"),
    ("max_wait_RT", "Max wait, time-sensitive", "periods"),
    ("mean_wait_DT", "Mean wait, delay-tolerant", "periods"),
    ("max_wait_DT", "Max wait, delay-tolerant", "periods"),
    ("n_priority_violations", "Priority inversions", ""),
    ("hottest_T_C", "Hottest server temperature", "C"),
    ("mean_T_C", "Mean server temperature", "C"),
    ("min_headroom_C", "Minimum headroom", "C"),
    ("mean_headroom_C", "Mean headroom", "C"),
    ("periods_above_dvfs", "Server-periods above DVFS temperature", ""),
    ("periods_above_cap", "Server-periods above thermal cap", ""),
    ("n_throttled_servers", "Servers throttled (DPF < 1)", ""),
    ("n_reassigned", "Workloads reassigned", ""),
    ("n_cross_zone", "Reassigned to another zone", ""),
]
_SCHEDULE_METRICS = ("n_reassigned", "n_cross_zone")


def _metrics_block(scenario: Scenario, ev: EvalResult, schedule: Schedule,
                   original_server: dict) -> dict:
    t = ev.totals
    block = {k: t.get(k) for k, _, _ in METRICS if k not in _SCHEDULE_METRICS}
    block["n_reassigned"] = _count_reassigned(schedule, original_server)
    block["n_cross_zone"] = _count_cross_zone(scenario, schedule, original_server)
    block["hottest_server"] = t.get("hottest_server")
    block["hottest_period"] = t.get("hottest_period")
    block["n_unplaced"] = t.get("n_unplaced")
    block["min_DPF"] = t.get("min_DPF")
    return to_jsonable(block)


def _side(scenario: Scenario, ev: EvalResult, schedule: Schedule, original_server: dict) -> dict:
    return {
        "valid": bool(ev.valid),
        "violations": list(ev.compliance.get("violations", [])),
        "metrics": _metrics_block(scenario, ev, schedule, original_server),
        "totals": to_jsonable(ev.totals),
        "compliance_flags": to_jsonable({k: v for k, v in ev.compliance.items()
                                         if k.endswith("_ok") or k == "all_ok"}),
    }


def _diff(b, o):
    if b is None or o is None:
        return {"baseline": b, "optimized": o, "diff": None, "pct": None}
    d = o - b
    pct = None if b == 0 else 100.0 * d / b
    return {"baseline": b, "optimized": o, "diff": d, "pct": pct}


def _solver_block(sr: SolveResult | None) -> dict | None:
    if sr is None:
        return None
    return to_jsonable({
        "status": sr.status, "solver_status_text": sr.solver_status_text,
        "solve_time_s": sr.solve_time_s, "mip_gap": sr.mip_gap,
        "objective_g": sr.objective_g, "best_bound_g": sr.best_bound_g,
        "n_variables": sr.n_variables, "n_binaries": sr.n_binaries,
        "n_constraints": sr.n_constraints, "relaxed": list(sr.relaxed),
        "has_schedule": sr.has_schedule, "notes": list(sr.notes),
    })


def _git_commit() -> str | None:
    """Commit of the code that made the run, with "+dirty" for uncommitted changes; None
    outside a git checkout (the notebooks run a copy of the code)."""
    here = Path(__file__).resolve().parent
    try:
        commit = subprocess.run(["git", "-C", str(here), "rev-parse", "--short", "HEAD"],
                                capture_output=True, text=True, timeout=5)
        if commit.returncode != 0:
            return None
        dirty = subprocess.run(["git", "-C", str(here), "status", "--porcelain",
                                "--untracked-files=no", "--", "."],
                               capture_output=True, text=True, timeout=5).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return None
    return commit.stdout.strip() + ("+dirty" if dirty else "")


def _package_version(name: str) -> str | None:
    try:
        return metadata.version(name)
    except metadata.PackageNotFoundError:
        return None


def provenance(scenario: Scenario, made_with: str) -> dict:
    """What made a run: the release, the scenario build it was solved on, and the solver.
    Two runs are comparable when their scenario fingerprints are equal."""
    return {
        "schema_version": SCHEMA_VERSION,
        "thermasched_version": VERSION,
        "made_with": made_with,
        "created_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "git_commit": _git_commit(),
        "scenario_fingerprint": scenario.fingerprint,
        "scenario_built_with": scenario.built_with,
        "highspy": _package_version("highspy"),
        "python": platform.python_version(),
    }


def write_results(out_dir, scenario: Scenario, settings: RunSettings,
                  original_server: dict, baseline_schedule: Schedule, baseline_eval: EvalResult,
                  optimized_schedule: Schedule | None, optimized_eval: EvalResult | None,
                  solve_result: SolveResult | None, infeasibility: dict | None,
                  checks: dict, made_with: str = "command line",
                  per_tick: dict | None = None) -> dict:
    """``per_tick``: the per-tick block (scheduler/pertick.py) of a per-tick run."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    _write_schedule_tables(out / "baseline", scenario, baseline_schedule, baseline_eval,
                           original_server)
    have_opt = optimized_schedule is not None and optimized_eval is not None
    if have_opt:
        _write_schedule_tables(out / "optimized", scenario, optimized_schedule, optimized_eval,
                               original_server)
        _write_reassignment(out / "optimized" / "reassignment.csv", scenario, settings,
                            optimized_schedule, optimized_eval, original_server)
    _write_comparison_period(out / "comparison_period.csv", scenario, baseline_eval,
                             optimized_eval if have_opt else None)

    base_side = _side(scenario, baseline_eval, baseline_schedule, original_server)
    opt_side = (_side(scenario, optimized_eval, optimized_schedule, original_server)
                if have_opt else None)
    comparison = {}
    for key, _, _ in METRICS:
        b = base_side["metrics"].get(key)
        o = opt_side["metrics"].get(key) if opt_side else None
        comparison[key] = _diff(b, o)

    summary = {
        "scenario": {"name": scenario.name, "I": scenario.I, "S": scenario.S, "Z": scenario.Z,
                     "T": scenario.T, "dt_seconds": scenario.dt_seconds,
                     "zones": [sv.zone for sv in scenario.servers],
                     "n_running": sum(w.B for w in scenario.workloads),
                     "n_unavailable_server_periods": int((scenario.availability() == 0).sum()),
                     "CI_mean_g_per_kWh": float(np.mean(scenario.CI_g_per_kWh))},
        "provenance": provenance(scenario, made_with),
        "settings": settings.as_dict(),
        "mode": "per_tick" if settings.per_tick else "whole_day",
        "per_tick": per_tick,
        "model_note": model_note(settings),
        "cold_plates": _cold_plate_block(scenario, settings, baseline_eval),
        "airflow_modelled": bool(baseline_eval.airflow_modelled),
        "thermal_cap_C": baseline_eval.compliance.get("thermal_cap_C"),
        "T_dvfs_C": scenario.constants.T_dvfs_C,
        "baseline": base_side,
        "optimized": opt_side,
        "has_optimized_schedule": have_opt,
        "comparison": comparison,
        "solver": _solver_block(solve_result),
        "infeasibility": infeasibility,
        "checks": checks,
    }
    summary = to_jsonable(summary)
    with open(out / "summary.json", "w") as fh:
        json.dump(summary, fh, indent=2, allow_nan=False)
    return summary


# ---------------------------------------------------------------------------
# Printed table
# ---------------------------------------------------------------------------

def _fmt(v, unit_key: str | None = None) -> str:
    if v is None:
        return "-"
    if isinstance(v, bool):
        return str(v)
    if isinstance(v, int):
        return str(v)
    a = abs(v)
    if a != 0 and a < 0.01:
        return f"{v:.2e}"
    return f"{v:,.2f}"


def _fmt_pct(p) -> str:
    return "-" if p is None else f"{p:+.1f}%"


def _fmt_diff(d) -> str:
    if d is None:
        return "-"
    if isinstance(d, int):
        return f"{d:+d}"
    return f"{d:+,.2f}" if (d == 0 or abs(d) >= 0.01) else f"{d:+.2e}"


def format_summary(summary: dict) -> str:
    sc = summary["scenario"]
    st = summary["settings"]
    lines = []
    lines.append(f"Scenario {sc['name']}: I={sc['I']} workloads, S={sc['S']} servers, "
                 f"Z={sc['Z']} zones, T={sc['T']} periods of {sc['dt_seconds']:g} s")
    lines.append(f"Run '{st.get('run_name')}': baseline={st.get('baseline_rule')} at "
                 f"{st.get('baseline_supply_temp_C')} C, reassignment={st.get('reassignment')}, "
                 f"placement={st.get('placement', 'thermal_aware')}, "
                 f"supply_temp_mode={st.get('supply_temp_mode')}, "
                 f"priority={'on' if st.get('priority', True) else 'off'}, "
                 f"thermal cap {summary.get('thermal_cap_C')} C")
    pv = summary.get("provenance") or {}
    if pv:
        lines.append(f"Made with ThermaSched {pv.get('thermasched_version')} ({pv.get('made_with')}"
                     + (f", commit {pv['git_commit']}" if pv.get("git_commit") else "")
                     + f"), scenario fingerprint {pv.get('scenario_fingerprint')}")
    extra = []
    if st.get("zone_map"):
        extra.append(f"zone map {st['zone_map']}")
    if st.get("carbon_file"):
        extra.append(f"carbon intensity from {st['carbon_file']}")
    if st.get("ci_flat"):
        extra.append(f"flat carbon intensity {sc.get('CI_mean_g_per_kWh', 0):.2f} g/kWh")
    if extra:
        lines.append("Scenario overrides: " + "; ".join(extra))
    cpb = summary.get("cold_plates") or {}
    if cpb.get("enabled"):
        lines.append(f"Cold plates per server {cpb.get('plates_per_server')} "
                     f"({cpb.get('count_source')}); flow settings {cpb.get('flow_settings_Lmin')} L/min; "
                     f"baseline fixed at {cpb.get('baseline_flow_Lmin')} L/min, "
                     f"{cpb.get('baseline_coolant_C')} C coolant"
                     + (f"; optimized fixed at {cpb.get('optimized_fixed_flow_Lmin')} L/min, "
                        f"{cpb.get('optimized_fixed_coolant_C')} C coolant"
                        if cpb.get("optimized_mode") == "fixed" else ""))
    lines.append("")

    have_opt = summary.get("has_optimized_schedule")
    rows = [("Metric", "Baseline", "Optimized", "Diff", "Diff %")]
    comp = summary["comparison"]
    for key, label, unit in METRICS:
        c = comp[key]
        name = f"{label} ({unit})" if unit else label
        if key == "periods_above_dvfs":
            name = f"Server-periods above {summary.get('T_dvfs_C'):g} C"
        b_txt = _fmt(c["baseline"])
        o_txt = _fmt(c["optimized"]) if have_opt else "-"
        if key == "hottest_T_C":
            b_txt += f" (server {summary['baseline']['metrics'].get('hottest_server')})"
            if have_opt:
                o_txt += f" (server {summary['optimized']['metrics'].get('hottest_server')})"
        rows.append((name, b_txt, o_txt,
                     _fmt_diff(c["diff"]) if have_opt else "-",
                     _fmt_pct(c["pct"]) if have_opt else "-"))
    rows.append(("Schedule valid (no limit broken)", str(summary["baseline"]["valid"]),
                 str(summary["optimized"]["valid"]) if have_opt else "-", "", ""))

    widths = [max(len(r[i]) for r in rows) for i in range(5)]
    for n, r in enumerate(rows):
        lines.append("  ".join(r[0].ljust(widths[0]) if i == 0 else r[i].rjust(widths[i])
                               for i in range(5)))
        if n == 0:
            lines.append("  ".join("-" * w for w in widths))

    for side, label in (("baseline", "Baseline"), ("optimized", "Optimized")):
        d = summary.get(side)
        if d and d["violations"]:
            lines.append("")
            lines.append(f"{label} violations:")
            lines.extend(f"  - {v}" for v in d["violations"])

    sv = summary.get("solver")
    lines.append("")
    if sv is None:
        lines.append("Solver: not run.")
    else:
        gap = sv.get("mip_gap")
        lines.append(f"Solver: status={sv['status']} ({sv.get('solver_status_text') or '-'}), "
                     f"time={sv['solve_time_s']:.1f} s, gap={'-' if gap is None else f'{gap:.4%}'}, "
                     f"objective={_fmt(sv.get('objective_g'))} g, bound={_fmt(sv.get('best_bound_g'))} g")
        lines.append(f"        {sv['n_variables']} variables, {sv['n_binaries']} binaries, "
                     f"{sv['n_constraints']} constraints")
        for note in sv.get("notes") or []:
            lines.append(f"        note: {note}")
    pt = summary.get("per_tick")
    if pt:
        slow = pt.get("slowest_tick_solve_s")
        lines.append(f"Per-tick re-planning: {pt['n_ticks']} ticks, {pt['n_ticks_optimal']} "
                     f"optimal, {pt['n_ticks_time_limit']} at the {pt['tick_time_limit_s']:g} s "
                     f"tick limit, slowest {'-' if slow is None else f'{slow:.1f}'} s "
                     f"(tick {pt.get('slowest_tick')}); log in {pt['ticks_file']}")
        if pt.get("stuck"):
            st = pt["stuck"]
            lines.append(f"STUCK at tick {st['tick']}: {st['limit_text']}. {st['detail']}.")
    if not have_opt:
        lines.append("")
        lines.append("NO VALID SCHEDULE WAS FOUND by the optimizer; only the baseline is shown.")
    inf = summary.get("infeasibility")
    if inf:
        lines.append("Infeasibility diagnosis (one constraint family relaxed at a time):")
        for fam, outcome in inf.items():
            lines.append(f"  {fam}: {outcome if outcome is not None else '-'}")
    lines.append("")
    lines.append("Note: " + summary["model_note"])
    return "\n".join(lines)
