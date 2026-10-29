"""Chapter 6 experiments: the fleet configurations and the tests each one goes through.

One list for the solver, the batch notebook and the site. A run belongs to a test when its
configuration and its switches match the test's, so a folder name never decides it: a run
made in the batch notebook or uploaded on the site is recognized too.

A configuration is a fleet on a load level. Fleets: 10 servers (3 slow / 4 mid / 3 fast),
6 servers (2 / 2 / 2) and 2 servers (2 mid). The slow (2.1 GHz) and mid (2.4 GHz) servers are
Dell R840s cooled by CRAC air; the fast (2.6 GHz) ones are Dell C6320s cooled by CRAC air and a
cold plate. The frequencies are those of SPEC CPU results for these models. Load levels: a
light, normal and heavy day, whose workloads are drawn until peak demand reaches 30, 60 or
85 % of the fleet's cores or memory, whichever fills first. The normal day of a fleet is scenario ``servers10`` (``servers6``,
``servers2``), the others ``servers10_light`` and ``servers10_heavy``; each has a ``_swing``
twin with a deeper daily carbon swing (6.4 Test 3b). ``thesis10`` and ``consolidated6`` (and
their ``_swing``) are the earlier names of the 10- and 6-server normal days.
"""

from __future__ import annotations

from dataclasses import dataclass

from scheduler.types import RunSettings

# Server tiers, slowest first: name -> clock frequency (MHz).
TIERS = {"slow": 2100.0, "mid": 2400.0, "fast": 2600.0}
COLD_PLATE_TIER = "fast"        # servers of this tier carry a cold plate (CT_s = 1)

Switches = tuple[tuple[str, object], ...]
SWING: Switches = (("ci_amplitude", 0.5),)


@dataclass(frozen=True)
class Level:
    key: str                    # "light", "normal", "heavy"
    label: str                  # "Normal day"
    target: float               # peak demand, as a share of the fleet's cores or memory

    @property
    def description(self) -> str:
        return (f"workloads drawn until peak demand reaches {self.target:.0%} of the fleet's "
                "cores or memory, whichever fills first")


LEVELS: tuple[Level, ...] = (
    Level("light", "Light day", 0.30),
    Level("normal", "Normal day", 0.60),
    Level("heavy", "Heavy day", 0.85),
)
LEVEL_BY_KEY = {lv.key: lv for lv in LEVELS}
NORMAL = "normal"


@dataclass(frozen=True)
class Configuration:
    key: str                    # results/<key>/ and the scenario name: servers10, servers10_light
    tiers: tuple[str, ...]      # tier of each server, in server order
    aliases: tuple[tuple[str, Switches], ...]   # scenario names holding it -> switches implied
    regroup_zone_map: tuple[int, ...] | None    # 6.1 Test 1; None: not applicable
    fleet_key: str = ""         # servers10, servers6, servers2
    level: str = NORMAL         # a LEVELS key

    @property
    def n_servers(self) -> int:
        return len(self.tiers)

    @property
    def size_label(self) -> str:
        return f"{self.n_servers} servers"

    @property
    def level_label(self) -> str:
        return LEVEL_BY_KEY[self.level].label

    @property
    def label(self) -> str:
        """'10 servers · normal day'."""
        return f"{self.size_label} · {self.level_label.lower()}"

    @property
    def fleet(self) -> str:
        """'4 slow · 3 mid · 3 fast'."""
        return " · ".join(f"{self.tiers.count(t)} {t}" for t in TIERS if t in self.tiers)

    @property
    def has_cold_plates(self) -> bool:
        return COLD_PLATE_TIER in self.tiers


def scenario_name(fleet_key: str, level: str) -> str:
    """The scenario of a fleet on a load level: servers10, servers10_light, servers10_heavy."""
    return fleet_key if level == NORMAL else f"{fleet_key}_{level}"


def _fleet(fleet_key: str, tiers: tuple[str, ...], regroup: tuple[int, ...] | None,
           earlier: tuple[str, ...] = ()) -> tuple[Configuration, ...]:
    """The fleet on each load level; ``earlier`` names its normal day had before."""
    out = []
    for level in LEVELS:
        names = [scenario_name(fleet_key, level.key)]
        if level.key == NORMAL:
            names += earlier
        aliases = tuple(a for n in names for a in ((n, ()), (f"{n}_swing", SWING)))
        out.append(Configuration(names[0], tiers, aliases, regroup, fleet_key, level.key))
    return tuple(out)


