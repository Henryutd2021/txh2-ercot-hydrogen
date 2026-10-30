"""Scenario tree and sensitivity cases.

The article combines two independent uncertain factors, each with three levels (its Tables 1 and 2):

* the electricity demand level, which scales the reference hourly demand profile, and
* the completion rate of planned renewable capacity, which sets how much of the planned additions
  produce on top of the existing fleet.

Every combination of levels is a scenario s with probability ξ_s = P(demand level) x P(completion
level), so 3 x 3 levels give 9 scenarios. :func:`build_instance` turns a :class:`BaseInputs`, a
:class:`ScenarioTree` and an optional :class:`Case` into a model :class:`Instance`:

    χ[i, t, s]   = demand_scale x demand_factor(level_d(s)) x demand[i, t]
    ε^r[i, t, s] = renewable_existing[i, t] + completion_rate(level_r(s)) x renewable_planned[i, t]
    β_i          = battery_existing[i] + battery_completion x battery_planned[i]

A :class:`Case` describes a sensitivity run as explicit overrides of these inputs and of the
parameters; see ``docs/scenarios.md``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Mapping, Optional, Sequence, Tuple

import numpy as np

from .inputs import BaseInputs, Instance


@dataclass(frozen=True)
class Level:
    """One level of an uncertain factor: a name, the value it applies and its probability."""

    name: str
    value: float
    probability: float


@dataclass(frozen=True)
class ScenarioTree:
    """Two independent factors whose level combinations are the scenarios."""

    demand_levels: Tuple[Level, ...]       # value = factor on the reference demand profile
    completion_levels: Tuple[Level, ...]   # value = completion rate of planned renewable capacity

    def __post_init__(self) -> None:
        for label, levels in (("demand", self.demand_levels), ("completion", self.completion_levels)):
            if not levels:
                raise ValueError(f"{label} levels are empty")
            names = [lv.name for lv in levels]
            if len(set(names)) != len(names):
                raise ValueError(f"{label} level names must be unique")
            total = sum(lv.probability for lv in levels)
            if abs(total - 1.0) > 1e-9:
                raise ValueError(f"{label} level probabilities sum to {total:.12g}, not 1")
            if any(lv.probability < 0 or lv.value < 0 for lv in levels):
                raise ValueError(f"{label} levels need non-negative values and probabilities")

    def scenarios(self):
        """(name, demand level, completion level, probability) for every combination, demand level
        in the outer loop (the order of the article's Table 2)."""
        out = []
        for d in self.demand_levels:
            for r in self.completion_levels:
                out.append((f"{d.name}-{r.name}", d, r, d.probability * r.probability))
        return out


@dataclass(frozen=True)
class Case:
    """A sensitivity case expressed as explicit changes to the benchmark inputs.

    demand_scale        multiplies the demand profile of every demand level.
    completion_rates    replaces the completion rate of the named completion levels, e.g. {"M": 0.4}.
    battery_completion  share of planned battery capacity that is built (1.0 = all of it).
    capex_scale         multiplies the installation cost c^ins of the listed technologies
                        (all three hydrogen technologies by default).
    params              replaces scalar parameters, e.g. {"c_pen": 0.2} or {"c_p": 0.1, "c_s": 0.1}.
    load_flexibility    if set (e.g. 0.05), hourly demand may deviate by this share while the total
                        demand of each zone and scenario stays the same (article Section 3.1).
    """

    name: str = "benchmark"
    description: str = ""
    demand_scale: float = 1.0
    completion_rates: Mapping[str, float] = field(default_factory=dict)
    battery_completion: float = 1.0
    capex_scale: float = 1.0
    capex_technologies: Tuple[str, ...] = ("electrolyzer", "tank", "fuel_cell")
    params: Mapping[str, float] = field(default_factory=dict)
    load_flexibility: Optional[float] = None

    def __post_init__(self) -> None:
        if self.demand_scale < 0 or self.capex_scale < 0:
            raise ValueError("scales must be non-negative")
        if not 0 <= self.battery_completion <= 1:
            raise ValueError("battery_completion must be in [0, 1]")
        if self.load_flexibility is not None and not 0 <= self.load_flexibility < 1:
            raise ValueError("load_flexibility must be in [0, 1)")


def _apply_completion_rates(tree: ScenarioTree, rates: Mapping[str, float]) -> ScenarioTree:
    names = {lv.name for lv in tree.completion_levels}
    unknown = set(rates) - names
    if unknown:
        raise KeyError(f"unknown completion level(s): {sorted(unknown)}")
    levels = tuple(Level(lv.name, float(rates.get(lv.name, lv.value)), lv.probability) for lv in tree.completion_levels)
    return ScenarioTree(tree.demand_levels, levels)


def build_instance(base: BaseInputs, tree: ScenarioTree, case: Optional[Case] = None,
                   hour_weight: Optional[float] = None) -> Instance:
    """Expand base inputs over the scenario tree, applying a sensitivity case if given."""
    case = case or Case()
    tree = _apply_completion_rates(tree, case.completion_rates) if case.completion_rates else tree
    params = base.params
    if case.capex_scale != 1.0:
        params = params.with_capex_scale(case.capex_scale, case.capex_technologies)
    if case.params:
        params = params.with_overrides(**case.params)

    scen = tree.scenarios()
    n_i, n_t, n_s = len(base.zones), base.hours, len(scen)
    demand = np.empty((n_i, n_t, n_s))
    renewable = np.empty((n_i, n_t, n_s))
    for s, (_, d, r, _) in enumerate(scen):
        demand[:, :, s] = case.demand_scale * d.value * base.demand
        renewable[:, :, s] = base.renewable_existing + r.value * base.renewable_planned
    meta: Dict[str, object] = {
        "case": case.name,
        "load_flexibility": case.load_flexibility,
        "demand_level": [d.name for _, d, _, _ in scen],
        "completion_level": [r.name for _, _, r, _ in scen],
    }
    return Instance(
        zones=base.zones,
        scenarios=tuple(name for name, _, _, _ in scen),
        probability=np.array([p for _, _, _, p in scen]),
        demand=demand,
        renewable=renewable,
        h2_demand=base.h2_demand.copy(),
        battery_capacity=base.battery_existing + case.battery_completion * base.battery_planned,
        pipelines=base.pipelines,
        params=params,
        hour_weight=hour_weight,
        name=case.name,
        meta=meta,
    )


def tree_from_table(rows: Sequence[Tuple[str, str, float, float]]) -> ScenarioTree:
    """Build a tree from (factor, level, value, probability) rows, factor in {"demand", "completion"}."""
    demand, completion = [], []
    for factor, level, value, prob in rows:
        if factor == "demand":
            demand.append(Level(str(level), float(value), float(prob)))
        elif factor == "completion":
            completion.append(Level(str(level), float(value), float(prob)))
        else:
            raise ValueError(f"unknown factor {factor!r} (expected 'demand' or 'completion')")
    return ScenarioTree(tuple(demand), tuple(completion))
