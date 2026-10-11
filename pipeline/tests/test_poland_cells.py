"""The committed cell list must agree with lepszapogoda.grid and the packaged JSON (SPEC §8.1, §12 a)."""

from pathlib import Path

import pandas as pd
import pytest

from lepszapogoda import grid

PARQUET = Path(__file__).resolve().parents[1] / "grid" / "poland_cells.parquet"


@pytest.fixture(scope="module")
def df() -> pd.DataFrame:
    return pd.read_parquet(PARQUET)


def test_parquet_matches_grid_module(df):
    assert list(df["cell_id"]) == [c.cell_id for c in grid.all_cells()]
    assert set(df["grid_version"]) == {grid.GRID_VERSION}
    for row in df.sample(200, random_state=0).itertuples():
        c = grid.get_cell(row.cell_id)
        assert (row.lat_min, row.lon_min, row.lat_max, row.lon_max) == (c.lat_min, c.lon_min, c.lat_max, c.lon_max)
        assert (row.centroid_lat, row.centroid_lon) == c.centroid
        assert row.area_km2 == pytest.approx(c.area_km2, abs=1e-3)
        assert row.geometry_wkt == c.wkt()


def test_parquet_pl_frac_matches_packaged_json(df):
    for row in df.itertuples():
        assert row.pl_frac == grid.pl_frac(row.cell_id)
