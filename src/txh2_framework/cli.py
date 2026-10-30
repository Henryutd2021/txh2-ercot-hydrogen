"""Command line: ``txh2-framework synthetic OUT_DIR`` and ``txh2-framework run INPUT_DIR``."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

from .io import read_inputs, write_inputs
from .model import ModelOptions, build_model
from .results import balance_residuals, summarize
from .scenarios import Case, build_instance
from .solve import solve
from .synthetic import article_scenario_tree, synthetic_inputs


def _cmd_synthetic(args) -> int:
    base = synthetic_inputs(zones=args.zones, hours=args.hours, seed=args.seed)
    out = write_inputs(args.out_dir, base, article_scenario_tree())
    print(f"wrote synthetic inputs to {out}")
    return 0


def _cmd_run(args) -> int:
    base, tree = read_inputs(args.input_dir)
    params = json.loads(args.params) if args.params else {}
    case = Case(name=args.case_name, demand_scale=args.demand_scale, battery_completion=args.battery_completion,
                capex_scale=args.capex_scale, params=params, load_flexibility=args.load_flexibility)
    inst = build_instance(base, tree, case)
    pm = build_model(inst, ModelOptions.from_instance(inst, curtailment=args.curtailment))
    res = solve(pm, solver=args.solver)
    summary = summarize(pm)
    with pd.option_context("display.width", 140, "display.max_columns", 20, "display.float_format", "{:,.1f}".format):
        print(f"case {case.name}: {res.termination}, objective {res.objective:,.1f} k$/yr")
        print(summary.capacities)
        print(summary.zones[["green_h2_sold_t", "smr_h2_t", "electrolysis_mwh", "ccgt_mwh", "ccgt_co2_t"]])
    if args.out_dir:
        summary.to_csv(args.out_dir)
        (Path(args.out_dir) / "balance_residuals.json").write_text(json.dumps(balance_residuals(pm), indent=2))
        print(f"wrote result tables to {args.out_dir}")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="txh2-framework", description=__doc__)
    sub = ap.add_subparsers(dest="command", required=True)

    s = sub.add_parser("synthetic", help="write a synthetic input directory")
    s.add_argument("out_dir")
    s.add_argument("--zones", type=int, default=4)
    s.add_argument("--hours", type=int, default=72)
    s.add_argument("--seed", type=int, default=7)
    s.set_defaults(func=_cmd_synthetic)

    r = sub.add_parser("run", help="build, solve and summarise one case")
    r.add_argument("input_dir")
    r.add_argument("--out-dir")
    r.add_argument("--solver", default="highs", choices=["highs", "gurobi"])
    r.add_argument("--case-name", default="benchmark")
    r.add_argument("--demand-scale", type=float, default=1.0)
    r.add_argument("--battery-completion", type=float, default=1.0)
    r.add_argument("--capex-scale", type=float, default=1.0, help="factor on the installation cost of all hydrogen technologies")
    r.add_argument("--params", help='JSON object of parameter overrides, e.g. \'{"c_pen": 0.2}\'')
    r.add_argument("--load-flexibility", type=float, help="e.g. 0.05 for +-5 %% hourly demand flexibility")
    r.add_argument("--curtailment", action="store_true", help="extension: allow explicit curtailment")
    r.set_defaults(func=_cmd_run)

    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
