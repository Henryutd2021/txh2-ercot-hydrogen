"""The two-stage stochastic linear program, written with linopy.

First stage (scenario-independent): installed capacities x[i, k] of electrolyzers (MW), hydrogen
tanks (t) and fuel cells (MW), and the green-hydrogen demand satisfaction rate ψ_i.
Second stage (per scenario s and hour t): battery and tank operation, electrolysis, fuel-cell
generation, electricity purchased from CCGT plants, hydrogen sold, SMR hydrogen, inter-zone
pipeline flows on the arcs between adjacent zones, water use and oxygen output.

Constraint names carry the equation numbers of the article (``eq04_energy_balance`` ... ``eq17_ccgt_bound``);
``docs/formulation.md`` gives the mathematics. Two optional extensions, both off by default and
not part of the article's formulation, are documented there as well: an explicit curtailment
variable and upper bounds on the installed capacities.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Optional, Union

import linopy
import numpy as np
import pandas as pd
import xarray as xr

from .inputs import Instance
from .parameters import TECHNOLOGIES

CapacityBound = Union[None, float, Mapping[str, float]]


@dataclass(frozen=True)
class ModelOptions:
    """Model variants.

    load_flexibility      e.g. 0.05: hourly demand may move within ±5 % of χ while each zone's total
                          demand over the horizon is unchanged (article Section 3.1). None = fixed demand.
    curtailment           extension: add a non-negative curtailment variable to Eq. (4).
    capacity_upper_bound  extension: upper bound on x[i, k], one value or one per technology.
    """

    load_flexibility: Optional[float] = None
    curtailment: bool = False
    capacity_upper_bound: CapacityBound = None

    @classmethod
    def from_instance(cls, inst: Instance, **overrides) -> "ModelOptions":
        values = {"load_flexibility": inst.meta.get("load_flexibility")}
        values.update(overrides)
        return cls(**values)


@dataclass
class PlanningModel:
    """A built linopy model together with the instance and options it was built from."""

    model: linopy.Model
    instance: Instance
    options: ModelOptions


def arc_name(zone_from: str, zone_to: str) -> str:
    """Coordinate label of the pipeline arc from one zone to another."""
    return f"{zone_from}->{zone_to}"


def _capacity_upper(bound: CapacityBound, coords) -> Union[float, xr.DataArray]:
    if bound is None:
        return np.inf
    if isinstance(bound, Mapping):
        return xr.DataArray([float(bound.get(k, np.inf)) for k in TECHNOLOGIES], coords=[coords])
    return float(bound)


def build_model(inst: Instance, options: Optional[ModelOptions] = None) -> PlanningModel:
    """Build the linopy model of one instance."""
    opt = options or ModelOptions.from_instance(inst)
    p = inst.params
    n_i = len(inst.zones)

    I = pd.Index(inst.zones, name="i")
    K = pd.Index(TECHNOLOGIES, name="k")
    T = pd.RangeIndex(1, inst.hours + 1, name="t")
    T0 = pd.RangeIndex(0, inst.hours + 1, name="t")    # storage levels include the initial period 0
    S = pd.Index(inst.scenarios, name="s")

    def its(a):
        return xr.DataArray(a, coords=[I, T, S])

    chi = its(inst.demand)
    eps_r = its(inst.renewable)
    bound17 = its(inst.net_demand_bound())
    kappa = xr.DataArray(inst.h2_demand, coords=[I, T])
    hd = kappa.sum("t")                                  # hd_i: total hydrogen demand over the horizon
    xi = xr.DataArray(inst.probability, coords=[S])
    beta = xr.DataArray(inst.battery_capacity, coords=[I])

    # Pipeline arcs a = (from, to), both directions of every corridor. Incidence matrices map each arc
    # to the zone it leaves (tail) and the zone it enters (head).
    arcs = inst.arcs()
    A = pd.Index([arc_name(a, b) for a, b, _ in arcs], name="a")
    tail, head = np.zeros((len(arcs), n_i)), np.zeros((len(arcs), n_i))
    for n, (a, b, _) in enumerate(arcs):
        tail[n, inst.zones.index(a)] = 1.0
        head[n, inst.zones.index(b)] = 1.0
    tail, head = xr.DataArray(tail, coords=[A, I]), xr.DataArray(head, coords=[A, I])
    distance = xr.DataArray([d for _, _, d in arcs], coords=[A])

    m = linopy.Model()

    # First-stage variables
    x = m.add_variables(lower=0, upper=_capacity_upper(opt.capacity_upper_bound, K), coords=[I, K], name="x")
    psi = m.add_variables(lower=0, upper=1, coords=[I], name="psi")

    # Second-stage variables
    eps_h = m.add_variables(lower=0, coords=[I, T, S], name="eps_h")        # fuel-cell output, MWh
    eps_dis = m.add_variables(lower=0, coords=[I, T, S], name="eps_dis")    # battery discharging, MWh
    eps_n = m.add_variables(lower=0, coords=[I, T, S], name="eps_n")        # electricity from CCGT, MWh
    eps_cha = m.add_variables(lower=0, coords=[I, T, S], name="eps_cha")    # battery charging, MWh
    eps_e2h = m.add_variables(lower=0, coords=[I, T, S], name="eps_e2h")    # electricity to electrolysis, MWh
    h_se = m.add_variables(lower=0, coords=[I, T, S], name="h_se")          # (green) hydrogen sold, t
    h_smr = m.add_variables(lower=0, coords=[I, T, S], name="h_smr")        # SMR hydrogen, t
    w = m.add_variables(lower=0, coords=[I, T, S], name="w")                # water, t
    o = m.add_variables(lower=0, coords=[I, T, S], name="o")                # oxygen, t
    theta_h = m.add_variables(lower=0, coords=[I, T0, S], name="theta_h")   # tank level, t
    theta_b = m.add_variables(lower=0, coords=[I, T0, S], name="theta_b")   # battery level, MWh
    has_arcs = len(arcs) > 0
    if has_arcs:
        h_tr = m.add_variables(lower=0, coords=[A, T, S], name="h_tr")    # pipeline flow on arc a, t

    # Objective, Eqs. (1)-(3): annualised installation cost + fixed O&M + expected operating cost
    c_ins = xr.DataArray([p.c_ins[k] for k in TECHNOLOGIES], coords=[K])
    c_om = xr.DataArray([p.c_om[k] for k in TECHNOLOGIES], coords=[K])
    capex = (c_ins * p.annuity_factor() * x).sum()
    fixed_om = (c_om * x).sum()
    operating = (
        (xi * p.c_w * w).sum()
        + (xi * (p.c_s * p.f_smr + p.h_cost) * h_smr).sum()
        + (xi * (p.c_p * p.f_power + p.c_pen) * eps_n).sum()
        - (xi * p.rho_h * h_se).sum()
        - (xi * p.rho_o * o).sum()
    )
    if has_arcs:
        operating = operating + (xi * p.c_tr * distance * h_tr).sum()
    m.add_objective(capex + fixed_om + inst.hour_weight * operating, sense="min")

    # Eq. (4) electricity balance
    net = eps_h + eps_dis + eps_n - eps_cha - eps_e2h
    if opt.curtailment:
        curt = m.add_variables(lower=0, coords=[I, T, S], name="curt")   # extension, MWh
        net = net - curt
    if opt.load_flexibility is None:
        m.add_constraints(net == chi - eps_r, name="eq04_energy_balance")
    else:
        f = float(opt.load_flexibility)
        chi_adj = m.add_variables(lower=(1 - f) * chi, upper=(1 + f) * chi, coords=[I, T, S], name="chi_adj")
        m.add_constraints(net - chi_adj == -eps_r, name="eq04_energy_balance")
        m.add_constraints(chi_adj.sum("t") == chi.sum("t"), name="load_flexibility_total")

    # Eq. (5) hydrogen tank balance
    tank = theta_h.shift(t=1).sel(t=T) + (1 / p.lambda_e2h) * eps_e2h - h_se - (1 / p.lambda_h2e) * eps_h
    if has_arcs:
        inflow = (head * h_tr).sum("a")       # sum over j of h_tr[j, i]
        outflow = (tail * h_tr).sum("a")      # sum over j of h_tr[i, j]
        tank = tank + inflow - outflow
    m.add_constraints(theta_h.sel(t=T) == tank, name="eq05_hydrogen_balance")

    # Eq. (6) battery balance
    m.add_constraints(
        theta_b.sel(t=T) == theta_b.shift(t=1).sel(t=T) + p.eta_cha * eps_cha - (1 / p.eta_dis) * eps_dis,
        name="eq06_battery_balance")

    # Eqs. (7)-(8) storage capacity
    m.add_constraints(theta_h.sel(t=T) <= x.sel(k="tank"), name="eq07_tank_capacity")
    m.add_constraints(theta_b.sel(t=T) <= beta, name="eq08_battery_capacity")

    # Eqs. (9)-(10) water use and oxygen output of electrolysis
    m.add_constraints(w == (p.r_w / p.lambda_e2h) * eps_e2h, name="eq09_water")
    m.add_constraints(o == (p.r_o / p.lambda_e2h) * eps_e2h, name="eq10_oxygen")

    # Eqs. (11)-(12) hydrogen demand
    m.add_constraints((xi * h_se).sum(["t", "s"]) - hd * psi == 0, name="eq11_satisfaction_rate")
    m.add_constraints((xi * (h_se + h_smr)).sum("s") >= kappa, name="eq12_hydrogen_demand")

    # Eqs. (13)-(14) conversion capacity
    m.add_constraints(eps_h <= x.sel(k="fuel_cell"), name="eq13_fuel_cell_capacity")
    m.add_constraints(eps_e2h <= x.sel(k="electrolyzer"), name="eq14_electrolyzer_capacity")

    # Eqs. (15)-(16) initial storage levels
    m.add_constraints(theta_b.sel(t=0) == p.battery_initial_soc * beta, name="eq15_battery_initial")
    m.add_constraints(theta_h.sel(t=0) == 0, name="eq16_tank_initial")

    # Eq. (17) CCGT purchase limited to the positive net demand of the hour
    m.add_constraints(eps_n <= bound17, name="eq17_ccgt_bound")

    return PlanningModel(model=m, instance=inst, options=opt)
