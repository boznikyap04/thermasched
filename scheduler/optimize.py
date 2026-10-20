"""MILP optimizer (HiGHS) for thermal-aware workload scheduling.

Equation numbers refer to docs/PROJECT_CONTEXT.md section 2. This module builds the
constraints itself and shares no code with evaluate.py (the independent referee) or
baseline.py.

Model in one paragraph
----------------------
Each workload i runs as one unbroken block of periods on one server. ``Y[i,s,t]`` says it
runs on s in t. ``U[i,s,t]`` ("started by t") is a monotone 0/1 step that replaces the
start indicators ``S[i,s,t] = U[i,s,t] - U[i,s,t-1]``; ``X[i,s]`` is the last step of U.
Server power, the temperature recursion, a linear upper bound on the performance factor
DPF, and the work credit ``w`` follow the approved thesis equations. The supply
temperature of every zone and period is chosen from whole degrees by a one-hot choice so
the COP is a lookup. With cold plates on, each cold-plate server picks one flow setting per
period (one-hot, so resistance and pump power are lookups) and a coolant temperature; the
heat removed is linear in the temperature difference split across the settings. Priority
(56)-(57) orders the start times ``ST[i]`` of workloads that share a server, and servers
take no work in periods where AV = 0 (11). All limits are hard.

Units: P_IT in W, Q_crac / P_crac / P_fan in kW, dt in seconds, energy in kWh, CI in
g/kWh, carbon in g.
"""

from __future__ import annotations

import dataclasses
import math
import os
import tempfile
import time
from collections import defaultdict

import numpy as np

import highspy

from .types import (
    RELAX_COOLING, RELAX_CAPACITY, RELAX_DEADLINES, RELAX_FAMILIES, RELAX_PRIORITY, RELAX_THERMAL,
    STATUS_INFEASIBLE, STATUS_NO_SOLUTION, STATUS_OPTIMAL, STATUS_TIME_LIMIT,
    ColdPlateOps, Placement, RunSettings, Scenario, Schedule, SolveResult, cold_plate_counts, cop,
    priority_pairs,
)

_INF = highspy.kHighsInf
_EPS = 1e-9
_IPM_BINARIES = 30_000   # above this many binaries the MIP's LP relaxations use interior point


# ---------------------------------------------------------------------------
# Small LP container filled in bulk and handed to HiGHS in one call
# ---------------------------------------------------------------------------

class _LP:
    def __init__(self) -> None:
        self.lb: list[float] = []
        self.ub: list[float] = []
        self.cost: list[float] = []
        self.integer: list[bool] = []
        self.r_lo: list[float] = []
        self.r_hi: list[float] = []
        self.r_len: list[int] = []
        self.r_idx: list[int] = []
        self.r_val: list[float] = []

    def col(self, lb: float, ub: float, cost: float = 0.0, integer: bool = False) -> int:
        self.lb.append(lb)
        self.ub.append(ub)
        self.cost.append(cost)
        self.integer.append(integer)
        return len(self.lb) - 1

    def row(self, terms, lo: float, hi: float) -> None:
        """Add ``lo <= sum coef*col <= hi``; duplicate columns are merged."""
        acc: dict[int, float] = {}
        for c, v in terms:
            if c is not None:
                acc[c] = acc.get(c, 0.0) + v
        items = [(c, v) for c, v in acc.items() if abs(v) > 1e-13]
        self.r_lo.append(lo)
        self.r_hi.append(hi)
        self.r_len.append(len(items))
        for c, v in items:
            self.r_idx.append(c)
            self.r_val.append(v)

    @property
    def n_cols(self) -> int:
        return len(self.lb)

    @property
    def n_rows(self) -> int:
        return len(self.r_lo)

    def to_highs(self, log: bool = False) -> highspy.Highs:
        h = highspy.Highs()
        h.setOptionValue("log_to_console", bool(log))   # before passModel: no banner
        lp = highspy.HighsLp()
        lp.num_col_ = self.n_cols
        lp.num_row_ = self.n_rows
        lp.col_cost_ = np.asarray(self.cost, dtype=np.float64)
        lp.col_lower_ = np.asarray(self.lb, dtype=np.float64)
        lp.col_upper_ = np.asarray(self.ub, dtype=np.float64)
        lp.row_lower_ = np.asarray(self.r_lo, dtype=np.float64)
        lp.row_upper_ = np.asarray(self.r_hi, dtype=np.float64)
        lp.a_matrix_.format_ = highspy.MatrixFormat.kRowwise
        start = np.zeros(self.n_rows + 1, dtype=np.int32)
        np.cumsum(np.asarray(self.r_len, dtype=np.int64), out=start[1:])
        lp.a_matrix_.start_ = start
        lp.a_matrix_.index_ = np.asarray(self.r_idx, dtype=np.int32)
        lp.a_matrix_.value_ = np.asarray(self.r_val, dtype=np.float64)
        integ = np.asarray(self.integer, dtype=bool)
        lp.integrality_ = [highspy.HighsVarType.kInteger if b else highspy.HighsVarType.kContinuous
                           for b in integ]
        h.passModel(lp)
        return h


# ---------------------------------------------------------------------------
# Cold plates. The temperature, heat-balance and objective code reference the columns
# Q_cp[s,t] (W heat removed by all plates of s) and P_cp[s,t] (W pump power).
# ---------------------------------------------------------------------------

class _ColdPlateCols:
    """Per cold-plate server k and period t: one-hot flow choice b[k][t][j], the temperature
    difference split d[k][t][j] across the settings, and the coolant temperature cool[k][t].
    With the settings fixed (cp_mode "fixed") b and cool are fixed columns, and neg[k][t]
    (coolant above T_prev) with the switch on[k][t] lets the drive fall to zero."""

    def __init__(self):
        self.b: dict[int, list[list[int]]] = {}
        self.d: dict[int, list[list[int]]] = {}
        self.cool: dict[int, list[int]] = {}
        self.neg: dict[int, list[int]] = {}
        self.on: dict[int, list[int]] = {}
        self.fixed: tuple[int, float] | None = None    # (flow level, coolant degC)


