"""Model: optimal solve of the synthetic case, balance checks, variants and extensions."""

import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

from txh2_framework import (Case, ModelOptions, Pipeline, balance_residuals, build_instance, build_model,
                            solution_arrays, solve, summarize)
from txh2_framework.cli import main as cli_main

TOL = 1e-6


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


def test_cli(tmp_path):
    inputs, out = tmp_path / "inputs", tmp_path / "out"
    assert cli_main(["synthetic", str(inputs), "--zones", "3", "--hours", "24"]) == 0
    assert cli_main(["run", str(inputs), "--out-dir", str(out), "--load-flexibility", "0.05"]) == 0
    for name in ("capacities.csv", "zones.csv", "flows.csv", "costs.csv", "balance_residuals.json"):
        assert (out / name).exists()


def test_minimal_example_runs():
    script = Path(__file__).resolve().parents[1] / "examples" / "minimal.py"
    done = subprocess.run([sys.executable, str(script)], capture_output=True, text=True, timeout=300)
    assert done.returncode == 0, done.stderr
    assert "optimal" in done.stdout
