"""Input directory format: round trip and schema checks."""

import numpy as np
import pandas as pd
import pytest

from txh2_framework import read_inputs, write_inputs


def test_round_trip(tmp_path, base, tree):
    write_inputs(tmp_path, base, tree)
    base2, tree2 = read_inputs(tmp_path)
    assert base2.zones == base.zones and base2.pipelines == base.pipelines
    for name in ("demand", "renewable_existing", "renewable_planned", "h2_demand", "battery_existing", "battery_planned"):
        np.testing.assert_allclose(getattr(base2, name), getattr(base, name))
    assert base2.params == base.params
    assert tree2 == tree
    assert "SYNTHETIC DATA" in (tmp_path / "README.txt").read_text()


def test_zone_columns_matched_by_name(tmp_path, base, tree):
    write_inputs(tmp_path, base, tree)
    df = pd.read_csv(tmp_path / "demand.csv")
    df[["hour"] + list(reversed(base.zones))].to_csv(tmp_path / "demand.csv", index=False)
    base2, _ = read_inputs(tmp_path)
    np.testing.assert_allclose(base2.demand, base.demand)


def test_missing_zone_column(tmp_path, base, tree):
    write_inputs(tmp_path, base, tree)
    df = pd.read_csv(tmp_path / "hydrogen_demand.csv").drop(columns=[base.zones[0]])
    df.to_csv(tmp_path / "hydrogen_demand.csv", index=False)
    with pytest.raises(ValueError, match="do not match"):
        read_inputs(tmp_path)


def test_hour_gap(tmp_path, base, tree):
    write_inputs(tmp_path, base, tree)
    df = pd.read_csv(tmp_path / "demand.csv")
    df.loc[5, "hour"] = 99
    df.to_csv(tmp_path / "demand.csv", index=False)
    with pytest.raises(ValueError, match="without gaps"):
        read_inputs(tmp_path)
