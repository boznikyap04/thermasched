"""Validation checks: small, controlled tests that show the model does what the thesis says.

Each check answers one question of the thesis group and returns a table: a list of rows
(dicts) whose keys are the column headers, with units. Where a check has an expected
answer, the row says whether it passed.

    uv run python -m scheduler.validate --scenario servers6

writes every table to ``results/validation/<scenario>/`` as CSV, with ``validation.json``
(release, date, scenario build, and the result of every check).
``notebooks/solver.ipynb`` computes the same tables in its last section.

The checks that solve build small scenarios from the real servers and constants of the
scenario, so every number comes from the model's own code: the optimizer (optimize.py) and
the independent evaluator (evaluate.py). The checks that read runs take a run folder under
``results/`` and are skipped when it is missing.
"""

from __future__ import annotations

import argparse
import csv
import dataclasses
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from .baseline import build_baseline, periods_needed
from .evaluate import evaluate
from .io import load_scenario
from .optimize import diagnose_infeasibility, solve
from .types import (
    STATUS_INFEASIBLE, STATUS_OPTIMAL, Placement, RunSettings, Scenario, Schedule, Workload,
    constant_supply_temp, cop, status_text,
)
from .version import VERSION

POWER_TOL_W = 0.01
TOY_TIME_LIMIT_S = 60.0

# Examples of the thesis group (validation questions of 2026-10-21), posed on thesis10, the
# earlier 10-server scenario. On another scenario the checks use the workloads of these
# numbers it has, and its first and last server.
EXAMPLE_WORKLOADS = (211, 232, 9, 5)
EXAMPLE_SERVERS = ("qh2-rcc165", "qh2-rcc183")


def _clock(period: int, start_hour: float | None, dt_seconds: float) -> str | None:
    """Local clock time at the start of ``period`` (1-based); None without a start hour."""
    if start_hour is None:
        return None
    minutes = round(start_hour * 60 + (period - 1) * dt_seconds / 60) % (24 * 60)
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def _server(scenario: Scenario, name: str):
    for sv in scenario.servers:
        if sv.name == name:
            return sv
    raise ValueError(f"no server named {name!r} in scenario {scenario.name!r}")


def _workload(scenario: Scenario, i: int) -> Workload:
    if not 1 <= i <= scenario.I:
        raise ValueError(f"workload {i} is not in scenario {scenario.name!r} (1..{scenario.I})")
    return scenario.workloads[i - 1]


def _toy(scenario: Scenario, servers, workloads, T: int, name: str) -> Scenario:
    """A small scenario: the given servers (renumbered, all in zone 1) and workloads, the
    first T periods of the carbon curve, and the scenario's constants."""
    svs = tuple(dataclasses.replace(sv, s=k, zone=1) for k, sv in enumerate(servers, 1))
    return dataclasses.replace(
        scenario, name=name, T=T, servers=svs, workloads=tuple(workloads), n_zones=1,
        CI_g_per_kWh=np.asarray(scenario.CI_g_per_kWh[:T], dtype=float), AV=None,
        fingerprint=None)


def _top_supply(scenario: Scenario) -> float:
    """Highest whole-degree supply temperature allowed: what every optimized run picks."""
    c = scenario.constants
    return float(math.floor(min(c.T_crac_max_C, c.T_max_zone_C) + 1e-9))


# ---------------------------------------------------------------------------
# Inputs: the workload table of the thesis (Section 5.2.2)
# ---------------------------------------------------------------------------

def workload_inputs(scenario: Scenario, start_hour: float | None = None) -> list[dict]:
    """One row per workload: what it asks for and when, with units."""
    dt_min = scenario.dt_seconds / 60.0
    rows = []
    for w in scenario.workloads:
        rows.append({
            "Workload": w.i,
            "Workload ID": w.workload_id,
            "Flavor": w.flavor,
            "Type": "time-sensitive" if w.RT else "delay-tolerant",
            "Requested CPU cores (vCPU)": w.C_req,
            "Requested RAM (GB)": round(w.M_req_MB / 1024.0, 3),
            "Arrival (period)": w.A,
            "Arrival (clock)": _clock(w.A, start_hour, scenario.dt_seconds),
            "Deadline (period)": w.D,
            "Deadline (clock)": _clock(w.D, start_hour, scenario.dt_seconds),
            "Base runtime (min)": w.ET_base * dt_min,
            "Allowed delay (min)": w.AD * dt_min,
            "Work required (MHz·s)": w.W_MHz_s,
        })
    return rows


# ---------------------------------------------------------------------------
# B9: server power at 0, 50 and 100 % CPU use
# ---------------------------------------------------------------------------