def _add_cold_plate_terms(lp: _LP, scenario: Scenario, plates: np.ndarray, d_max: float,
                          ci_w_to_g: np.ndarray, fixed: tuple[int, float] | None = None):
    """Q_cp[s,t] and P_cp[s,t] columns, plus the choice columns of servers with cold plates.

    Servers without cold plates get Q_cp = P_cp = 0. P_cp enters the objective with the same
    weight as IT power (W -> g per period). ``fixed`` = (flow level, coolant) holds every
    plate at one setting. The rows are added by _add_cold_plate_rows.
    """
    S, T = scenario.S, scenario.T
    cp = scenario.cold_plate
    pump = cp.pump_W()
    nlev = len(cp.flow_settings_Lmin)
    cols = _ColdPlateCols()
    cols.fixed = fixed
    Q_cp, P_cp = [], []
    for k in range(S):
        n = int(plates[k])
        Q_cp.append([lp.col(0.0, n * cp.Q_max_per_plate_W) for _ in range(T)])
        P_cp.append([lp.col(n * pump.min(), n * pump.max(), cost=float(ci_w_to_g[t]))
                     for t in range(T)])
        if n == 0:
            continue
        if fixed is None:
            cols.b[k] = [[lp.col(0.0, 1.0, integer=True) for _ in range(nlev)] for _ in range(T)]
            cols.cool[k] = [lp.col(cp.coolant_min_C, cp.coolant_max_C) for _ in range(T)]
        else:
            lv, cool = fixed
            cols.b[k] = [[lp.col(float(j == lv), float(j == lv)) for j in range(nlev)]
                         for _ in range(T)]
            cols.cool[k] = [lp.col(cool, cool) for _ in range(T)]
            cols.on[k] = [lp.col(0.0, 1.0, integer=True) for _ in range(T)]
            cols.neg[k] = [lp.col(0.0, _INF) for _ in range(T)]
        cols.d[k] = [[lp.col(0.0, d_max) for _ in range(nlev)] for _ in range(T)]
    return Q_cp, P_cp, cols


def _add_cold_plate_rows(lp: _LP, scenario: Scenario, plates: np.ndarray, d_max: float,
                         cols: _ColdPlateCols, Q_cp, P_cp, P_IT, Tcol,
                         neg_max: dict[int, float] | None = None) -> None:
    """For server k with n plates in period t, with T_prev = T[k,t-1] (T0 in period 1):

        sum_j b_j = 1                              one flow setting
        sum_j d_j = T_prev - coolant               d_j <= d_max * b_j, d_j >= 0
        Q_cp <= n * sum_j G_j * d_j                heat through the plates, "<=" as agreed
        Q_cp <= P_IT                               no more than the server's heat
        Q_cp <= n * Q_max                          column bound, Eq. (55)
        P_cp  = n * sum_j pump_j * b_j             Eq. (48) at the chosen setting

    With the settings fixed the coolant cannot follow T_prev down, so the drive is
    max(0, T_prev - coolant): sum_j d_j - neg = T_prev - coolant, sum_j d_j <= d_max * on,
    neg <= neg_max[k] * (1 - on).
    """
    cp = scenario.cold_plate
    G = cp.conductance_W_per_C()
    pump = cp.pump_W()
    for k, bk in cols.b.items():
        n = int(plates[k])
        sv = scenario.servers[k]
        for t in range(scenario.T):
            b, d, cool = bk[t], cols.d[k][t], cols.cool[k][t]
            lp.row([(c_, 1.0) for c_ in b], 1.0, 1.0)
            terms = [(c_, 1.0) for c_ in d] + [(cool, 1.0)]
            if cols.fixed is not None:
                on, neg = cols.on[k][t], cols.neg[k][t]
                terms.append((neg, -1.0))
                lp.row([(c_, 1.0) for c_ in d] + [(on, -d_max)], -_INF, 0.0)
                lp.row([(neg, 1.0), (on, neg_max[k])], -_INF, neg_max[k])
            if t == 0:
                lp.row(terms, sv.T0_C, sv.T0_C)
            else:
                lp.row(terms + [(Tcol[k][t - 1], -1.0)], 0.0, 0.0)
            for dj, bj in zip(d, b):
                lp.row([(dj, 1.0), (bj, -d_max)], -_INF, 0.0)
            lp.row([(Q_cp[k][t], 1.0)] + [(dj, -n * float(g)) for dj, g in zip(d, G)], -_INF, 0.0)
            lp.row([(Q_cp[k][t], 1.0), (P_IT[k][t], -1.0)], -_INF, 0.0)
            lp.row([(P_cp[k][t], 1.0)] + [(bj, -n * float(pw)) for bj, pw in zip(b, pump)], 0.0, 0.0)


def _add_fan_terms(lp: _LP, scenario: Scenario, ci_kw_to_g: np.ndarray):
    """P_fan[z,t] (kW): fixed at zero; enters the objective (kW -> g per period)."""
    Z, T = scenario.Z, scenario.T
    return [[lp.col(0.0, 0.0, cost=float(ci_kw_to_g[t])) for t in range(T)] for _ in range(Z)]


# ---------------------------------------------------------------------------
# Model construction
# ---------------------------------------------------------------------------

class _Window:
    __slots__ = ("a", "b", "ya", "yb", "n_min", "n_max")

    def __init__(self, a, b, ya, yb, n_min, n_max):
        self.a, self.b, self.ya, self.yb, self.n_min, self.n_max = a, b, ya, yb, n_min, n_max


class _Built:
    """The assembled model plus the index maps needed to read a solution."""


def _levels(scenario: Scenario) -> list[int]:
    c = scenario.constants
    lo = math.ceil(c.T_crac_min_C - _EPS)
    hi = math.floor(c.T_crac_max_C + _EPS)
    levels = [k for k in range(lo, hi + 1) if k <= c.T_max_zone_C + _EPS]
    if not levels:
        raise ValueError("no whole-degree supply temperature lies in the CRAC range and "
                         "below the zone limit")
    return levels


def _allowed_servers(scenario: Scenario, original_server: dict[int, int],
                     settings: RunSettings) -> dict[int, list[int]]:
    zone_of = {sv.s: sv.zone for sv in scenario.servers}
    out: dict[int, list[int]] = {}
    for w in scenario.workloads:
        if w.i not in original_server:
            raise ValueError(f"original_server has no entry for workload {w.i}")
        o = original_server[w.i]
        if o not in zone_of:
            raise ValueError(f"original_server[{w.i}] = {o} is not a server of the scenario")
        if w.B == 1 or settings.reassignment == "none":
            out[w.i] = [o]
        elif settings.reassignment == "same_zone":
            out[w.i] = [sv.s for sv in scenario.servers if sv.zone == zone_of[o]]
        else:
            out[w.i] = [sv.s for sv in scenario.servers]
    return out