CONFIGURATIONS: tuple[Configuration, ...] = (
    # 6.1 Test 1 regroups by tier: the slow tier in zone 1, the others in zone 2.
    *_fleet("servers10", ("slow",) * 3 + ("mid",) * 4 + ("fast",) * 3,
            (1, 1, 1, 2, 2, 2, 2, 2, 2, 2), earlier=("thesis10",)),
    *_fleet("servers6", ("slow",) * 2 + ("mid",) * 2 + ("fast",) * 2,
            (1, 1, 2, 2, 2, 2), earlier=("consolidated6",)),
    # Base zones alternate (server 1 in zone 1, server 2 in zone 2); regrouping puts both in
    # one zone. No fast server, so no cold plate: 6.2 does not apply.
    *_fleet("servers2", ("mid", "mid"), (1, 1)),
)
CONFIGURATION_BY_KEY = {c.key: c for c in CONFIGURATIONS}
# The fleets, in order: key -> its normal-day configuration (for the size and fleet labels).
FLEETS = {c.fleet_key: c for c in CONFIGURATIONS if c.level == NORMAL}


def configuration(fleet_key: str, level: str = NORMAL) -> Configuration:
    return CONFIGURATION_BY_KEY[scenario_name(fleet_key, level)]


# A switch whose value comes from the configuration (6.1 Test 1's zone map).
REGROUP = "<regroup zone map>"


@dataclass(frozen=True)
class Test:
    __test__ = False            # not a pytest test class
    id: str                     # also the run folder: results/<configuration>/<id>/
    name: str
    switches: Switches = ()
    needs: str | None = None    # "regroup" or "cold_plates": not applicable without it


TESTS: tuple[Test, ...] = (
    Test("base", "Base"),
    Test("s1_t1_zones", "Same-type servers regrouped into one zone",
         (("zone_map", REGROUP),), needs="regroup"),
    Test("s1_t2_same_zone", "Moves only within the original zone",
         (("reassignment", "same_zone"),)),
    # Cold plates are on in every run (RunSettings default), so 6.2's reference is the Base.
    Test("s2_t1_crac", "CRAC changed, cold plates fixed",
         (("cp_mode", "fixed"),), needs="cold_plates"),
    Test("s2_t2_cold_plate", "Cold plates changed, CRAC fixed",
         (("supply_temp_mode", "fixed"),), needs="cold_plates"),
    Test("s3_t1_hmin_high", "High safety margin, 19 °C", (("H_min_C", 19.0),)),
    Test("s3_t2_hmin_med", "Medium safety margin, 15 °C", (("H_min_C", 15.0),)),
    Test("s3_t3_hmin_low", "Low safety margin, 5 °C", (("H_min_C", 5.0),)),
    Test("s4_t1_no_moves", "No reassignment (r_is = 0)", (("reassignment", "none"),)),
    Test("s4_t2_blind", "Moves chosen without temperature",
         (("placement", "thermal_blind"),)),
    Test("s4_t3a_ci_flat", "Flat carbon intensity", (("ci_amplitude", 0.0),)),
    Test("s4_t3b_ci_swing", "Deeper daily carbon swing (amplitude 0.50)",
         (("ci_amplitude", 0.5),)),
)
TEST_BY_ID = {t.id: t for t in TESTS}


@dataclass(frozen=True)
class Section:
    key: str                    # "6.1"
    title: str
    question: str
    goal: str
    tests: tuple[tuple[str, str], ...]      # (tag, test id): the first is the reference
    note: str = ""


SECTIONS: tuple[Section, ...] = (
    Section("6.1", "Effect of cooling zone restrictions on workload reassignment",
            "How does the zoning of servers interact with workload reassignment?",
            "Determine whether grouping servers into cooling zones affects where workloads "
            "are assigned or reassigned, and whether restricting reassignment to the same "
            "zone affects performance.",
            (("Base", "base"), ("Test 1", "s1_t1_zones"), ("Test 2", "s1_t2_same_zone")),
            "Same servers, workloads, cooling settings and carbon intensity in every run. "
            "Test 1 changes only the zone of each server; Test 2 lets a waiting workload "
            "move only within its original zone, and workloads already running stay put."),
    Section("6.2", "Effect of cooling configuration on server temperature",
            "Which cooling system has a greater impact on reducing server temperature?",
            "Determine which cooling system has a greater effect on reducing server "
            "temperature.",
            (("Base", "base"), ("Test 1", "s2_t1_crac"), ("Test 2", "s2_t2_cold_plate")),
            "Both cooling systems stay active, as in every run; the Base optimizes both. "
            "Test 1 lets the CRAC supply air temperature change with the cold plates fixed; "
            "Test 2 lets the cold-plate coolant temperature and flow change with the CRAC "
            "fixed at 18 °C. Airflow is not modelled, so the CRAC changes only its supply air "
            "temperature."),
    Section("6.3", "Effect of thermal headroom on workload completion and QoS",
            "How does controlling thermal stress affect workload completion time and QoS "
            "under deadline-aware scheduling?",
            "Determine whether requiring servers to stay cooler affects how quickly "
            "workloads finish and whether deadlines are met.",
            (("Base", "base"), ("Test 1", "s3_t1_hmin_high"), ("Test 2", "s3_t2_hmin_med"),
             ("Test 3", "s3_t3_hmin_low")),
            "Only the minimum thermal headroom H_min changes: 10 °C in the base, then 19, 15 "
            "and 5 °C. Each server must stay H_min below its temperature limit."),
    Section("6.4", "Effect of thermal-aware reassignment on carbon footprint and QoS",
            "How does thermal-aware reassignment of workloads affect total carbon footprint "
            "and QoS?",
            "Determine whether considering temperature when reassigning waiting workloads "
            "reduces total carbon emissions while still meeting deadlines.",
            (("Base", "base"), ("Test 1", "s4_t1_no_moves"), ("Test 2", "s4_t2_blind"),
             ("Test 3a", "s4_t3a_ci_flat"), ("Test 3b", "s4_t3b_ci_swing")),
            "The base weighs server capacity, temperature and effective speed. Test 2 "
            "chooses servers without temperature, then applies every safety limit. Test 3 "
            "changes the shape of carbon intensity over the day: flat (3a) or a deeper swing "
            "(3b). Scaling it up or down by a constant would leave the schedule unchanged."),
)
SECTION_BY_KEY = {s.key: s for s in SECTIONS}


