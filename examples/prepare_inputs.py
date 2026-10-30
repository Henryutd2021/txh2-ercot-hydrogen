"""From raw interval records to an input directory, on SYNTHETIC records (docs/data_pipeline.md, steps 2-8).

The "raw" data below are invented: 15-minute power records of a few wind and solar resources in
three zones, with some missing intervals and one resource that has no zone. They stand in for
the SCED, EIA-860, queue, load-forecast and hydrogen-demand data of a real study.

    python examples/prepare_inputs.py [OUT_DIR]      # default: outputs/prepared_inputs
"""

import sys

import numpy as np
import pandas as pd

from txh2_framework import Pipeline, build_instance, build_model, read_inputs, solve, write_inputs
from txh2_framework.preprocess import (base_inputs_from_frames, capacity_factors, fill_short_gaps, flat_hourly,
                                       hourly_axis, hourly_resource_output, planned_output, sum_by_zone)
from txh2_framework.synthetic import article_scenario_tree, illustrative_parameters

ZONES = ["North", "Central", "Coast"]                       # invented zone names
RESOURCES = {                                               # resource -> (zone, type, MW)
    "WIND_A": ("North", "wind", 300.0), "WIND_B": ("North", "wind", 150.0),
    "WIND_C": ("Central", "wind", 80.0), "SOLAR_A": ("Central", "solar", 120.0),
    "SOLAR_B": ("Coast", "solar", 100.0),
}


def synthetic_records(axis: pd.DatetimeIndex, rng) -> pd.DataFrame:
    """15-minute power records (MW) per resource, with a few dropped intervals and an unknown resource."""
    stamps = pd.date_range(axis[0], axis[-1] + pd.Timedelta(minutes=45), freq="15min")
    hour = stamps.hour + stamps.minute / 60
    rows = []
    for name, (_, kind, mw) in list(RESOURCES.items()) + [("WIND_X", (None, "wind", 50.0))]:
        if kind == "wind":
            cf = np.clip(0.4 + 0.2 * np.cos(2 * np.pi * (hour - 3) / 24) + rng.normal(0, 0.05, len(stamps)), 0, 1)
        else:
            cf = np.clip(np.sin(np.pi * (hour - 6) / 12), 0, None) * 0.85
        rows.append(pd.DataFrame({"timestamp": stamps, "resource": name, "mw": mw * cf}))
    records = pd.concat(rows, ignore_index=True)
    drop = records.sample(frac=0.02, random_state=1).index                     # scattered missing intervals
    gap = (records["resource"] == "WIND_C") & records["timestamp"].between(axis[10], axis[11] + pd.Timedelta(minutes=45))
    return records.drop(drop.union(records.index[gap]))                         # WIND_C silent for 2 hours


def main(out_dir: str = "outputs/prepared_inputs") -> None:
    rng = np.random.default_rng(5)
    axis = hourly_axis("2030-01-01", 72, tz="UTC")                              # one clock for every series

    # Steps 1-3: hourly output per resource, gaps per resource, sum by zone, capacity factors
    records = synthetic_records(axis, rng)
    by_resource = hourly_resource_output(records, axis)
    print("missing resource-hours:", by_resource.isna().sum()[lambda n: n > 0].to_dict())
    by_resource = fill_short_gaps(by_resource, max_gap=3)
    resource_zone = {r: z for r, (z, _, _) in RESOURCES.items()}
    existing, unmatched = sum_by_zone(by_resource, resource_zone, zones=ZONES)
    print("resources without a zone (left out, to review):", unmatched)
    capacity = pd.Series({r: mw for r, (_, _, mw) in RESOURCES.items()}).groupby(resource_zone).sum()
    cf = capacity_factors(existing, capacity)

    # Step 4: planned additions at 100 % completion, using the zone capacity factors
    planned = planned_output(cf, {"North": 250.0, "Central": 150.0, "Coast": 120.0})

    # Steps 5-8: batteries, demand, hydrogen demand, corridors
    load_shape = 1 + 0.15 * np.sin(2 * np.pi * (axis.hour - 9) / 24)
    demand = pd.DataFrame({z: base * load_shape for z, base in zip(ZONES, (60.0, 180.0, 320.0))}, index=axis)
    h2 = flat_hourly({"North": 0.0, "Central": 8000.0, "Coast": 30000.0}, axis)   # t/yr -> t/h
    pipelines = [Pipeline("North", "Central", 250.0), Pipeline("Central", "Coast", 180.0)]

    base = base_inputs_from_frames(
        demand, existing, planned, h2,
        battery_existing={"North": 30.0, "Central": 60.0, "Coast": 90.0},
        battery_planned={"North": 20.0, "Central": 30.0, "Coast": 40.0},
        pipelines=pipelines, params=illustrative_parameters(), zones=ZONES,
        description="SYNTHETIC DATA from examples/prepare_inputs.py; all values are invented.")
    write_inputs(out_dir, base, article_scenario_tree())
    print(f"wrote {out_dir}")

    base2, tree = read_inputs(out_dir)                                          # validated on reading
    result = solve(build_model(build_instance(base2, tree)))
    print(f"solved: {result.termination}, objective {result.objective:,.0f} k$/yr")


if __name__ == "__main__":
    main(*sys.argv[1:2])