def _build(scenario: Scenario, original_server: dict[int, int], settings: RunSettings,
           relax: tuple[str, ...], feasibility_only: bool, ignore_temperature: bool = False):
    """``ignore_temperature`` leaves server temperature out: no temperature recursion, no
    thermal cap, DPF = 1. Pass 1 of the thermal-blind placement uses it to choose servers."""
    settings.validate()
    for fam in relax:
        if fam not in RELAX_FAMILIES:
            raise ValueError(f"unknown relaxation family {fam!r}")
    c = scenario.constants
    S, Z, T, I = scenario.S, scenario.Z, scenario.T, scenario.I
    dt = scenario.dt_seconds
    dt_h = scenario.dt_hours
    cap = settings.thermal_cap_C(scenario)
    if cap > c.T_throttle_C + _EPS:
        raise ValueError(
            f"thermal cap {cap:g} degC (T_max - H_min) exceeds T_throttle {c.T_throttle_C:g} degC: "
            "the linear DPF bound is only valid below T_throttle")

    relax_dead = RELAX_DEADLINES in relax
    relax_therm = RELAX_THERMAL in relax
    relax_cap = RELAX_CAPACITY in relax
    relax_cool = RELAX_COOLING in relax
    notes: list[str] = []

    fixed_mode = settings.supply_temp_mode == "fixed"
    if feasibility_only and not fixed_mode:
        # Feasibility does not depend on the supply schedule: the lowest level gives the lowest
        # temperatures, the same Q_crac cap, and trivially satisfies the ramps and zone limit.
        fixed_mode = True
        feas_supply = float(_levels(scenario)[0])
        settings = dataclasses.replace(settings, supply_temp_mode="fixed",
                                       fixed_supply_temp_C=feas_supply)
    if fixed_mode:
        v = float(settings.optimized_fixed_supply_temp_C())
        if not (c.T_crac_min_C - _EPS <= v <= c.T_crac_max_C + _EPS):
            raise ValueError(f"fixed supply temperature {v:g} degC is outside the CRAC range "
                             f"[{c.T_crac_min_C:g}, {c.T_crac_max_C:g}]")
        if v > c.T_max_zone_C + _EPS:
            raise ValueError(f"fixed supply temperature {v:g} degC exceeds the zone limit "
                             f"{c.T_max_zone_C:g}")
        fixed_value = v
        levels: list[int] = []
    else:
        fixed_value = None
        levels = _levels(scenario)
    cop_levels = [float(cop(c, k)) for k in levels]

    # Highest temperature the T columns may take; the linear DPF bound holds up to T_throttle.
    cap_eff = c.T_throttle_C if relax_therm else cap
    derating = cap_eff > c.T_dvfs_C + _EPS and not ignore_temperature   # DPF can fall below 1
    slope = c.R_dvfs / (c.T_throttle_C - c.T_dvfs_C)
    dpf_cap = min(1.0, 1.0 - slope * (cap_eff - c.T_dvfs_C)) if derating else 1.0

    servers = scenario.servers
    zone_of = np.array([sv.zone for sv in servers], dtype=int)
    allowed = _allowed_servers(scenario, original_server, settings)
    CI = np.asarray(scenario.CI_g_per_kWh, dtype=float)
    if CI.shape != (T,):
        raise ValueError("CI_g_per_kWh must have shape (T,)")

    # ---- windows per (i, s) ------------------------------------------------
    win: dict[tuple[int, int], _Window] = {}
    empty_workloads: list[int] = []
    for w in scenario.workloads:
        D = T + 1 if relax_dead else min(w.D, T + 1)
        last_start_by_wait = T + 1 if relax_dead else w.A + w.AD
        for s in allowed[w.i]:
            sv = servers[s - 1]
            per_full = w.C_req * sv.f_MHz * dt          # work of one full-speed period
            if w.W_MHz_s <= 0:
                n_min = n_max = 1
            else:
                n_min = max(1, math.ceil(w.W_MHz_s / per_full - _EPS))
                n_max = (T if dpf_cap <= 1e-6 else
                         max(n_min, math.ceil(w.W_MHz_s / (per_full * dpf_cap) - _EPS)))
            a = max(w.A, 1)
            b = min(last_start_by_wait, D - n_min)
            if b < a:
                continue
            ya = a
            yb = min(D - 1, b + n_max - 1)
            win[(w.i, s)] = _Window(a, b, ya, yb, n_min, n_max)
        if not any((w.i, s) in win for s in allowed[w.i]):
            empty_workloads.append(w.i)

    built = _Built()
    built.empty_workloads = empty_workloads
    built.notes = notes
    built.win = win
    built.levels = levels
    built.fixed_value = fixed_value
    built.derating = derating
    built.relax = relax
    built.feasibility_only = feasibility_only
    built.ignore_temperature = ignore_temperature
    if empty_workloads:
        return built

    lp = _LP()
    ci_w_to_g = CI * dt_h / 1000.0      # g per W held for one period
    ci_kw_to_g = CI * dt_h              # g per kW held for one period
    if feasibility_only:
        ci_w_to_g = np.zeros(T)
        ci_kw_to_g = np.zeros(T)

    # ---- scheduling columns ------------------------------------------------
    # X[i,s]: assigned; U[i,s,t]: started by t (t in [a, b-1]; U at b is X);
    # E[i,s,t]: tail period (beyond the n_min core periods) is on.
    X: dict[tuple[int, int], int] = {}
    U: dict[tuple[int, int], dict[int, int]] = {}
    E: dict[tuple[int, int], dict[int, int]] = {}
    for w in scenario.workloads:
        for s in allowed[w.i]:
            wd = win.get((w.i, s))
            if wd is None:
                continue
            X[(w.i, s)] = lp.col(0.0, 1.0, integer=True)
            U[(w.i, s)] = {t: lp.col(0.0, 1.0, integer=True) for t in range(wd.a, wd.b)}
            E[(w.i, s)] = {}
            if wd.n_max > wd.n_min:
                for t in range(wd.a + wd.n_min, wd.yb + 1):
                    E[(w.i, s)][t] = lp.col(0.0, 1.0, integer=True)
    built.X, built.U, built.E = X, U, E

    def ustep(i: int, s: int, t: int):
        """Column of 'started by t' for (i, s), or None when it is the constant 0."""
        wd = win[(i, s)]
        if t < wd.a:
            return None
        if t >= wd.b:
            return X[(i, s)]
        return U[(i, s)][t]

    # Occupancy of (i,s) in period t = core + tail = U[t] - U[t-n_min] + E[t]
    by_st: dict[tuple[int, int], list[tuple[int, list]]] = defaultdict(list)
    for (i, s), wd in win.items():
        emap = E[(i, s)]
        for t in range(wd.a, wd.yb + 1):
            terms = []
            if t <= wd.b + wd.n_min - 1:
                terms += [(ustep(i, s, t), 1.0), (ustep(i, s, t - wd.n_min), -1.0)]
            if t in emap:
                terms.append((emap[t], 1.0))
            by_st[(s, t)].append((i, terms))

    # Upper bound of IT power per server: all workloads that could ever run there.
    max_cores: dict[int, float] = defaultdict(float)
    for (i, s) in win:
        max_cores[s] += scenario.workloads[i - 1].C_req
    P_ub = []
    for sv in servers:
        if relax_cap:
            ub = sv.P_idle_W + (sv.P_max_W - sv.P_idle_W) * max_cores[sv.s] / sv.C_cores
        else:
            ub = sv.P_idle_W + (sv.P_max_W - sv.P_idle_W) * min(1.0, max_cores[sv.s] / sv.C_cores)
        P_ub.append(ub)

    # ---- system columns ----------------------------------------------------
    P_IT = [[lp.col(sv.P_idle_W, P_ub[sv.s - 1], cost=float(ci_w_to_g[t])) for t in range(T)]
            for sv in servers]
    plates = cold_plate_counts(scenario, settings)
    cp_d_max = max([cap_eff] + [sv.T0_C for sv in servers]) - scenario.cold_plate.coolant_min_C
    for sv in servers:
        if plates[sv.s - 1] > 0 and sv.T0_C < scenario.cold_plate.coolant_min_C:
            raise ValueError(f"server {sv.s}: T0 {sv.T0_C:g} C is below the lowest coolant "
                             f"temperature {scenario.cold_plate.coolant_min_C:g} C")
    cp_fixed = None
    cp_neg_max: dict[int, float] = {}
    if settings.cp_mode == "fixed" and plates.any():
        flow, cool = settings.optimized_fixed_cp()
        cps = scenario.cold_plate
        if not cps.coolant_min_C - _EPS <= cool <= cps.coolant_max_C + _EPS:
            raise ValueError(f"fixed coolant temperature {cool:g} degC is outside "
                             f"[{cps.coolant_min_C:g}, {cps.coolant_max_C:g}], Eq. (49)")
        cp_fixed = (cps.level_of(flow), cool)
        # Lowest temperature a server can reach: the steady state with all heat removed.
        sup_min = fixed_value if fixed_mode else float(levels[0])
        for sv in servers:
            cp_neg_max[sv.s - 1] = max(1.0, cool - min(sv.T0_C, sup_min + sv.th_a_C) + 1.0)
    Q_cp, P_cp, cp_cols = _add_cold_plate_terms(lp, scenario, plates, cp_d_max, ci_w_to_g,
                                                cp_fixed)
    P_fan = _add_fan_terms(lp, scenario, ci_kw_to_g)
    T_ub = _INF if ignore_temperature else cap_eff
    Tcol = [[lp.col(-_INF, T_ub) for t in range(T)] for _ in servers]
    # Loss L = 1 - DPF (only where some workload has tail periods, i.e. where DPF matters),
    # and its running sum CL, per server and period.
    Lmax = min(1.0, 1.0 - dpf_cap)
    tail_servers = {s for (i, s), wd in win.items() if wd.n_max > wd.n_min}
    Lcol: dict[int, list[int]] = {}
    CLcol: dict[int, list[int]] = {}
    if derating:
        for s in tail_servers:
            Lcol[s] = [lp.col(0.0, Lmax) for t in range(T)]
            CLcol[s] = [lp.col(0.0, T * Lmax) for t in range(T)]

    # Q_crac upper bound: Eq. (54) as a bound (also the big-M of the level split)
    sum_pub_kw = [sum(P_ub[sv.s - 1] for sv in servers if sv.zone == z) / 1000.0
                  for z in range(1, Z + 1)]
    Qmax = [sum_pub_kw[z - 1] if relax_cool else min(c.Q_crac_kW, sum_pub_kw[z - 1])
            for z in range(1, Z + 1)]
    Qcrac = [[None] * T for _ in range(Z)]
    Tsup = [[None] * T for _ in range(Z)]
    choice: dict[tuple[int, int], list[int]] = {}
    qcols: dict[tuple[int, int], list[int]] = {}
    for z in range(1, Z + 1):
        for t in range(T):
            if fixed_mode:
                Tsup[z - 1][t] = lp.col(fixed_value, fixed_value)
                cost = float(ci_kw_to_g[t] / cop(c, fixed_value))
                Qcrac[z - 1][t] = lp.col(0.0, Qmax[z - 1], cost=cost)
            else:
                Tsup[z - 1][t] = lp.col(levels[0], levels[-1])
                Qcrac[z - 1][t] = lp.col(0.0, Qmax[z - 1])
                choice[(z, t)] = [lp.col(0.0, 1.0, integer=True) for _ in levels]
                qcols[(z, t)] = [lp.col(0.0, Qmax[z - 1], cost=float(ci_kw_to_g[t] / cp))
                                 for cp in cop_levels]

    # ---- workload rows -----------------------------------------------------
    for w in scenario.workloads:
        i = w.i
        lp.row([(X[(i, s)], 1.0) for s in allowed[i] if (i, s) in X], 1.0, 1.0)          # (9)
        work_terms = []
        for s in allowed[i]:
            wd = win.get((i, s))
            if wd is None:
                continue
            Ucols = U[(i, s)]
            for t in range(wd.a + 1, wd.b):                      # monotone started-by
                lp.row([(Ucols[t], 1.0), (Ucols[t - 1], -1.0)], 0.0, _INF)
            if wd.b > wd.a:
                lp.row([(X[(i, s)], 1.0), (Ucols[wd.b - 1], -1.0)], 0.0, _INF)
            emap = E[(i, s)]
            for t, e in emap.items():
                # tail period t is on only inside the tail region of the actual start
                lp.row([(e, 1.0), (ustep(i, s, t - wd.n_min), -1.0), (ustep(i, s, t - wd.n_max), 1.0)],
                       -_INF, 0.0)
                # ... and only as an unbroken extension of the core block
                lp.row([(e, 1.0), (emap.get(t - 1), -1.0), (ustep(i, s, t - wd.n_min), -1.0),
                        (ustep(i, s, t - wd.n_min - 1), 1.0)], -_INF, 0.0)
            if w.W_MHz_s <= 0:
                continue
            coef = w.C_req * servers[s - 1].f_MHz * dt / w.W_MHz_s
            if wd.n_max == wd.n_min:
                # n_max == n_min: any core block delivers at least W even at the worst DPF
                work_terms.append((X[(i, s)], 1.0))
                continue
            work_terms.append((X[(i, s)], coef * wd.n_min))
            if not derating:
                work_terms += [(e, coef) for e in emap.values()]
                continue
            # derating: core credit n_min - (loss over the core block of the chosen start)
            M = wd.n_min * Lmax
            cl = lp.col(0.0, M)
            work_terms.append((cl, -coef))
            CL = CLcol[s]
            for tau in range(wd.a, wd.b + 1):
                lp.row([(cl, 1.0), (CL[tau + wd.n_min - 2], -1.0),
                        (CL[tau - 2] if tau >= 2 else None, 1.0),
                        (ustep(i, s, tau), -M), (ustep(i, s, tau - 1), M)], -M, _INF)
            # tail credit: wt <= E, wt <= 1 - L
            for t, e in emap.items():
                wt = lp.col(0.0, 1.0)
                lp.row([(wt, 1.0), (e, -1.0)], -_INF, 0.0)
                lp.row([(wt, 1.0), (Lcol[s][t - 1], 1.0)], -_INF, 1.0)
                work_terms.append((wt, coef))
        if w.W_MHz_s > 0:
            lp.row(work_terms, 1.0, _INF)                                               # (39)
    if derating:
        for s in tail_servers:
            sv = servers[s - 1]
            for t in range(1, T + 1):
                # L >= slope * (T - T_dvfs): the linear piece of Eq. (37)
                lp.row([(Lcol[s][t - 1], 1.0), (Tcol[s - 1][t - 1], -slope)], -slope * c.T_dvfs_C, _INF)
                lp.row([(CLcol[s][t - 1], 1.0), (CLcol[s][t - 2] if t >= 2 else None, -1.0),
                        (Lcol[s][t - 1], -1.0)], 0.0, 0.0)

    # ---- priority, Eq. (56)-(57) -------------------------------------------
    # ST[i] = sum_s (b * X[i,s] - sum_{t<b} U[i,s,t]), the start period. For a pair (i, j)
    # with O_ij = 1 and a shared server s:
    #   ST_i - ST_j <= M * (2 - X_is - X_js) + M * started_j(A_i - 1)
    # so i starts no later than j when both run on s and j had not started when i arrived.
    ST: dict[int, int] = {}

    def st_col(i: int) -> int:
        if i not in ST:
            spans = [win[(i, s)] for s in allowed[i] if (i, s) in win]
            col = lp.col(float(min(wd.a for wd in spans)), float(max(wd.b for wd in spans)))
            terms = [(col, 1.0)]
            for s in allowed[i]:
                wd = win.get((i, s))
                if wd is None:
                    continue
                terms.append((X[(i, s)], -float(wd.b)))
                terms += [(uc, 1.0) for uc in U[(i, s)].values()]
            lp.row(terms, 0.0, 0.0)
            ST[i] = col
        return ST[i]

    n_priority_rows = 0
    if settings.priority and RELAX_PRIORITY not in relax:
        for i, j in priority_pairs(scenario):
            A_i = scenario.workloads[i - 1].A
            shared = [s for s in allowed[i] if (i, s) in win and (j, s) in win]
            if not shared:
                continue
            M = (max(win[(i, s)].b for s in allowed[i] if (i, s) in win)
                 - min(win[(j, s)].a for s in allowed[j] if (j, s) in win))
            if M <= 0:
                continue                      # i can never start after j
            started_j = [(ustep(j, s, A_i - 1), -float(M)) for s in allowed[j] if (j, s) in win]
            for s in shared:
                wi, wj = win[(i, s)], win[(j, s)]
                if wj.b < A_i or wi.b <= max(wj.a, A_i):
                    continue                  # no inversion possible on s
                lp.row([(st_col(i), 1.0), (st_col(j), -1.0), (X[(i, s)], float(M)),
                        (X[(j, s)], float(M))] + started_j, -_INF, 2.0 * M)
                n_priority_rows += 1

    # ---- per server, per period -------------------------------------------
    AV = scenario.availability()
    for sv in servers:
        k = sv.s - 1
        dP = sv.P_max_W - sv.P_idle_W
        alpha, R, a_s = sv.th_alpha, sv.th_R_C_per_W, sv.th_a_C
        z = sv.zone
        for t in range(1, T + 1):
            items = by_st.get((sv.s, t), [])
            if not AV[k, t - 1]:
                for _, occ in items:                                                   # (11)
                    lp.row(occ, 0.0, 0.0)
            # (16), (20), (21): P_IT = P_idle + dP * sum C_req * occupancy / C_s
            terms = [(P_IT[k][t - 1], 1.0)]
            cpu: list = []
            mem: list = []
            cpu_sum = mem_sum = 0.0
            for i, occ in items:
                wl = scenario.workloads[i - 1]
                terms += [(col, -dP * wl.C_req / sv.C_cores * v) for col, v in occ]
                cpu += [(col, wl.C_req / sv.C_cores * v) for col, v in occ]
                mem += [(col, wl.M_req_MB / sv.M_MB * v) for col, v in occ]
                cpu_sum += wl.C_req / sv.C_cores
                mem_sum += wl.M_req_MB / sv.M_MB
            lp.row(terms, sv.P_idle_W, sv.P_idle_W)
            if not relax_cap:
                if cpu_sum > 1.0 + 1e-12:                                              # (12)
                    lp.row(cpu, -_INF, 1.0)
                if mem_sum > 1.0 + 1e-12:                                              # (13)
                    lp.row(mem, -_INF, 1.0)
            if ignore_temperature:
                continue
            # temperature recursion (approved)
            terms = [(Tcol[k][t - 1], 1.0), (Tsup[z - 1][t - 1], -(1 - alpha)),
                     (P_IT[k][t - 1], -(1 - alpha) * R), (Q_cp[k][t - 1], (1 - alpha) * R)]
            rhs = (1 - alpha) * a_s
            if t == 1:
                rhs += alpha * sv.T0_C
            else:
                terms.append((Tcol[k][t - 2], -alpha))
            lp.row(terms, rhs, rhs)

    _add_cold_plate_rows(lp, scenario, plates, cp_d_max, cp_cols, Q_cp, P_cp, P_IT, Tcol,
                         cp_neg_max)

    # ---- cooling zones -----------------------------------------------------
    members = {z: [sv for sv in servers if sv.zone == z] for z in range(1, Z + 1)}
    for z in range(1, Z + 1):
        for t in range(1, T + 1):
            # heat balance: Q_crac >= sum (P_IT - Q_cp) / 1000   (A3)
            terms = [(Qcrac[z - 1][t - 1], 1.0)]
            for sv in members[z]:
                terms.append((P_IT[sv.s - 1][t - 1], -1e-3))
                terms.append((Q_cp[sv.s - 1][t - 1], 1e-3))
            lp.row(terms, 0.0, _INF)
            if not fixed_mode:
                ch = choice[(z, t - 1)]
                lp.row([(col, 1.0) for col in ch], 1.0, 1.0)
                lp.row([(Tsup[z - 1][t - 1], 1.0)] + [(col, -float(lv)) for col, lv in zip(ch, levels)],
                       0.0, 0.0)
                qs = qcols[(z, t - 1)]
                lp.row([(Qcrac[z - 1][t - 1], 1.0)] + [(q, -1.0) for q in qs], 0.0, 0.0)
                for q, col in zip(qs, ch):
                    lp.row([(q, 1.0), (col, -Qmax[z - 1])], -_INF, 0.0)
        if not fixed_mode:
            for lag, lim in ((c.ramp_short_lag, c.ramp_short_C), (c.ramp_long_lag, c.ramp_long_C)):
                for t in range(lag + 1, T + 1):                                         # (35), (36)
                    lp.row([(Tsup[z - 1][t - 1], 1.0), (Tsup[z - 1][t - 1 - lag], -1.0)], -lim, lim)

    # ---- objective: P_IT, P_cp, P_fan and CRAC columns already carry CI * energy factors
    built.lp = lp
    built.P_IT, built.Q_cp, built.P_cp, built.P_fan = P_IT, Q_cp, P_cp, P_fan
    built.Tcol, built.Qcrac, built.Tsup = Tcol, Qcrac, Tsup
    built.slope = slope
    built.choice = choice
    built.dpf_cap = dpf_cap
    built.plates, built.cp_cols = plates, cp_cols
    built.n_priority_rows = n_priority_rows
    built.n_unavailable = int((AV == 0).sum())
    return built