def power_check(scenario: Scenario) -> list[dict]:
    """For every server: power at 0, 50 and 100 % CPU use, expected from its listed idle and
    maximum power, against the optimizer's and the evaluator's value.

    Each server is solved alone over two periods with one workload that fills half or all of
    its cores in period 1; period 2 is idle (0 %). Its starting temperature is set to 30 °C
    so that heat cannot get in the way; power does not depend on temperature."""
    rows = []
    dt = scenario.dt_seconds
    for sv in scenario.servers:
        measured: dict[float, tuple[float, float]] = {}
        for share in (0.5, 1.0):
            cores = max(1, round(share * sv.C_cores))
            w = Workload(i=1, workload_id="power-test", flavor="test", A=1, D=2, AD=0,
                         ET_base=1, RT=0, B=0, X0=1, C_req=cores, M_req_MB=1.0,
                         W_MHz_s=cores * sv.f_MHz * dt)
            toy = _toy(scenario, [dataclasses.replace(sv, T0_C=30.0)], [w], 2,
                       f"power-{sv.name}")
            st = RunSettings(scenario=toy.name, reassignment="none",
                             time_limit_s=TOY_TIME_LIMIT_S)
            res = solve(toy, {1: 1}, st)
            if not res.has_schedule:
                raise RuntimeError(f"power check of {sv.name}: no schedule ({res.status})")
            ev = evaluate(toy, res.schedule, res.supply_temp_C, st)
            opt_p = res.model_values["P_IT_W"][0]
            measured[cores / sv.C_cores] = (float(opt_p[0]), float(ev.P_IT_W[0, 0]))
            measured[0.0] = (float(opt_p[1]), float(ev.P_IT_W[0, 1]))
        for share in sorted(measured):
            opt_w, ev_w = measured[share]
            expected = sv.P_idle_W + (sv.P_max_W - sv.P_idle_W) * share
            ok = abs(opt_w - expected) <= POWER_TOL_W and abs(ev_w - expected) <= POWER_TOL_W
            rows.append({
                "Server": sv.name, "Speed (MHz)": sv.f_MHz,
                "CPU use (%)": round(share * 100, 1),
                "Idle power (W)": sv.P_idle_W, "Maximum power (W)": sv.P_max_W,
                "Expected power (W)": round(expected, 3),
                "Optimizer power (W)": round(opt_w, 3),
                "Evaluator power (W)": round(ev_w, 3),
                "Pass": ok,
            })
    return rows


# ---------------------------------------------------------------------------
# B4: server speed in the execution time; B5: the same task on server A or B
# ---------------------------------------------------------------------------

def _single_run(scenario: Scenario, w: Workload, sv, n: int, supply_C: float,
                settings: RunSettings):
    """Evaluate ``w`` alone on ``sv`` (in its own fleet) from arrival for ``n`` periods. A run
    past the end of the horizon is evaluated on a horizon extended to its end (the carbon
    intensity of the last period repeated), so its work is still counted."""
    one = dataclasses.replace(w, i=1)
    T = max(scenario.T, w.A + n - 1)
    ci = np.asarray(scenario.CI_g_per_kWh, dtype=float)
    ci = np.concatenate([ci, np.full(T - scenario.T, ci[-1])])
    sc = dataclasses.replace(scenario, workloads=(one,), T=T, CI_g_per_kWh=ci, AV=None)
    sched = Schedule((Placement(1, sv.s, w.A, w.A + n),))
    return sc, evaluate(sc, sched, constant_supply_temp(sc, supply_C), settings)


def execution_check(scenario: Scenario, workloads=EXAMPLE_WORKLOADS, servers=EXAMPLE_SERVERS,
                    start_hour: float | None = None) -> list[dict]:
    """The same workload (same work, cores, start at arrival) on each server: the run length
    from the model's rule, ceil(W / (cores x MHz x DPF x period)), and whether the evaluator
    agrees that this is the shortest run that delivers the work, and whether it meets the
    deadline. Each workload runs alone, at the top supply temperature, so DPF is the
    evaluator's (1 unless the server passes T_dvfs)."""
    st = RunSettings(scenario=scenario.name)
    dt = scenario.dt_seconds
    supply = _top_supply(scenario)
    rows = []
    for i in workloads:
        w = _workload(scenario, i)
        for name in servers:
            sv = _server(scenario, name)
            exact = w.W_MHz_s / (w.C_req * sv.f_MHz * dt)
            n = periods_needed(w, sv, dt)
            _, ev = _single_run(scenario, w, sv, n, supply, st)
            enough = bool(ev.work_complete[0])
            short = n > 1 and bool(_single_run(scenario, w, sv, n - 1, supply, st)[1].work_complete[0])
            end = w.A + n
            rows.append({
                "Workload": w.i, "Type": "time-sensitive" if w.RT else "delay-tolerant",
                "Cores": w.C_req, "Work required (MHz·s)": w.W_MHz_s,
                "Server": sv.name, "Speed (MHz)": sv.f_MHz,
                "Lowest DPF during the run": round(float(ev.min_DPF_run[0]), 4),
                "Periods, exact": round(exact, 2), "Periods, rounded up": n,
                "Execution time (min)": n * dt / 60,
                "Start (period)": w.A, "Start (clock)": _clock(w.A, start_hour, dt),
                "Finish (period)": end, "Finish (clock)": _clock(end, start_hour, dt),
                "Deadline (period)": w.D, "Deadline (clock)": _clock(w.D, start_hour, dt),
                "Meets deadline": end <= w.D,
                "Pass": enough and not short,
            })
    return rows


