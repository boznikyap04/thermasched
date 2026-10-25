"""Per-tick re-planning (docs/PLAN.md section 2, option 2A).

At every tick t (one period) the optimizer of optimize.py solves a window that runs from t to
the end of the horizon. The window holds:

- the workloads that have arrived (A_i <= t) and not started, with their arrival, deadline and
  allowed delay measured from t; workloads that arrive later are not in it;
- the workloads already running, on their server and with their start fixed (they occupy the
  window from its first period), counting only the work they have left;
- each server's temperature at the end of period t - 1 as T0 (Eq. 30);
- the supply temperatures of the last periods as fixed history, so the ramp limits (35)-(36)
  hold across ticks;
- the carbon intensity of every remaining period.

Only period t's decisions are kept: which workloads start at t and on which server, the supply
temperature of each zone and the cold-plate settings. The rest of the plan is offered to the
next tick as a starting solution and otherwise discarded. Period t is then played out with the
same physics as the evaluator: the server temperatures, and for every running workload the work
delivered at the DPF it actually ran at. A running workload ends once its work is done.

A tick with no valid schedule stops the run and names the limit; nothing is relaxed. The state
is saved after every tick in ``<run folder>/checkpoint/``, so a stopped run resumes where it
stopped and gives the same schedule.
"""

from __future__ import annotations

import csv
import dataclasses
import json
import math
import os
import shutil
import time
from dataclasses import dataclass, field, replace
from pathlib import Path

import numpy as np

from .evaluate import dpf
from .optimize import WindowExtras, _build, _solve_impl, diagnose_infeasibility, solve
from .types import (
    RELAX_CAPACITY, RELAX_COOLING, RELAX_DEADLINES, RELAX_PRIORITY, RELAX_THERMAL,
    STATUS_INFEASIBLE, STATUS_NO_SOLUTION, STATUS_OPTIMAL, STATUS_TIME_LIMIT, ColdPlateOps,
    Placement, RunSettings, Scenario, Schedule, SolveResult, cold_plate_counts, priority_pairs,
)

CHECKPOINT_DIR = "checkpoint"
STATE_FILE = "state.json"
TICKS_FILE = "ticks.csv"
PARTIAL_FILE = "partial_schedule.csv"
CHECKPOINT_FORMAT = 1
DONE_REL_TOL = 1e-7         # a running workload ends once it has delivered W * (1 - this)
BLIND_SHARE = 0.7           # thermal-blind placement: share of the tick limit for pass 1

OUTCOME_DONE = "done"
OUTCOME_STOPPED = "stopped"     # wall-time limit: resume by running the same command again
OUTCOME_STUCK = "stuck"         # a tick has no valid schedule

# Limits a stuck tick can name.
LIMIT_SUPPLY_RAMP = "supply_ramp"
LIMIT_TICK_TIME = "tick_time_limit"
LIMIT_COMBINATION = "several_limits_together"
LIMIT_MODEL = "model_input"
LIMIT_TEXT = {
    RELAX_DEADLINES: "deadlines and allowed waiting (Eq. 27-28)",
    RELAX_THERMAL: "thermal cap T <= T_max - H_min (Eq. 31-33)",
    RELAX_CAPACITY: "server CPU and memory capacity (Eq. 12-13)",
    RELAX_COOLING: "CRAC cooling capacity (Eq. 54)",
    RELAX_PRIORITY: "priority (Eq. 56-57)",
    LIMIT_SUPPLY_RAMP: "supply-air ramp limits across ticks (Eq. 35-36)",
    LIMIT_TICK_TIME: "no schedule found within the tick time limit",
    LIMIT_COMBINATION: "no single limit: only several relaxed together would allow a schedule",
    LIMIT_MODEL: "the window's inputs are outside what the model accepts",
}

TICK_COLUMNS = ["tick", "status", "solve_s", "mip_gap", "n_waiting", "n_started", "n_running",
                "n_arrived", "n_done", "objective_g", "kept_carbon_g", "n_binaries",
                "n_constraints", "tick_wall_s"]