def _model_notes(scenario: Scenario, settings: RunSettings, built: _Built) -> list[str]:
    n = [
        "Y[i,s,t] is eliminated: a workload occupies n_min core periods after its start, "
        "U[t] - U[t-n_min], plus optional tail binaries E[i,s,t] only where n_max > n_min, because "
        "the Y-based model made the root LP of 'consolidated6' unsolvable (500k rows).",
        "Start indicators S are replaced by cumulative 'started by t' steps U[i,s,t] (S = U[t] - "
        "U[t-1], X[i,s] is the last step), so one unbroken block needs no window sums.",
        "The tail E[t] <= U[t-n_min] - U[t-n_max] and E[t] <= E[t-1] + U[t-n_min] - U[t-n_min-1] keep "
        "the run unbroken and within n_min..n_max periods; Y <= X (10) is then implied and Eq. (9) is kept.",
        "n_min = ceil(W/(C_req*f_s*dt)) is the shortest run since DPF <= 1, and starts with t + n_min > D "
        "are dropped.",
        "n_max = ceil(W/(C_req*f_s*dt*DPF_cap)) caps the run: valid for the optimum because trimming the "
        "tail of a run never raises power, heat or temperature, so every other limit stays met.",
        "DPF enters only through the loss L = 1 - DPF >= slope*(T - T_dvfs), L >= 0 (the linear piece of "
        "Eq. 37, valid below T_throttle, so a cap above T_throttle is rejected), and only on servers where "
        "some pair has n_max > n_min; higher DPF never hurts, so no binaries are needed.",
        "Work (39) uses core credit n_min*X - coreLoss, where coreLoss >= CL[tau+n_min-1] - CL[tau-1] "
        "- M(1 - sigma_tau) over the running sum CL of L, plus tail credits wt <= E, wt <= 1 - L; for a pair "
        "with n_max == n_min any core block delivers at least W, so its term is exactly X.",
        "The work row is divided by W_i (right side 1), and with the cap at or below T_dvfs there are no "
        "loss, tail or work-credit columns at all.",
        "Server utilisation and heat are substituted into P_IT[s,t] = P_idle + (P_max-P_idle)*"
        "sum C_req*occupancy/C_s (Eq. 16, 20, 21); P_IT is bounded by P_max (or by the cores of the "
        "workloads that can ever run there) as a column bound.",
        "Eq. (54) Q_crac <= 116 kW and the big-M of the supply-level split are one column bound "
        "Qmax = min(116, sum of the zone's maximum IT power in kW); the heat balance sets Q_crac >= "
        "heat and the cost increases in Q_crac, so it sits at equality in any optimum.",
        "CRAC power is Q_crac / COP (divide), COP looked up per whole-degree level; the printed "
        "Eq. (46) multiplies.",
        "Fan power P_fan is a named column fixed at zero (_add_fan_terms) that already appears in "
        "the objective.",
        "Idle energy is in the objective through the P_IT columns (lower bound P_idle), so "
        "objective_g equals total carbon with no separate offset.",
        "The wait limit (28) is applied to all workloads, which includes (25). Workloads with "
        "B_i = 1 keep their original server (29).",
    ]
    if settings.priority and RELAX_PRIORITY not in built.relax:
        n.append(
            f"Priority (56)-(57): O_ij = 1 for a time-sensitive i and a delay-tolerant j, and for the "
            f"earlier arrival of two same-type, same-deadline workloads. It is linked to the start "
            f"times as: on a shared server, j may not start while i waits (A_i <= ST_j implies "
            f"ST_i <= ST_j), through ST_i = sum_s (b X - sum U) and big-M rows "
            f"({getattr(built, 'n_priority_rows', 0)} pair-server rows after dropping those that "
            f"cannot bind). EDF within a type is not in the equations and is not modelled.")
    else:
        n.append("Priority (56)-(57) is off for this run: start order is not constrained.")
    n_off = getattr(built, "n_unavailable", 0)
    n.append(f"Availability (11): {n_off} server-period(s) with AV = 0 take no work; their "
             "servers stay on at idle power." if n_off else
             "Availability (11): every server is available in every period (AV = 1).")
    plates = getattr(built, "plates", cold_plate_counts(scenario, settings))
    if plates.any():
        cp = scenario.cold_plate
        n.append(
            f"Cold plates: {int(plates.sum())} on {int((plates > 0).sum())} server(s). "
            f"Each picks one of the flow settings {list(cp.flow_settings_Lmin)} L/min per period "
            "(one-hot), so its resistance and the cubic pump power of Eq. (48) are lookups. "
            "T_prev - coolant is split into d_j <= d_max*b_j, so Q_cp <= n*sum G_j*d_j is linear "
            "(G_j = min(1/R_j, flow_j*c_pw)); Q_cp <= P_IT and Q_cp <= n*0.3 kW. T_prev is the "
            "previous period's temperature, and d_j >= 0 keeps the coolant at or below it.")
        if settings.cp_mode == "fixed":
            flow, cool = settings.optimized_fixed_cp()
            n.append(f"Cold plates fixed (cp_mode fixed): every plate runs at {flow:g} L/min and "
                     f"{cool:g} C coolant in every period. The drive is max(0, T_prev - coolant), "
                     "with one on/off binary per server and period.")
    else:
        n.append("Cold plates are off: Q_cp and P_cp are columns fixed at zero.")
    if getattr(built, "ignore_temperature", False):
        n.append("Server temperature ignored (pass 1 of the thermal-blind placement): no temperature "
                 "recursion, no thermal cap T <= T_max - H_min and DPF = 1, so temperature plays no part "
                 "in choosing servers. Cold plates may remove up to min(P_IT, n*0.3 kW) whatever the "
                 "server temperature.")
    if built.feasibility_only:
        n.append("Feasibility-only solve (diagnosis): zero objective and the supply fixed at the lowest "
                 "whole degree, which gives the same feasibility as optimising it (lowest temperatures, "
                 "same Q_crac cap, no ramp).")
    if RELAX_THERMAL in built.relax:
        n.append("RELAX_THERMAL: the cap T <= T_max - H_min is replaced by T <= T_throttle, the limit "
                 "of validity of the linear DPF bound, with DPF >= 0.")
    if RELAX_CAPACITY in built.relax:
        n.append("RELAX_CAPACITY: CPU and memory rows are dropped; P_IT is bounded by the cores of the "
                 "workloads that can run on the server.")
    if RELAX_COOLING in built.relax:
        n.append("RELAX_COOLING: Q_crac <= 116 dropped; the column bound is the zone's maximum IT power.")
    if RELAX_DEADLINES in built.relax:
        n.append("RELAX_DEADLINES: starts and runs may extend over A_i..T (arrival still enforced).")
    return n


