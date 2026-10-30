"""Read and write the input directory format (schemas in ``docs/data_pipeline.md``).

An input directory holds eight CSV files:

    zones.csv               zone, battery_existing_mwh, battery_planned_mwh
    pipelines.csv           zone_a, zone_b, distance_km
    demand.csv              hour, <one column per zone>      reference electricity demand, MWh
    renewable_existing.csv  hour, <one column per zone>      output of existing wind + solar, MWh
    renewable_planned.csv   hour, <one column per zone>      output of planned capacity at 100 %, MWh
    hydrogen_demand.csv     hour, <one column per zone>      hydrogen demand, t
    scenario_levels.csv     factor, level, value, probability
    parameters.csv          name, value, unit   (units must be exactly those of parameters.canonical_units())

Hourly files have one row per hour, ``hour`` = 1..T. Zone columns are matched to ``zones.csv`` by
name; their order does not matter, but every zone must appear exactly once.
"""

from __future__ import annotations

from pathlib import Path
from typing import Tuple

import numpy as np
import pandas as pd

from .inputs import BaseInputs, Pipeline
from .parameters import Parameters
from .scenarios import ScenarioTree, tree_from_table

HOURLY_FILES = {
    "demand": "demand.csv",
    "renewable_existing": "renewable_existing.csv",
    "renewable_planned": "renewable_planned.csv",
    "h2_demand": "hydrogen_demand.csv",
}


def _read_hourly(path: Path, zones) -> np.ndarray:
    df = pd.read_csv(path)
    if "hour" not in df.columns:
        raise ValueError(f"{path.name}: missing column 'hour'")
    hours = df["hour"].to_numpy()
    if not np.array_equal(hours, np.arange(1, len(df) + 1)):
        raise ValueError(f"{path.name}: 'hour' must run 1..{len(df)} without gaps")
    cols = [c for c in df.columns if c != "hour"]
    missing, extra = set(zones) - set(cols), set(cols) - set(zones)
    if missing or extra:
        raise ValueError(f"{path.name}: zone columns do not match zones.csv (missing {sorted(missing)}, extra {sorted(extra)})")
    return df[list(zones)].to_numpy(dtype=float).T          # [zone, hour]


def read_inputs(directory) -> Tuple[BaseInputs, ScenarioTree]:
    """Read an input directory into base inputs and a scenario tree (validated)."""
    d = Path(directory)
    zones_df = pd.read_csv(d / "zones.csv")
    zones = tuple(str(z) for z in zones_df["zone"])
    pipes_df = pd.read_csv(d / "pipelines.csv")
    pipelines = tuple(Pipeline(str(r.zone_a), str(r.zone_b), float(r.distance_km)) for r in pipes_df.itertuples())
    arrays = {key: _read_hourly(d / name, zones) for key, name in HOURLY_FILES.items()}
    lengths = {a.shape[1] for a in arrays.values()}
    if len(lengths) != 1:
        raise ValueError("hourly files have different numbers of rows")
    params_df = pd.read_csv(d / "parameters.csv", dtype={"name": str, "unit": str}, keep_default_na=False, na_values=[""])
    missing_cols = {"name", "value", "unit"} - set(params_df.columns)
    if missing_cols:
        raise ValueError(f"parameters.csv: missing column(s) {sorted(missing_cols)}")
    params = Parameters.from_records(params_df[["name", "value", "unit"]].itertuples(index=False, name=None))
    levels_df = pd.read_csv(d / "scenario_levels.csv")
    tree = tree_from_table(list(levels_df[["factor", "level", "value", "probability"]].itertuples(index=False, name=None)))
    base = BaseInputs(
        zones=zones,
        demand=arrays["demand"],
        renewable_existing=arrays["renewable_existing"],
        renewable_planned=arrays["renewable_planned"],
        h2_demand=arrays["h2_demand"],
        battery_existing=zones_df["battery_existing_mwh"].to_numpy(dtype=float),
        battery_planned=zones_df["battery_planned_mwh"].to_numpy(dtype=float),
        pipelines=pipelines,
        params=params,
        description=(d / "README.txt").read_text().strip() if (d / "README.txt").exists() else "",
    )
    return base, tree


def write_inputs(directory, base: BaseInputs, tree: ScenarioTree) -> Path:
    """Write base inputs and a scenario tree in the input directory format."""
    d = Path(directory)
    d.mkdir(parents=True, exist_ok=True)
    pd.DataFrame({
        "zone": base.zones,
        "battery_existing_mwh": base.battery_existing,
        "battery_planned_mwh": base.battery_planned,
    }).to_csv(d / "zones.csv", index=False)
    pd.DataFrame([(p.zone_a, p.zone_b, p.distance_km) for p in base.pipelines],
                 columns=["zone_a", "zone_b", "distance_km"]).to_csv(d / "pipelines.csv", index=False)
    hours = np.arange(1, base.hours + 1)
    for key, name in HOURLY_FILES.items():
        df = pd.DataFrame(getattr(base, key).T, columns=list(base.zones))
        df.insert(0, "hour", hours)
        df.to_csv(d / name, index=False)
    rows = [("demand", lv.name, lv.value, lv.probability) for lv in tree.demand_levels]
    rows += [("completion", lv.name, lv.value, lv.probability) for lv in tree.completion_levels]
    pd.DataFrame(rows, columns=["factor", "level", "value", "probability"]).to_csv(d / "scenario_levels.csv", index=False)
    pd.DataFrame(base.params.to_records(), columns=["name", "value", "unit"]).to_csv(d / "parameters.csv", index=False)
    if base.description:
        (d / "README.txt").write_text(base.description + "\n")
    return d