def equal_time_count(scenario: Scenario, servers=EXAMPLE_SERVERS) -> dict:
    """How many workloads get the same number of periods on every server in ``servers``,
    because the run length is rounded up to whole periods."""
    svs = [_server(scenario, n) for n in servers]
    same = [w.i for w in scenario.workloads
            if len({periods_needed(w, sv, scenario.dt_seconds) for sv in svs}) == 1]
    return {"servers": list(servers), "workloads": scenario.I, "same_periods": len(same),
            "examples": same[:10]}


def server_choice_check(scenario: Scenario, workloads=EXAMPLE_WORKLOADS,
                        servers=EXAMPLE_SERVERS) -> list[dict]:
    """The same workload on server A or B: how long it runs, the server electricity it
    causes (idle part and added part), the fleet's electricity over the whole day, and
    whether it meets the deadline. Every server draws its idle power all day whatever runs
    on it (the model has no on/off decision), so the fleet's idle electricity is the same
    in every option. A run past the end of the day counts in full for the server, and up to
    the end of the day for the fleet."""
    st = RunSettings(scenario=scenario.name)
    dt = scenario.dt_seconds
    supply = _top_supply(scenario)
    to_kwh = dt / 3.6e6
    idle_day = sum(sv.P_idle_W for sv in scenario.servers) * scenario.T * to_kwh
    rows = []
    for i in workloads:
        w = _workload(scenario, i)
        for name in servers:
            sv = _server(scenario, name)
            n = periods_needed(w, sv, dt)
            _, ev = _single_run(scenario, w, sv, n, supply, st)
            k, lo, hi = sv.s - 1, w.A - 1, w.A - 1 + n
            during = float(ev.P_IT_W[k, lo:hi].sum()) * to_kwh
            idle_part = sv.P_idle_W * (hi - lo) * to_kwh
            rows.append({
                "Workload": w.i, "Cores": w.C_req, "Server": sv.name, "Speed (MHz)": sv.f_MHz,
                "Execution time (min)": n * dt / 60,
                "Server electricity during the run (kWh)": round(during, 5),
                "of which idle (kWh)": round(idle_part, 5),
                "of which added by the workload (kWh)": round(during - idle_part, 5),
                "Fleet idle electricity, whole day (kWh)": round(idle_day, 3),
                "Fleet IT electricity, whole day (kWh)": round(float(ev.E_IT_kWh[:scenario.T].sum()), 5),
                "Meets deadline": w.A + n <= w.D,
            })
    return rows


# ---------------------------------------------------------------------------
# B2: reassignment where a move is needed or helps
# ---------------------------------------------------------------------------

def _pick_pair(scenario: Scenario, key) -> tuple[str, str]:
    """(worst, best) server by ``key``, lowest number first among equals."""
    ranked = sorted(scenario.servers, key=lambda sv: (key(sv), sv.s))
    return ranked[-1].name, ranked[0].name