# ---------------------------------------------------------------------------
# Solving
# ---------------------------------------------------------------------------

def _infeasible_result(built: _Built, relax, t0: float, text: str) -> SolveResult:
    return SolveResult(
        status=STATUS_INFEASIBLE, schedule=None, supply_temp_C=None, objective_g=None,
        best_bound_g=None, mip_gap=None, solve_time_s=time.perf_counter() - t0,
        n_variables=0, n_binaries=0, n_constraints=0, relaxed=tuple(relax),
        solver_status_text=text, notes=list(built.notes))


def _warm_start_values(scenario: Scenario, built: _Built, schedule: Schedule,
                       supply: np.ndarray | None, settings: RunSettings) -> dict[int, float]:
    vals: dict[int, float] = {}
    for p in schedule.placements:
        if p.server is None or p.start is None or p.end is None:
            continue
        wd = built.win.get((p.i, p.server))
        if wd is None or not (wd.a <= p.start <= wd.b):
            continue
        m = min(p.end - p.start, wd.n_max)       # a longer run is cut to n_max (never needed)
        if m < wd.n_min or p.start + m - 1 > wd.yb:
            continue
        for s in range(1, scenario.S + 1):
            xc = built.X.get((p.i, s))
            if xc is None:
                continue
            on = s == p.server
            vals[xc] = 1.0 if on else 0.0
            for t, uc in built.U[(p.i, s)].items():
                vals[uc] = 1.0 if (on and t >= p.start) else 0.0
            for t, ec in built.E[(p.i, s)].items():
                vals[ec] = 1.0 if (on and p.start + wd.n_min <= t < p.start + m) else 0.0
    if built.cp_cols.b:
        lv = (built.cp_cols.fixed[0] if built.cp_cols.fixed is not None
              else scenario.cold_plate.level_of(settings.baseline_cp_flow_Lmin))
        for bk in built.cp_cols.b.values():
            for b in bk:
                for j, col in enumerate(b):
                    vals[col] = 1.0 if j == lv else 0.0
    if supply is not None and built.fixed_value is None:
        supply = np.asarray(supply, dtype=float)
        if supply.shape == (scenario.Z, scenario.T):
            for (z, t), cols in built.choice.items():
                v = supply[z - 1, t]
                k = int(round(v)) if abs(v - round(v)) < 1e-6 else None
                if k in built.levels:
                    for col, lv in zip(cols, built.levels):
                        vals[col] = 1.0 if lv == k else 0.0
    return vals


