"""Read a solved :class:`PlanningModel` into tables, and check its balances.

All "expected annual" quantities are probability-weighted over scenarios and multiplied by the
instance's ``hour_weight`` (8760 / modelled hours), so they are annual even for a short horizon.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict

import numpy as np
import pandas as pd

from .model import PlanningModel, arc_name
from .parameters import TECHNOLOGIES

HOURLY = ("eps_h", "eps_dis", "eps_n", "eps_cha", "eps_e2h", "h_se", "h_smr", "w", "o")

# How printed tables show a cell without a value. In the result tables this is only the satisfaction
# rate of a zone without hydrogen demand, where psi has no meaning (docs/formulation.md, conventions).
NO_VALUE = "–"
NO_DEMAND_NOTE = f"{NO_VALUE} : zone without hydrogen demand"


def solution_arrays(pm: PlanningModel) -> Dict[str, np.ndarray]:
    """Solution values as numpy arrays: [i, t, s] for hourly variables (storage levels without the
    initial period), [i, k] for x, [i] for psi, [i, j, t, s] for h_tr (flow from zone i to zone j;
    0 where there is no pipeline)."""
    m, inst = pm.model, pm.instance
    out: Dict[str, np.ndarray] = {}
    for name in HOURLY:
        out[name] = m.variables[name].solution.transpose("i", "t", "s").values
    for name in ("theta_h", "theta_b"):
        out[name] = m.variables[name].solution.transpose("i", "t", "s").values[:, 1:, :]
        out[name + "_0"] = m.variables[name].solution.transpose("i", "t", "s").values[:, 0, :]
    out["x"] = m.variables["x"].solution.transpose("i", "k").values
    out["psi"] = m.variables["psi"].solution.values
    n_i = len(inst.zones)
    out["h_tr"] = np.zeros((n_i, n_i, inst.hours, len(inst.scenarios)))
    if "h_tr" in m.variables:
        flows = m.variables["h_tr"].solution
        for a, b, _ in inst.arcs():
            out["h_tr"][inst.zones.index(a), inst.zones.index(b)] = flows.sel(a=arc_name(a, b)).transpose("t", "s").values
    out["curt"] = (m.variables["curt"].solution.transpose("i", "t", "s").values
                   if "curt" in m.variables else np.zeros_like(out["eps_n"]))
    out["chi_adj"] = (m.variables["chi_adj"].solution.transpose("i", "t", "s").values
                      if "chi_adj" in m.variables else inst.demand.copy())
    return out


def balance_residuals(pm: PlanningModel) -> Dict[str, float]:
    """Largest absolute residual of the balance equations, recomputed from the solution values.

    eq04 electricity (MWh), eq05 hydrogen (t), eq06 battery (MWh), eq11 satisfaction rate (t),
    eq12 hydrogen demand (t, shortfall only), eq17 CCGT bound (MWh, excess only).
    """
    inst, p = pm.instance, pm.instance.params
    v = solution_arrays(pm)
    xi = inst.probability
    net = v["eps_h"] + v["eps_dis"] + v["eps_n"] - v["eps_cha"] - v["eps_e2h"] - v["curt"]
    r04 = net - (v["chi_adj"] - inst.renewable)

    inflow = v["h_tr"].sum(axis=0)          # [j, t, s]: into zone j
    outflow = v["h_tr"].sum(axis=1)         # [i, t, s]: out of zone i
    prev_h = np.concatenate([v["theta_h_0"][:, None, :], v["theta_h"][:, :-1, :]], axis=1)
    r05 = v["theta_h"] - (prev_h + inflow - outflow + v["eps_e2h"] / p.lambda_e2h - v["h_se"] - v["eps_h"] / p.lambda_h2e)
    prev_b = np.concatenate([v["theta_b_0"][:, None, :], v["theta_b"][:, :-1, :]], axis=1)
    r06 = v["theta_b"] - (prev_b + p.eta_cha * v["eps_cha"] - v["eps_dis"] / p.eta_dis)

    hd = inst.h2_demand.sum(axis=1)
    r11 = np.einsum("s,its->i", xi, v["h_se"]) - v["psi"] * hd
    r12 = np.maximum(inst.h2_demand - np.einsum("s,its->it", xi, v["h_se"] + v["h_smr"]), 0)
    r17 = np.maximum(v["eps_n"] - inst.net_demand_bound(), 0)
    return {
        "eq04_energy_balance": float(np.abs(r04).max()),
        "eq05_hydrogen_balance": float(np.abs(r05).max()),
        "eq06_battery_balance": float(np.abs(r06).max()),
        "eq11_satisfaction_rate": float(np.abs(r11).max()),
        "eq12_hydrogen_demand": float(r12.max()),
        "eq17_ccgt_bound": float(r17.max()),
    }


@dataclass
class Summary:
    """Result tables of one solved instance."""

    capacities: pd.DataFrame     # zone x technology
    zones: pd.DataFrame          # expected annual quantities by zone
    flows: pd.DataFrame          # expected annual pipeline flow by directed arc
    costs: pd.DataFrame          # annual cost components (k$/yr); they sum to the objective
    objective: float

    def to_csv(self, out_dir) -> None:
        out = Path(out_dir)
        out.mkdir(parents=True, exist_ok=True)
        self.capacities.to_csv(out / "capacities.csv")
        self.zones.to_csv(out / "zones.csv")
        self.flows.to_csv(out / "flows.csv", index=False)
        self.costs.to_csv(out / "costs.csv")


def format_table(table: pd.DataFrame, index: bool = True) -> str:
    """A result table as text, for printing.

    Cells without a value (NaN) are shown as "–"; when they are satisfaction rates, a footnote says
    that the zone has no hydrogen demand. The table itself is not changed: it keeps NaN, and
    ``Summary.to_csv`` leaves such cells empty. Numbers follow the pandas display options, e.g.
    ``display.float_format``.
    """
    text = table.to_string(na_rep=NO_VALUE, index=index)
    if "satisfaction_rate" in table.columns and table["satisfaction_rate"].isna().any():
        text += "\n" + NO_DEMAND_NOTE
    return text


def _clean(a: np.ndarray, tol: float = 1e-9) -> np.ndarray:
    """Set solver noise (|value| < tol, including -0.0) to 0 for reporting."""
    a = np.asarray(a, dtype=float)
    return np.where(np.abs(a) < tol, 0.0, a)


def summarize(pm: PlanningModel) -> Summary:
    inst, p = pm.instance, pm.instance.params
    v = {k: _clean(a) for k, a in solution_arrays(pm).items()}
    xi, W = inst.probability, inst.hour_weight

    def annual(a):      # [i, t, s] -> expected annual value per zone
        return W * np.einsum("s,its->i", xi, a)

    capacities = pd.DataFrame(v["x"], index=pd.Index(inst.zones, name="zone"), columns=list(TECHNOLOGIES))
    hd = inst.h2_demand.sum(axis=1)
    zones = pd.DataFrame({
        "h2_demand_t": W * hd,
        "green_h2_sold_t": annual(v["h_se"]),
        "smr_h2_t": annual(v["h_smr"]),
        "satisfaction_rate": np.where(hd > 0, v["psi"], np.nan),
        "electrolysis_mwh": annual(v["eps_e2h"]),
        "fuel_cell_mwh": annual(v["eps_h"]),
        "ccgt_mwh": annual(v["eps_n"]),
        "ccgt_peak_mw": v["eps_n"].max(axis=(1, 2)),
        "ccgt_co2_t": p.f_power * annual(v["eps_n"]),
        "smr_co2_t": p.f_smr * annual(v["h_smr"]),
        "battery_charge_mwh": annual(v["eps_cha"]),
        "battery_discharge_mwh": annual(v["eps_dis"]),
        "curtailment_mwh": annual(v["curt"]),
        "h2_export_t": annual(v["h_tr"].sum(axis=1)),
        "h2_import_t": annual(v["h_tr"].sum(axis=0)),
    }, index=pd.Index(inst.zones, name="zone"))

    rows = []
    for a, b, d in inst.arcs():
        ia, ib = inst.zones.index(a), inst.zones.index(b)
        rows.append({"from": a, "to": b, "distance_km": d,
                     "expected_flow_t": W * float(np.einsum("s,ts->", xi, v["h_tr"][ia, ib]))})
    flows = pd.DataFrame(rows, columns=["from", "to", "distance_km", "expected_flow_t"])

    c_ins = np.array([p.c_ins[k] for k in TECHNOLOGIES])
    c_om = np.array([p.c_om[k] for k in TECHNOLOGIES])
    dist = np.zeros((len(inst.zones),) * 2)
    for a, b, d in inst.arcs():
        dist[inst.zones.index(a), inst.zones.index(b)] = d
    transport = W * p.c_tr * float(np.einsum("s,ij,ijts->", xi, dist, v["h_tr"]))
    costs = pd.Series({
        "installation_annualised": float((v["x"] * c_ins).sum() * p.annuity_factor()),
        "fixed_om": float((v["x"] * c_om).sum()),
        "pipeline_transport": transport,
        "water": p.c_w * annual(v["w"]).sum(),
        "smr_hydrogen_and_carbon": (p.c_s * p.f_smr + p.h_cost) * annual(v["h_smr"]).sum(),
        "ccgt_electricity_and_ccs": (p.c_p * p.f_power + p.c_pen) * annual(v["eps_n"]).sum(),
        "hydrogen_revenue": -p.rho_h * annual(v["h_se"]).sum(),
        "oxygen_revenue": -p.rho_o * annual(v["o"]).sum(),
    }, name="k$_per_year").to_frame()
    if not np.all(np.isfinite(costs["k$_per_year"].to_numpy())):
        bad = costs.index[~np.isfinite(costs["k$_per_year"].to_numpy())].tolist()
        raise ValueError(f"non-finite cost component(s): {bad}")
    costs.loc["total"] = costs["k$_per_year"].sum()
    return Summary(capacities=capacities, zones=zones, flows=flows, costs=costs,
                   objective=float(pm.model.objective.value))