def reassignment_check(scenario: Scenario, necessary=None, helpful=None,
                       T: int = 24) -> list[dict]:
    """Two small cases built from the scenario's real servers, each solved with
    reassignment "none" and "free".

    *Move needed*: a time-sensitive workload starts on a slow server where it cannot meet its
    deadline; on the fast server it can. Expected: "none" has no valid schedule, "free"
    moves it and meets the deadline.
    *Move helps*: a delay-tolerant workload starts on the server that uses the most
    electricity per unit of work; it fits on both. Expected: "free" moves it to the most
    efficient server and emits less carbon than "none".

    ``necessary`` and ``helpful`` are (original server, other server) names; by default the
    slowest and fastest, and the least and most efficient servers."""
    dt = scenario.dt_seconds
    necessary = necessary or _pick_pair(scenario, lambda sv: -sv.f_MHz)
    helpful = helpful or _pick_pair(
        scenario, lambda sv: (sv.P_max_W - sv.P_idle_W) / (sv.C_cores * sv.f_MHz))

    cases = []
    slow, fast = (_server(scenario, n) for n in necessary)
    n_fast = 4
    cores = min(8, slow.C_cores, fast.C_cores)
    work = cores * fast.f_MHz * dt * n_fast
    w = Workload(i=1, workload_id="move-needed", flavor="test", A=2, D=2 + n_fast, AD=0,
                 ET_base=n_fast, RT=1, B=0, X0=1, C_req=cores, M_req_MB=8192.0, W_MHz_s=work)
    cases.append(("Move needed", "time-sensitive", (slow, fast), w))

    worse, better = (_server(scenario, n) for n in helpful)
    n_better = 12
    cores = min(16, worse.C_cores, better.C_cores)
    work = cores * better.f_MHz * dt * n_better
    w = Workload(i=1, workload_id="move-helps", flavor="test", A=2, D=T + 1,
                 AD=T + 1 - 2 - n_better, ET_base=n_better, RT=0, B=0, X0=1, C_req=cores,
                 M_req_MB=16384.0, W_MHz_s=work)
    cases.append(("Move helps", "delay-tolerant", (worse, better), w))

    rows = []
    for case, kind, (orig, other), w in cases:
        toy = _toy(scenario, [orig, other], [w], T, f"reassign-{case}")
        results = {}
        for mode in ("none", "free"):
            st = RunSettings(scenario=toy.name, reassignment=mode, time_limit_s=TOY_TIME_LIMIT_S)
            res = solve(toy, {1: 1}, st)
            ev = (evaluate(toy, res.schedule, res.supply_temp_C, st)
                  if res.has_schedule else None)
            results[mode] = (res, ev)
        for mode, (res, ev) in results.items():
            p = res.schedule.placements[0] if res.has_schedule else None
            on = toy.servers[p.server - 1].name if p else None
            if case == "Move needed":
                expected = ("no valid schedule" if mode == "none"
                            else f"moves to {other.name}, on time")
                ok = (res.status == STATUS_INFEASIBLE if mode == "none" else
                      res.status == STATUS_OPTIMAL and on == other.name and p.end <= w.D)
            else:
                expected = (f"stays on {orig.name}" if mode == "none"
                            else f"moves to {other.name}, less carbon")
                none_ev = results["none"][1]
                ok = (res.status == STATUS_OPTIMAL and on == orig.name if mode == "none" else
                      res.status == STATUS_OPTIMAL and on == other.name and none_ev is not None
                      and ev.total_carbon_g < none_ev.total_carbon_g)
            rows.append({
                "Case": case, "Workload type": kind, "Cores": w.C_req,
                "Starts on": orig.name, "Other server": other.name,
                "Reassignment": mode, "Solver status": status_text(res.status),
                "Runs on": on, "Moved": None if p is None else on != orig.name,
                "Start (period)": p.start if p else None,
                "Finish (period)": p.end if p else None, "Deadline (period)": w.D,
                "Carbon (g CO2)": round(ev.total_carbon_g, 3) if ev else None,
                "Expected": expected, "Pass": bool(ok),
            })
    return rows


# ---------------------------------------------------------------------------
# B1: the CRAC supply temperature is chosen by the solver
# ---------------------------------------------------------------------------

