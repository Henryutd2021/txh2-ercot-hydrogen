"""Preprocessing helpers (docs/data_pipeline.md)."""

import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from txh2_framework import Pipeline
from txh2_framework.preprocess import (base_inputs_from_frames, capacity_factors, fill_short_gaps, flat_hourly,
                                       hourly_axis, hourly_resource_output, planned_output, sum_by_zone)
from txh2_framework.synthetic import illustrative_parameters


def test_hourly_resource_output_averages_intervals():
    axis = hourly_axis("2030-01-01", 3, tz="UTC")
    stamps = pd.date_range(axis[0], periods=8, freq="15min")      # hours 1 and 2 only
    records = pd.DataFrame({"timestamp": stamps, "resource": "R1", "mw": [10, 20, 30, 40, 50, 50, 50, 50]})
    out = hourly_resource_output(records, axis)
    assert out["R1"].iloc[0] == pytest.approx(25.0) and out["R1"].iloc[1] == pytest.approx(50.0)
    assert np.isnan(out["R1"].iloc[2])                          # no record -> missing, not zero


def test_fill_short_gaps():
    s = pd.DataFrame({"a": [1.0, np.nan, np.nan, 4.0, 5.0]})
    np.testing.assert_allclose(fill_short_gaps(s, max_gap=2)["a"], [1, 2, 3, 4, 5])
    with pytest.raises(ValueError, match="gap longer"):
        fill_short_gaps(s, max_gap=1)
    with pytest.raises(ValueError, match="edge"):
        fill_short_gaps(pd.DataFrame({"a": [np.nan, 1.0, 2.0]}), max_gap=3)


def test_sum_by_zone_and_unmatched():
    frame = pd.DataFrame({"R1": [1.0, 2.0], "R2": [3.0, 4.0], "RX": [9.0, 9.0]})
    out, unmatched = sum_by_zone(frame, {"R1": "Z1", "R2": "Z1"}, zones=["Z1", "Z2"])
    np.testing.assert_allclose(out["Z1"], [4, 6])
    np.testing.assert_allclose(out["Z2"], [0, 0])
    assert unmatched == ["RX"]


def test_capacity_factors_and_planned_output():
    out = pd.DataFrame({"Z1": [50.0, 120.0], "Z2": [0.0, 0.0]})
    cf = capacity_factors(out, {"Z1": 100.0, "Z2": 0.0})
    np.testing.assert_allclose(cf["Z1"], [0.5, 1.0])               # clipped to 1
    np.testing.assert_allclose(cf["Z2"], [0.0, 0.0])               # no capacity -> 0
    np.testing.assert_allclose(planned_output(cf, {"Z1": 10.0})["Z1"], [5.0, 10.0])
    np.testing.assert_allclose(planned_output(cf, {"Z1": 10.0})["Z2"], [0.0, 0.0])


def test_base_inputs_from_frames_aligns_by_name():
    axis = hourly_axis("2030-01-01", 4)
    demand = pd.DataFrame({"A": 1.0, "B": 2.0}, index=axis)
    shuffled = demand[["B", "A"]] * 0.5
    h2 = flat_hourly({"A": 8760.0, "B": 0.0}, axis)
    base = base_inputs_from_frames(demand, shuffled, shuffled, h2, {"A": 1.0, "B": 2.0}, {"A": 0.0, "B": 0.0},
                                   [Pipeline("A", "B", 10.0)], illustrative_parameters())
    np.testing.assert_allclose(base.renewable_existing[1], 1.0)     # zone B = 0.5 x 2
    np.testing.assert_allclose(base.h2_demand[0], 1.0)              # 8760 t/yr -> 1 t/h
    with pytest.raises(ValueError, match="index"):
        base_inputs_from_frames(demand, shuffled.iloc[:3], shuffled, h2, {"A": 1, "B": 2}, {"A": 0, "B": 0},
                                [], illustrative_parameters())


def test_prepare_inputs_example_runs(tmp_path):
    script = Path(__file__).resolve().parents[1] / "examples" / "prepare_inputs.py"
    done = subprocess.run([sys.executable, str(script), str(tmp_path / "prepared")], capture_output=True, text=True, timeout=300)
    assert done.returncode == 0, done.stderr
    assert "solved: optimal" in done.stdout and "WIND_X" in done.stdout