def _solve_impl(scenario: Scenario, original_server: dict[int, int], settings: RunSettings, *,
                relax: tuple[str, ...], warm_start: Schedule | None,
                warm_start_supply_temp_C: np.ndarray | None, time_limit_s: float | None,
                log: bool, feasibility_only: bool,
                ignore_temperature: bool = False) -> SolveResult:
    relax = tuple(relax)
    t_build0 = time.perf_counter()
    built = _build(scenario, original_server, settings, relax, feasibility_only,
                   ignore_temperature)
    notes = _model_notes(scenario, settings, built)
    built.notes[:] = notes
    if built.empty_workloads:
        res = _infeasible_result(built, relax, t_build0,
                                 "no feasible server/start window for workload(s) "
                                 + ", ".join(map(str, built.empty_workloads[:10])))
        res.notes.append("Detected before building the model: some workload has no server and start "
                         "period that meets arrival, wait limit, deadline and minimum run length.")
        return res
    lp = built.lp
    h = lp.to_highs(log)
    build_time = time.perf_counter() - t_build0

    limit = settings.time_limit_s if time_limit_s is None else time_limit_s
    h.setOptionValue("time_limit", float(limit))
    h.setOptionValue("mip_rel_gap", 1.0 if feasibility_only else float(settings.mip_rel_gap))
    lp_solver = "choose"
    if sum(lp.integer) > _IPM_BINARIES:
        lp_solver = "ipm"
        if h.setOptionValue("mip_lp_solver", "ipm") != highspy.HighsStatus.kOk:
            raise RuntimeError("HiGHS rejected mip_lp_solver = ipm")
        notes.append(f"More than {_IPM_BINARIES} binaries: the MIP's LP relaxations use interior point "
                     "(mip_lp_solver = ipm) because dual and primal simplex do not finish the root LP "
                     "on large models.")
    h.setOptionValue("log_to_console", bool(log))
    log_path = None
    n_ws_set = 0
    if warm_start is not None and not feasibility_only:
        vals = _warm_start_values(scenario, built, warm_start, warm_start_supply_temp_C, settings)
        if vals:
            idx = np.array(sorted(vals), dtype=np.int32)
            h.setSolution(len(idx), idx, np.array([vals[k] for k in idx], dtype=np.float64))
            n_ws_set = len(idx)
            fd, log_path = tempfile.mkstemp(suffix=".log")
            os.close(fd)
            h.setOptionValue("log_file", log_path)

    t0 = time.perf_counter()
    h.run()
    solve_time = time.perf_counter() - t0
    ws_text = ""
    if log_path is not None:
        try:
            with open(log_path) as f:
                ws_text = f.read()
        finally:
            os.unlink(log_path)

    info = h.getInfo()
    ms = h.getModelStatus()
    text = h.modelStatusToString(ms)
    MS = highspy.HighsModelStatus
    has_sol = info.primal_solution_status == 2
    if ms == MS.kInfeasible or ms == MS.kUnboundedOrInfeasible:
        status = STATUS_INFEASIBLE
    elif ms == MS.kOptimal:
        status = STATUS_OPTIMAL
    elif has_sol:
        status = STATUS_TIME_LIMIT
    else:
        status = STATUS_NO_SOLUTION

    nv, nr = lp.n_cols, lp.n_rows
    nb = int(sum(lp.integer))
    out = SolveResult(status=status, schedule=None, supply_temp_C=None, objective_g=None,
                      best_bound_g=None, mip_gap=None, solve_time_s=solve_time,
                      n_variables=nv, n_binaries=nb, n_constraints=nr, relaxed=relax,
                      solver_status_text=text, notes=notes)
    out.model_values["build_time_s"] = build_time
    out.model_values["mip_lp_solver"] = lp_solver
    if n_ws_set:
        out.model_values["warm_start_columns_set"] = n_ws_set
        out.model_values["warm_start_log"] = "\n".join(
            ln for ln in ws_text.splitlines() if "MIP start" in ln or "solution" in ln.lower())[:2000]
    if status in (STATUS_OPTIMAL, STATUS_TIME_LIMIT) and has_sol:
        x = np.asarray(h.getSolution().col_value)
        out.objective_g = None if feasibility_only else float(info.objective_function_value)
        out.best_bound_g = None if feasibility_only else float(info.mip_dual_bound)
        out.mip_gap = None if feasibility_only else float(info.mip_gap)
        out.schedule = _extract_schedule(scenario, built, x)
        out.supply_temp_C = _extract_supply(scenario, built, x)
        S, Z, T = scenario.S, scenario.Z, scenario.T
        out.model_values["T_C"] = np.array([[x[c_] for c_ in row] for row in built.Tcol])
        Tm = out.model_values["T_C"]
        c = scenario.constants
        out.model_values["DPF"] = np.clip(1.0 - built.slope * (Tm - c.T_dvfs_C), 0.0, 1.0)
        out.model_values["Q_crac_kW"] = np.array([[x[c_] for c_ in row] for row in built.Qcrac])
        out.model_values["P_IT_W"] = np.array([[x[c_] for c_ in row] for row in built.P_IT])
        out.model_values["Q_cp_W"] = np.array([[x[c_] for c_ in row] for row in built.Q_cp])
        out.cold_plate_ops = _extract_cold_plate_ops(scenario, built, x)
    elif status == STATUS_INFEASIBLE:
        pass
    return out