def crac_check(scenario: Scenario, h_mins=(None, 18.0, 19.0, 20.0),
               time_limit_s: float = 120.0) -> tuple[list[dict], list[dict], list[dict]]:
    """Solve the scenario with reassignment "none" (proven best in seconds) at several safety
    margins H_min, with the supply temperature optimized per zone and period. Returns a
    summary row per H_min, the supply temperature of every zone and period, and the CRAC's
    COP at each whole-degree supply temperature.

    With a wide margin no temperature limit binds and the solver keeps the supply at the top
    of its range, where the CRAC's COP is highest. Narrow enough, a server would pass its cap
    and the solver lowers the supply in just those periods. Too narrow, and no schedule
    exists (the infeasibility diagnosis names the limit)."""
    c = scenario.constants
    top = _top_supply(scenario)
    rows, supply_rows = [], []
    for h in h_mins:
        st = RunSettings(scenario=scenario.name, reassignment="none", H_min_C=h,
                         time_limit_s=time_limit_s)
        base = build_baseline(scenario, st)
        original = base.server_of()
        res = solve(scenario, original, st, warm_start=base,
                    warm_start_supply_temp_C=constant_supply_temp(scenario, st.baseline_supply_temp_C))
        h_val = st.h_min(scenario)
        row = {"H_min (°C)": h_val, "Thermal cap (°C)": st.thermal_cap_C(scenario),
               "Solver status": status_text(res.status)}
        if res.has_schedule:
            ev = evaluate(scenario, res.schedule, res.supply_temp_C, st)
            sup = np.asarray(res.supply_temp_C)
            below = []
            for z in range(scenario.Z):
                lows = [(t + 1, sup[z, t]) for t in range(scenario.T) if sup[z, t] < top - 1e-9]
                below += [f"zone {z + 1}, period {t}: {v:g} °C" for t, v in lows]
                row[f"Zone {z + 1} supply, lowest (°C)"] = float(sup[z].min())
                row[f"Zone {z + 1} periods below {top:g} °C"] = len(lows)
                for t in range(scenario.T):
                    supply_rows.append({"H_min (°C)": h_val, "Zone": z + 1, "Period": t + 1,
                                        "Supply temperature (°C)": float(sup[z, t])})
            row.update({
                "Hottest server (°C)": round(float(ev.T_C.max()), 2),
                "Carbon (kg CO2)": round(ev.total_carbon_g / 1000, 4),
                "Lower supply in": "; ".join(below) or "none",
            })
        elif res.status == STATUS_INFEASIBLE:
            diag = diagnose_infeasibility(scenario, original, st, time_limit_s=time_limit_s)
            row["Lower supply in"] = ("no valid schedule; feasible only without: "
                                      + (", ".join(f for f, v in diag.items() if v == "feasible")
                                         or "none of the limits"))
        rows.append(row)
    cop_rows = [{"Supply temperature (°C)": float(k), "COP": round(float(cop(c, k)), 4)}
                for k in range(math.ceil(c.T_crac_min_C), int(top) + 1)]
    return rows, supply_rows, cop_rows


# ---------------------------------------------------------------------------
# B6: a hot server slows down and the run gets longer
# ---------------------------------------------------------------------------

def slowdown_check(scenario: Scenario, server: str | None = None, share: float = 0.75,
                   periods: int = 6, supplies=(18.0, None), h_min: float = 5.0) -> list[dict]:
    """One workload that fills ``share`` of a server's cores and needs exactly ``periods``
    periods at full speed, solved alone on that server with the supply temperature fixed.
    At the cooler supply the server stays below T_dvfs and the run takes ``periods``; at the
    warmer one it passes T_dvfs, DPF drops below 1 and the run needs an extra period.
    ``h_min`` 5 °C (the 6.3 low margin) leaves room above T_dvfs before the cap. A row passes
    when the run takes exactly ``periods`` with DPF 1 throughout, and longer once DPF drops.
    By default the server is the one that heats up fastest under this load."""
    c = scenario.constants
    dt = scenario.dt_seconds
    top = _top_supply(scenario)
    supplies = tuple(top if s is None else float(s) for s in supplies)
    if server is None:
        def heat(sv):
            p = sv.P_idle_W + (sv.P_max_W - sv.P_idle_W) * share
            temp = sv.T0_C
            for _ in range(periods):
                temp = sv.th_alpha * temp + (1 - sv.th_alpha) * (top + sv.th_a_C + sv.th_R_C_per_W * p)
            return temp
        server = max(scenario.servers, key=heat).name
    sv = _server(scenario, server)
    cores = max(1, round(share * sv.C_cores))
    work = cores * sv.f_MHz * dt * periods
    T = periods + 4
    w = Workload(i=1, workload_id="slowdown", flavor="test", A=1, D=T + 1, AD=0,
                 ET_base=periods, RT=0, B=0, X0=1, C_req=cores, M_req_MB=1.0, W_MHz_s=work)
    toy = _toy(scenario, [sv], [w], T, f"slowdown-{sv.name}")
    rows = []
    for sup in supplies:
        st = RunSettings(scenario=toy.name, reassignment="none", supply_temp_mode="fixed",
                         fixed_supply_temp_C=sup, H_min_C=h_min, time_limit_s=TOY_TIME_LIMIT_S)
        res = solve(toy, {1: 1}, st)
        row = {"Server": sv.name, "Cores": cores, "CPU use (%)": round(cores / sv.C_cores * 100, 1),
               "Supply temperature (°C)": sup, "H_min (°C)": h_min,
               "T_dvfs (°C)": c.T_dvfs_C, "Periods at full speed": periods,
               "Solver status": status_text(res.status)}
        if res.has_schedule:
            ev = evaluate(toy, res.schedule, res.supply_temp_C, st)
            p = res.schedule.placements[0]
            idx = slice(p.start - 1, p.end - 1)
            row.update({
                "Hottest temperature during the run (°C)": round(float(ev.T_C[0, idx].max()), 2),
                "Lowest DPF during the run": round(float(ev.DPF[0, idx].min()), 4),
                "Periods run": p.end - p.start,
                "Execution time (min)": (p.end - p.start) * dt / 60,
                "Work delivered / required": round(float(ev.work_delivered_MHz_s[0]) / work, 4),
                "Valid under the evaluator": ev.valid,
            })
        rows.append(row)
    for r in rows:
        if "Periods run" in r:
            # at full speed the work fits exactly, so any slowdown needs an extra period
            slowed = r["Lowest DPF during the run"] < 1.0
            r["Pass"] = r["Valid under the evaluator"] and (
                r["Periods run"] > periods if slowed else r["Periods run"] == periods)
    return rows


