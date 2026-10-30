"""Sensitivity cases on the synthetic region: how each family of cases in docs/scenarios.md is set up.

The data are SYNTHETIC; the comparison shows how to run and read the cases, not what they imply
for ERCOT.

    python examples/sensitivity.py
"""

import pandas as pd

from txh2_framework import (Case, article_scenario_tree, build_instance, build_model, format_table, solve, summarize,
                            synthetic_inputs)

CASES = [
    Case("benchmark", "synthetic benchmark"),
    Case("completion_up", "higher completion of planned renewables (medium and high levels)", completion_rates={"M": 0.4, "H": 0.9}),
    Case("demand_up", "higher final electricity demand", demand_scale=1.05),
    Case("battery_60", "60 % of planned battery capacity built", battery_completion=0.6),
    Case("capex_-50", "hydrogen equipment installation cost halved", capex_scale=0.5),
    Case("ccgt_price_high", "electricity from CCGT plants at 400 $/MWh", params={"c_pen": 0.4}),
    Case("ccs_cost_low", "lower CO2 capture and storage cost for CCGT and SMR", params={"c_p": 0.03, "c_s": 0.03}),
    Case("load_flex_5", "hourly demand flexibility of ±5 % with fixed totals", load_flexibility=0.05),
]


def main() -> None:
    base = synthetic_inputs()
    tree = article_scenario_tree()
    rows = []
    for case in CASES:
        pm = build_model(build_instance(base, tree, case))
        result = solve(pm)
        s = summarize(pm)
        cap = s.capacities.sum()
        rows.append({
            "case": case.name,
            "objective_k$": result.objective,
            "electrolyzer_mw": cap["electrolyzer"],
            "tank_t": cap["tank"],
            "fuel_cell_mw": cap["fuel_cell"],
            "green_h2_t": s.zones["green_h2_sold_t"].sum(),
            "ccgt_co2_t": s.zones["ccgt_co2_t"].sum(),
            "smr_co2_t": s.zones["smr_co2_t"].sum(),
        })
    with pd.option_context("display.width", 160, "display.max_columns", 20, "display.float_format", "{:,.1f}".format):
        print(format_table(pd.DataFrame(rows).set_index("case")))


if __name__ == "__main__":
    main()
