# Scenarios and sensitivity cases

## Scenario tree

The article models two uncertain factors (Section 2, Tables 1–2).

| Factor | Level | Value | Probability |
|---|---|---|---|
| Electricity demand | Low | 2 % below the 2030 projection | 0.2 |
| | Medium | 2030 projection | 0.5 |
| | High | 2 % above the 2030 projection | 0.3 |
| Completion rate of planned renewable capacity | Low | 0 % (existing fleet only) | 0.1 |
| | Medium | 30 % | 0.7 |
| | High | 80 % | 0.2 |

- The two factors are independent, so the nine combinations form the scenario set $`S`$.
- Each scenario has probability $`\xi_s = P(\text{demand level}) \cdot P(\text{completion level})`$. For example, Medium–Medium has $`0.5 \times 0.7 = 0.35`$.
- Scenarios are ordered with the demand level in the outer loop (`L-L`, `L-M`, `L-H`, `M-L`, …), as in the article's Table 2.
- Hydrogen demand and planned battery capacity are not uncertain in this design. The battery completion rate is 100 %.

In code:

- `ScenarioTree` holds the two lists of `Level(name, value, probability)`.
- `synthetic.article_scenario_tree()` returns the tree above.
- An input directory stores the tree in `scenario_levels.csv`.

## From profiles to scenario data

`scenarios.build_instance(base, tree, case)` builds the scenario-dependent data from the scenario-independent profiles of `BaseInputs`:

```math
\chi_{i,t,s} = \text{demand\_scale} \cdot f^{D}_{d(s)} \cdot \text{demand}_{i,t}
```

```math
\epsilon^{r}_{i,t,s} = \text{renewable\_existing}_{i,t} + r_{c(s)} \cdot \text{renewable\_planned}_{i,t}
```

```math
\beta_i = \text{battery\_existing}_i + b \cdot \text{battery\_planned}_i
```

The symbols are:

- $`f^{D}`$: the demand factor of the demand level $`d(s)`$;
- $`r`$: the completion rate of the completion level $`c(s)`$;
- $`b`$: the share of planned battery capacity that is built;
- `renewable_planned`: the output of all planned wind and solar capacity at a 100 % completion rate. Each zone's planned capacity uses the zone's capacity factors (see [data_pipeline.md](data_pipeline.md)).

## Sensitivity cases

The article runs four families of sensitivity cases. Each one is a `Case`, i.e. a set of explicit changes to the benchmark inputs:

| Family (article) | What changes | `Case` field |
|---|---|---|
| Power system (Table 5: A1–A2) | completion rate of planned renewables in the medium and high cases, ±10 % | `completion_rates={"M": …, "H": …}` |
| Power system (Table 5: A3–A4) | final electricity demand, ±5 % | `demand_scale` |
| Power system (Table 5: A5–A6) | completion of planned battery storage, 80 % and 60 % | `battery_completion` |
| Hydrogen system (Table 6: B1–B5) | installation cost of hydrogen equipment, reductions up to 50 % | `capex_scale` (with `capex_technologies`) |
| Hydrogen system (Table 6: B6–B9) | wholesale price of CCGT electricity, \$50–250 per MWh | `params={"c_pen": …}` (k\$/MWh) |
| CO2 abatement (Table 9: C1–C2) | CO2 capture and storage cost | `params={"c_p": …, "c_s": …}` (k\$/t) |
| CO2 abatement (Table 9: C3–C4) | different carbon costs for power and for SMR | `params={"c_p": …, "c_s": …}` |
| Load flexibility (Section 3.1) | hourly demand ±5 % with fixed totals | `load_flexibility=0.05` |

`Case` takes values, not percentages: for example, a completion rate of 0.4 or a price of 0.2 k\$/MWh. Each case therefore states exactly what it changes. The article's tables define the case values.

Example on the synthetic data (also in [`examples/sensitivity.py`](../examples/sensitivity.py)):

```python
from txh2_framework import Case, article_scenario_tree, build_instance, build_model, solve, summarize, synthetic_inputs

base, tree = synthetic_inputs(), article_scenario_tree()
cases = [
    Case("benchmark"),
    Case("capex_-50", "hydrogen equipment cost halved", capex_scale=0.5),
    Case("ccgt_price_high", "CCGT electricity at 400 $/MWh", params={"c_pen": 0.4}),
    Case("load_flex_5", "±5 % hourly demand flexibility", load_flexibility=0.05),
]
for case in cases:
    pm = build_model(build_instance(base, tree, case))
    print(case.name, solve(pm).objective, summarize(pm).capacities.sum().to_dict())
```

From the command line, a case is given as options:

```bash
txh2-framework run my_inputs/ --capex-scale 0.5 --out-dir outputs/capex_-50
txh2-framework run my_inputs/ --params '{"c_pen": 0.2}' --out-dir outputs/ccgt_200
txh2-framework run my_inputs/ --load-flexibility 0.05 --out-dir outputs/load_flex
txh2-framework run my_inputs/ --capacity-bound '{"electrolyzer": 500}' --out-dir outputs/capped
```