def throttled_run_rows(run_dir: Path, scenario: Scenario) -> tuple[list[dict], list[dict]]:
    """From a solved run: every server that slowed (DPF < 1), and every workload that ran
    while its server was slowed, with its run length against the full-speed length."""
    run_dir = Path(run_dir)
    sp = _read_csv(run_dir / "optimized" / "server_period.csv")
    sched = _read_csv(run_dir / "optimized" / "schedule.csv")
    names = {sv.s: sv.name for sv in scenario.servers}
    slow: dict[int, list[tuple[int, float, float]]] = {}
    for r in sp:
        d = float(r["DPF"])
        if d < 1.0 - 1e-9:
            slow.setdefault(int(r["s"]), []).append((int(r["t"]), d, float(r["temperature_C"])))
    servers = [{
        "Server": names.get(s, s), "Periods slowed": len(v),
        "Periods": ", ".join(str(t) for t, _, _ in v),
        "Lowest DPF": round(min(d for _, d, _ in v), 4),
        "Hottest temperature (°C)": round(max(x for _, _, x in v), 2),
    } for s, v in sorted(slow.items())]
    slow_set = {(s, t) for s, v in slow.items() for t, _, _ in v}
    work = []
    for r in sched:
        if r.get("placed") in ("0", "") or not r.get("server"):
            continue
        s, start, n = int(r["server"]), int(r["start"]), int(r["periods_run"])
        hit = [t for t in range(start, start + n) if (s, t) in slow_set]
        if not hit:
            continue
        w = scenario.workloads[int(r["i"]) - 1]
        full = periods_needed(w, scenario.servers[s - 1], scenario.dt_seconds)
        work.append({
            "Workload": w.i, "Server": names.get(s, s), "Periods slowed": len(hit),
            "Periods at full speed": full, "Periods run": n, "Extra periods": n - full,
            "Spare work from rounding up (%)": round(
                (full * w.C_req * scenario.servers[s - 1].f_MHz * scenario.dt_seconds
                 / w.W_MHz_s - 1) * 100, 2),
            "Work delivered / required": round(float(r["work_delivered_MHz_s"])
                                               / float(r["work_required_MHz_s"]), 4),
            "Finish (period)": int(r["finish"]), "Deadline (period)": int(r["deadline"]),
        })
    return servers, work


# ---------------------------------------------------------------------------
# B8: cold plates, checked on a run that has them
# ---------------------------------------------------------------------------

def cold_plate_rows(run_dir: Path, scenario: Scenario,
                    no_plate_run_dir: Path | None = None) -> list[dict]:
    """Every limit of the cold plates, per server with plates, from a solved run; and the
    server's hottest temperature against a run without cold plates, if given."""
    run_dir = Path(run_dir)
    summary = json.loads((run_dir / "summary.json").read_text())
    cps = summary.get("cold_plates") or {}
    if not cps.get("enabled"):
        raise ValueError(f"{run_dir.name} has cold plates off")
    plates = cps["plates_per_server"]
    flows = [float(f) for f in cps["flow_settings_Lmin"]]
    lo_c, hi_c = cps["coolant_limits_C"]
    q_max = float(cps["Q_max_per_plate_W"])
    sp = _read_csv(run_dir / "optimized" / "server_period.csv")
    hot_without = {}
    if no_plate_run_dir is not None and (Path(no_plate_run_dir) / "optimized").is_dir():
        for r in _read_csv(Path(no_plate_run_dir) / "optimized" / "server_period.csv"):
            s = int(r["s"])
            hot_without[s] = max(hot_without.get(s, -1e9), float(r["temperature_C"]))
    dt_h = scenario.dt_seconds / 3600.0
    rows = []
    for sv in scenario.servers:
        n = int(plates[sv.s - 1])
        if n == 0:
            continue
        mine = [r for r in sp if int(r["s"]) == sv.s]
        q = [float(r["Q_cp_W"]) for r in mine]
        p_it = [float(r["P_IT_W"]) for r in mine]
        flow = [float(r["cp_flow_Lmin"]) for r in mine if r["cp_flow_Lmin"] != ""]
        cool = [float(r["cp_coolant_C"]) for r in mine if r["cp_coolant_C"] != ""]
        pump_wh = sum(float(r["P_cp_W"]) for r in mine) * dt_h
        hot = max(float(r["temperature_C"]) for r in mine)
        checks = {
            "Heat removed ≤ server heat": all(a <= b + 1e-6 for a, b in zip(q, p_it)),
            f"Heat removed ≤ {q_max:g} W per plate": max(q) <= n * q_max + 1e-6,
            "Flow is one of the settings": all(any(abs(f - x) < 1e-6 for x in flows) for f in flow),
            "Coolant within limits": all(lo_c - 1e-6 <= x <= hi_c + 1e-6 for x in cool),
        }
        rows.append({
            "Server": sv.name, "Cold plates": n,
            "Peak heat removed (W)": round(max(q), 2), "Peak server heat (W)": round(max(p_it), 2),
            "Heat removed over the day (kWh)": round(sum(q) * dt_h / 1000, 4),
            "Flow used (L/min)": ", ".join(f"{x:g}" for x in sorted(set(flow))),
            "Coolant used (°C)": f"{min(cool):g}–{max(cool):g}" if cool else "",
            "Pump electricity (Wh)": round(pump_wh, 5),
            "Hottest temperature (°C)": round(hot, 2),
            "Hottest without cold plates (°C)": (round(hot_without[sv.s], 2)
                                                  if sv.s in hot_without else None),
            **checks,
            "Pass": all(checks.values()),
        })
    return rows


