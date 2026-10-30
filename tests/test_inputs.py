"""Data interface: validation, parameters, scenario tree and sensitivity cases."""

import dataclasses

import numpy as np
import pytest

from txh2_framework import BaseInputs, Case, Level, Parameters, Pipeline, ScenarioTree, build_instance
from txh2_framework.synthetic import illustrative_parameters


def _replace(base, **changes):
    fields = {f.name: getattr(base, f.name) for f in dataclasses.fields(base)}
    fields.update(changes)
    return BaseInputs(**fields)


def test_synthetic_inputs_are_valid(base):
    assert base.hours == 48 and len(base.zones) == 3
    assert "SYNTHETIC DATA" in base.description
    assert (base.renewable_existing + base.renewable_planned > base.demand).any()   # surplus hours exist
    assert (base.h2_demand.sum(axis=1) == 0).any()                                  # a zone without H2 demand


@pytest.mark.parametrize("change, message", [
    ({"demand": np.ones((2, 48))}, "demand"),
    ({"renewable_existing": -np.ones((3, 48))}, "negative"),
    ({"h2_demand": np.full((3, 48), np.nan)}, "NaN"),
    ({"battery_planned": np.ones(4)}, "battery_planned"),
    ({"pipelines": (Pipeline("Z1", "Z9", 100.0),)}, "unknown zone"),
    ({"pipelines": (Pipeline("Z1", "Z1", 100.0),)}, "itself"),
    ({"pipelines": (Pipeline("Z1", "Z2", 100.0), Pipeline("Z2", "Z1", 90.0))}, "twice"),
    ({"pipelines": (Pipeline("Z1", "Z2", 0.0),)}, "positive, finite distance"),
    ({"pipelines": (Pipeline("Z1", "Z2", float("inf")),)}, "positive, finite distance"),
    ({"zones": ("Z1", "Z1", "Z3")}, "unique"),
])
def test_base_inputs_validation(base, change, message):
    with pytest.raises(ValueError, match=message):
        _replace(base, **change)


def test_parameters_validation_and_records():
    p = illustrative_parameters()
    assert Parameters.from_records((n, v) for n, v, _ in p.to_records()) == p
    with pytest.raises(ValueError, match="keys"):
        dataclasses.replace(p, c_ins={"electrolyzer": 1.0})
    with pytest.raises(ValueError, match="eta_cha"):
        dataclasses.replace(p, eta_cha=1.5)
    with pytest.raises(KeyError):
        p.with_overrides(not_a_parameter=1.0)
    assert p.with_capex_scale(0.5).c_ins["tank"] == 0.5 * p.c_ins["tank"]


def test_annuity_factor():
    p = illustrative_parameters()
    assert dataclasses.replace(p, delta=0.0).annuity_factor() == pytest.approx(1 / p.lifetime)
    expected = 1 / sum(1.05 ** -tau for tau in range(1, 26))
    assert p.annuity_factor() == pytest.approx(expected)


def test_tree_probabilities(tree):
    scen = tree.scenarios()
    assert len(scen) == 9
    assert sum(p for *_, p in scen) == pytest.approx(1.0)
    assert [name for name, *_ in scen][:3] == ["L-L", "L-M", "L-H"]       # demand level is the outer loop
    with pytest.raises(ValueError, match="sum"):
        ScenarioTree((Level("M", 1.0, 0.9),), (Level("M", 0.3, 1.0),))


def test_build_instance_formulas(base, tree):
    inst = build_instance(base, tree)
    scen = tree.scenarios()
    for s, (_, d, r, prob) in enumerate(scen):
        np.testing.assert_allclose(inst.demand[:, :, s], d.value * base.demand)
        np.testing.assert_allclose(inst.renewable[:, :, s], base.renewable_existing + r.value * base.renewable_planned)
        assert inst.probability[s] == pytest.approx(prob)
    np.testing.assert_allclose(inst.battery_capacity, base.battery_existing + base.battery_planned)
    assert inst.hour_weight == pytest.approx(8760 / 48)


def test_case_overrides(base, tree):
    case = Case(name="c", demand_scale=1.05, completion_rates={"M": 0.4}, battery_completion=0.6,
                capex_scale=0.5, params={"c_pen": 0.2})
    inst = build_instance(base, tree, case)
    s_mm = inst.scenarios.index("M-M")
    np.testing.assert_allclose(inst.demand[:, :, s_mm], 1.05 * base.demand)
    np.testing.assert_allclose(inst.renewable[:, :, s_mm], base.renewable_existing + 0.4 * base.renewable_planned)
    np.testing.assert_allclose(inst.battery_capacity, base.battery_existing + 0.6 * base.battery_planned)
    assert inst.params.c_pen == 0.2
    assert inst.params.c_ins["electrolyzer"] == 0.5 * base.params.c_ins["electrolyzer"]
    with pytest.raises(KeyError):
        build_instance(base, tree, Case(completion_rates={"X": 0.5}))


@pytest.mark.parametrize("field, value", [("rho_h", float("nan")), ("c_w", float("inf")), ("lambda_e2h", float("nan")),
                                          ("c_pen", -0.1), ("lifetime", 2.5), ("delta", 1.0)])
def test_parameters_reject_invalid_values(field, value):
    with pytest.raises(ValueError):
        dataclasses.replace(illustrative_parameters(), **{field: value})
    with pytest.raises(ValueError):
        dataclasses.replace(illustrative_parameters(), c_ins={"electrolyzer": float("nan"), "tank": 1.0, "fuel_cell": 1.0})


def test_parameter_records_check_units_and_duplicates():
    records = illustrative_parameters().to_records()
    assert Parameters.from_records(records) == illustrative_parameters()
    wrong_unit = [(n, v, "$/MWh") if n == "c_pen" else (n, v, u) for n, v, u in records]
    with pytest.raises(ValueError, match="expected 'k\\$/MWh'"):
        Parameters.from_records(wrong_unit)
    with pytest.raises(ValueError, match="more than once"):
        Parameters.from_records(records + [("c_pen", 0.2, "k$/MWh")])
    with pytest.raises(ValueError, match="not a number"):
        Parameters.from_records([(n, "" if n == "c_w" else v, u) for n, v, u in records])
    with pytest.raises(ValueError, match="finite"):
        Parameters.from_records([(n, float("nan") if n == "c_w" else v, u) for n, v, u in records])
