"""Model: optimal solve of the synthetic case, balance checks, variants and extensions."""

import re
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from txh2_framework import (Case, ModelOptions, Pipeline, balance_residuals, build_instance, build_model,
                            format_table, solution_arrays, solve, summarize)
from txh2_framework.cli import main as cli_main

TOL = 1e-6
NAN_WORD = re.compile(r"\bnan\b", re.IGNORECASE)


def test_benchmark_is_optimal(solved):
    pm, result = solved
    assert result.termination == "optimal"
    assert np.isfinite(result.objective)


def test_balances_hold(solved):
    pm, _ = solved
    res = balance_residuals(pm)
    assert all(v < TOL for v in res.values()), res


def test_first_stage_and_bounds(solved):
    pm, _ = solved
    v = solution_arrays(pm)
    assert np.all(v["x"] >= -TOL)
    assert np.all((v["psi"] >= -TOL) & (v["psi"] <= 1 + TOL))
    x = dict(zip(("electrolyzer", "tank", "fuel_cell"), np.moveaxis(v["x"], 1, 0)))
    assert np.all(v["eps_e2h"] <= x["electrolyzer"][:, None, None] + TOL)       # Eq. (14)
    assert np.all(v["eps_h"] <= x["fuel_cell"][:, None, None] + TOL)            # Eq. (13)
    assert np.all(v["theta_h"] <= x["tank"][:, None, None] + TOL)               # Eq. (7)
    assert np.all(v["theta_b"] <= pm.instance.battery_capacity[:, None, None] + TOL)  # Eq. (8)
    np.testing.assert_allclose(v["theta_b_0"], pm.instance.params.battery_initial_soc * pm.instance.battery_capacity[:, None] * np.ones((1, len(pm.instance.scenarios))))
    np.testing.assert_allclose(v["theta_h_0"], 0, atol=TOL)                      # Eq. (16)


def test_water_and_oxygen(solved):
    pm, _ = solved
    v, p = solution_arrays(pm), pm.instance.params
    np.testing.assert_allclose(v["w"], p.r_w * v["eps_e2h"] / p.lambda_e2h, atol=TOL)
    np.testing.assert_allclose(v["o"], p.r_o * v["eps_e2h"] / p.lambda_e2h, atol=TOL)


def test_flows_only_on_pipelines(solved):
    pm, _ = solved
    v = solution_arrays(pm)
    zones = pm.instance.zones
    allowed = {(a, b) for a, b, _ in pm.instance.arcs()}
    for i, a in enumerate(zones):
        for j, b in enumerate(zones):
            if (a, b) not in allowed:
                assert np.abs(v["h_tr"][i, j]).max() == 0


def test_costs_sum_to_objective(solved):
    pm, result = solved
    s = summarize(pm)
    assert s.costs.loc["total"].iloc[0] == pytest.approx(result.objective, rel=1e-9)
    assert s.zones["green_h2_sold_t"].sum() > 0          # the synthetic case uses electrolysis


def test_zone_without_demand_printed_as_dash(solved):
    pm, _ = solved
    s = summarize(pm)
    no_demand = pm.instance.h2_demand.sum(axis=1) == 0
    assert no_demand.any() and not no_demand.all()                        # the synthetic case has both kinds
    assert s.zones["satisfaction_rate"][no_demand].isna().all()           # the table keeps NaN ...
    assert s.zones["satisfaction_rate"][~no_demand].notna().all()
    with pd.option_context("display.float_format", "{:,.1f}".format):
        text = format_table(s.zones)
    assert not NAN_WORD.search(text)                                      # ... the printed text shows "–"
    assert text.splitlines()[-1] == "– : zone without hydrogen demand"
    rows = {line.split()[0]: line.split() for line in text.splitlines()[2:-1]}
    col = list(s.zones.columns).index("satisfaction_rate") + 1
    for zone, missing in zip(s.zones.index, no_demand):
        assert (rows[zone][col] == "–") == missing
    assert "zone without hydrogen demand" not in format_table(s.capacities)   # footnote only when needed


