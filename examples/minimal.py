"""Minimal example: build, solve and summarise the synthetic benchmark with HiGHS (a few seconds).

The data are SYNTHETIC (see txh2_framework.synthetic); the numbers printed say nothing about ERCOT.

    python examples/minimal.py
"""

import time

import pandas as pd

from txh2_framework import article_scenario_tree, balance_residuals, build_instance, build_model, solve, summarize, synthetic_inputs


def main() -> None:
    start = time.perf_counter()
    base = synthetic_inputs(zones=4, hours=72, seed=7)          # 4 zones, 3 days, illustrative values
    inst = build_instance(base, article_scenario_tree())       # 3 demand levels x 3 completion levels = 9 scenarios
    pm = build_model(inst)
    result = solve(pm)                                          # HiGHS; solve(pm, solver="gurobi") also works
    summary = summarize(pm)

    print(base.description)
    print(f"{len(inst.zones)} zones, {inst.hours} hours, {len(inst.scenarios)} scenarios; "
          f"{pm.model.nvars:,} variables, {pm.model.ncons:,} constraints")
    print(f"solver: {result.termination}; objective {result.objective:,.0f} k$/yr; {time.perf_counter() - start:.1f} s")
    with pd.option_context("display.width", 140, "display.max_columns", 20, "display.float_format", "{:,.1f}".format):
        print("\nInstalled capacity (electrolyzer and fuel cell in MW, tank in t):")
        print(summary.capacities)
        print("\nExpected annual quantities by zone:")
        print(summary.zones[["h2_demand_t", "green_h2_sold_t", "smr_h2_t", "satisfaction_rate",
                             "electrolysis_mwh", "ccgt_mwh", "ccgt_co2_t", "smr_co2_t"]])
        print("\nPipeline flows (expected annual, t):")
        print(summary.flows[summary.flows["expected_flow_t"] > 0].to_string(index=False))
        print("\nAnnual cost components (k$/yr):")
        print(summary.costs)
    worst = max(balance_residuals(pm).values())
    print(f"\nlargest balance residual: {worst:.1e}")


if __name__ == "__main__":
    main()
