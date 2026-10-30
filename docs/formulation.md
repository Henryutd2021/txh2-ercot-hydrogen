# Mathematical formulation

This document states the optimization model as implemented by this framework. The model is that of Li & Zhang, "Hydrogen's role in expanding renewable energy and reducing carbon emissions in Texas", *International Journal of Hydrogen Energy* 113 (2025) 77–89, [doi:10.1016/j.ijhydene.2025.02.303](https://doi.org/10.1016/j.ijhydene.2025.02.303), Section 2.

- Equation numbers (1)–(17) follow the article, so that each part can be matched to it.
- [Conventions of this implementation](#conventions-of-this-implementation) lists the definitions that the framework makes explicit.
- Notation follows the article's nomenclature. The last column of each table gives the name used in the code ([`model.py`](../src/txh2_framework/model.py), [`parameters.py`](../src/txh2_framework/parameters.py)).

The model is a two-stage stochastic linear program:

- **First stage:** the capacities of electrolyzers, hydrogen tanks and fuel cells in every zone. These are decided before the uncertainty is resolved.
- **Second stage:** the hourly operation of the system in each scenario. This covers batteries, tanks, electrolysis, fuel cells, electricity bought from combined-cycle gas-turbine (CCGT) plants, steam methane reforming (SMR) hydrogen and inter-zone hydrogen pipelines.

The objective minimizes the annualized installation cost plus the expected annual operating cost.

## Sets

| Symbol | Meaning | Code |
|---|---|---|
| $I$ | zones (the article uses ERCOT's eight weather zones) | `i` |
| $K$ | technologies: $k=1$ electrolyzer, $k=2$ hydrogen storage tank, $k=3$ hydrogen fuel cell | `k` = `electrolyzer`, `tank`, `fuel_cell` |
| $T$ | hours, $t = 1,\dots,\lvert T\rvert$ (8,760 in the article); storage levels also have $t = 0$ | `t` |
| $S$ | scenarios (combinations of demand level and completion level, see [scenarios.md](scenarios.md)) | `s` |
| $A \subseteq I \times I$ | directed pipeline arcs. Pipelines connect only adjacent zones (article Fig. 6a); each corridor is usable in both directions | `pipelines.csv` |

## Parameters

| Symbol | Meaning | Unit | Code |
|---|---|---|---|
| $\xi_s$ | probability of scenario $s$ | – | `Instance.probability` |
| $\chi_{i,t,s}$ | hourly electricity demand | MWh | `Instance.demand` |
| $\epsilon^{r}_{i,t,s}$ | hourly renewable (wind and solar) generation | MWh | `Instance.renewable` |
| $\kappa_{i,t}$ | hourly hydrogen demand | t | `Instance.h2_demand` |
| $hd_i$ | zonal hydrogen demand, $hd_i = \sum_{t} \kappa_{i,t}$ | t | computed |
| $\beta_i$ | battery capacity | MWh | `Instance.battery_capacity` |
| $d_{i,j}$ | straight-line distance between the centres of zones $i$ and $j$ | km | `Pipeline.distance_km` |
| $c^{ins}_k$ | installation cost per unit of capacity | k\$/MW (k = 1, 3), k\$/t (k = 2) | `c_ins` |
| $c^{om}_k$ | fixed O&M cost per unit of capacity and year | k\$/MW/yr, k\$/t/yr | `c_om` |
| $\delta$ | discount rate | – | `delta` |
| lifetime | technology lifetime | years | `lifetime` |
| $\lambda^{e2h}$ | electricity per tonne of hydrogen produced by electrolysis | MWh/t | `lambda_e2h` |
| $\lambda^{h2e}$ | electricity generated per tonne of hydrogen in the fuel cell | MWh/t | `lambda_h2e` |
| $\eta^{cha}$, $\eta^{dis}$ | battery charging and discharging efficiency | – | `eta_cha`, `eta_dis` |
| $\rho^{h}$, $\rho^{o}$ | hydrogen and oxygen sale prices | k\$/t | `rho_h`, `rho_o` |
| $c^{w}$ | deionized water cost | k\$/t | `c_w` |
| $r^{w}$, $r^{o}$ | water use and oxygen output per tonne of hydrogen | t/t | `r_w`, `r_o` |
| $c^{tr}$ | pipeline transport cost per tonne and km | k\$/(t·km) | `c_tr` |
| $c^{s}$ | carbon cost of SMR CO2 | k\$/t CO2 | `c_s` |
| $f^{smr}$ | SMR emission factor | t CO2/t | `f_smr` |
| $h^{cost}$ | cost of SMR hydrogen | k\$/t | `h_cost` |
| $c^{p}$ | capture and storage cost of CCGT CO2 | k\$/t CO2 | `c_p` |
| $f^{power}$ | CCGT emission factor | t CO2/MWh | `f_power` |
| $c^{pen}$ | price (penalty) of electricity purchased from CCGT plants | k\$/MWh | `c_pen` |

The benchmark values used in the article are listed in its Table 3. This repository does not ship benchmark values. The synthetic example uses illustrative values ([`synthetic.py`](../src/txh2_framework/synthetic.py)).

## Decision variables

| Symbol | Stage | Meaning | Unit | Code |
|---|---|---|---|---|
| $x_{i,k}$ | first | installed capacity of technology $k$ in zone $i$ | MW (k = 1, 3), t (k = 2) | `x` |
| $\psi_i$ | first | hydrogen demand satisfaction rate of zone $i$ (by green hydrogen) | – | `psi` |
| $\epsilon^{cha}_{i,t,s}$, $\epsilon^{dis}_{i,t,s}$ | second | battery charging and discharging | MWh | `eps_cha`, `eps_dis` |
| $\epsilon^{e2h}_{i,t,s}$ | second | electricity used for electrolysis | MWh | `eps_e2h` |
| $\epsilon^{h}_{i,t,s}$ | second | electricity generated from hydrogen (fuel cell) | MWh | `eps_h` |
| $\epsilon^{n}_{i,t,s}$ | second | electricity purchased from CCGT plants | MWh | `eps_n` |
| $\theta^{b}_{i,t,s}$ | second | battery state of charge | MWh | `theta_b` |
| $\theta^{h}_{i,t,s}$ | second | hydrogen tank level | t | `theta_h` |
| $h^{se}_{i,t,s}$ | second | (green) hydrogen sold | t | `h_se` |
| $h^{smr}_{i,t,s}$ | second | hydrogen from SMR | t | `h_smr` |
| $h^{tr}_{i,j,t,s}$ | second | hydrogen pipeline flow from $i$ to $j$, $(i,j) \in A$ | t | `h_tr` |
| $w_{i,t,s}$, $o_{i,t,s}$ | second | water use and oxygen output | t | `w`, `o` |

All variables are non-negative, and $0 \le \psi_i \le 1$ (see the conventions).

## Objective

$$
\min\; \mathbb{E}_s(\mathrm{ATC}) = \mathrm{Capex} + \mathbb{E}_s(\mathrm{O\&M}_s) \tag{1}
$$

$$
\mathrm{Capex} = \sum_{i \in I} \sum_{k \in K} \frac{x_{i,k}\, c^{ins}_k}{\sum_{\tau=1}^{\mathrm{lifetime}} (1+\delta)^{-\tau}} \tag{2}
$$

$$
\begin{aligned}
\mathbb{E}_s(\mathrm{O\&M}_s) = {} & \sum_{i \in I} \sum_{k \in K} x_{i,k}\, c^{om}_k
+ \sum_{s \in S} \xi_s \Big[ \sum_{(i,j) \in A} \sum_{t \in T} c^{tr}\, h^{tr}_{i,j,t,s}\, d_{i,j}
+ \sum_{i,t} c^{w}\, w_{i,t,s} \\
& + \sum_{i,t} \big(c^{s} f^{smr} + h^{cost}\big)\, h^{smr}_{i,t,s}
+ \sum_{i,t} \big(c^{p} f^{power} + c^{pen}\big)\, \epsilon^{n}_{i,t,s}
- \sum_{i,t} \rho^{h}\, h^{se}_{i,t,s} - \sum_{i,t} \rho^{o}\, o_{i,t,s} \Big]
\end{aligned} \tag{3}
$$

The denominator in Eq. (2) is the present-worth factor over the lifetime. Dividing by it turns the installation cost into an equivalent annual cost (`Parameters.annuity_factor()`).

In Eq. (3), every scenario-dependent operating term is weighted by the scenario probability $\xi_s$: the operating cost is its expected value over the scenarios (article Section 2).

## Constraints

Energy balance, for all $i, t, s$:

$$
\epsilon^{h}_{i,t,s} + \epsilon^{dis}_{i,t,s} + \epsilon^{n}_{i,t,s} - \epsilon^{cha}_{i,t,s} - \epsilon^{e2h}_{i,t,s} = \chi_{i,t,s} - \epsilon^{r}_{i,t,s} \tag{4}
$$

Hydrogen balance, for all $i, t, s$:

$$
\theta^{h}_{i,t,s} = \theta^{h}_{i,t-1,s} + \sum_{j \neq i} \big(h^{tr}_{j,i,t,s} - h^{tr}_{i,j,t,s}\big) + \frac{\epsilon^{e2h}_{i,t,s}}{\lambda^{e2h}} - h^{se}_{i,t,s} - \frac{\epsilon^{h}_{i,t,s}}{\lambda^{h2e}} \tag{5}
$$

Battery balance, for all $i, t, s$:

$$
\theta^{b}_{i,t,s} = \theta^{b}_{i,t-1,s} + \eta^{cha}\, \epsilon^{cha}_{i,t,s} - \frac{\epsilon^{dis}_{i,t,s}}{\eta^{dis}} \tag{6}
$$

Storage capacity, for all $i, t, s$:

$$
\theta^{h}_{i,t,s} \le x_{i,2} \tag{7}
$$

$$
\theta^{b}_{i,t,s} \le \beta_i \tag{8}
$$

Water use and oxygen output of electrolysis, for all $i, t, s$:

$$
w_{i,t,s} = r^{w}\, \frac{\epsilon^{e2h}_{i,t,s}}{\lambda^{e2h}} \tag{9}
$$

$$
o_{i,t,s} = r^{o}\, \frac{\epsilon^{e2h}_{i,t,s}}{\lambda^{e2h}} \tag{10}
$$

Hydrogen demand:

$$
\sum_{s \in S} \xi_s \sum_{t \in T} h^{se}_{i,t,s} = \psi_i\, hd_i \qquad \forall i \tag{11}
$$

$$
\sum_{s \in S} \xi_s \big(h^{se}_{i,t,s} + h^{smr}_{i,t,s}\big) \ge \kappa_{i,t} \qquad \forall i, t \tag{12}
$$

Conversion capacity, for all $i, t, s$:

$$
\epsilon^{h}_{i,t,s} \le x_{i,3} \tag{13}
$$

$$
\epsilon^{e2h}_{i,t,s} \le x_{i,1} \tag{14}
$$

Initial storage levels, for all $i, s$:

$$
\theta^{b}_{i,0,s} = 0.8\, \beta_i \tag{15}
$$

The share 0.8 is the default of the parameter `battery_initial_soc`.

$$
\theta^{h}_{i,0,s} = 0 \tag{16}
$$

CCGT purchase limited to the positive net demand of the hour, for all $i, t, s$:

$$
\epsilon^{n}_{i,t,s} \le \max\big(\chi_{i,t,s} - \epsilon^{r}_{i,t,s},\, 0\big) \tag{17}
$$

The right-hand side of Eq. (17) is data, so the constraint is linear (`Instance.net_demand_bound()`).

| Equation | Constraint name in the code |
|---|---|
| (4) | `eq04_energy_balance` |
| (5) | `eq05_hydrogen_balance` |
| (6) | `eq06_battery_balance` |
| (7), (8) | `eq07_tank_capacity`, `eq08_battery_capacity` |
| (9), (10) | `eq09_water`, `eq10_oxygen` |
| (11), (12) | `eq11_satisfaction_rate`, `eq12_hydrogen_demand` |
| (13), (14) | `eq13_fuel_cell_capacity`, `eq14_electrolyzer_capacity` |
| (15), (16) | `eq15_battery_initial`, `eq16_tank_initial` |
| (17) | `eq17_ccgt_bound` |

## Variant: demand-side load flexibility (article Section 3.1)

The article describes this variant as a band of ±5 % around the hourly demand, with total demand unchanged. The framework defines it as follows. Hourly demand may deviate from $\chi$ within a band of $\pm\varphi$, and the total demand of each zone and scenario over the horizon stays unchanged. The adjusted demand $\tilde\chi_{i,t,s}$ is a variable:

$$
(1-\varphi)\,\chi_{i,t,s} \le \tilde\chi_{i,t,s} \le (1+\varphi)\,\chi_{i,t,s}, \qquad \sum_{t \in T} \tilde\chi_{i,t,s} = \sum_{t \in T} \chi_{i,t,s} \quad \forall i, s
$$

$\tilde\chi$ replaces $\chi$ on the right-hand side of Eq. (4). Eq. (17) keeps the reference demand $\chi$, so its right-hand side stays a constant.

In code, set `Case(load_flexibility=0.05)` or `ModelOptions(load_flexibility=0.05)`. The constraint `load_flexibility_total` holds the total, and the variable is named `chi_adj`.

## Conventions of this implementation

- **Units:** k\$, MWh (an hourly flow in MW is the same number in MWh), and tonnes. The objective is in k\$ per year.
  - `parameters.csv` must state these units; values in other units are refused, not converted.
  - Converting values from the literature: \$/kg equals k\$/t, \$/kW equals k\$/MW, and kWh/kg equals MWh/t, number for number. An O&M cost given as a share of the installation cost becomes share × $c^{ins}_k$ per year.
  - The tank capacity $x_{i,2}$ is in tonnes, because Eq. (7) compares it with the tank level.
- **Variable domains:** all variables are non-negative. $\psi_i$ is a rate, so $0 \le \psi_i \le 1$. $hd_i = \sum_t \kappa_{i,t}$.
- **Operating cost:** all scenario-dependent terms of Eq. (3) are expected values (weighted by $\xi_s$).
- **Initial storage levels:** the battery starts at `battery_initial_soc` × $\beta_i$ (0.8 by default, Eq. 15); the hydrogen tank starts empty (Eq. 16).
- **Horizon:**
  - The article models a full year.
  - For a shorter, contiguous block of hours (examples, tests, a few weeks), the operating terms of Eq. (3) are multiplied by $W = 8760 / \lvert T\rvert$, so that they stay annual next to the annual Capex and fixed O&M. For a full year, $W = 1$ (`Instance.hour_weight`).
  - The weight is uniform and storage links consecutive hours. Non-contiguous representative periods would need per-period weights and storage linking between periods; the framework does not implement them.
  - Eqs. (11)–(12) do not need the factor.
- **Pipelines:** $h^{tr}$ exists only on the arcs in $A$, i.e. between adjacent zones listed in `pipelines.csv`. The sum over $j \neq i$ in Eq. (5) therefore runs over the neighbours of $i$.
- **Zones without hydrogen demand** ($hd_i = 0$): Eq. (11) gives $\sum_s \xi_s \sum_t h^{se}_{i,t,s} = 0$. Such a zone can still produce hydrogen and send it to other zones. Its $\psi_i$ has no meaning and is not reported.
- **Indicators reported by `results.summarize`** (computed after the solve, not part of the optimization):
  - CCGT CO2: $f^{power}\epsilon^{n}$;
  - SMR CO2: $f^{smr} h^{smr}$;
  - peak CCGT purchase per zone: $\max_{t,s} \epsilon^{n}_{i,t,s}$;
  - expected annual quantities: $W \sum_s \xi_s \sum_t (\cdot)$;
  - the cost components of Eqs. (2)–(3), which sum to the objective.

## Modelling notes

- **Hydrogen demand:**
  - Eq. (12) requires the scenario-weighted (expected) hydrogen supply to cover the demand of every hour.
  - Eq. (11) links expected green-hydrogen sales over the horizon to the satisfaction rate.
  - Hydrogen demand is the same in all scenarios. The article keeps it fixed (Section 2).
- **Storage:** the battery starts at 80 % of its capacity and the tank starts empty (Eqs. 15–16). The formulation has no end-of-horizon condition on storage levels.
- **Surplus energy:** Eq. (4) is an energy balance without a spill term. For applications that need explicit curtailment of renewable output, enable the curtailment extension below.

## Study setting: capacity upper bounds

Eqs. (1)–(17) place no upper bound on $x_{i,k}$. The article's case study caps electrolyzer capacity at 500 MW per zone, for spatial reasons (Section 3.2).

- `ModelOptions(capacity_upper_bound={"electrolyzer": 500})` adds $x_{i,1} \le 500$.
- One value bounds all technologies; a mapping bounds the named technologies only.
- No bound is the default.

## Extension (off by default; not part of the article's formulation)

| Option | Effect |
|---|---|
| `ModelOptions(curtailment=True)` | adds $\epsilon^{curt}_{i,t,s} \ge 0$ (`curt`) with a minus sign on the left-hand side of Eq. (4) |

Options given to `build_model` replace those of the instance. To keep a case's load flexibility and add the extension, use `ModelOptions.from_instance(inst, curtailment=True)`.
