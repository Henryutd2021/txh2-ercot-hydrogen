"""txh2_framework: a two-stage stochastic linear program for siting electrolyzers, hydrogen storage,
fuel cells and inter-zone hydrogen pipelines in a renewable-rich power system.

Implements the formulation of Li & Zhang, "Hydrogen's role in expanding renewable energy and
reducing carbon emissions in Texas", Int. J. Hydrogen Energy 113 (2025) 77-89,
doi:10.1016/j.ijhydene.2025.02.303. See docs/formulation.md.

Typical use::

    from txh2_framework import synthetic_inputs, article_scenario_tree, build_instance, build_model, solve, summarize
    base = synthetic_inputs()                      # or io.read_inputs("my_inputs/")
    inst = build_instance(base, article_scenario_tree())
    pm = build_model(inst)
    solve(pm)                                      # HiGHS by default
    print(summarize(pm).capacities)
"""

from .inputs import BaseInputs, Instance, Pipeline
from .io import read_inputs, write_inputs
from .model import ModelOptions, PlanningModel, build_model
from .parameters import TECHNOLOGIES, Parameters
from .results import Summary, balance_residuals, solution_arrays, summarize
from .scenarios import Case, Level, ScenarioTree, build_instance
from .solve import SolveError, SolveResult, solve
from .synthetic import article_scenario_tree, illustrative_parameters, synthetic_inputs

__version__ = "1.0.1"

__all__ = [
    "BaseInputs", "Instance", "Pipeline", "read_inputs", "write_inputs", "ModelOptions", "PlanningModel",
    "build_model", "TECHNOLOGIES", "Parameters", "Summary", "balance_residuals", "solution_arrays", "summarize",
    "Case", "Level", "ScenarioTree", "build_instance", "SolveError", "SolveResult", "solve",
    "article_scenario_tree", "illustrative_parameters", "synthetic_inputs", "__version__",
]