# ---------------------------------------------------------------------------
# B3 and A1: how complete each solver result is
# ---------------------------------------------------------------------------

def runs_of(results_dir: Path, scenario_name: str) -> list[Path]:
    """Every run folder under ``<results_dir>/<folder>/<run>/`` solved on the scenario, by the
    name in its summary.json: ``results/<scenario>/`` as the notebooks write it, or a folder
    such as ``results/servers10/`` that holds renamed runs."""
    out = []
    for d in sorted(Path(results_dir).glob("*/*/summary.json")):
        if d.parent.parent.name.startswith("archive-"):
            continue
        try:
            name = (json.loads(d.read_text()).get("scenario") or {}).get("name")
        except (OSError, ValueError):
            continue
        if (name or d.parent.parent.name) == scenario_name:
            out.append(d.parent)
    return out


def _named_run(runs: list[Path], names: tuple[str, ...]) -> Path | None:
    for name in names:
        for d in runs:
            if d.name == name:
                return d
    return None


def solver_rows(results_dir: Path, scenario_name: str) -> list[dict]:
    """One row per run of the scenario: what it allowed, the solver's status in plain words,
    the gap, the solve time, carbon, the solver's lower bound, and the most a better
    schedule could still save (carbon minus bound)."""
    rows = []
    for run in runs_of(results_dir, scenario_name):
        d = run / "summary.json"
        s = json.loads(d.read_text())
        st, sol = s.get("settings") or {}, s.get("solver") or {}
        opt = (s.get("optimized") or {}).get("metrics") or {}
        carbon = opt.get("carbon_kg") if s.get("has_optimized_schedule") else None
        bound = sol.get("best_bound_g")
        supply = ("optimized" if st.get("supply_temp_mode") == "optimize" else
                  f"fixed {st.get('fixed_supply_temp_C') or st.get('baseline_supply_temp_C'):g} °C")
        rows.append({
            "Run": d.parent.name,
            "Release": (s.get("provenance") or {}).get("thermasched_version"),
            "Reassignment": str(st.get("reassignment", "")).replace("_", " "),
            "CRAC supply": supply,
            "Cold plates": bool(st.get("cold_plates")),
            "H_min (°C)": st.get("H_min_C"),
            "Time limit (s)": st.get("time_limit_s"),
            # a thermal-blind run reports its second pass, which keeps the servers fixed
            "Solver status": status_text(sol.get("status")) + (
                " (servers fixed in pass 2)" if st.get("placement") == "thermal_blind" else ""),
            "MIP gap (%)": None if sol.get("mip_gap") is None else round(sol["mip_gap"] * 100, 3),
            "Solve time (s)": None if sol.get("solve_time_s") is None else round(sol["solve_time_s"], 1),
            "Carbon (kg CO2)": None if carbon is None else round(carbon, 4),
            "Lower bound (kg CO2)": None if bound is None else round(bound / 1000, 4),
            "Most a better schedule could save (kg CO2)": (
                None if carbon is None or bound is None else round(max(0.0, carbon - bound / 1000), 4)),
            "Workloads moved": opt.get("n_reassigned"),
        })
    return rows