def _extract_schedule(scenario: Scenario, built: _Built, x: np.ndarray) -> Schedule:
    chosen: dict[int, tuple[int, int, int]] = {}
    for (i, s), xc in built.X.items():
        if x[xc] <= 0.5:
            continue
        wd = built.win[(i, s)]
        # start = first period at which the started-by step is 1 (the last step is X itself)
        steps = sorted(t for t, uc in built.U[(i, s)].items() if x[uc] > 0.5)
        start = steps[0] if steps else wd.b
        tail = sum(1 for ec in built.E[(i, s)].values() if x[ec] > 0.5)
        chosen[i] = (s, start, start + wd.n_min + tail)
    pl = []
    for w in scenario.workloads:
        if w.i in chosen:
            s, st, en = chosen[w.i]
            pl.append(Placement(i=w.i, server=s, start=st, end=en))
        else:
            pl.append(Placement(i=w.i, server=None, start=None, end=None))
    return Schedule(placements=tuple(pl))


def _extract_supply(scenario: Scenario, built: _Built, x: np.ndarray) -> np.ndarray:
    Z, T = scenario.Z, scenario.T
    if built.fixed_value is not None:
        return np.full((Z, T), float(built.fixed_value))
    out = np.zeros((Z, T))
    for (z, t), cols in built.choice.items():
        k = int(np.argmax([x[col] for col in cols]))
        out[z - 1, t] = built.levels[k]
    return out


