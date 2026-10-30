import pytest

from txh2_framework import article_scenario_tree, build_instance, build_model, solve, synthetic_inputs


@pytest.fixture(scope="session")
def base():
    return synthetic_inputs(zones=3, hours=48, seed=11)


@pytest.fixture(scope="session")
def tree():
    return article_scenario_tree()


@pytest.fixture(scope="session")
def solved(base, tree):
    """The synthetic benchmark, solved once with HiGHS."""
    pm = build_model(build_instance(base, tree))
    result = solve(pm)
    return pm, result