@dataclass
class PerTickOutcome:
    """What run_per_tick returns. ``schedule`` and the arrays are None unless status is done."""
    status: str
    ticks: list[dict]
    schedule: Schedule | None = None
    supply_temp_C: np.ndarray | None = None
    cold_plate_ops: ColdPlateOps | None = None
    result: SolveResult | None = None
    stuck: dict | None = None
    resumed_from_tick: int | None = None
    next_tick: int | None = None


@dataclass
class _State:
    """Everything the next tick needs; saved as JSON after every tick."""
    next_tick: int
    temp: list[float]                       # (S,) server temperature at the end of next_tick - 1
    supply: list[list[float]]               # (Z, next_tick - 1) kept supply temperatures
    cp_flow: list[list[float | None]]       # (S, next_tick - 1), None without cold plates
    cp_coolant: list[list[float | None]]
    server: dict[int, int] = field(default_factory=dict)
    start: dict[int, int] = field(default_factory=dict)
    end: dict[int, int] = field(default_factory=dict)
    delivered: dict[int, float] = field(default_factory=dict)
    plan: dict[int, list[int]] | None = None        # last window's plan, original periods
    plan_supply: list[list[float]] | None = None    # last window's supply, (Z, its T)
    ticks: list[dict] = field(default_factory=list)
    tick_status: dict[str, int] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)  # model notes of the first tick
    max_size: list[int] = field(default_factory=lambda: [0, 0, 0])

    def to_json(self) -> dict:
        d = dataclasses.asdict(self)
        for k in ("server", "start", "end", "delivered", "plan"):
            if d[k] is not None:
                d[k] = {str(i): v for i, v in d[k].items()}
        return d

    @classmethod
    def from_json(cls, d: dict) -> "_State":
        d = dict(d)
        for k in ("server", "start", "end", "delivered", "plan"):
            if d.get(k) is not None:
                d[k] = {int(i): v for i, v in d[k].items()}
        return cls(**d)


# ---------------------------------------------------------------------------
# Checkpoint
# ---------------------------------------------------------------------------

def _plain(x):
    """JSON round trip, so settings compare equal whether fresh or read back."""
    from .report import to_jsonable
    return json.loads(json.dumps(to_jsonable(x)))


def _write_json_atomic(path: Path, data: dict) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w") as fh:
        json.dump(data, fh, allow_nan=False)
    os.replace(tmp, path)


def _save_checkpoint(folder: Path, settings: RunSettings, scenario: Scenario,
                     state: _State) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    _write_json_atomic(folder / STATE_FILE, {
        "format": CHECKPOINT_FORMAT, "settings": _plain(settings.as_dict()),
        "scenario_fingerprint": scenario.fingerprint, "state": state.to_json()})


def _load_checkpoint(folder: Path, settings: RunSettings, scenario: Scenario) -> _State | None:
    path = folder / STATE_FILE
    if not path.is_file():
        return None
    with open(path) as fh:
        data = json.load(fh)
    if data.get("format") != CHECKPOINT_FORMAT:
        raise ValueError(f"{path}: checkpoint format {data.get('format')} is not "
                         f"{CHECKPOINT_FORMAT}; delete the folder to start again")
    if data.get("settings") != _plain(settings.as_dict()):
        theirs, ours = data.get("settings") or {}, _plain(settings.as_dict())
        diff = sorted(k for k in set(theirs) | set(ours) if theirs.get(k) != ours.get(k))
        raise ValueError(f"{path}: the checkpoint was made with other settings ({', '.join(diff)}); "
                         "run the same command, or delete the folder to start again")
    if data.get("scenario_fingerprint") != scenario.fingerprint:
        raise ValueError(f"{path}: the checkpoint was made on another build of scenario "
                         f"{scenario.name}; delete the folder to start again")
    return _State.from_json(data["state"])


