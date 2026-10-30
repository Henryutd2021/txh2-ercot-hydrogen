"""Solve a :class:`PlanningModel` with HiGHS (default) or Gurobi through linopy."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Optional

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


def solve(pm: PlanningModel, solver: str = "highs", options: Optional[Mapping[str, object]] = None,
          log_file: Optional[str] = None, require_optimal: bool = True) -> SolveResult:
    """Solve in memory and return status, termination condition and objective (k$ per year).

    ``solver`` selects the backend ("highs" or "gurobi"; other linopy solvers also work).
    ``options`` are solver options, passed unchanged; they override the defaults above, e.g.
    ``options={"solver": "simplex", "time_limit": 600}`` for HiGHS or ``{"Threads": 8}`` for Gurobi.
    """
    defaults = {"highs": HIGHS_DEFAULTS, "gurobi": GUROBI_DEFAULTS}.get(solver, {})
    options = {**defaults, **(options or {})}
    kwargs = {"io_api": "direct", "progress": False}
    if log_file:
        kwargs["log_fn"] = log_file
    status, termination = pm.model.solve(solver_name=solver, **kwargs, **options)
    status, termination = str(status), str(termination)
    if require_optimal and termination != "optimal":
        raise SolveError(f"solver {solver} returned status={status}, termination={termination}")
    objective = float(pm.model.objective.value) if termination == "optimal" else float("nan")
    return SolveResult(status=status, termination=termination, objective=objective)
