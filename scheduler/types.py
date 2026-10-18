"""Shared data structures for the thermal-aware scheduling prototype.

This file is the contract between the loader, the baseline, the evaluator, the
optimizer, and the report writer. Equation numbers refer to PROJECT_CONTEXT.md.

Conventions (all modules):
- Periods are numbered 1..T as in the scenario files. Arrays over periods have length T
  and are indexed by ``t - 1``.
- Servers are numbered 1..S, zones 1..Z, workloads 1..I, all contiguous. Arrays over
  servers are indexed by ``s - 1`` and over zones by ``z - 1``.
- A workload that starts in period ``start`` and runs ``n`` periods occupies periods
  ``start, ..., start + n - 1`` and has ``end = start + n`` (exclusive, the same as
  ``end`` in ``baseline_schedule.csv``). It is on time when ``end <= D_i``.
- ``T[s, t]`` is the server temperature at the end of period t, produced by the power
  drawn during period t. ``DPF[s, t]`` is taken from ``T[s, t]`` of the same period.
- Units: power in W, ``Q_crac`` and ``P_crac`` in kW, ``dt`` in seconds, energy in kWh,
  carbon intensity in g/kWh, carbon in g, work in MHz*s, temperature in degC.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

import numpy as np

BASELINE_RULES = ("least_loaded", "fastest_first", "random")
REASSIGNMENT_MODES = ("free", "same_zone", "none")
SUPPLY_TEMP_MODES = ("optimize", "fixed")
COLD_PLATE_MODES = ("optimize", "fixed")

# Constraint families that the infeasibility diagnosis relaxes one at a time.
RELAX_DEADLINES = "deadlines_and_waiting"   # (27), (28): windows widened to the horizon
RELAX_THERMAL = "thermal_cap"               # (31)-(33): T <= T_max - H_min dropped
RELAX_CAPACITY = "capacity"                 # (12), (13)
RELAX_COOLING = "cooling_capacity"          # (54): Q_crac <= Q_crac_kW
RELAX_PRIORITY = "priority"                 # (56), (57): start order dropped
RELAX_FAMILIES = (RELAX_DEADLINES, RELAX_THERMAL, RELAX_CAPACITY, RELAX_COOLING, RELAX_PRIORITY)

# Solver outcomes reported by the optimizer.
STATUS_OPTIMAL = "optimal"            # solved to the requested gap
STATUS_TIME_LIMIT = "time_limit"      # stopped on the time limit with a valid schedule
STATUS_INFEASIBLE = "infeasible"      # proven: no valid schedule exists
STATUS_NO_SOLUTION = "no_solution"    # stopped on the time limit with no schedule found


class NotDefinedYet(NotImplementedError):
    """Raised when a switch asks for a term the thesis does not define yet."""


@dataclass(frozen=True)
class Workload:
    i: int
    workload_id: str
    flavor: str
    A: int                # first period it may run
    D: int                # period by which it must be finished (end <= D)
    AD: int               # maximum allowable delay in periods, Eq. (22)
    ET_base: int          # baseline execution time in periods at f_ref
    RT: int               # 1 time-sensitive, 0 delay-tolerant
    B: int                # 1 already started: stays on its original server
    X0: int | None        # server in the scenario's own least-loaded baseline
    C_req: int            # cores
    M_req_MB: float
    W_MHz_s: float        # work required
    usage_imputed: int = 0


@dataclass(frozen=True)
class Server:
    s: int
    name: str
    zone: int
    f_MHz: float
    C_cores: int
    M_MB: float
    P_idle_W: float
    P_max_W: float
    T0_C: float
    CT_cold_plate: int    # CT_s: 1 if the server has cold-plate cooling
    th_a_C: float         # a_s
    th_R_C_per_W: float   # R_s
    th_alpha: float       # alpha_s per period
    n_cold_plates: int | None = None   # editable count; None: CT_cold_plate (0 or 1)

    @property
    def plates(self) -> int:
        """Cold plates installed on the server."""
        return self.CT_cold_plate if self.n_cold_plates is None else self.n_cold_plates


@dataclass(frozen=True)
class Constants:
    """Constants of PROJECT_CONTEXT.md section 4.1 (params.json, constants_as_printed)."""
    R_dvfs: float
    F_throttle: float
    T_max_server_C: float
    H_min_C: float
    T_dvfs_C: float
    T_throttle_C: float
    Q_crac_kW: float
    COP_coeffs: tuple[float, float, float]   # COP(T) = c0*T^2 + c1*T + c2, T in degC
    T_crac_min_C: float
    T_crac_max_C: float
    T_max_zone_C: float
    ramp_short_lag: int = 3       # Eq. (35): 15 minutes
    ramp_short_C: float = 5.0
    ramp_long_lag: int = 12       # Eq. (36): one hour (decided, section 10)
    ramp_long_C: float = 20.0


@dataclass(frozen=True)
class ColdPlateSpec:
    """Cold-plate model agreed with the thesis group (PROJECT_CONTEXT.md section 10).

    Every plate is identical and has its own pump. Per plate and period the heat removed
    is the least of: Q_max_per_plate_W, the server's heat P_IT, and
    G_k * (T[s,t-1] - coolant), where G_k = min(1/R_k, flow_k * density * c_pw) for the
    chosen flow setting k. Pump power is pump_ref_W * (flow_k / pump_ref_flow_Lmin)^3, Eq. (48).
    """
    # Wang et al. (2026), Fig. 10(a), CPU 1: R = (T_cpu,max - T_in) / P_cpu at 200 W
    flow_settings_Lmin: tuple[float, ...] = (0.10, 0.15, 0.20, 0.25, 0.30)
    R_C_per_W: tuple[float, ...] = (0.1543, 0.1143, 0.0943, 0.0843, 0.0793)
    flow_min_Lmin: float = 0.05          # Eq. (47); the table's printed 0.005 is a typo
    flow_max_Lmin: float = 0.35
    Q_max_per_plate_W: float = 300.0     # Eq. (55), 0.3 kW per cold plate
    coolant_min_C: float = 20.0          # Eq. (49), 293.15 K
    coolant_max_C: float = 39.95         # 313.1 K as printed
    pump_ref_W: float = 0.657e-3         # Wang and Tao (2025): 0.657 mW at 0.264 L/min
    pump_ref_flow_Lmin: float = 0.264
    c_pw_J_per_kgC: float = 4182.0       # printed with a "kJ" label, read as J
    water_density_kg_per_L: float = 1.0

    def validate(self) -> None:
        n = len(self.flow_settings_Lmin)
        if n == 0 or len(self.R_C_per_W) != n:
            raise ValueError("cold plate: flow_settings_Lmin and R_C_per_W must be non-empty "
                             "and of equal length")
        if any(r <= 0 for r in self.R_C_per_W):
            raise ValueError("cold plate: every R_C_per_W must be positive")
        if any(not self.flow_min_Lmin - 1e-9 <= f <= self.flow_max_Lmin + 1e-9
               for f in self.flow_settings_Lmin):
            raise ValueError(f"cold plate: flow settings {self.flow_settings_Lmin} must lie in "
                             f"[{self.flow_min_Lmin:g}, {self.flow_max_Lmin:g}] L/min, Eq. (47)")
        if self.coolant_min_C > self.coolant_max_C:
            raise ValueError("cold plate: coolant_min_C exceeds coolant_max_C")

    def conductance_W_per_C(self) -> np.ndarray:
        """Per plate and flow setting: min(1/R, water heat capacity rate), W per degC."""
        flow = np.asarray(self.flow_settings_Lmin, dtype=float)
        water = flow / 60.0 * self.water_density_kg_per_L * self.c_pw_J_per_kgC   # Eq. (53)
        return np.minimum(1.0 / np.asarray(self.R_C_per_W, dtype=float), water)

    def pump_W(self) -> np.ndarray:
        """Per plate and flow setting, Eq. (48)."""
        flow = np.asarray(self.flow_settings_Lmin, dtype=float)
        return self.pump_ref_W * (flow / self.pump_ref_flow_Lmin) ** 3

    def level_of(self, flow_Lmin: float) -> int:
        """Index of a flow setting; raises if the flow is not one of the settings."""
        for k, f in enumerate(self.flow_settings_Lmin):
            if abs(f - flow_Lmin) < 1e-9:
                return k
        raise ValueError(f"cold-plate flow {flow_Lmin:g} L/min is not one of the settings "
                         f"{self.flow_settings_Lmin}")


@dataclass(frozen=True)
class ColdPlateOps:
    """Cold-plate operating decisions, shape (S, T). NaN for servers without cold plates."""
    flow_Lmin: np.ndarray
    coolant_C: np.ndarray


@dataclass(frozen=True)
class Scenario:
    name: str
    T: int
    dt_seconds: float
    workloads: tuple[Workload, ...]   # sorted by i; workloads[i - 1].i == i
    servers: tuple[Server, ...]       # sorted by s; servers[s - 1].s == s
    n_zones: int
    CI_g_per_kWh: np.ndarray          # shape (T,)
    constants: Constants
    cold_plate: ColdPlateSpec = field(default_factory=ColdPlateSpec)
    AV: np.ndarray | None = None      # (S, T) 0/1 availability, Eq. (11); None: all 1

    @property
    def I(self) -> int:
        return len(self.workloads)

    @property
    def S(self) -> int:
        return len(self.servers)

    @property
    def Z(self) -> int:
        return self.n_zones

    @property
    def dt_hours(self) -> float:
        return self.dt_seconds / 3600.0

    def servers_in_zone(self, z: int) -> tuple[Server, ...]:
        return tuple(sv for sv in self.servers if sv.zone == z)

    def availability(self) -> np.ndarray:
        """AV[s, t] as a (S, T) 0/1 int array, Eq. (11)."""
        if self.AV is None:
            return np.ones((self.S, self.T), dtype=int)
        return np.asarray(self.AV, dtype=int)


@dataclass
class RunSettings:
    """Every switch of a run. Written verbatim to summary.json."""
    scenario: str = "small"
    run_name: str = "default"
    # baseline
    baseline_rule: str = "least_loaded"
    seed: int = 42
    baseline_supply_temp_C: float = 18.0
    # optimized model
    reassignment: str = "free"
    supply_temp_mode: str = "optimize"
    fixed_supply_temp_C: float | None = None   # None: use baseline_supply_temp_C
    H_min_C: float | None = None               # None: use the scenario constant
    time_limit_s: float = 600.0
    mip_rel_gap: float = 1e-3
    # cold plates (off: Q_cp and pump power are zero everywhere)
    cold_plates: bool = False
    cold_plate_count: int | None = None        # plates on every server; None: servers.csv
    baseline_cp_flow_Lmin: float = 0.30        # baseline runs its cold plates fixed at these
    baseline_cp_coolant_C: float = 20.0
    cp_mode: str = "optimize"                  # "fixed": the optimized run holds them too
    fixed_cp_flow_Lmin: float | None = None    # None: use baseline_cp_flow_Lmin
    fixed_cp_coolant_C: float | None = None    # None: use baseline_cp_coolant_C
    # priority, Eq. (56)-(57)
    priority: bool = True
    # scenario overrides (applied by io.apply_overrides)
    zone_map: tuple[int, ...] | None = None    # zone per server, replaces servers.csv
    carbon_file: str | None = None             # CSV with t, CI_t_g_per_kWh
    ci_flat: bool = False                      # CI_t held at the scenario's mean
    # slot that is not defined yet
    fan_power: bool = False

    def validate(self) -> None:
        if self.baseline_rule not in BASELINE_RULES:
            raise ValueError(f"baseline_rule must be one of {BASELINE_RULES}")
        if self.reassignment not in REASSIGNMENT_MODES:
            raise ValueError(f"reassignment must be one of {REASSIGNMENT_MODES}")
        if self.supply_temp_mode not in SUPPLY_TEMP_MODES:
            raise ValueError(f"supply_temp_mode must be one of {SUPPLY_TEMP_MODES}")
        if self.cp_mode not in COLD_PLATE_MODES:
            raise ValueError(f"cp_mode must be one of {COLD_PLATE_MODES}")
        if self.carbon_file is not None and self.ci_flat:
            raise ValueError("carbon_file and ci_flat cannot both be set")
        if self.zone_map is not None and any(int(z) < 1 for z in self.zone_map):
            raise ValueError("zone_map: zones are numbered from 1")
        if self.cold_plate_count is not None:
            if not self.cold_plates:
                raise ValueError("cold_plate_count is set but cold_plates is off")
            if self.cold_plate_count < 0:
                raise ValueError("cold_plate_count must be 0 or more")
        if self.fan_power:
            raise NotDefinedYet(
                "fan_power: not defined yet. The model document has no fan-power "
                "equation; airflow is not modelled.")

    def h_min(self, scenario: Scenario) -> float:
        return scenario.constants.H_min_C if self.H_min_C is None else self.H_min_C

    def thermal_cap_C(self, scenario: Scenario) -> float:
        """Highest allowed server temperature: T_max - H_min, Eq. (31)-(33)."""
        return scenario.constants.T_max_server_C - self.h_min(scenario)

    def optimized_fixed_supply_temp_C(self) -> float:
        if self.fixed_supply_temp_C is None:
            return self.baseline_supply_temp_C
        return self.fixed_supply_temp_C

    def optimized_fixed_cp(self) -> tuple[float, float]:
        """(flow L/min, coolant degC) held by the optimized run when cp_mode is fixed."""
        flow = self.baseline_cp_flow_Lmin if self.fixed_cp_flow_Lmin is None else self.fixed_cp_flow_Lmin
        cool = (self.baseline_cp_coolant_C if self.fixed_cp_coolant_C is None
                else self.fixed_cp_coolant_C)
        return float(flow), float(cool)

    def as_dict(self) -> dict:
        return asdict(self)


def cold_plate_counts(scenario: Scenario, settings: RunSettings) -> np.ndarray:
    """Cold plates per server, shape (S,): zero everywhere when cold plates are off."""
    if not settings.cold_plates:
        return np.zeros(scenario.S, dtype=int)
    if settings.cold_plate_count is not None:
        return np.full(scenario.S, int(settings.cold_plate_count))
    return np.array([sv.plates for sv in scenario.servers], dtype=int)


def fixed_cold_plate_ops(scenario: Scenario, plates: np.ndarray, flow_Lmin: float,
                         coolant_C: float) -> ColdPlateOps:
    """One flow setting and coolant temperature for every cold plate and period."""
    scenario.cold_plate.level_of(flow_Lmin)
    has = (np.asarray(plates) > 0)[:, None]
    shape = (scenario.S, scenario.T)
    return ColdPlateOps(flow_Lmin=np.where(has, float(flow_Lmin), np.nan) * np.ones(shape),
                        coolant_C=np.where(has, float(coolant_C), np.nan) * np.ones(shape))


def priority_pairs(scenario: Scenario) -> list[tuple[int, int]]:
    """Ordered pairs (i, j) with O_ij = 1: i goes before j.

    Eq. (56): a time-sensitive i goes before a delay-tolerant j. Eq. (57): between two
    workloads of the same type and deadline, the earlier arrival goes first.

    O_ij is linked to the schedule as follows (the thesis prints no link, see
    PROJECT_CONTEXT.md A6): if i and j run on the same server and j starts while i is
    waiting (A_i <= ST_j), then ST_i <= ST_j. Workloads on different servers do not
    compete, and j may start before i arrives.
    """
    out = []
    for wi in scenario.workloads:
        for wj in scenario.workloads:
            if wi.i == wj.i:
                continue
            if (wi.RT == 1 and wj.RT == 0) or (wi.RT == wj.RT and wi.D == wj.D and wi.A < wj.A):
                out.append((wi.i, wj.i))
    return out


def cop(constants: Constants, T_supply_C):
    """CRAC coefficient of performance at a supply temperature in degC (section 4.1)."""
    c0, c1, c2 = constants.COP_coeffs
    return c0 * T_supply_C ** 2 + c1 * T_supply_C + c2


@dataclass(frozen=True)
class Placement:
    """One workload's place in a schedule. ``server`` is None if it was not placed."""
    i: int
    server: int | None
    start: int | None
    end: int | None       # exclusive: start + periods run

    @property
    def periods_run(self) -> int | None:
        return None if self.start is None else self.end - self.start


