"""Solve a :class:`PlanningModel` with HiGHS (default) or Gurobi through linopy."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from .model import PlanningModel

# HiGHS: interior point followed by crossover gives a vertex solution, which is easier to read
# (capacities and flows without spurious small values). Any HiGHS option can be passed instead.
HIGHS_DEFAULTS = {"solver": "ipm", "run_crossover": "on", "output_flag": False}
# Gurobi: barrier with crossover, the usual choice for large planning LPs.
GUROBI_DEFAULTS = {"Method": 2, "OutputFlag": 0}


class SolveError(RuntimeError):
    """The solver did not return an optimal solution."""


@dataclass
class SolveResult:
    status: str
    termination: str
    objective: float


def solve(pm: PlanningModel, solver: str = "highs", log_file: Optional[str] = None,
          require_optimal: bool = True, **solver_options) -> SolveResult:
    """Solve in memory and return status, termination condition and objective (k$ per year).

    ``solver_options`` are passed to the solver unchanged and override the defaults above.
    """
    defaults = {"highs": HIGHS_DEFAULTS, "gurobi": GUROBI_DEFAULTS}.get(solver, {})
    options = {**defaults, **solver_options}
    kwargs = {"io_api": "direct", "progress": False}
    if log_file:
        kwargs["log_fn"] = log_file
    status, termination = pm.model.solve(solver_name=solver, **kwargs, **options)
    status, termination = str(status), str(termination)
    if require_optimal and termination != "optimal":
        raise SolveError(f"solver {solver} returned status={status}, termination={termination}")
    objective = float(pm.model.objective.value) if termination == "optimal" else float("nan")
    return SolveResult(status=status, termination=termination, objective=objective)
