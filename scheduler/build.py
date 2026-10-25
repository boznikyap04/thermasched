"""Scenario builder: turns the cleaned tables in data/clean/ into a scenario folder.

``build_scenario`` writes servers.csv, workloads.csv, carbon.csv, baseline_schedule.csv and
params.json from a dict of scenario settings, the thesis constants and the cold-plate table.
``notebooks/data_prep.ipynb`` calls it for the scenarios of its Settings cell: the 6-server
fleet on a light, normal and heavy day, and ``small``.
``derive_scenario`` builds a new scenario from an existing one's params.json with some values
changed, for ``notebooks/solver.ipynb``. It reads only data/clean/, not the raw datasets.

Both notebooks hold a copy of this file, so that each runs on its own (on Colab, say);
after editing it, run ``uv run python tools/sync_notebooks.py``.
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
import random
import shutil
from pathlib import Path

from scheduler.version import VERSION


def read_csv_rows(path):
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def write_csv(path, records, fields=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = fields or list(records[0].keys())
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(records)


def pick_servers(sc, clean_dir):
    pool = [s for s in read_csv_rows(Path(clean_dir) / "servers.csv") if s["eligible"] == "1"]
    for s in pool:
        for k, v in s.items():
            if k != "server":
                s[k] = float(v)
    pool.sort(key=lambda s: s["P_max_W"] - s["P_idle_W"])
    n = sc["n_servers"]
    if n > len(pool):
        raise ValueError(f"n_servers = {n}, but only {len(pool)} servers in the cleaned table are eligible")
    chosen = [pool[int((i + 0.5) * len(pool) / n)] for i in range(n)]   # bin midpoints, no extremes

    freqs = [f for f, k in zip(sc["freq_mhz"], sc["freq_split"]) for _ in range(k)]
    top_f = max(sc["freq_mhz"])
    out = []
    for rank, (s, f) in enumerate(zip(sorted(chosen, key=lambda s: s["P_max_W"]), freqs)):
        out.append({
            "s": rank + 1, "server": s["server"], "zone": rank % sc["n_zones"] + 1,
            "f_s_MHz": f, "N_cores": int(s["N_cores"]), "C_s_cores": int(s["C_s_cores"]),
            "M_s_MB": round(s["M_s_MB"]), "PC_s_MHz": s["N_cores"] * f,
            "P_idle_W": round(s["P_idle_W"], 2), "P_max_W": round(s["P_max_W"], 2),
            "P_fit_full_load_W": round(s["P_fit_full_load_W"], 2),
            "T0_C": round(s["T0_C"], 2), "CT_s_cold_plate": int(f == top_f),
            "n_cold_plates": int(f == top_f),   # editable: plates on the server (0 = none)
            "th_a_C": round(s["th_a_C"], 3), "th_R_C_per_W": round(s["th_R_C_per_W"], 5),
            "th_alpha_5min": round(s["th_alpha_5min"], 5),
            # dynamic watts drawn per MHz of work delivered: lower is more efficient
            "W_per_MHz": round((s["P_max_W"] - s["P_idle_W"]) / (s["N_cores"] * f), 6),
        })
    return out


def is_time_sensitive(vm_id, seed, share):
    # Seeded hash of the VM id, uniform on [0, 1): depends only on this workload, so the
    # flag does not change when other workloads enter or leave the catalogue. Keyed on
    # the UFCG id because workload_id is a sort position in the catalogue and shifts with it.
    h = hashlib.sha256(f"{seed}:{vm_id}".encode()).digest()
    return int(int.from_bytes(h[:8], "big") / 2 ** 64 < share)


def pick_workloads(sc, fleet_cores, fleet_mem_mb, clean_dir):
    # Draw in seeded random order until peak requested vCPUs reach target_peak_load of the
    # fleet's cores, or peak requested memory that share of its memory, whichever comes first.
    # With top_up_by_repeats, a catalogue that runs out first is drawn again in the same
    # order: each copy keeps the workload's arrival time, work and flags, and its ID gets
    # "-r1", "-r2", ... (column `repeat`).
    T, rng = sc["periods"], random.Random(sc["seed"])
    per_day = 86400 // sc["dt_seconds"]
    start = sc["start_hour_local"] * 3600 // sc["dt_seconds"]
    cat = [w for w in read_csv_rows(Path(clean_dir) / "workloads.csv")
           if sc["min_et_periods"] <= int(w["ET_base_periods"]) <= sc["max_et_periods"]]
    rng.shuffle(cat)

    demand, mem, picked = [0] * (T + 2), [0] * (T + 2), []

    def full():
        return (max(demand) >= sc["target_peak_load"] * fleet_cores
                or max(mem) >= sc["target_peak_load"] * fleet_mem_mb)

    repeat = 0
    while True:
        n_before = len(picked)
        for w in cat:
            et, vcpu, mb = int(w["ET_base_periods"]), int(w["C_req_vcpu"]), int(w["M_req_MB"])
            a = (int(w["arrival_slot_of_day"]) - start) % per_day + 1
            rt = is_time_sensitive(w["ufcg_server_id"], sc["seed"], sc["rt_share"])
            slack = max(1, math.ceil(sc["rt_slack_frac"] * et)) if rt else \
                min(sc["dt_slack_max"], max(sc["dt_slack_min"], math.ceil(sc["dt_slack_mult"] * et)))
            d = min(a + et + slack, T + 1)          # D_i: first period by which it must be done
            if d - a - et < 1:
                continue                            # cannot finish inside the horizon
            for t in range(a, a + et):
                demand[t] += vcpu
                mem[t] += mb
            picked.append({
                "workload_id": w["workload_id"] + (f"-r{repeat}" if repeat else ""),
                "flavor": w["flavor_name"],
                "A_i": a, "D_i": d, "AD_i": d - a - et, "ET_base_i": et, "RT_i": rt, "B_i": 0,
                "C_req_i": vcpu, "M_req_i_MB": mb, "W_i_MHz_s": float(w["W_MHz_s"]),
                "usage_imputed": int(w["usage_imputed"]), "repeat": repeat,
            })
            if full():
                break
        if full() or len(picked) == n_before or not sc.get("top_up_by_repeats", False):
            break
        repeat += 1
    if not picked:
        raise ValueError("no workload fits: none can finish inside the horizon with these settings")
    picked.sort(key=lambda w: (w["A_i"], w["workload_id"]))
    for i, w in enumerate(picked, 1):
        w["i"] = i
    return picked, max(demand), max(mem), len(cat)


def carbon_profile(sc):
    # Annual mean with a synthetic daily shape: a midday dip and an evening peak.
    T, dt = sc["periods"], sc["dt_seconds"]
    hours = [(sc["start_hour_local"] + (t + 0.5) * dt / 3600) % 24 for t in range(T)]
    bump = lambda h, mu, sd: math.exp(-0.5 * (min(abs(h - mu), 24 - abs(h - mu)) / sd) ** 2)
    day = [bump(h / 12, 19, 2.0) - bump(h / 12, 12, 3.0) for h in range(288)]
    mean, span = sum(day) / 288, max(abs(x - sum(day) / 288) for x in day)
    shape = lambda h: (bump(h, 19, 2.0) - bump(h, 12, 3.0) - mean) / span
    return [{"t": t + 1, "hour_local": round(h, 3),
             "CI_t_g_per_kWh": round(sc["ci_mean_g_per_kwh"] * (1 + sc["ci_amplitude"] * shape(h)), 2)}
            for t, h in enumerate(hours)]


def baseline_schedule(servers, workloads, sc, unavailable=frozenset()):
    # Thermally unaware reference: each workload starts at arrival on the least-loaded
    # server that has room for its cores and memory, Eq. (12)-(13). `unavailable` holds
    # (server, period) pairs with AV = 0, Eq. (11).
    T, dt = sc["periods"], sc["dt_seconds"]
    used = {s["s"]: [0] * (T + 2) for s in servers}
    mem = {s["s"]: [0] * (T + 2) for s in servers}
    sched = []
    for w in workloads:
        placed = None
        for start in range(w["A_i"], T + 1):
            for s in sorted(servers, key=lambda s: (used[s["s"]][start], s["s"])):
                et = math.ceil(w["W_i_MHz_s"] / (w["C_req_i"] * s["f_s_MHz"] * dt))
                span = range(start, start + max(1, et))
                if span[-1] <= T and all(used[s["s"]][t] + w["C_req_i"] <= s["C_s_cores"]
                                         and mem[s["s"]][t] + w["M_req_i_MB"] <= s["M_s_MB"]
                                         and (s["s"], t) not in unavailable for t in span):
                    placed = (s, span)
                    break
            if placed:
                break
        if not placed:
            sched.append({"i": w["i"], "s": "", "start": "", "end": "", "late": 1})
            continue
        s, span = placed
        for t in span:
            used[s["s"]][t] += w["C_req_i"]
            mem[s["s"]][t] += w["M_req_i_MB"]
        w["X0_s"] = s["s"]
        sched.append({"i": w["i"], "s": s["s"], "start": span[0], "end": span[-1] + 1,
                      "late": int(span[-1] + 1 > w["D_i"])})
    return sched, used


def check_settings(sc):
    """The scenario settings must describe a fleet the builder can make."""
    if len(sc["freq_mhz"]) != len(sc["freq_split"]):
        raise ValueError(f"freq_mhz has {len(sc['freq_mhz'])} entries but freq_split has {len(sc['freq_split'])}")
    if sum(sc["freq_split"]) != sc["n_servers"]:
        raise ValueError(f"freq_split {sc['freq_split']} adds up to {sum(sc['freq_split'])}, "
                         f"not n_servers = {sc['n_servers']}")
    if not 1 <= sc["n_zones"] <= sc["n_servers"]:
        raise ValueError(f"n_zones = {sc['n_zones']} must be between 1 and n_servers = {sc['n_servers']}")
    if sc["periods"] < 1 or sc["min_et_periods"] > sc["max_et_periods"]:
        raise ValueError("periods must be at least 1 and min_et_periods at most max_et_periods")


def build_scenario(name, sc, const, cold_plate, *, clean_dir, scenarios_dir, f_ref_mhz,
                   slot_seconds=300, extra=None):
    """Write scenarios_dir/name/ from scenario settings ``sc``, the constants and the
    cold-plate table. ``extra`` is added to params.json. Returns (servers, diagnostics)."""
    assert sc["dt_seconds"] == slot_seconds, "period length must match the UFCG slot"
    check_settings(sc)
    out = Path(scenarios_dir) / name
    T, dt = sc["periods"], sc["dt_seconds"]

    servers = pick_servers(sc, clean_dir)
    fleet = sum(s["C_s_cores"] for s in servers)
    fleet_mem = sum(s["M_s_MB"] for s in servers)
    workloads, peak, peak_mem, n_cat = pick_workloads(sc, fleet, fleet_mem, clean_dir)
    carbon = carbon_profile(sc)
    sched, used = baseline_schedule(servers, workloads, sc)

    # Baseline IT energy and carbon by Eq. (16), (20), (3), (6); cooling is not included.
    ci = [c["CI_t_g_per_kWh"] for c in carbon]
    kwh = [sum(s["P_idle_W"] + (s["P_max_W"] - s["P_idle_W"]) * used[s["s"]][t] / s["C_s_cores"]
               for s in servers) * dt / 3.6e6 for t in range(1, T + 1)]
    cap_T = const["T_max_server_C"] - const["H_min_C"]

    def u_ceiling(s, inlet):
        # Highest steady utilization that keeps the server at or under T_max - H_min.
        p = (cap_T - inlet - s["th_a_C"]) / s["th_R_C_per_W"]
        return round(max(0.0, min(1.0, (p - s["P_idle_W"]) / (s["P_max_W"] - s["P_idle_W"]))), 3)

    for s in servers:
        s["U_ceiling_inlet_min"] = u_ceiling(s, const["T_crac_min_C"])
        s["U_ceiling_inlet_max"] = u_ceiling(s, const["T_crac_max_C"])

    write_csv(out / "servers.csv", servers)
    write_csv(out / "workloads.csv", workloads, ["i", "workload_id", "flavor", "A_i", "D_i", "AD_i", "ET_base_i",
                                                 "RT_i", "B_i", "X0_s", "C_req_i", "M_req_i_MB", "W_i_MHz_s",
                                                 "usage_imputed", "repeat"])
    write_csv(out / "carbon.csv", carbon)
    write_csv(out / "baseline_schedule.csv", sched)

    top_f = max(sc["freq_mhz"])
    top_cores = sum(s["C_s_cores"] for s in servers if s["f_s_MHz"] == top_f)   # 0: no server of that tier
    diag = {
        "I_workloads": len(workloads), "S_servers": len(servers), "Z_zones": sc["n_zones"], "T_periods": T,
        # Y_ist can only be 1 between arrival and deadline, so this is the real count
        "Y_ist_binaries_inside_windows": sum(w["D_i"] - w["A_i"] for w in workloads) * len(servers),
        "catalogue_size_within_ET_limits": n_cat,
        "fleet_cores": fleet,
        "peak_requested_vcpus": peak,
        "peak_load_share_of_fleet": round(peak / fleet, 3),
        "peak_load_share_of_fastest_tier": round(peak / top_cores, 3) if top_cores else None,
        "fleet_memory_MB": fleet_mem,
        "peak_requested_memory_MB": peak_mem,
        "peak_memory_share_of_fleet": round(peak_mem / fleet_mem, 3),
        "time_sensitive_workloads": sum(w["RT_i"] for w in workloads),
        "workloads_with_imputed_usage": sum(w["usage_imputed"] for w in workloads),
        "repeated_workloads": sum(w["repeat"] > 0 for w in workloads),
        "median_slack_periods_delay_tolerant": sorted(w["AD_i"] for w in workloads if not w["RT_i"])[
            sum(1 for w in workloads if not w["RT_i"]) // 2] if any(not w["RT_i"] for w in workloads) else None,
        "W_per_MHz_spread_best_to_worst": round(max(s["W_per_MHz"] for s in servers) / min(s["W_per_MHz"] for s in servers), 2),
        "servers_thermally_capped_at_coldest_inlet": sum(s["U_ceiling_inlet_min"] < 1 for s in servers),
        "servers_thermally_capped_at_warmest_inlet": sum(s["U_ceiling_inlet_max"] < 1 for s in servers),
        "CI_min_max_g_per_kWh": [min(ci), max(ci)],
        "baseline_IT_energy_kWh": round(sum(kwh), 2),
        # idle draw is paid whatever the schedule is: the model has no server on/off variable
        "baseline_idle_share_of_IT_energy": round(sum(s["P_idle_W"] for s in servers) * T * dt / 3.6e6 / sum(kwh), 3),
        "baseline_IT_carbon_kg": round(sum(k * c for k, c in zip(kwh, ci)) / 1000, 2),
        "baseline_unplaced_or_late": sum(x["late"] for x in sched),
    }
    params = {
        "scenario": name, "settings": sc, "constants_as_printed": const,
        "cold_plate": cold_plate,
        "time": {"dt_seconds": dt, "T": T, "period_1_local_hour": sc["start_hour_local"],
                 "convention": "A_i = first period it may run; D_i = period by which it must be finished "
                               "(CT_i = ST_i + ET_i <= D_i); AD_i = D_i - A_i - ET_base_i, Eq. (22) as an equality"},
        "work_rule": "ET_is = W_i / (C_req_i * f_s * DPF * dt): a workload is served by its own requested "
                     "cores, not the whole server. ET_base_i uses f_ref.",
        "f_ref_MHz": f_ref_mhz,
        "thermal_fit": "steady state T_cpu = T_inlet + th_a_C + th_R_C_per_W * P_IT; "
                       "per period T[t] = alpha*T[t-1] + (1-alpha)*steady, alpha = th_alpha_5min. "
                       "Fitted from UniMelb; not part of the thesis formulation.",
        "assumed_not_from_data": ["RT_i", "D_i", "zone", "CT_s_cold_plate", "n_cold_plates",
                                  "f_s_MHz assignment",
                                  "daily shape of CI_t", "AV_st = 1 for all s, t", "B_i = 0"],
        "diagnostics": diag,
        **(extra or {}),
        "built_with": {"thermasched": VERSION},
    }
    with open(out / "params.json", "w") as f:
        json.dump(params, f, indent=2)
    return servers, diag


def build_running_variant(name, start_from, running_arrivals, outage, *, scenarios_dir):
    """Write scenarios_dir/name/ as scenario ``start_from`` with some workloads already running
    (B_i = 1 for those arriving in periods ``running_arrivals`` = [first, last], Eq. 29) and
    one server down (``outage`` = {"server": s, "periods": [first, last]}, AV = 0, Eq. 11).
    The baseline schedule is rebuilt by the same least-loaded rule, skipping the downtime."""
    src, out = Path(scenarios_dir) / start_from, Path(scenarios_dir) / name
    with open(src / "params.json") as f:
        params = json.load(f)
    T, dt = params["time"]["T"], params["time"]["dt_seconds"]
    server_rows = read_csv_rows(src / "servers.csv")
    rows = read_csv_rows(src / "workloads.csv")
    servers = [{"s": int(r["s"]), "f_s_MHz": float(r["f_s_MHz"]), "C_s_cores": int(r["C_s_cores"]),
                "M_s_MB": int(r["M_s_MB"])} for r in server_rows]
    workloads = [{"i": int(r["i"]), "A_i": int(r["A_i"]), "D_i": int(r["D_i"]),
                  "C_req_i": int(r["C_req_i"]), "M_req_i_MB": int(r["M_req_i_MB"]),
                  "W_i_MHz_s": float(r["W_i_MHz_s"])} for r in rows]

    first, last = running_arrivals
    running = [r for r in rows if first <= int(r["A_i"]) <= last]
    for r in running:
        r["B_i"] = 1
    down_s, (t0, t1) = outage["server"], outage["periods"]
    if not 1 <= down_s <= len(servers) or not 1 <= t0 <= t1 <= T:
        raise ValueError(f"outage {outage} is outside the {len(servers)} servers or {T} periods")
    down = {(down_s, t) for t in range(t0, t1 + 1)}
    sched, _ = baseline_schedule(servers, workloads, {"periods": T, "dt_seconds": dt}, down)
    for r, w in zip(rows, workloads):
        r["X0_s"] = w.get("X0_s", "")

    out.mkdir(parents=True, exist_ok=True)
    for fname in ("servers.csv", "carbon.csv"):
        shutil.copyfile(src / fname, out / fname)
    write_csv(out / "workloads.csv", rows)
    write_csv(out / "baseline_schedule.csv", sched)
    write_csv(out / "availability.csv", [{"s": s, "t": t, "AV": 0} for s, t in sorted(down)])

    params.pop("variant_of", None)
    params.pop("built_with", None)
    params["scenario"] = name
    params["assumed_not_from_data"] = [
        {"AV_st = 1 for all s, t": "AV_st (availability.csv)", "B_i = 0": "B_i (first arrivals)"}.get(a, a)
        for a in params["assumed_not_from_data"]]
    params["derived_from"] = {
        "scenario": start_from,
        "changes": [
            f"B_i = 1 for the {len(running)} workloads arriving in periods {first}-{last} (already "
            f"running at the start, so they keep their server, Eq. 29)",
            f"availability.csv: server {down_s} has AV = 0 in periods {t0}-{t1} "
            f"({(t1 - t0 + 1) * dt / 3600:g} h of maintenance, Eq. 11)",
            "baseline_schedule.csv and X0_s rebuilt with the least-loaded rule, which skips "
            "unavailable periods",
        ],
        "purpose": "exercise Eq. (11) and (29), which are never binding in the other scenarios",
    }
    params["built_with"] = {"thermasched": VERSION}
    with open(out / "params.json", "w") as f:
        json.dump(params, f, indent=2)
    return sched


# A scenario's inputs, in the order they enter its fingerprint.
FINGERPRINT_FILES = ("params.json", "servers.csv", "workloads.csv", "carbon.csv",
                     "baseline_schedule.csv", "availability.csv")


def scenario_fingerprint(folder):
    """Short hash of a scenario folder's inputs: equal fingerprints mean the same scenario.
    params.json is compared by content without ``built_with``, and line endings are
    ignored, so a rebuild with a newer release or on another system still matches.
    None if the folder has no params.json."""
    folder = Path(folder)
    if not (folder / "params.json").is_file():
        return None
    h = hashlib.sha256()
    for fname in FINGERPRINT_FILES:
        path = folder / fname
        if not path.is_file():
            continue
        if fname == "params.json":
            params = json.loads(path.read_text())
            params.pop("built_with", None)
            data = json.dumps(params, sort_keys=True).encode()
        else:
            data = path.read_bytes().replace(b"\r\n", b"\n")
        h.update(fname.encode() + b"\0" + data + b"\0")
    return h.hexdigest()[:12]


# --- Only notebooks/solver.ipynb uses what follows: new scenarios from existing ones.
# (tools/sync_notebooks.py copies the code above this line into notebooks/data_prep.ipynb.)

# Written by data_prep.ipynb from its Settings cell.
# derive_scenario never overwrites them.
SHIPPED_SCENARIOS = ("servers6_light", "servers6", "servers6_heavy", "small", "small_running")


def _changed(base: dict, changes: dict | None, what: str) -> dict:
    changes = dict(changes or {})
    unknown = sorted(set(changes) - set(base))
    if unknown:
        raise ValueError(f"unknown {what}: {unknown}. Known: {sorted(base)}")
    return {k: v for k, v in changes.items() if v != base[k]}


def derive_scenario(name, start_from, settings=None, constants=None, cold_plate=None, *,
                    scenarios_dir="scenarios", clean_dir="data/clean"):
    """Build scenario ``name`` from scenario ``start_from``: its settings, constants and
    cold-plate table, with the given values changed. Each dict holds only the keys to change.

    Refuses to write over the shipped scenarios or over a folder this function did not
    write. Returns a dict with the starting and new params and the values that changed.
    """
    scenarios_dir = Path(scenarios_dir)
    if name in SHIPPED_SCENARIOS or name == start_from:
        raise ValueError(f"'{name}' is a shipped scenario or the starting one; choose a new name")
    out = scenarios_dir / name
    if out.exists() and not _built_here(out):
        raise ValueError(f"{out} exists and was not built by derive_scenario; choose a new name")
    start_path = scenarios_dir / start_from / "params.json"
    if not start_path.is_file():
        raise ValueError(f"scenario to start from not found: {start_path}")
    with open(start_path) as f:
        start = json.load(f)
    if "derived_from" in start:
        raise ValueError(f"'{start_from}' was edited by hand ({start['derived_from']['scenario']} plus "
                         f"running workloads or downtime), which the builder does not reproduce; "
                         f"start from '{start['derived_from']['scenario']}'")

    changed = {
        "settings": _changed(start["settings"], settings, "scenario setting"),
        "constants": _changed(start["constants_as_printed"], constants, "constant"),
        "cold_plate": _changed(start["cold_plate"], cold_plate, "cold-plate value"),
    }
    if "dt_seconds" in changed["settings"]:
        raise ValueError("dt_seconds is the slot length of the cleaned data and cannot be changed here")
    sc = start["settings"] | changed["settings"]
    const = start["constants_as_printed"] | changed["constants"]
    cp = start["cold_plate"] | changed["cold_plate"]
    built_from = {"scenario": start_from, "changed": {k: v for k, v in changed.items() if v}}

    build_scenario(name, sc, const, cp, clean_dir=clean_dir, scenarios_dir=scenarios_dir,
                   f_ref_mhz=start["f_ref_MHz"], slot_seconds=start["settings"]["dt_seconds"],
                   extra={"built_from": built_from})
    with open(out / "params.json") as f:
        new = json.load(f)
    return {"start": start, "params": new, "changed": built_from["changed"]}


def _built_here(d: Path) -> bool:
    try:
        with open(d / "params.json") as f:
            return "built_from" in json.load(f)
    except (OSError, ValueError):
        return False
