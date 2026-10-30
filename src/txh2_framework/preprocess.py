"""Helpers that turn raw time series into model inputs (the steps of ``docs/data_pipeline.md``).

Each function is one step and works on pandas objects:

    hourly_resource_output  interval power records of individual resources -> hourly energy (MWh)
    fill_short_gaps       interpolate short runs of missing hours; refuse long runs and edge gaps
    sum_by_zone           resource columns -> zone columns; lists resources without a zone
    capacity_factors      hourly zone output / installed zone capacity
    planned_output        zone capacity factors x planned capacity
    flat_hourly           annual totals -> constant hourly rate
    base_inputs_from_frames  hour x zone frames + zone data -> BaseInputs (zones aligned by name)

All hourly frames share one index: a complete hourly ``DatetimeIndex`` on a single clock (see
"Data preparation rules" in ``docs/data_pipeline.md``), with one column per zone.
``examples/prepare_inputs.py`` runs the whole chain on synthetic records.
"""

from __future__ import annotations

from typing import Iterable, List, Mapping, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

from .inputs import BaseInputs, Pipeline
from .parameters import Parameters


def hourly_axis(start: str, hours: int, tz: Optional[str] = None) -> pd.DatetimeIndex:
    """A complete hour-beginning axis, e.g. ``hourly_axis("2022-01-01", 8760, tz="UTC")``."""
    return pd.date_range(start=start, periods=hours, freq="h", tz=tz, name="hour")


def hourly_resource_output(records: pd.DataFrame, axis: pd.DatetimeIndex, time: str = "timestamp",
                           resource: str = "resource", value: str = "mw") -> pd.DataFrame:
    """Hourly energy (MWh) of each resource from interval power records (MW).

    ``records`` has one row per resource and interval, for example a dispatch base point every few
    minutes. Each resource's intervals are averaged within each hour, which gives its energy in that
    hour. The result has one column per resource on ``axis``; an hour without any record of a
    resource is NaN, so that gaps are found per resource (before resources are summed by zone,
    where a silent resource would be hidden by the others).
    """
    df = records[[time, resource, value]].copy()
    df["hour"] = pd.DatetimeIndex(df[time]).floor("h")
    out = df.groupby(["hour", resource])[value].mean().unstack(resource).reindex(axis)
    out.index.name = "hour"
    return out


def sum_by_zone(resource_output: pd.DataFrame, resource_zone: Mapping[str, str],
                zones: Optional[Sequence[str]] = None) -> Tuple[pd.DataFrame, List[str]]:
    """Sum resource columns by zone.

    Returns the hour x zone frame and the sorted list of resources that have no zone in
    ``resource_zone``; they are left out and should be reviewed. Zones without resources are 0.
    Fill or resolve missing hours first (:func:`fill_short_gaps`): a NaN here would propagate.
    """
    unmatched = sorted(str(r) for r in resource_output.columns if r not in resource_zone)
    matched = [r for r in resource_output.columns if r in resource_zone]
    zones = list(zones) if zones is not None else sorted(set(resource_zone.values()))
    out = pd.DataFrame(0.0, index=resource_output.index, columns=zones)
    for z in zones:
        cols = [r for r in matched if resource_zone[r] == z]
        if cols:
            out[z] = resource_output[cols].sum(axis=1, min_count=len(cols))
    return out, unmatched


def fill_short_gaps(frame: pd.DataFrame, max_gap: int = 3) -> pd.DataFrame:
    """Linearly interpolate runs of at most ``max_gap`` missing hours inside each column.

    Longer runs, and gaps at the start or end, are not guessed: a ValueError names the column and
    the first missing hour, so the gap can be fixed at the source or filled by an explicit rule.
    """
    out = frame.copy()
    interpolated = frame.interpolate(method="linear", limit_area="inside")
    for col in frame.columns:
        missing = frame[col].isna()
        run_id = (missing != missing.shift()).cumsum()
        run_length = missing.groupby(run_id).transform("sum")
        short = missing & (run_length <= max_gap)
        out.loc[short, col] = interpolated.loc[short, col]
    left = out.isna()
    if left.to_numpy().any():
        col = left.any().idxmax()
        raise ValueError(f"{col!r}: gap longer than {max_gap} h, or at the edge of the series, from {left[col].idxmax()}")
    return out


def capacity_factors(output: pd.DataFrame, capacity: Mapping[str, float]) -> pd.DataFrame:
    """Hourly capacity factor per zone: output (MWh in the hour) / installed capacity (MW).

    Zones with no capacity get 0. Values are clipped to [0, 1]; clipping hides data problems,
    so check ``(output / capacity).max()`` first (see the QA checks in docs/data_pipeline.md).
    """
    cap = pd.Series(capacity, dtype=float).reindex(output.columns).fillna(0.0)
    cf = output.div(cap.where(cap > 0), axis=1).fillna(0.0)
    return cf.clip(lower=0.0, upper=1.0)


def planned_output(cf: pd.DataFrame, planned_capacity: Mapping[str, float]) -> pd.DataFrame:
    """Hourly output of planned capacity at a 100 % completion rate: zone capacity factor x MW."""
    cap = pd.Series(planned_capacity, dtype=float).reindex(cf.columns).fillna(0.0)
    return cf.mul(cap, axis=1)


def flat_hourly(annual: Mapping[str, float], axis: pd.DatetimeIndex, hours_per_year: float = 8760.0) -> pd.DataFrame:
    """Constant hourly rate from annual totals (e.g. t/yr of hydrogen -> t per hour)."""
    rates = pd.Series(annual, dtype=float) / hours_per_year
    return pd.DataFrame(np.tile(rates.to_numpy(), (len(axis), 1)), index=axis, columns=rates.index)


def base_inputs_from_frames(demand: pd.DataFrame, renewable_existing: pd.DataFrame, renewable_planned: pd.DataFrame,
                            h2_demand: pd.DataFrame, battery_existing: Mapping[str, float],
                            battery_planned: Mapping[str, float], pipelines: Iterable[Pipeline], params: Parameters,
                            zones: Optional[Sequence[str]] = None, description: str = "") -> BaseInputs:
    """Assemble :class:`BaseInputs` from hour x zone frames, aligning every frame by zone name.

    All frames must have the same hourly index. ``zones`` sets the order (default: the demand columns).
    """
    zones = list(zones) if zones is not None else list(demand.columns)
    frames = {"demand": demand, "renewable_existing": renewable_existing,
              "renewable_planned": renewable_planned, "h2_demand": h2_demand}
    for name, f in frames.items():
        missing = set(zones) - set(f.columns)
        if missing:
            raise ValueError(f"{name}: no column for zone(s) {sorted(missing)}")
        if not f.index.equals(demand.index):
            raise ValueError(f"{name}: hourly index differs from the demand index")
    arrays = {name: f[zones].to_numpy(dtype=float).T for name, f in frames.items()}

    def by_zone(values, label):
        s = pd.Series(values, dtype=float)
        missing = set(zones) - set(s.index)
        if missing:
            raise ValueError(f"{label}: no value for zone(s) {sorted(missing)}")
        return s[zones].to_numpy()

    return BaseInputs(
        zones=tuple(zones),
        battery_existing=by_zone(battery_existing, "battery_existing"),
        battery_planned=by_zone(battery_planned, "battery_planned"),
        pipelines=tuple(pipelines),
        params=params,
        description=description,
        **arrays,
    )