@dataclass(frozen=True)
class Schedule:
    placements: tuple[Placement, ...]   # sorted by i; placements[i - 1].i == i

    def server_of(self) -> dict[int, int | None]:
        return {p.i: p.server for p in self.placements}


def constant_supply_temp(scenario: Scenario, value_C: float) -> np.ndarray:
    """Supply temperature array of shape (Z, T) at one fixed value."""
    return np.full((scenario.Z, scenario.T), float(value_C))


@dataclass
class EvalResult:
    """Everything the shared evaluator recomputes from a schedule and supply temperatures.

    Shapes: (S, T) per server per period, (Z, T) per zone per period, (T,) per period,
    (I,) per workload. Unplaced workloads have NaN in the per-workload float arrays.
    """
    # per server per period
    cpu_used_cores: np.ndarray      # sum of C_req running, Eq. (12) left side
    mem_used_MB: np.ndarray         # Eq. (13) left side
    util: np.ndarray                # Eq. (16)
    P_IT_W: np.ndarray              # Eq. (20); equals Q_heat, Eq. (21)
    Q_cp_W: np.ndarray              # cold-plate heat removed (all plates of the server)
    P_cp_W: np.ndarray              # cold-plate pump power, Eq. (48)
    T_C: np.ndarray                 # temperature recursion
    headroom_C: np.ndarray          # Eq. (31)
    DPF: np.ndarray                 # Eq. (37), all three branches
    PC_eff_MHz: np.ndarray          # Eq. (38): N_cores * f_s * DPF
    # per zone per period
    T_supply_C: np.ndarray          # as given
    Q_crac_kW: np.ndarray           # heat removed = heat balance at equality
    COP: np.ndarray
    P_crac_kW: np.ndarray           # Q_crac / COP
    P_fan_kW: np.ndarray            # zero slot; airflow not modelled
    # per period
    E_IT_kWh: np.ndarray            # Eq. (3) summed over servers
    E_crac_kWh: np.ndarray          # Eq. (4) summed over zones
    E_cp_kWh: np.ndarray            # Eq. (5) summed over servers
    E_fan_kWh: np.ndarray           # zero slot
    E_total_kWh: np.ndarray         # Eq. (2)
    carbon_g: np.ndarray            # Eq. (6)
    # per workload
    wait_periods: np.ndarray        # start - A, Eq. (24)
    work_delivered_MHz_s: np.ndarray
    work_required_MHz_s: np.ndarray
    placed: np.ndarray              # bool
    starts_on_or_after_arrival: np.ndarray   # bool, Eq. (23)
    wait_within_allowed: np.ndarray          # bool, Eq. (28)
    on_time: np.ndarray                      # bool, Eq. (27): end <= D
    work_complete: np.ndarray                # bool, Eq. (39)
    compliant: np.ndarray                    # bool: all of the above
    min_DPF_run: np.ndarray                  # lowest DPF over the periods it runs, NaN if unplaced
    # totals
    total_carbon_g: float           # Eq. (7), (8)
    totals: dict = field(default_factory=dict)       # scalar totals, see evaluate()
    compliance: dict = field(default_factory=dict)   # every check, see evaluate()
    airflow_modelled: bool = False
    n_cold_plates: np.ndarray | None = None     # (S,)
    cp_flow_Lmin: np.ndarray | None = None      # (S, T), NaN without cold plates
    cp_coolant_C: np.ndarray | None = None      # (S, T), NaN without cold plates

    @property
    def valid(self) -> bool:
        """True when the schedule breaks no limit of the model."""
        return bool(self.compliance["all_ok"])


@dataclass
class SolveResult:
    """What the optimizer returns. Numbers here are the solver's own; the comparison
    uses the evaluator's numbers for the same schedule."""
    status: str                         # one of the STATUS_* values
    schedule: Schedule | None           # None when no schedule was found
    supply_temp_C: np.ndarray | None    # shape (Z, T)
    objective_g: float | None           # solver objective, grams CO2
    best_bound_g: float | None
    mip_gap: float | None               # relative gap reported by the solver
    solve_time_s: float
    n_variables: int
    n_binaries: int
    n_constraints: int
    relaxed: tuple[str, ...] = ()       # constraint families relaxed in this solve
    solver_status_text: str = ""        # raw HiGHS model status
    notes: list[str] = field(default_factory=list)
    model_values: dict = field(default_factory=dict)   # optional solver-side T, DPF, ...
    cold_plate_ops: ColdPlateOps | None = None          # None when cold plates are off

    @property
    def has_schedule(self) -> bool:
        return self.schedule is not None
