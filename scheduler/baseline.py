"""Greedy, thermally blind baseline scheduler.

Workloads are taken in arrival order (the order of ``scenario.workloads``). Each one starts
at the earliest period at or after its arrival where some server has room for its cores
and memory (Eq. 12-13) for the whole run and is available (AV = 1, Eq. 11) throughout. Only
cores, memory and availability are checked: no temperature or deadline. A workload that fits
nowhere gets ``Placement(i, None, None, None)``.
"""

from __future__ import annotations

import math
import random

from scheduler.types import BASELINE_RULES, Placement, RunSettings, Scenario, Schedule


def periods_needed(workload, server, dt_seconds: float) -> int:
    """Run length of ``workload`` on ``server`` in periods: ceil(W / (C_req * f * dt)), at least 1."""
    return max(1, math.ceil(workload.W_MHz_s / (workload.C_req * server.f_MHz * dt_seconds)))


def build_baseline(scenario: Scenario, settings: RunSettings) -> Schedule:
    rule = settings.baseline_rule
    if rule not in BASELINE_RULES:
        raise ValueError(f"baseline_rule must be one of {BASELINE_RULES}, got {rule!r}")

    T, dt = scenario.T, scenario.dt_seconds
    servers = scenario.servers
    # used[s - 1][t] = cores in use in period t (index 0 unused, periods 1..T)
    used = [[0] * (T + 2) for _ in servers]
    mem = [[0.0] * (T + 2) for _ in servers]    # MB in use, the same way
    AV = scenario.availability()
    rng = random.Random(settings.seed)
    by_speed = sorted(servers, key=lambda sv: (-sv.f_MHz, sv.s))

    def has_room(sv, w, start: int) -> int | None:
        """Return the end (exclusive) of the run if ``w`` fits on ``sv`` from ``start``."""
        end = start + periods_needed(w, sv, dt)
        if end - 1 > T:
            return None
        u, m, av = used[sv.s - 1], mem[sv.s - 1], AV[sv.s - 1]
        if all(u[t] + w.C_req <= sv.C_cores and m[t] + w.M_req_MB <= sv.M_MB and av[t - 1]
               for t in range(start, end)):
            return end
        return None

    placements: list[Placement] = []
    for w in scenario.workloads:
        chosen = None  # (server, start, end)
        for start in range(max(1, w.A), T + 1):
            if rule == "least_loaded":
                order = sorted(servers, key=lambda sv: (used[sv.s - 1][start], sv.s))
            elif rule == "fastest_first":
                order = by_speed
            else:  # random: pick uniformly among servers with room
                order = servers
            fits = []
            for sv in order:
                end = has_room(sv, w, start)
                if end is not None:
                    fits.append((sv, end))
                    if rule != "random":
                        break
            if fits:
                sv, end = rng.choice(fits) if rule == "random" else fits[0]
                chosen = (sv, start, end)
                break
        if chosen is None:
            placements.append(Placement(w.i, None, None, None))
            continue
        sv, start, end = chosen
        u, m = used[sv.s - 1], mem[sv.s - 1]
        for t in range(start, end):
            u[t] += w.C_req
            m[t] += w.M_req_MB
        placements.append(Placement(w.i, sv.s, start, end))
    return Schedule(tuple(placements))