def test_load_flexibility(base, tree, solved):
    _, bench = solved
    inst = build_instance(base, tree, Case(name="lf", load_flexibility=0.05))
    pm = build_model(inst)
    result = solve(pm)
    assert result.objective <= bench.objective + 1e-6 * abs(bench.objective)   # a relaxation of the benchmark
    v = solution_arrays(pm)
    np.testing.assert_allclose(v["chi_adj"].sum(axis=1), inst.demand.sum(axis=1), rtol=1e-9)
    assert np.all(v["chi_adj"] >= 0.95 * inst.demand - TOL) and np.all(v["chi_adj"] <= 1.05 * inst.demand + TOL)
    assert max(balance_residuals(pm).values()) < TOL


def test_curtailment_extension(base, tree, solved):
    _, bench = solved
    inst = build_instance(base, tree)
    pm = build_model(inst, ModelOptions(curtailment=True))
    result = solve(pm)
    assert result.objective <= bench.objective + 1e-6 * abs(bench.objective)
    assert max(balance_residuals(pm).values()) < TOL


def test_capacity_upper_bound(base, tree):
    inst = build_instance(base, tree)
    pm = build_model(inst, ModelOptions(capacity_upper_bound={"electrolyzer": 10.0}))
    solve(pm)
    assert solution_arrays(pm)["x"][:, 0].max() <= 10.0 + TOL


def test_without_pipelines(base, tree):
    inst = build_instance(base, tree)
    inst.pipelines = ()
    pm = build_model(inst)
    solve(pm)
    s = summarize(pm)
    assert s.flows.empty and max(balance_residuals(pm).values()) < TOL


def test_model_options_validation(base, tree):
    with pytest.raises(ValueError, match="load_flexibility"):
        ModelOptions(load_flexibility=1.1)
    with pytest.raises(ValueError, match="unknown technology"):
        ModelOptions(capacity_upper_bound={"electrolyser": 10.0})
    with pytest.raises(ValueError, match="non-negative"):
        ModelOptions(capacity_upper_bound=-1.0)
    inst = build_instance(base, tree, Case(name="lf", load_flexibility=0.05))
    with pytest.raises(ValueError, match="from_instance"):
        build_model(inst, ModelOptions(curtailment=True))          # would silently drop the flexibility
    pm = build_model(inst, ModelOptions.from_instance(inst, curtailment=True))
    assert "chi_adj" in pm.model.variables and "curt" in pm.model.variables


def test_solver_options_mapping(base, tree):
    pm = build_model(build_instance(base, tree))
    result = solve(pm, options={"solver": "simplex"})           # a HiGHS option named like the backend argument
    assert result.termination == "optimal"


def test_cli(tmp_path, capsys):
    inputs, out = tmp_path / "inputs", tmp_path / "out"
    assert cli_main(["synthetic", str(inputs), "--zones", "3", "--hours", "24"]) == 0
    assert cli_main(["run", str(inputs), "--out-dir", str(out), "--load-flexibility", "0.05",
                     "--capacity-bound", '{"electrolyzer": 50}', "--curtailment"]) == 0
    assert not NAN_WORD.search(capsys.readouterr().out)
    for name in ("capacities.csv", "zones.csv", "flows.csv", "costs.csv", "balance_residuals.json"):
        assert (out / name).exists()
    assert pd.read_csv(out / "capacities.csv")["electrolyzer"].max() <= 50 + TOL
    rates = pd.read_csv(out / "zones.csv", index_col="zone", keep_default_na=False)["satisfaction_rate"]
    assert rates["Z1"] == ""                                       # no hydrogen demand: the CSV cell stays empty


def test_minimal_example_runs():
    script = Path(__file__).resolve().parents[1] / "examples" / "minimal.py"
    done = subprocess.run([sys.executable, str(script)], capture_output=True, text=True, timeout=300)
    assert done.returncode == 0, done.stderr
    assert "optimal" in done.stdout
    assert not NAN_WORD.search(done.stdout)
    assert "– : zone without hydrogen demand" in done.stdout