def sections_of(test_id: str) -> list[tuple[Section, str]]:
    """Every (section, tag) a test appears in; the base appears in every section."""
    return [(s, tag) for s in SECTIONS for tag, tid in s.tests if tid == test_id]


def title_of(test: Test) -> str:
    """'6.1 · Test 1 · Same-type servers regrouped into one zone'; the shared base is 'Base'."""
    where = sections_of(test.id)
    if test.id == "base" or not where:
        return test.name
    section, tag = where[0]
    return f"{section.key} · {tag} · {test.name}"


def applicable(test: Test, config: Configuration) -> bool:
    if test.needs == "regroup":
        return config.regroup_zone_map is not None
    if test.needs == "cold_plates":
        return config.has_cold_plates
    return True


def switches_for(test: Test, config: Configuration) -> dict:
    """The test's switches for this configuration (the regroup zone map filled in)."""
    return {k: (config.regroup_zone_map if v == REGROUP else v) for k, v in test.switches}


# ---------------------------------------------------------------------------
# Matching a run to its configuration and tests
# ---------------------------------------------------------------------------

# Settings that never decide a test: names, solver limits, the seed of a rule not used, and
# whether the optimizer re-plans every tick or plans the whole day at once.
IGNORED = frozenset({"scenario", "run_name", "time_limit_s", "mip_rel_gap", "seed", "per_tick",
                     "tick_time_limit_s"})


def configuration_of(scenario: str | None) -> tuple[Configuration, dict] | None:
    """The configuration a scenario holds, and the switches the scenario implies."""
    for config in CONFIGURATIONS:
        for name, implied in config.aliases:
            if name == scenario:
                return config, dict(implied)
    return None


def _value(key: str, value):
    if key == "zone_map" and value is not None:
        return tuple(int(z) for z in value)
    if isinstance(value, bool) or value is None or isinstance(value, str):
        return value
    if isinstance(value, (int, float)):
        return float(value)
    return value


def _defaults() -> dict:
    d = {k: v for k, v in RunSettings().as_dict().items() if k not in IGNORED}
    d.pop("ci_flat", None)
    d.pop("carbon_file", None)
    d["ci_amplitude"] = None            # the scenario's own carbon profile
    return {k: _value(k, v) for k, v in d.items()}


def effective_switches(settings: dict, implied: dict | None = None) -> dict:
    """A run's switches in the form the tests use. The carbon intensity becomes one switch,
    ``ci_amplitude``: 0 for a flat profile, the scenario's implied value, the run's own value,
    or None for the scenario's profile. A run with its own carbon file matches no test."""
    defaults = _defaults()
    have = {k: _value(k, settings.get(k, d)) for k, d in defaults.items()}
    amplitude = settings.get("ci_amplitude", (implied or {}).get("ci_amplitude"))
    if settings.get("ci_flat"):
        amplitude = 0.0
    have["ci_amplitude"] = _value("ci_amplitude", amplitude)
    if settings.get("carbon_file"):
        have["ci_amplitude"] = f"file:{settings['carbon_file']}"
    for k, v in (implied or {}).items():
        if k != "ci_amplitude":
            have[k] = _value(k, v)
    return have


def identify(settings: dict, scenario: str | None) -> tuple[Configuration | None, list[Test]]:
    """The configuration of a run (from its scenario) and the tests it matches: every test
    switch equal, every other switch at its default. A random baseline matches no test."""
    found = configuration_of(scenario)
    if found is None:
        return None, []
    config, implied = found
    if settings.get("baseline_rule", "least_loaded") == "random":
        return config, []
    have = effective_switches(settings, implied)
    defaults = _defaults()
    out = []
    for test in TESTS:
        if not applicable(test, config):
            continue
        want = dict(defaults)
        want.update({k: _value(k, v) for k, v in switches_for(test, config).items()})
        if have == want:
            out.append(test)
    return config, out
