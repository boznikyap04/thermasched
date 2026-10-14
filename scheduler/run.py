"""Command line: build the baseline, solve the optimized schedule, compare the two.

    uv run python -m scheduler.run --scenario small
    uv run python -m scheduler.run --scenario small --baseline-rule fastest_first --baseline-supply-temp 27
    uv run python -m scheduler.run --scenario small --cold-plates
    uv run python -m scheduler.run --scenario small --cold-plate-count 2

Both schedules are scored by the shared evaluator; only its numbers are compared.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import replace
from pathlib import Path

from scheduler.baseline import build_baseline
from scheduler.evaluate import evaluate
from scheduler.io import load_reference_baseline, load_scenario
from scheduler.optimize import diagnose_infeasibility, solve
from scheduler.report import format_summary, write_results
from scheduler.types import (
    BASELINE_RULES, REASSIGNMENT_MODES, STATUS_INFEASIBLE, SUPPLY_TEMP_MODES,
    NotDefinedYet, RunSettings, constant_supply_temp,
)

OBJECTIVE_REL_TOL = 1e-6    # optimizer objective against the evaluator's carbon
NO_WORSE_REL_TOL = 1e-9     # optimized carbon against the baseline's
STAGE_SHARE = 0.2           # share of the time limit for the fixed-server first stage


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

    run_name = a.run_name or "_".join([
        a.baseline_rule, f"base{a.baseline_supply_temp:g}", a.reassignment,
        a.supply_temp_mode if a.supply_temp_mode == "optimize" else
        f"fixed{(a.baseline_supply_temp if a.fixed_supply_temp is None else a.fixed_supply_temp):g}",
    ] + ([] if not cold_plates else
         ["cp" if a.cold_plate_count is None else f"cp{a.cold_plate_count}"]))
    settings = RunSettings(
        scenario=a.scenario, run_name=run_name, baseline_rule=a.baseline_rule, seed=a.seed,
        baseline_supply_temp_C=a.baseline_supply_temp, reassignment=a.reassignment,
        supply_temp_mode=a.supply_temp_mode, fixed_supply_temp_C=a.fixed_supply_temp,
        H_min_C=a.h_min, time_limit_s=a.time_limit, mip_rel_gap=a.mip_gap,
        cold_plates=cold_plates, cold_plate_count=a.cold_plate_count,
        baseline_cp_flow_Lmin=a.baseline_cp_flow, baseline_cp_coolant_C=a.baseline_cp_coolant,
        fan_power=a.fan_power,
    )
    return settings, a


def _solve_staged(scenario, original, settings, base_sched, base_supply, warm_start, log):
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


def run(settings: RunSettings, *, scenarios_dir="scenarios", results_dir="results",
        baseline_only=False, warm_start=True, diagnosis_time_limit_s=120.0,
        solver_log=False, quiet=False) -> dict:
    """Run one comparison and write its results. Returns the summary dict."""
    settings.validate()
    scenario = load_scenario(settings.scenario, scenarios_dir)
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
        result = _solve_staged(scenario, original, settings, base_sched, base_supply,
                               warm_start, solver_log)
        if result.status == STATUS_INFEASIBLE:
            infeasibility = diagnose_infeasibility(scenario, original, settings,
                                                   time_limit_s=diagnosis_time_limit_s)
        if result.has_schedule:
            opt_eval = evaluate(scenario, result.schedule, result.supply_temp_C, settings,
                                result.cold_plate_ops)
            diff = abs(result.objective_g - opt_eval.total_carbon_g)
            checks["optimizer_objective_equals_evaluator_carbon"] = {
                "passed": diff <= OBJECTIVE_REL_TOL * abs(opt_eval.total_carbon_g),
                "optimizer_objective_g": result.objective_g,
                "evaluator_carbon_g": opt_eval.total_carbon_g,
                "relative_difference": diff / abs(opt_eval.total_carbon_g)}
            checks["optimized_schedule_valid_under_evaluator"] = {
                "passed": opt_eval.valid, "violations": opt_eval.compliance["violations"]}
            same_temp = (settings.supply_temp_mode == "fixed" and
                         settings.optimized_fixed_supply_temp_C() == settings.baseline_supply_temp_C)
            if settings.reassignment == "none" and same_temp:
                name = "optimized_no_worse_than_valid_baseline"
                if base_eval.valid:
                    checks[name] = {
                        "passed": opt_eval.total_carbon_g <=
                        base_eval.total_carbon_g * (1 + NO_WORSE_REL_TOL),
                        "baseline_carbon_g": base_eval.total_carbon_g,
                        "optimized_carbon_g": opt_eval.total_carbon_g}
                else:
                    checks[name] = {"passed": None, "not_applicable":
                                    "the baseline breaks limits, so it is not a valid schedule"}

    out_dir = Path(results_dir) / settings.scenario / settings.run_name
    summary = write_results(
        out_dir, scenario, settings, original, base_sched, base_eval,
        result.schedule if result else None, opt_eval, result, infeasibility, checks)
    if not quiet:
        print(format_summary(summary))
        print(f"\nChecks:")
        for name, c in checks.items():
            state = {True: "PASS", False: "FAIL", None: "n/a"}.get(c.get("passed"), "info")
            detail = {k: v for k, v in c.items() if k != "passed"}
            print(f"  [{state}] {name}" + (f"  {detail}" if detail else ""))
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