def _extract_cold_plate_ops(scenario: Scenario, built: _Built, x: np.ndarray) -> ColdPlateOps | None:
    if not built.cp_cols.b:
        return None
    flows = scenario.cold_plate.flow_settings_Lmin
    flow = np.full((scenario.S, scenario.T), np.nan)
    cool = np.full((scenario.S, scenario.T), np.nan)
    for k, bk in built.cp_cols.b.items():
        for t, b in enumerate(bk):
            flow[k, t] = flows[int(np.argmax([x[c_] for c_ in b]))]
            cool[k, t] = x[built.cp_cols.cool[k][t]]
    cp = scenario.cold_plate
    cool = np.clip(cool, cp.coolant_min_C, cp.coolant_max_C)    # solver round-off only
    return ColdPlateOps(flow_Lmin=flow, coolant_C=cool)


def solve(scenario: Scenario, original_server: dict[int, int], settings: RunSettings, *,
          relax: tuple[str, ...] = (), warm_start: Schedule | None = None,
          warm_start_supply_temp_C: np.ndarray | None = None,
          time_limit_s: float | None = None, log: bool = False,
          ignore_temperature: bool = False) -> SolveResult:
    """Build and solve the MILP. See the module docstring for the model.

    ``ignore_temperature`` solves it without server temperature (no recursion, no thermal
    cap, DPF = 1); its schedule is not checked against the thermal limits."""
    return _solve_impl(scenario, original_server, settings, relax=relax, warm_start=warm_start,
                       warm_start_supply_temp_C=warm_start_supply_temp_C,
                       time_limit_s=time_limit_s, log=log, feasibility_only=False,
                       ignore_temperature=ignore_temperature)


def diagnose_infeasibility(scenario: Scenario, original_server: dict[int, int],
                           settings: RunSettings, *,
                           time_limit_s: float = 120.0) -> dict[str, str]:
    """Re-solve with one constraint family relaxed at a time (first feasible point is enough).

    Returns {family: "feasible" | "infeasible" | "unknown (time limit)"} for all families.
    ``time_limit_s`` applies to each family separately.
    """
    settings.validate()
    out: dict[str, str] = {}
    for fam in RELAX_FAMILIES:
        if fam == RELAX_PRIORITY and not settings.priority:
            continue
        res = _solve_impl(scenario, original_server, settings, relax=(fam,), warm_start=None,
                          warm_start_supply_temp_C=None, time_limit_s=time_limit_s, log=False,
                          feasibility_only=True)
        if res.status in (STATUS_OPTIMAL, STATUS_TIME_LIMIT):
            out[fam] = "feasible"
        elif res.status == STATUS_INFEASIBLE:
            out[fam] = "infeasible"
        else:
            out[fam] = "unknown (time limit)"
    return out