# ---------------------------------------------------------------------------
# Writing every table
# ---------------------------------------------------------------------------

def _read_csv(path: Path) -> list[dict]:
    with open(path, newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def write_table(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields: list[str] = []
    for r in rows:
        fields += [k for k in r if k not in fields]
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in rows:
            w.writerow({k: ("" if v is None else v) for k, v in r.items()})


# Runs the run-based checks read, under results/<scenario>/ (or another scenario's folder).
# The run with cold plates on and the base run, by the names a run may have: the short
# Chapter 6 name, or the name the solver gives it.
COLD_PLATE_RUN = ("s2_base", "least_loaded_base18_free_optimize_cp_tl1800")
NO_PLATE_RUN = ("base", "least_loaded_base18_free_optimize_tl1800")
WARM_RUN = ("thesis10_warm", "least_loaded_base18_free_optimize")


def _passed(rows, key="Pass"):
    vals = [r[key] for r in rows if r.get(key) is not None]
    return None if not vals else all(vals)


def write_all(scenario_name: str = "servers6", scenarios_dir="scenarios", results_dir="results",
              out_dir=None, log=print) -> dict:
    """Run every check on the scenario and write the tables to
    ``<results_dir>/validation/<scenario>/``. Returns what validation.json holds."""
    scenarios_dir, results_dir = Path(scenarios_dir), Path(results_dir)
    out = Path(out_dir) if out_dir else results_dir / "validation" / scenario_name
    sc = load_scenario(scenario_name, scenarios_dir)
    params = json.loads((scenarios_dir / scenario_name / "params.json").read_text())
    hour = (params.get("time") or {}).get("period_1_local_hour")
    checks: dict = {}

    def table(key, rows, note=None):
        write_table(out / f"{key}.csv", rows)
        checks[key] = {"rows": len(rows), "passed": _passed(rows), **({"note": note} if note else {})}
        log(f"  {key}: {len(rows)} rows, passed = {checks[key]['passed']}")

    log(f"Validation of {scenario_name} (release {VERSION}) -> {out}/")
    table("workload_inputs", workload_inputs(sc, hour))
    table("power", power_check(sc))
    examples = [n for n in EXAMPLE_SERVERS if any(sv.name == n for sv in sc.servers)]
    servers = examples if len(examples) == 2 else [sc.servers[0].name, sc.servers[-1].name]
    work = [i for i in EXAMPLE_WORKLOADS if i <= sc.I] or [1]
    table("execution_time", execution_check(sc, work, servers, hour))
    checks["execution_time"]["equal_periods"] = equal_time_count(sc, servers)
    table("server_choice", server_choice_check(sc, work, servers))
    table("reassignment", reassignment_check(sc, necessary=tuple(servers)))
    crac, supply, cops = crac_check(sc)
    table("crac", crac)
    table("crac_supply", supply)
    table("crac_cop", cops)
    table("slowdown", slowdown_check(sc))

    warm_dir = results_dir / WARM_RUN[0] / WARM_RUN[1]
    if (warm_dir / "summary.json").is_file() and (scenarios_dir / WARM_RUN[0]).is_dir():
        srv, wl = throttled_run_rows(warm_dir, load_scenario(WARM_RUN[0], scenarios_dir))
        table("throttled_servers", srv, note=f"{WARM_RUN[0]}/{WARM_RUN[1]}")
        table("throttled_workloads", wl, note=f"{WARM_RUN[0]}/{WARM_RUN[1]}")
    runs = runs_of(results_dir, scenario_name)
    cp_dir, base_dir = _named_run(runs, COLD_PLATE_RUN), _named_run(runs, NO_PLATE_RUN)
    if cp_dir is not None:
        table("cold_plates", cold_plate_rows(cp_dir, sc, base_dir),
              note=f"{cp_dir.parent.name}/{cp_dir.name}")
    table("solver", solver_rows(results_dir, scenario_name))

    meta = {"scenario": scenario_name, "scenario_fingerprint": sc.fingerprint,
            "thermasched_version": VERSION,
            "created_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "period_1_local_hour": hour, "dt_seconds": sc.dt_seconds,
            "checks": checks}
    (out / "validation.json").write_text(json.dumps(meta, indent=2) + "\n")
    return meta


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="scheduler.validate", description=__doc__.split("\n\n")[0])
    p.add_argument("--scenario", default="servers6")
    p.add_argument("--scenarios-dir", default="scenarios")
    p.add_argument("--results-dir", default="results")
    a = p.parse_args(argv)
    meta = write_all(a.scenario, a.scenarios_dir, a.results_dir)
    failed = [k for k, v in meta["checks"].items() if v["passed"] is False]
    if failed:
        print(f"FAILED: {failed}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
