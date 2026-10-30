"""Techno-economic parameters of the planning model.

Field names follow the nomenclature of the article (Li & Zhang, Int. J. Hydrogen Energy 113 (2025)
77-89); the symbol of each field is given in its comment. Units are those of the model:
costs in k$ (thousand US dollars), electricity in MWh (an hourly flow in MW equals MWh per hour),
hydrogen, water, oxygen and CO2 in metric tonnes (t).

There are no built-in benchmark values: the article lists its benchmark values in Table 3, and
:func:`txh2_framework.synthetic.illustrative_parameters` provides illustrative values for the
synthetic example.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from typing import Dict, Mapping

# Technology set K of the article: k = 1 electrolyzer, k = 2 hydrogen storage tank, k = 3 fuel cell.
TECHNOLOGIES = ("electrolyzer", "tank", "fuel_cell")
TECHNOLOGY_UNITS = {"electrolyzer": "MW", "tank": "t", "fuel_cell": "MW"}

# Scalar parameters: field name -> (article symbol, unit, description)
SCALAR_PARAMETERS: Dict[str, tuple] = {
    "delta": ("δ", "-", "discount rate"),
    "lifetime": ("lifetime", "years", "technology lifetime"),
    "lambda_e2h": ("λ^e2h", "MWh/t", "electricity per tonne of hydrogen produced by electrolysis"),
    "lambda_h2e": ("λ^h2e", "MWh/t", "electricity generated per tonne of hydrogen in the fuel cell"),
    "eta_cha": ("η^cha", "-", "battery charging efficiency"),
    "eta_dis": ("η^dis", "-", "battery discharging efficiency"),
    "rho_h": ("ρ^h", "k$/t", "hydrogen sale price (green hydrogen sold)"),
    "rho_o": ("ρ^o", "k$/t", "oxygen sale price"),
    "c_w": ("c^w", "k$/t", "deionized water cost"),
    "r_w": ("r^w", "t/t", "water use per tonne of hydrogen"),
    "r_o": ("r^o", "t/t", "oxygen output per tonne of hydrogen"),
    "c_tr": ("c^tr", "k$/(t km)", "pipeline transport cost per tonne and km"),
    "c_s": ("c^s", "k$/t CO2", "carbon (capture and storage) cost of SMR CO2"),
    "f_smr": ("f^smr", "t CO2/t", "SMR emission factor"),
    "h_cost": ("h^cost", "k$/t", "cost of SMR hydrogen"),
    "c_p": ("c^p", "k$/t CO2", "capture and storage cost of CCGT CO2"),
    "f_power": ("f^power", "t CO2/MWh", "CCGT emission factor"),
    "c_pen": ("c^pen", "k$/MWh", "price (penalty) of electricity purchased from CCGT plants"),
    "battery_initial_soc": ("-", "-", "initial battery state of charge as a share of capacity, Eq. (15)"),
}


@dataclass(frozen=True)
class Parameters:
    """All parameters of the objective and constraints except the time series and zone data."""

    c_ins: Mapping[str, float]   # c^ins_k: installation cost, k$/MW (electrolyzer, fuel cell) or k$/t (tank)
    c_om: Mapping[str, float]    # c^om_k: fixed O&M cost per year, same capacity units as c_ins
    delta: float
    lifetime: int
    lambda_e2h: float
    lambda_h2e: float
    eta_cha: float
    eta_dis: float
    rho_h: float
    rho_o: float
    c_w: float
    r_w: float
    r_o: float
    c_tr: float
    c_s: float
    f_smr: float
    h_cost: float
    c_p: float
    f_power: float
    c_pen: float
    battery_initial_soc: float = 0.8   # Eq. (15)

    def __post_init__(self) -> None:
        for name in ("c_ins", "c_om"):
            costs = getattr(self, name)
            missing = set(TECHNOLOGIES) - set(costs)
            extra = set(costs) - set(TECHNOLOGIES)
            if missing or extra:
                raise ValueError(f"{name} needs exactly the keys {TECHNOLOGIES}; missing {sorted(missing)}, extra {sorted(extra)}")
            if any(v < 0 for v in costs.values()):
                raise ValueError(f"{name} must be non-negative")
            object.__setattr__(self, name, dict(costs))
        if not 0 <= self.delta < 1:
            raise ValueError("delta must be in [0, 1)")
        if self.lifetime < 1:
            raise ValueError("lifetime must be at least one year")
        for name in ("lambda_e2h", "lambda_h2e", "eta_cha", "eta_dis"):
            if getattr(self, name) <= 0:
                raise ValueError(f"{name} must be positive")
        for name in ("eta_cha", "eta_dis", "battery_initial_soc"):
            if not 0 <= getattr(self, name) <= 1:
                raise ValueError(f"{name} must be in [0, 1]")

    def annuity_factor(self) -> float:
        """1 / sum_{tau=1}^{lifetime} (1 + delta)^-tau, the factor that turns installation cost into an
        equivalent annual cost in Eq. (2)."""
        return 1.0 / sum((1.0 + self.delta) ** -tau for tau in range(1, int(self.lifetime) + 1))

    def with_overrides(self, **values) -> "Parameters":
        """A copy with some fields replaced, e.g. ``p.with_overrides(c_pen=0.2)``."""
        unknown = set(values) - set(self.to_dict())
        if unknown:
            raise KeyError(f"unknown parameter(s): {sorted(unknown)}")
        return replace(self, **values)

    def with_capex_scale(self, scale: float, technologies=TECHNOLOGIES) -> "Parameters":
        """A copy with the installation cost of the given technologies multiplied by ``scale``."""
        c_ins = {k: v * scale if k in technologies else v for k, v in self.c_ins.items()}
        return replace(self, c_ins=c_ins)

    def to_dict(self) -> Dict[str, object]:
        return asdict(self)

    def to_records(self):
        """Flat (name, value, unit) records, the layout of ``parameters.csv``."""
        rows = []
        for k in TECHNOLOGIES:
            rows.append((f"c_ins.{k}", self.c_ins[k], f"k$/{TECHNOLOGY_UNITS[k]}"))
        for k in TECHNOLOGIES:
            rows.append((f"c_om.{k}", self.c_om[k], f"k$/{TECHNOLOGY_UNITS[k]}/yr"))
        for name, (_, unit, _) in SCALAR_PARAMETERS.items():
            rows.append((name, getattr(self, name), unit))
        return rows

    @classmethod
    def from_records(cls, records) -> "Parameters":
        """Inverse of :meth:`to_records`; ``records`` is an iterable of (name, value)."""
        c_ins, c_om, scalars = {}, {}, {}
        for name, value in records:
            if name.startswith("c_ins."):
                c_ins[name.split(".", 1)[1]] = float(value)
            elif name.startswith("c_om."):
                c_om[name.split(".", 1)[1]] = float(value)
            elif name in SCALAR_PARAMETERS:
                scalars[name] = int(float(value)) if name == "lifetime" else float(value)
            else:
                raise KeyError(f"unknown parameter {name!r}")
        missing = set(SCALAR_PARAMETERS) - set(scalars) - {"battery_initial_soc"}
        if missing:
            raise KeyError(f"missing parameter(s): {sorted(missing)}")
        return cls(c_ins=c_ins, c_om=c_om, **scalars)


__all__ = ["Parameters", "TECHNOLOGIES", "TECHNOLOGY_UNITS", "SCALAR_PARAMETERS"]
