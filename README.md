# TXH2 framework: stochastic planning of hydrogen in a renewable-rich power system

Author: [Honglin Li](https://henryutd2021.github.io/)

A documented, runnable implementation of the planning framework in:

> Honglin Li and Jie Zhang. **Hydrogen's role in expanding renewable energy and reducing carbon emissions in Texas.** *International Journal of Hydrogen Energy* 113 (2025) 77–89. [doi:10.1016/j.ijhydene.2025.02.303](https://doi.org/10.1016/j.ijhydene.2025.02.303)

The framework is a two-stage stochastic linear program. It decides where to build electrolyzers, hydrogen storage tanks and hydrogen fuel cells. It also decides how to operate them hour by hour, together with batteries, backup gas generation, SMR hydrogen and hydrogen transport between neighbouring zones. It does this under uncertain future renewable build-out and electricity demand.

## Research question

Where should electrolyzers, hydrogen storage and fuel cells be built in the ERCOT system, and how should hydrogen move between zones, to absorb surplus renewable generation and supply industrial hydrogen demand? The 2030 renewable build-out and electricity demand are uncertain.

## System and scope

| Aspect | In the article | In this framework |
|---|---|---|
| Spatial resolution | ERCOT's eight weather zones | any set of zones |
| Temporal resolution | hourly, one year (8,760 h) | hourly, any horizon (operating costs are annualized) |
| Uncertainty | 3 electricity-demand levels × 3 completion rates of planned renewable capacity = 9 scenarios | any two-factor tree (`ScenarioTree`) |
| First-stage decisions | electrolyzer, hydrogen tank and fuel-cell capacity per zone | same |
| Second-stage decisions | hourly battery and tank operation, electrolysis, fuel-cell output, electricity from CCGT plants, SMR hydrogen, pipeline flows between adjacent zones | same |
| Hydrogen transport | pipelines between adjacent zones, cost per tonne and km; no pipeline capacity or build decision | same, on the corridors listed in the inputs |
| Capacity limits | electrolyzer capacity capped per zone (Section 3.2) | optional bounds per technology |
| Objective | annualized installation cost + fixed O&M + expected operating cost, net of hydrogen and oxygen sales | same |
| Carbon | CO2 from CCGT plants and SMR is captured and stored at a cost (CCUS) | same; emissions reported per zone |

The complete mathematics, with the article's equation numbers, is in [docs/formulation.md](docs/formulation.md).

## What is in this repository

| Path | Content |
|---|---|
| [`docs/formulation.md`](docs/formulation.md) | sets, parameters, first- and second-stage variables, objective and every constraint, Eqs. (1)–(17); the load-flexibility variant; implementation conventions |
| [`docs/data_pipeline.md`](docs/data_pipeline.md) | how each input is built from public sources (ERCOT SCED, EIA-860, LBNL queue, ERCOT load forecast, hydrogen-demand data), and the input file schemas |
| [`docs/scenarios.md`](docs/scenarios.md) | the scenario tree and the sensitivity-case families, and how to express them |
| [`docs/architecture.md`](docs/architecture.md) | modules, data flow, solver options, problem size, tests |
| [`src/txh2_framework/`](src/txh2_framework/) | the implementation (linopy; HiGHS by default, Gurobi optional), preprocessing helpers, data validation, result tables, command line |
| [`examples/`](examples/) | `minimal.py` (one solve, a few seconds), `sensitivity.py` (eight cases) and `prepare_inputs.py` (raw interval records to an input directory), all on synthetic data |
| [`tests/`](tests/) | 50 tests: input and parameter validation, preprocessing, scenario construction, optimal solve, balance equations recomputed from the solution, variants, printed output, command line |

## Quick start

```bash
git clone https://github.com/Henryutd2021/txh2-ercot-hydrogen.git
cd txh2-ercot-hydrogen
python3 -m venv .venv && source .venv/bin/activate    # needs Python 3.10+ (check: python3 --version); if older, use e.g. python3.12
pip install -e ".[test]"
python examples/minimal.py                              # synthetic 4-zone example, HiGHS
pytest
```

With conda instead: `conda env create -f environment.yml && conda activate txh2-framework && pip install -e .`

The command line works on input directories:

```bash
txh2-framework synthetic my_inputs/                     # write a synthetic input directory
txh2-framework run my_inputs/ --out-dir outputs/bench   # solve and write result tables
txh2-framework run my_inputs/ --load-flexibility 0.05 --out-dir outputs/flex
```

In Python:

```python
from txh2_framework import read_inputs, build_instance, build_model, solve, summarize, Case

base, tree = read_inputs("my_inputs/")                  # your own data, see docs/data_pipeline.md
inst = build_instance(base, tree, Case("capex_-50", capex_scale=0.5))
pm = build_model(inst)
solve(pm)                                               # or solve(pm, solver="gurobi")
summary = summarize(pm)
summary.to_csv("outputs/capex_-50")
```

**About the example data:** `txh2_framework.synthetic` generates a small invented region (four zones, three days, round illustrative costs). It shows how the model behaves and how to read its output. Its numbers say nothing about ERCOT or Texas.

## Using your own data

1. Build the eight input files described in [docs/data_pipeline.md](docs/data_pipeline.md), following its preparation rules. `txh2_framework.preprocess` and `examples/prepare_inputs.py` cover the generic steps. The format is validated when read: zone columns are matched by name, hours must be complete, values must be finite, and probabilities must sum to 1.
2. Put your techno-economic values in `parameters.csv`, in the units it states. Values in other units are refused. The article's benchmark values are listed in its Table 3 and need converting to these units ([docs/formulation.md](docs/formulation.md), conventions).
3. Run the benchmark and your sensitivity cases ([docs/scenarios.md](docs/scenarios.md)). The output tables are described in [docs/architecture.md](docs/architecture.md#output-tables).

A full-year model of eight zones and nine scenarios has about eight million variables. It needs a commercial barrier solver, or a reduced horizon with annualized weights ([docs/architecture.md](docs/architecture.md)).

## What this repository does not contain

This repository presents the modelling framework. It does not contain the code, the input data or the results used for the published article. For the article's results, see the article.

## Citation

If you use this framework, please cite the article above. Citation metadata for both the article and this software are in [`CITATION.cff`](CITATION.cff).

## Licence

- Code: [MIT](LICENSE).
- Documentation (`README.md`, `docs/`): [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/).
