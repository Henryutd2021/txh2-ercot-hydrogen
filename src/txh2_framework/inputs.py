"""The data interface of the model.

Two levels:

* :class:`BaseInputs` holds what the data pipeline produces for a study region: the zones, the
  pipeline corridors, hourly reference profiles (electricity demand, output of existing and of
  planned renewable capacity, hydrogen demand), battery capacities and the parameters. It does not
  depend on the scenario.
* :class:`Instance` is one model instance: the scenario-dependent arrays χ[i,t,s] and ε^r[i,t,s]
  built from a :class:`BaseInputs` and a scenario tree (see :mod:`txh2_framework.scenarios`).

Array layout: zone first, then hour, then scenario, i.e. ``[i, t]`` or ``[i, t, s]``. Hours are
1..T; storage levels also have an initial period 0, which the model adds itself.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Sequence, Tuple

import numpy as np

from .parameters import Parameters

HOURS_PER_YEAR = 8760


@dataclass(frozen=True)
class Pipeline:
    """A candidate pipeline corridor between two adjacent zones; flows are allowed both ways."""

    zone_a: str
    zone_b: str
    distance_km: float   # d_ij, straight-line distance between the zone centres


def _check_array(name: str, a: np.ndarray, shape: Tuple[int, ...]) -> np.ndarray:
    a = np.asarray(a, dtype=float)
    if a.shape != shape:
        raise ValueError(f"{name} has shape {a.shape}, expected {shape}")
    if not np.all(np.isfinite(a)):
        raise ValueError(f"{name} contains NaN or infinite values")
    if np.any(a < 0):
        raise ValueError(f"{name} contains negative values")
    return a


def _check_pipelines(zones: Sequence[str], pipelines: Sequence[Pipeline]) -> None:
    seen = set()
    for p in pipelines:
        if p.zone_a not in zones or p.zone_b not in zones:
            raise ValueError(f"pipeline {p.zone_a}-{p.zone_b} refers to an unknown zone")
        if p.zone_a == p.zone_b:
            raise ValueError(f"pipeline {p.zone_a}-{p.zone_b} connects a zone to itself")
        key = frozenset((p.zone_a, p.zone_b))
        if key in seen:
            raise ValueError(f"pipeline {p.zone_a}-{p.zone_b} is listed twice")
        seen.add(key)
        if not (np.isfinite(p.distance_km) and p.distance_km > 0):
            raise ValueError(f"pipeline {p.zone_a}-{p.zone_b} needs a positive, finite distance")


@dataclass
class BaseInputs:
    """Scenario-independent inputs of one study region.

    ``demand``, ``renewable_existing``, ``renewable_planned`` (MWh per hour) and ``h2_demand``
    (t per hour) have shape [zones, hours]. ``renewable_planned`` is the output of all planned
    capacity at a 100 % completion rate. Battery capacities are energy capacities in MWh.
    """

    zones: Tuple[str, ...]
    demand: np.ndarray
    renewable_existing: np.ndarray
    renewable_planned: np.ndarray
    h2_demand: np.ndarray
    battery_existing: np.ndarray
    battery_planned: np.ndarray
    pipelines: Tuple[Pipeline, ...]
    params: Parameters
    description: str = ""

    def __post_init__(self) -> None:
        self.zones = tuple(self.zones)
        self.pipelines = tuple(self.pipelines)
        self.validate()

    @property
    def hours(self) -> int:
        return int(np.asarray(self.demand).shape[1])

    def validate(self) -> None:
        if len(self.zones) == 0 or len(set(self.zones)) != len(self.zones):
            raise ValueError("zones must be a non-empty list of unique names")
        n_i = len(self.zones)
        demand = np.asarray(self.demand)
        if demand.ndim != 2 or demand.shape[0] != n_i or demand.shape[1] < 1:
            raise ValueError(f"demand must have shape [zones={n_i}, hours]")
        n_t = demand.shape[1]
        self.demand = _check_array("demand", demand, (n_i, n_t))
        self.renewable_existing = _check_array("renewable_existing", self.renewable_existing, (n_i, n_t))
        self.renewable_planned = _check_array("renewable_planned", self.renewable_planned, (n_i, n_t))
        self.h2_demand = _check_array("h2_demand", self.h2_demand, (n_i, n_t))
        self.battery_existing = _check_array("battery_existing", self.battery_existing, (n_i,))
        self.battery_planned = _check_array("battery_planned", self.battery_planned, (n_i,))
        _check_pipelines(self.zones, self.pipelines)


@dataclass
class Instance:
    """One model instance: base inputs expanded over a set of scenarios.

    ``hour_weight`` turns sums over the modelled hours into annual values in the objective
    (``8760 / hours`` by default, i.e. 1 for a full year). Probabilities must sum to 1.
    """

    zones: Tuple[str, ...]
    scenarios: Tuple[str, ...]
    probability: np.ndarray          # ξ_s
    demand: np.ndarray               # χ[i, t, s], MWh
    renewable: np.ndarray            # ε^r[i, t, s], MWh
    h2_demand: np.ndarray            # κ[i, t], t
    battery_capacity: np.ndarray     # β_i, MWh
    pipelines: Tuple[Pipeline, ...]
    params: Parameters
    hour_weight: float = None        # type: ignore[assignment]
    name: str = "instance"
    meta: Dict[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.zones = tuple(self.zones)
        self.scenarios = tuple(self.scenarios)
        self.pipelines = tuple(self.pipelines)
        if self.hour_weight is None:
            self.hour_weight = HOURS_PER_YEAR / np.asarray(self.demand).shape[1]
        self.validate()

    @property
    def hours(self) -> int:
        return int(self.demand.shape[1])

    def validate(self) -> None:
        n_i, n_s = len(self.zones), len(self.scenarios)
        if n_i == 0 or len(set(self.zones)) != n_i:
            raise ValueError("zones must be a non-empty list of unique names")
        if n_s == 0 or len(set(self.scenarios)) != n_s:
            raise ValueError("scenarios must be a non-empty list of unique names")
        demand = np.asarray(self.demand)
        if demand.ndim != 3:
            raise ValueError("demand must have shape [zones, hours, scenarios]")
        n_t = demand.shape[1]
        self.probability = _check_array("probability", self.probability, (n_s,))
        if abs(self.probability.sum() - 1.0) > 1e-9:
            raise ValueError(f"scenario probabilities sum to {self.probability.sum():.12g}, not 1")
        self.demand = _check_array("demand", demand, (n_i, n_t, n_s))
        self.renewable = _check_array("renewable", self.renewable, (n_i, n_t, n_s))
        self.h2_demand = _check_array("h2_demand", self.h2_demand, (n_i, n_t))
        self.battery_capacity = _check_array("battery_capacity", self.battery_capacity, (n_i,))
        _check_pipelines(self.zones, self.pipelines)
        if not (np.isfinite(self.hour_weight) and self.hour_weight > 0):
            raise ValueError("hour_weight must be positive and finite")

    def arcs(self):
        """Directed arcs (from, to, distance) of the pipeline network, both directions."""
        out = []
        for p in self.pipelines:
            out.append((p.zone_a, p.zone_b, p.distance_km))
            out.append((p.zone_b, p.zone_a, p.distance_km))
        return out

    def net_demand_bound(self) -> np.ndarray:
        """max(χ - ε^r, 0) for every zone, hour and scenario: the right-hand side of Eq. (17)."""
        return np.maximum(self.demand - self.renewable, 0.0)