def _write_ticks(path: Path, ticks: list[dict]) -> None:
    from .report import _cell
    with open(path, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(TICK_COLUMNS)
        for r in ticks:
            w.writerow([_cell(r.get(c)) for c in TICK_COLUMNS])


# ---------------------------------------------------------------------------
# One tick
# ---------------------------------------------------------------------------

class _Tick:
    """The window of tick t: its scenario and the maps between window and day numbers."""

    def __init__(self, scenario: Scenario, original: dict[int, int], state: _State, t: int,
                 pairs_by_i: dict[int, list[int]], pairs: list[tuple[int, int]],
                 settings: RunSettings):
        self.t = t
        running = sorted(i for i in state.start if i not in state.end)
        waiting = sorted(w.i for w in scenario.workloads
                         if w.A <= t and w.i not in state.start)
        self.running, self.waiting = running, waiting
        self.ids = sorted(running + waiting)              # window workload k is ids[k - 1]
        self.k_of = {i: k for k, i in enumerate(self.ids, start=1)}
        run_set = set(running)
        wl, orig = [], {}
        for k, i in enumerate(self.ids, start=1):
            w = scenario.workloads[i - 1]
            if i in run_set:
                # running: occupies the window from its first period, on its server, with the
                # work it has left; no wait limit applies any more
                wl.append(replace(w, i=k, A=1, AD=0, D=w.D - t + 1, B=1,
                                  W_MHz_s=w.W_MHz_s - state.delivered[i]))
                orig[k] = state.server[i]
            else:
                # waiting: the latest start A + AD stays where it was
                wl.append(replace(w, i=k, A=1, AD=w.A + w.AD - t, D=w.D - t + 1))
                orig[k] = original[i]
        self.original = orig
        servers = tuple(replace(sv, T0_C=float(state.temp[sv.s - 1])) for sv in scenario.servers)
        av = None if scenario.AV is None else np.asarray(scenario.AV)[:, t - 1:]
        self.scenario = replace(
            scenario, name=f"{scenario.name}@tick{t}", T=scenario.T - t + 1,
            workloads=tuple(wl), servers=servers,
            CI_g_per_kWh=np.asarray(scenario.CI_g_per_kWh, dtype=float)[t - 1:], AV=av,
            fingerprint=None)

        # Priority: pairs between waiting workloads keep their whole-day order. A waiting i may
        # not use the server of a started j that started while i was waiting (A_i <= ST_j),
        # or j would have overtaken it there.
        wait_set = set(waiting)
        win_pairs = tuple((self.k_of[i], self.k_of[j]) for i, j in pairs
                          if i in wait_set and j in wait_set)
        forbidden: dict[int, frozenset[int]] = {}
        if settings.priority:
            for i in waiting:
                A_i = scenario.workloads[i - 1].A
                bad = {state.server[j] for j in pairs_by_i.get(i, ())
                       if j in state.start and A_i <= state.start[j]}
                if bad:
                    forbidden[self.k_of[i]] = frozenset(bad)
        hist = None
        if state.supply and len(state.supply[0]):
            c = scenario.constants
            h = min(max(c.ramp_short_lag, c.ramp_long_lag), len(state.supply[0]))
            hist = np.asarray(state.supply, dtype=float)[:, -h:]
        self.extras = WindowExtras(priority_pairs=win_pairs, forbidden=forbidden or None,
                                   supply_history=hist)

    def warm_start(self, state: _State):
        """The previous tick's plan in window numbers; new arrivals are left open."""
        if state.plan is None:
            return None, None
        run_set = set(self.running)
        pl = []
        for k, i in enumerate(self.ids, start=1):
            p = state.plan.get(i)
            if p is None:
                pl.append(Placement(k, None, None, None))
                continue
            s, st, en = p
            st = 1 if i in run_set else st - self.t + 1
            en = en - self.t + 1
            pl.append(Placement(k, s, st, en) if st >= 1 and en > st
                      else Placement(k, None, None, None))
        sup = None
        if state.plan_supply is not None:
            arr = np.asarray(state.plan_supply, dtype=float)
            if arr.shape[1] == self.scenario.T + 1:
                sup = arr[:, 1:]
        return Schedule(tuple(pl)), sup


def _solve_tick(tick: _Tick, settings: RunSettings, warm, warm_supply, log: bool) -> SolveResult:
    sc, limit = tick.scenario, settings.tick_time_limit_s
    if settings.placement != "thermal_blind":
        return solve(sc, tick.original, settings, warm_start=warm,
                     warm_start_supply_temp_C=warm_supply, time_limit_s=limit, log=log,
                     extras=tick.extras)
    # thermal-blind: servers chosen with temperature left out, then the full model on them
    pass1 = solve(sc, tick.original, settings, warm_start=warm,
                  warm_start_supply_temp_C=warm_supply, time_limit_s=BLIND_SHARE * limit,
                  log=log, ignore_temperature=True, extras=tick.extras)
    if not pass1.has_schedule:
        return pass1
    servers = pass1.schedule.server_of()
    extras = replace(tick.extras, forbidden=None)        # pass 1 already kept to them
    pass2 = solve(sc, servers, replace(settings, reassignment="none"),
                  warm_start=pass1.schedule, warm_start_supply_temp_C=pass1.supply_temp_C,
                  time_limit_s=max(1.0, limit - pass1.solve_time_s), log=log, extras=extras)
    pass2.solve_time_s += pass1.solve_time_s
    return pass2


def _kept_carbon_g(tick: _Tick, res: SolveResult) -> float | None:
    """Carbon of period t by the solver's own numbers (the objective's period-t terms)."""
    mv = res.model_values
    if "P_crac_kW" not in mv:
        return None
    kw = (mv["P_IT_W"][:, 0].sum() + mv["P_cp_W"][:, 0].sum()) / 1000.0 \
        + mv["P_crac_kW"][:, 0].sum() + mv["P_fan_kW"][:, 0].sum()
    return float(tick.scenario.CI_g_per_kWh[0] * tick.scenario.dt_hours * kw)


def _diagnose(tick: _Tick, settings: RunSettings, res: SolveResult | None, error: str | None,
              time_limit_s: float) -> dict:
    """Which limit leaves tick t with no valid schedule."""
    ids = tick.ids
    out: dict = {"tick": tick.t, "status": None if res is None else res.status,
                 "solver_status_text": error if res is None else res.solver_status_text,
                 "n_waiting": len(tick.waiting), "n_running": len(tick.running)}
    if res is None:
        limits, detail = [LIMIT_MODEL], error
    elif res.status == STATUS_NO_SOLUTION:
        limits = [LIMIT_TICK_TIME]
        detail = (f"HiGHS stopped at the tick time limit ({settings.tick_time_limit_s:g} s) "
                  "without a schedule; whether one exists is not known")
    else:
        built = _build(tick.scenario, tick.original, settings, (), False,
                       extras=tick.extras)
        if built.empty_workloads:
            free = _build(tick.scenario, tick.original, settings, (), False,
                          extras=replace(tick.extras, forbidden=None))
            who = [ids[k - 1] for k in built.empty_workloads]
            out["workloads"] = [tick_wid(tick, k) for k in built.empty_workloads]
            if not free.empty_workloads:
                limits = [RELAX_PRIORITY]
                detail = (f"workload(s) {who} may use no server: on every server they may use, "
                          "a lower-priority workload started while they waited")
            else:
                limits = [RELAX_DEADLINES]
                detail = (f"workload(s) {who} have no server and start left that meets their "
                          "allowed delay and deadline")
        else:
            base = _solve_impl(tick.scenario, tick.original, settings, relax=(), warm_start=None,
                               warm_start_supply_temp_C=None, time_limit_s=time_limit_s,
                               log=False, feasibility_only=True, extras=tick.extras)
            if base.status in (STATUS_OPTIMAL, STATUS_TIME_LIMIT):
                limits = [LIMIT_SUPPLY_RAMP]
                detail = ("a schedule exists with the supply temperature free of its recent "
                          "history, so the ramp limits from the previous ticks block it")
            else:
                fams = diagnose_infeasibility(tick.scenario, tick.original, settings,
                                              time_limit_s=time_limit_s, extras=tick.extras)
                out["relaxed_one_at_a_time"] = fams
                freed = [f for f, v in fams.items() if v == "feasible"]
                limits = freed or [LIMIT_COMBINATION]
                detail = ("relaxing " + " or ".join(LIMIT_TEXT[f] for f in freed)
                          + " alone gives a schedule") if freed else LIMIT_TEXT[LIMIT_COMBINATION]
    out["limits"] = limits
    out["limit_text"] = "; ".join(LIMIT_TEXT[x] for x in limits)
    out["detail"] = detail
    return out


def tick_wid(tick: _Tick, k: int) -> str:
    return tick.scenario.workloads[k - 1].workload_id


def _play_period(scenario: Scenario, plates: np.ndarray, state: _State, t: int,
                 supply_t: np.ndarray, flow_t: np.ndarray, cool_t: np.ndarray) -> None:
    """Period t with the kept decisions, by the evaluator's physics: temperatures, work
    delivered at the DPF actually reached, and the end of every workload whose work is done."""
    S = scenario.S
    running = sorted(i for i in state.start if i not in state.end)
    cpu = np.zeros(S)
    for i in running:
        cpu[state.server[i] - 1] += scenario.workloads[i - 1].C_req
    cp = scenario.cold_plate
    G = cp.conductance_W_per_C()
    temp = np.zeros(S)
    for sv in scenario.servers:
        k = sv.s - 1
        P = sv.P_idle_W + (sv.P_max_W - sv.P_idle_W) * (cpu[k] / sv.C_cores)
        Q = 0.0
        n = int(plates[k])
        if n > 0:
            lv = cp.level_of(float(flow_t[k]))
            drive = max(0.0, state.temp[k] - float(cool_t[k]))
            Q = min(n * cp.Q_max_per_plate_W, P, n * G[lv] * drive)
        steady = supply_t[sv.zone - 1] + sv.th_a_C + sv.th_R_C_per_W * (P - Q)
        temp[k] = sv.th_alpha * state.temp[k] + (1.0 - sv.th_alpha) * steady
    D = dpf(temp, scenario.constants)
    dt = scenario.dt_seconds
    for i in running:
        w = scenario.workloads[i - 1]
        sv = scenario.servers[state.server[i] - 1]
        state.delivered[i] += w.C_req * sv.f_MHz * dt * float(D[sv.s - 1])
        if state.delivered[i] >= w.W_MHz_s * (1.0 - DONE_REL_TOL):
            state.end[i] = t + 1
    state.temp = [float(x) for x in temp]


# ---------------------------------------------------------------------------
# The loop
# ---------------------------------------------------------------------------

def _initial_state(scenario: Scenario) -> _State:
    S, Z = scenario.S, scenario.Z
    return _State(next_tick=1, temp=[float(sv.T0_C) for sv in scenario.servers],
                  supply=[[] for _ in range(Z)], cp_flow=[[] for _ in range(S)],
                  cp_coolant=[[] for _ in range(S)])


def _aggregate(scenario: Scenario, state: _State) -> SolveResult:
    ticks = state.ticks
    n = len(ticks)
    n_opt = state.tick_status.get(STATUS_OPTIMAL, 0)
    n_tl = state.tick_status.get(STATUS_TIME_LIMIT, 0)
    gaps = [r["mip_gap"] for r in ticks if r.get("mip_gap") is not None]
    kept = [r["kept_carbon_g"] for r in ticks]
    slow = max(ticks, key=lambda r: r["solve_s"]) if ticks else {"solve_s": 0.0, "tick": None}
    notes = list(state.notes) + [
        "Per-tick re-planning: the model above is solved once per tick over a window from the "
        "tick to the end of the horizon, holding only the workloads that have arrived; running "
        "workloads keep their server and start and count only the work they have left; T0 is "
        "each server's temperature at the end of the previous tick (Eq. 30), and the supply "
        "temperatures of the previous ticks bound the ramps (35)-(36). Only the tick's own "
        "decisions are kept.",
        f"{n} ticks: {n_opt} solved to the gap, {n_tl} stopped at the tick time limit "
        f"(slowest {slow['solve_s']:.1f} s, tick {slow['tick']}). "
        "The objective is the sum of each tick's own carbon for its period; the gap shown is "
        "the largest of any tick.",
    ]
    return SolveResult(
        status=STATUS_OPTIMAL if n_tl == 0 else STATUS_TIME_LIMIT, schedule=None,
        supply_temp_C=None,
        objective_g=None if any(k is None for k in kept) else float(sum(kept)),
        best_bound_g=None, mip_gap=max(gaps) if gaps else None,
        solve_time_s=float(sum(r["solve_s"] for r in ticks)),
        n_variables=state.max_size[0], n_binaries=state.max_size[1],
        n_constraints=state.max_size[2],
        solver_status_text=f"per tick: {n_opt} of {n} optimal, {n_tl} at the tick time limit",
        notes=notes)


def per_tick_block(outcome: PerTickOutcome, settings: RunSettings) -> dict:
    """The "per_tick" block of summary.json."""
    ticks = outcome.ticks
    slow = max(ticks, key=lambda r: r["solve_s"]) if ticks else None
    return {
        "outcome": outcome.status,
        "n_ticks": len(ticks),
        "tick_time_limit_s": settings.tick_time_limit_s,
        "n_ticks_optimal": sum(1 for r in ticks if r["status"] == STATUS_OPTIMAL),
        "n_ticks_time_limit": sum(1 for r in ticks if r["status"] == STATUS_TIME_LIMIT),
        "total_solve_s": float(sum(r["solve_s"] for r in ticks)),
        "slowest_tick": None if slow is None else slow["tick"],
        "slowest_tick_solve_s": None if slow is None else slow["solve_s"],
        "max_mip_gap": max((r["mip_gap"] for r in ticks if r.get("mip_gap") is not None),
                           default=None),
        "resumed_from_tick": outcome.resumed_from_tick,
        "stuck": outcome.stuck,
        "ticks_file": TICKS_FILE,
    }


def stuck_result(outcome: PerTickOutcome, scenario: Scenario) -> SolveResult:
    """The solver result of a run stuck at a tick: no schedule, the tick and the limit."""
    st = outcome.stuck
    return SolveResult(
        status=st["status"] or STATUS_INFEASIBLE, schedule=None, supply_temp_C=None,
        objective_g=None, best_bound_g=None, mip_gap=None,
        solve_time_s=float(sum(r["solve_s"] for r in outcome.ticks)),
        n_variables=0, n_binaries=0, n_constraints=0,
        solver_status_text=f"stuck at tick {st['tick']}: {st['limit_text']}",
        notes=[f"Per-tick re-planning stopped at tick {st['tick']} of {scenario.T}: no valid "
               f"schedule. Limit: {st['limit_text']}. {st['detail']}."])


def run_per_tick(scenario: Scenario, original: dict[int, int], settings: RunSettings,
                 run_dir: str | Path, *, warm_start: bool = True, log: bool = False,
                 wall_time_limit_s: float | None = None, started_at: float | None = None,
                 diagnosis_time_limit_s: float = 120.0, quiet: bool = True,
                 on_tick=None, stop_after_ticks: int | None = None) -> PerTickOutcome:
    """Run (or resume) the per-tick loop of one run. ``original``: the baseline's server of
    every workload (reassignment none / same_zone and B_i = 1 refer to it).

    ``wall_time_limit_s``: after a tick, stop with the checkpoint saved once this much time has
    passed since ``started_at`` (time.monotonic(); default: now). ``on_tick(t, tick, result,
    state)`` is called after every tick (tests). ``stop_after_ticks`` stops like the wall-time
    limit after that many ticks of this call (tests)."""
    t_begin = time.monotonic() if started_at is None else started_at
    run_dir = Path(run_dir)
    ckpt = run_dir / CHECKPOINT_DIR
    state = _load_checkpoint(ckpt, settings, scenario)
    resumed = None
    if state is None:
        state = _initial_state(scenario)
    else:
        resumed = state.next_tick
        if not quiet:
            print(f"Resuming from the checkpoint at tick {resumed}.")
    run_dir.mkdir(parents=True, exist_ok=True)
    plates = cold_plate_counts(scenario, settings)
    pairs = priority_pairs(scenario) if settings.priority else []
    pairs_by_i: dict[int, list[int]] = {}
    for i, j in pairs:
        pairs_by_i.setdefault(i, []).append(j)
    T = scenario.T
    done_here = 0

    while state.next_tick <= T:
        t = state.next_tick
        t0 = time.perf_counter()
        tick = _Tick(scenario, original, state, t, pairs_by_i, pairs, settings)
        warm, warm_sup = tick.warm_start(state) if warm_start else (None, None)
        res, error = None, None
        try:
            res = _solve_tick(tick, settings, warm, warm_sup, log)
        except ValueError as e:
            error = str(e)
        if res is None or not res.has_schedule:
            stuck = _diagnose(tick, settings, res, error, diagnosis_time_limit_s)
            row = {"tick": t, "status": STATUS_INFEASIBLE if res is None else res.status,
                   "solve_s": 0.0 if res is None else res.solve_time_s, "mip_gap": None,
                   "n_waiting": len(tick.waiting), "n_started": 0,
                   "n_running": len(tick.running),
                   "n_arrived": sum(1 for w in scenario.workloads if w.A == t),
                   "n_done": len(state.end), "objective_g": None, "kept_carbon_g": None,
                   "n_binaries": None if res is None else res.n_binaries,
                   "n_constraints": None if res is None else res.n_constraints,
                   "tick_wall_s": time.perf_counter() - t0}
            ticks = state.ticks + [row]
            _write_ticks(run_dir / TICKS_FILE, ticks)
            _write_partial(run_dir / PARTIAL_FILE, scenario, state)
            shutil.rmtree(ckpt, ignore_errors=True)
            if not quiet:
                print(f"Tick {t}: no valid schedule. Limit: {stuck['limit_text']}. {stuck['detail']}")
            return PerTickOutcome(status=OUTCOME_STUCK, ticks=ticks, stuck=stuck,
                                  resumed_from_tick=resumed, next_tick=t)

        # keep period t
        pl = res.schedule.placements
        started_now = []
        for k, i in enumerate(tick.ids, start=1):
            p = pl[k - 1]
            if i in state.start:
                if p.server != state.server[i] or p.start != 1:
                    raise RuntimeError(f"tick {t}: running workload {i} moved in the window "
                                       f"({p.server}, {p.start})")
            elif p.start == 1:
                state.server[i], state.start[i] = int(p.server), t
                state.delivered[i] = 0.0
                started_now.append(i)
            elif p.start is None or p.start < 1:
                raise RuntimeError(f"tick {t}: workload {i} has no start in the window")
        supply_t = np.asarray(res.supply_temp_C, dtype=float)[:, 0]
        S = scenario.S
        if res.cold_plate_ops is not None:
            flow_t = np.asarray(res.cold_plate_ops.flow_Lmin)[:, 0]
            cool_t = np.asarray(res.cold_plate_ops.coolant_C)[:, 0]
        else:
            flow_t = cool_t = np.full(S, np.nan)
        for z in range(scenario.Z):
            state.supply[z].append(float(supply_t[z]))
        for k in range(S):
            state.cp_flow[k].append(None if math.isnan(flow_t[k]) else float(flow_t[k]))
            state.cp_coolant[k].append(None if math.isnan(cool_t[k]) else float(cool_t[k]))
        state.plan = {i: [p.server, p.start + t - 1, p.end + t - 1]
                      for i, p in zip(tick.ids, pl) if p.server is not None}
        state.plan_supply = np.asarray(res.supply_temp_C, dtype=float).tolist()
        n_running = len(tick.running) + len(started_now)
        _play_period(scenario, plates, state, t, supply_t, flow_t, cool_t)

        if t == 1:
            state.notes = list(res.notes)
        state.tick_status[res.status] = state.tick_status.get(res.status, 0) + 1
        state.max_size = [max(state.max_size[0], res.n_variables),
                          max(state.max_size[1], res.n_binaries),
                          max(state.max_size[2], res.n_constraints)]
        state.ticks.append({
            "tick": t, "status": res.status, "solve_s": float(res.solve_time_s),
            "mip_gap": None if res.mip_gap is None else float(res.mip_gap),
            "n_waiting": len(tick.waiting), "n_started": len(started_now),
            "n_running": n_running,
            "n_arrived": sum(1 for w in scenario.workloads if w.A == t),
            "n_done": len(state.end),
            "objective_g": None if res.objective_g is None else float(res.objective_g),
            "kept_carbon_g": _kept_carbon_g(tick, res),
            "n_binaries": res.n_binaries, "n_constraints": res.n_constraints,
            "tick_wall_s": time.perf_counter() - t0})
        state.next_tick = t + 1
        done_here += 1
        if state.next_tick <= T:
            _save_checkpoint(ckpt, settings, scenario, state)
        _write_ticks(run_dir / TICKS_FILE, state.ticks)
        if on_tick is not None:
            on_tick(t, tick, res, state)
        if not quiet:
            r = state.ticks[-1]
            gap = "-" if r["mip_gap"] is None else f"{r['mip_gap']:.2%}"
            print(f"tick {t}/{T}: {r['status']}, {r['solve_s']:.2f} s, gap {gap}, "
                  f"{r['n_waiting']} waiting, {r['n_started']} started, "
                  f"{r['n_running']} running", flush=True)
        if state.next_tick <= T and (
                (wall_time_limit_s is not None
                 and time.monotonic() - t_begin >= wall_time_limit_s)
                or (stop_after_ticks is not None and done_here >= stop_after_ticks)):
            return PerTickOutcome(status=OUTCOME_STOPPED, ticks=list(state.ticks),
                                  resumed_from_tick=resumed, next_tick=state.next_tick)

    # every tick done
    missing = [w.i for w in scenario.workloads if w.i not in state.end]
    if missing:
        raise RuntimeError(f"per-tick run ended with workloads not finished: {missing[:10]}")
    schedule = Schedule(tuple(Placement(w.i, state.server[w.i], state.start[w.i], state.end[w.i])
                              for w in scenario.workloads))
    supply = np.asarray(state.supply, dtype=float)
    ops = None
    if plates.any():
        f = np.array([[np.nan if v is None else v for v in row] for row in state.cp_flow])
        c = np.array([[np.nan if v is None else v for v in row] for row in state.cp_coolant])
        ops = ColdPlateOps(flow_Lmin=f, coolant_C=c)
    result = _aggregate(scenario, state)
    result.schedule, result.supply_temp_C, result.cold_plate_ops = schedule, supply, ops
    shutil.rmtree(ckpt, ignore_errors=True)
    return PerTickOutcome(status=OUTCOME_DONE, ticks=list(state.ticks), schedule=schedule,
                          supply_temp_C=supply, cold_plate_ops=ops, result=result,
                          resumed_from_tick=resumed, next_tick=None)


def _write_partial(path: Path, scenario: Scenario, state: _State) -> None:
    """Starts kept before a stuck tick (end blank for workloads still running)."""
    with open(path, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["i", "workload_id", "server", "start", "end"])
        for i in sorted(state.start):
            w.writerow([i, scenario.workloads[i - 1].workload_id, state.server[i],
                        state.start[i], state.end.get(i, "")])
