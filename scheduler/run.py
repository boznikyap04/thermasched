"""Command line: build the baseline, solve the optimized schedule, compare the two.

    uv run python -m scheduler.run --scenario small
    uv run python -m scheduler.run --scenario small --baseline-rule fastest_first --baseline-supply-temp 27
    uv run python -m scheduler.run --scenario small --cold-plates
    uv run python -m scheduler.run --scenario small --cold-plate-count 2
    uv run python -m scheduler.run --scenario consolidated6 --zone-map 1,1,1,2,2,2
    uv run python -m scheduler.run --scenario consolidated6 --cold-plates --cp-mode fixed
    uv run python -m scheduler.run --scenario consolidated6 --ci-flat
    uv run python -m scheduler.run --scenario small --thermal-blind

Both schedules are scored by the shared evaluator; only its numbers are compared.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import replace
from pathlib import Path

from scheduler.baseline import build_baseline
from scheduler.evaluate import evaluate
from scheduler.io import apply_overrides, load_reference_baseline, load_scenario
from scheduler.optimize import diagnose_infeasibility, solve
from scheduler.report import format_summary, write_results
from scheduler.types import (
    BASELINE_RULES, COLD_PLATE_MODES, REASSIGNMENT_MODES, STATUS_INFEASIBLE, SUPPLY_TEMP_MODES,
    NotDefinedYet, RunSettings, constant_supply_temp,
)

OBJECTIVE_REL_TOL = 1e-6    # optimizer objective against the evaluator's carbon
NO_WORSE_REL_TOL = 1e-9     # optimized carbon against the baseline's
STAGE_SHARE = 0.2           # share of the time limit for the fixed-server first stage
BLIND_SHARE = 0.7           # thermal-blind placement: share of the time limit for pass 1


def parse_args(argv=None) -> tuple[RunSettings, argparse.Namespace]:
    d = RunSettings()
    p = argparse.ArgumentParser(prog="scheduler.run", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--scenario", default=d.scenario)
    p.add_argument("--run-name", default=None,
                   help="folder under results/<scenario>/ (default: built from the switches)")
    p.add_argument("--baseline-rule", choices=BASELINE_RULES, default=d.baseline_rule)
    p.add_argument("--seed", type=int, default=d.seed, help="for the random baseline rule")
    p.add_argument("--baseline-supply-temp", type=float, default=d.baseline_supply_temp_C,
                   help="fixed supply air temperature of the baseline, degC")
    p.add_argument("--reassignment", choices=REASSIGNMENT_MODES, default=d.reassignment)
    p.add_argument("--thermal-blind", action="store_true",
                   help="choose servers with server temperature left out, then set start times "
                        "and cooling on those servers with every thermal limit (two passes)")
    p.add_argument("--supply-temp-mode", choices=SUPPLY_TEMP_MODES, default=d.supply_temp_mode)
    p.add_argument("--fixed-supply-temp", type=float, default=None,
                   help="supply temperature when --supply-temp-mode fixed "
                        "(default: the baseline's)")
    p.add_argument("--h-min", type=float, default=None,
                   help="override the minimum thermal headroom H_min, degC")
    p.add_argument("--time-limit", type=float, default=d.time_limit_s, help="seconds")
    p.add_argument("--mip-gap", type=float, default=d.mip_rel_gap, help="relative gap")
    p.add_argument("--cold-plates", action="store_true",
                   help="model cold plates; plates per server from servers.csv (n_cold_plates, "
                        "else CT_s_cold_plate)")
    p.add_argument("--cold-plate-count", type=int, default=None,
                   help="put this many cold plates on every server (0 disables them); "
                        "implies --cold-plates")
    p.add_argument("--baseline-cp-flow", type=float, default=d.baseline_cp_flow_Lmin,
                   help="fixed cold-plate flow of the baseline, L/min (one of the flow settings)")
    p.add_argument("--baseline-cp-coolant", type=float, default=d.baseline_cp_coolant_C,
                   help="fixed cold-plate coolant temperature of the baseline, degC")
    p.add_argument("--cp-mode", choices=COLD_PLATE_MODES, default=d.cp_mode,
                   help="optimize: the optimized run picks flow and coolant per server and period; "
                        "fixed: it holds them at --fixed-cp-flow / --fixed-cp-coolant")
    p.add_argument("--fixed-cp-flow", type=float, default=None,
                   help="cold-plate flow when --cp-mode fixed, L/min (default: the baseline's)")
    p.add_argument("--fixed-cp-coolant", type=float, default=None,
                   help="coolant temperature when --cp-mode fixed, degC (default: the baseline's)")
    p.add_argument("--no-priority", action="store_true",
                   help="drop the priority rules (56)-(57) from the optimized run")
    p.add_argument("--zone-map", default=None,
                   help="zone of each server in order, e.g. 1,1,1,2,2,2 (replaces servers.csv)")
    ci = p.add_mutually_exclusive_group()
    ci.add_argument("--carbon-file", default=None,
                    help="CSV with columns t, CI_t_g_per_kWh replacing the scenario's carbon.csv")
    ci.add_argument("--ci-flat", action="store_true",
                    help="hold carbon intensity at the scenario's mean in every period")
    p.add_argument("--fan-power", action="store_true", help="not defined yet")
    p.add_argument("--baseline-only", action="store_true", help="skip the optimized run")
    p.add_argument("--no-warm-start", action="store_true",
                   help="do not offer the solver a starting schedule")
    p.add_argument("--diagnosis-time-limit", type=float, default=120.0,
                   help="seconds per relaxed re-solve when no valid schedule exists")
    p.add_argument("--solver-log", action="store_true")
    p.add_argument("--scenarios-dir", default="scenarios")
    p.add_argument("--results-dir", default="results")
    a = p.parse_args(argv)
    cold_plates = a.cold_plates or a.cold_plate_count is not None
    zone_map = None
    if a.zone_map:
        try:
            zone_map = tuple(int(z) for z in a.zone_map.split(","))
        except ValueError:
            p.error(f"--zone-map must be comma-separated zone numbers, got {a.zone_map!r}")

    settings = RunSettings(
        scenario=a.scenario, baseline_rule=a.baseline_rule, seed=a.seed,
        baseline_supply_temp_C=a.baseline_supply_temp, reassignment=a.reassignment,
        placement="thermal_blind" if a.thermal_blind else d.placement,
        supply_temp_mode=a.supply_temp_mode, fixed_supply_temp_C=a.fixed_supply_temp,
        H_min_C=a.h_min, time_limit_s=a.time_limit, mip_rel_gap=a.mip_gap,
        cold_plates=cold_plates, cold_plate_count=a.cold_plate_count,
        baseline_cp_flow_Lmin=a.baseline_cp_flow, baseline_cp_coolant_C=a.baseline_cp_coolant,
        cp_mode=a.cp_mode, fixed_cp_flow_Lmin=a.fixed_cp_flow, fixed_cp_coolant_C=a.fixed_cp_coolant,
        priority=not a.no_priority, zone_map=zone_map, carbon_file=a.carbon_file,
        ci_flat=a.ci_flat, fan_power=a.fan_power,
    )
    settings.run_name = a.run_name or default_run_name(settings)
    return settings, a


def default_run_name(settings: RunSettings) -> str:
    """Run folder name built from the switches, e.g. ``least_loaded_base18_free_optimize``.

    Every switch that can change the result and differs from its default is in the name,
    so two runs with different switches never share a folder."""
    st, d = settings, RunSettings()
    fixed_temp = st.optimized_fixed_supply_temp_C()
    cp_fixed = st.cold_plates and st.cp_mode == "fixed"
    fixed_cp = (None if (st.fixed_cp_flow_Lmin, st.fixed_cp_coolant_C) == (None, None)
                else st.optimized_fixed_cp())
    cp_values = ((st.baseline_cp_flow_Lmin, st.baseline_cp_coolant_C)
                 != (d.baseline_cp_flow_Lmin, d.baseline_cp_coolant_C))
    return "_".join([
        st.baseline_rule, f"base{st.baseline_supply_temp_C:g}", st.reassignment,
        st.supply_temp_mode if st.supply_temp_mode == "optimize" else f"fixed{fixed_temp:g}",
    ] + (["tblind"] if st.placement == "thermal_blind" else []) + ([] if not st.cold_plates else
         ["cp" if st.cold_plate_count is None else f"cp{st.cold_plate_count}"])
      + ([f"bcp{st.baseline_cp_flow_Lmin:g}-{st.baseline_cp_coolant_C:g}"]
         if st.cold_plates and cp_values else [])
      + ([] if not cp_fixed else
         ["cpfixed" if fixed_cp is None else f"cpfixed{fixed_cp[0]:g}-{fixed_cp[1]:g}"])
      + (["noprio"] if not st.priority else [])
      + ([f"zones{''.join(map(str, st.zone_map))}"] if st.zone_map else [])
      + (["ciflat"] if st.ci_flat else [])
      + ([f"ci-{Path(st.carbon_file).stem}"] if st.carbon_file else [])
      + ([f"hmin{st.H_min_C:g}"] if st.H_min_C is not None else [])
      + ([f"seed{st.seed}"] if st.baseline_rule == "random" else [])
      + ([f"tl{st.time_limit_s:g}"] if st.time_limit_s != d.time_limit_s else [])
      + ([f"gap{st.mip_rel_gap:g}"] if st.mip_rel_gap != d.mip_rel_gap else []))


def solve_staged(scenario, original, settings, base_sched, base_supply, warm_start, log):
    """Solve the optimized model, offering the solver a starting schedule.

    The start is the baseline. When servers may change, the same model is first solved
    with every server fixed (a much smaller problem whose solutions are all valid for
    the full one) and its schedule is offered instead. A start only gives the solver a
    first incumbent; it does not change the model or its optimum.
    """
    if not warm_start:
        return solve(scenario, original, settings, log=log)
    start_sched, start_supply = base_sched, base_supply
    stage_time, stage_note = 0.0, None
    if settings.reassignment != "none":
        stage = solve(scenario, original, replace(settings, reassignment="none"),
                      warm_start=base_sched, warm_start_supply_temp_C=base_supply,
                      time_limit_s=STAGE_SHARE * settings.time_limit_s, log=log)
        stage_time = stage.solve_time_s
        if stage.has_schedule:
            start_sched, start_supply = stage.schedule, stage.supply_temp_C
            stage_note = (
                f"Starting schedule: the same model with reassignment=none, solved first "
                f"({stage.status}, {stage.objective_g:,.2f} g, {stage_time:.1f} s); its time "
                f"is included in the solve time.")
        else:
            stage_note = (f"Starting schedule: the baseline (the reassignment=none stage "
                          f"ended with status {stage.status} after {stage_time:.1f} s).")
    result = solve(scenario, original, settings, warm_start=start_sched,
                   warm_start_supply_temp_C=start_supply,
                   time_limit_s=max(1.0, settings.time_limit_s - stage_time), log=log)
    result.solve_time_s += stage_time
    if stage_note:
        result.notes.append(stage_note)
    return result


def solve_thermal_blind(scenario, original, settings, base_sched, base_supply, warm_start, log):
    """Thermal-blind placement in two passes. Returns the result and the (servers, settings)
    the result was solved with, for the infeasibility diagnosis.

    Pass 1 solves the model with server temperature left out (no recursion, no thermal cap,
    DPF = 1) and keeps only the server of each workload. Pass 2 fixes every workload to that
    server and solves the full model, every thermal limit included, for start times and
    cooling. If pass 2 has no valid schedule, that is the result: no fallback.
    """
    t1 = BLIND_SHARE * settings.time_limit_s
    pass1 = solve(scenario, original, settings, ignore_temperature=True,
                  warm_start=base_sched if warm_start else None,
                  warm_start_supply_temp_C=base_supply if warm_start else None,
                  time_limit_s=t1, log=log)
    gap = "-" if pass1.mip_gap is None else f"{pass1.mip_gap:.2%}"
    if not pass1.has_schedule:
        pass1.notes.append(
            f"Thermal-blind placement: pass 1 (servers chosen with server temperature left out) "
            f"ended with status {pass1.status} after {pass1.solve_time_s:.1f} s and no schedule, "
            "so pass 2 was not run.")
        return pass1, (original, settings)
    servers = pass1.schedule.server_of()
    moved = sum(1 for i, sv in servers.items() if sv != original[i])
    fixed = replace(settings, reassignment="none")
    pass2 = solve(scenario, servers, fixed,
                  warm_start=pass1.schedule if warm_start else None,
                  warm_start_supply_temp_C=pass1.supply_temp_C if warm_start else None,
                  time_limit_s=max(1.0, settings.time_limit_s - pass1.solve_time_s), log=log)
    pass2.solve_time_s += pass1.solve_time_s
    pass2.notes.append(
        f"Thermal-blind placement, pass 1: servers chosen with server temperature left out "
        f"(no temperature recursion, no thermal cap, DPF = 1); {pass1.status}, "
        f"{pass1.objective_g:,.2f} g, gap {gap}, {pass1.solve_time_s:.1f} s; {moved} workload(s) "
        f"on another server than the baseline's.")
    pass2.notes.append(
        "Thermal-blind placement, pass 2: every workload fixed to its pass-1 server; start times "
        "and cooling solved with every thermal limit. The status, gap and objective above are "
        "pass 2's; the solve time includes pass 1.")
    return pass2, (servers, fixed)


def optimized_checks(scenario, settings, original, base_eval, result, opt_eval) -> dict:
    """Checks on an optimized schedule: the solver's objective equals the evaluator's carbon,
    the evaluator finds no broken limit, running workloads stay put, and with nothing to
    optimise but timing the result is no worse than a valid baseline."""
    out: dict = {}
    diff = abs(result.objective_g - opt_eval.total_carbon_g)
    out["optimizer_objective_equals_evaluator_carbon"] = {
        "passed": diff <= OBJECTIVE_REL_TOL * abs(opt_eval.total_carbon_g),
        "optimizer_objective_g": result.objective_g,
        "evaluator_carbon_g": opt_eval.total_carbon_g,
        "relative_difference": diff / abs(opt_eval.total_carbon_g)}
    out["optimized_schedule_valid_under_evaluator"] = {
        "passed": opt_eval.valid, "violations": opt_eval.compliance["violations"]}
    running = [w.i for w in scenario.workloads if w.B == 1]
    if running:
        moved = [i for i in running
                 if result.schedule.placements[i - 1].server != original[i]]
        out["running_workloads_not_reassigned"] = {
            "passed": not moved, "running": len(running), "moved": moved}
    same_temp = (settings.supply_temp_mode == "fixed" and
                 settings.optimized_fixed_supply_temp_C() == settings.baseline_supply_temp_C)
    if settings.reassignment == "none" and same_temp:
        name = "optimized_no_worse_than_valid_baseline"
        if base_eval.valid:
            out[name] = {
                "passed": opt_eval.total_carbon_g <=
                base_eval.total_carbon_g * (1 + NO_WORSE_REL_TOL),
                "baseline_carbon_g": base_eval.total_carbon_g,
                "optimized_carbon_g": opt_eval.total_carbon_g}
        else:
            out[name] = {"passed": None, "not_applicable":
                         "the baseline breaks limits, so it is not a valid schedule"}
    return out


def format_checks(checks: dict) -> str:
    lines = ["Checks:"]
    for name, c in checks.items():
        state = {True: "PASS", False: "FAIL", None: "n/a"}.get(c.get("passed"), "info")
        detail = {k: v for k, v in c.items() if k != "passed"}
        lines.append(f"  [{state}] {name}" + (f"  {detail}" if detail else ""))
    return "\n".join(lines)


def run(settings: RunSettings, *, scenarios_dir="scenarios", results_dir="results",
        baseline_only=False, warm_start=True, diagnosis_time_limit_s=120.0,
        solver_log=False, quiet=False, made_with="command line") -> dict:
    """Run one comparison and write its results. Returns the summary dict."""
    settings.validate()
    scenario = apply_overrides(load_scenario(settings.scenario, scenarios_dir), settings)
    checks: dict = {}

    # baseline
    base_sched = build_baseline(scenario, settings)
    if settings.baseline_rule == "least_loaded":
        ref = load_reference_baseline(settings.scenario, scenarios_dir)
        checks["least_loaded_reproduces_baseline_schedule_csv"] = {
            "passed": base_sched == ref}
    base_supply = constant_supply_temp(scenario, settings.baseline_supply_temp_C)
    base_eval = evaluate(scenario, base_sched, base_supply, settings)
    original = base_sched.server_of()

    # optimized
    result = opt_eval = infeasibility = None
    if baseline_only:
        pass
    elif any(sv is None for sv in original.values()):
        unplaced = [i for i, sv in original.items() if sv is None]
        checks["optimized_run_skipped"] = {
            "reason": f"the baseline could not place workloads {unplaced}, so they have no "
                      "original server"}
    else:
        if settings.placement == "thermal_blind":
            result, (diag_servers, diag_settings) = solve_thermal_blind(
                scenario, original, settings, base_sched, base_supply, warm_start, solver_log)
        else:
            result = solve_staged(scenario, original, settings, base_sched, base_supply,
                                  warm_start, solver_log)
            diag_servers, diag_settings = original, settings
        if result.status == STATUS_INFEASIBLE:
            infeasibility = diagnose_infeasibility(scenario, diag_servers, diag_settings,
                                                   time_limit_s=diagnosis_time_limit_s)
        if result.has_schedule:
            opt_eval = evaluate(scenario, result.schedule, result.supply_temp_C, settings,
                                result.cold_plate_ops)
            checks.update(optimized_checks(scenario, settings, original, base_eval,
                                           result, opt_eval))

    out_dir = Path(results_dir) / settings.scenario / settings.run_name
    summary = write_results(
        out_dir, scenario, settings, original, base_sched, base_eval,
        result.schedule if result else None, opt_eval, result, infeasibility, checks,
        made_with=made_with)
    if not quiet:
        print(format_summary(summary))
        print("\n" + format_checks(checks))
        print(f"\nResults written to {out_dir}/")
    return summary


def main(argv=None) -> int:
    settings, a = parse_args(argv)
    try:
        summary = run(settings, scenarios_dir=a.scenarios_dir, results_dir=a.results_dir,
                      baseline_only=a.baseline_only, warm_start=not a.no_warm_start,
                      diagnosis_time_limit_s=a.diagnosis_time_limit, solver_log=a.solver_log)
    except NotDefinedYet as e:
        print(f"Not defined yet: {e}", file=sys.stderr)
        return 2
    failed = [n for n, c in summary.get("checks", {}).items() if c.get("passed") is False]
    if failed:
        print(f"\nFAILED checks: {failed}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
