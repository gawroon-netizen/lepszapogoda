"""Satellite observations per cell from Earth Engine (SPEC §8.2, decisions in docs/reports/etap-0-gee.md).

- precipitation: IMERG V07, daily sum 06 UTC D .. 06 UTC D+1 (IMGW convention), only complete days
  (all 48 half-hourly images present); ready for D-2;
- cloud: MODIS Terra (MOD09GA) and Aqua (MYD09GA) `state_1km` cloud state, fraction per cell at overpass
  (cloudy = 1, mixed = 0.5, "not set" = missing) plus the fraction of the cell with a valid observation;
  ready for D-4. Overpass time is nominal: 10:30 (Terra) / 13:30 (Aqua) local solar time at the cell centre,
  converted to UTC; the real swath time differs by up to ~45 min.

Files: {data}/obs/imerg/{date}.parquet, {data}/obs/modis_terra/{date}.parquet, {data}/obs/modis_aqua/{date}.parquet.

Usage:
    EE_PROJECT=<project> python -m pipeline.ingest.satellite [--date YYYY-MM-DD] [--days 31]
"""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import ee
import pandas as pd

from lepszapogoda import grid
from pipeline.gee.auth import init_ee
from pipeline.paths import DATA_DIR

IMERG = "NASA/GPM_L3/IMERG_V07"
MODIS = {"modis_terra": "MODIS/061/MOD09GA", "modis_aqua": "MODIS/061/MYD09GA"}
NOMINAL_LST_H = {"modis_terra": 10.5, "modis_aqua": 13.5}
LAG_DAYS = {"imerg": 2, "modis_terra": 4, "modis_aqua": 4}
SCALE_M = 1000
CHUNK = 1000  # cells per interactive request
DAYS_PER_IMAGE = 15  # bands per reduction


def _cell_collections(cells: Sequence[grid.Cell]) -> list[ee.FeatureCollection]:
    out = []
    for k in range(0, len(cells), CHUNK):
        feats = [
            ee.Feature(ee.Geometry(c.geometry(), "EPSG:4326", False), {"cell_id": c.cell_id})
            for c in cells[k : k + CHUNK]
        ]
        out.append(ee.FeatureCollection(feats))
    return out


def _reduce(image: ee.Image, fcs: list[ee.FeatureCollection]) -> list[dict]:
    rows = []
    for fc in fcs:
        res = image.reduceRegions(collection=fc, reducer=ee.Reducer.mean(), scale=SCALE_M, crs="EPSG:4326")
        rows += [f["properties"] for f in res.getInfo()["features"]]
    return rows


def _key(d: date) -> str:
    return d.strftime("%Y%m%d")


# ---------------------------------------------------------------- IMERG


def _imerg_window(d: date) -> tuple[str, str]:
    start = datetime(d.year, d.month, d.day, 6, tzinfo=UTC)
    return start.isoformat(), (start + timedelta(days=1)).isoformat()


def imerg_complete_days(days: Sequence[date]) -> list[date]:
    """Days whose 06-06 UTC window has all 48 half-hourly IMERG images."""
    col = ee.ImageCollection(IMERG)
    sizes = ee.List([col.filterDate(*_imerg_window(d)).size() for d in days]).getInfo()
    return [d for d, n in zip(days, sizes, strict=True) if n == 48]


def imerg_rows(days: Sequence[date], fcs: list[ee.FeatureCollection]) -> pd.DataFrame:
    bands = [
        ee.ImageCollection(IMERG)
        .filterDate(*_imerg_window(d))
        .select("precipitation")
        .sum()
        .multiply(0.5)
        .rename(f"p_{_key(d)}")
        for d in days
    ]
    rows = _reduce(ee.Image.cat(bands), fcs)
    out = [{"cell_id": r["cell_id"], "date": d, "precip": r.get(f"p_{_key(d)}")} for r in rows for d in days]
    return pd.DataFrame(out)


# ---------------------------------------------------------------- MODIS


def modis_available_days(source: str, days: Sequence[date]) -> list[date]:
    col = ee.ImageCollection(MODIS[source])
    sizes = ee.List([col.filterDate(d.isoformat(), (d + timedelta(days=1)).isoformat()).size() for d in days]).getInfo()
    return [d for d, n in zip(days, sizes, strict=True) if n >= 1]


def modis_rows(source: str, days: Sequence[date], fcs: list[ee.FeatureCollection]) -> pd.DataFrame:
    bands = []
    for d in days:
        img = ee.Image(
            ee.ImageCollection(MODIS[source]).filterDate(d.isoformat(), (d + timedelta(days=1)).isoformat()).first()
        )
        state = img.select("state_1km").bitwiseAnd(3)  # bits 0-1: 0 clear, 1 cloudy, 2 mixed, 3 not set
        cloud = state.eq(1).add(state.eq(2).multiply(0.5)).updateMask(state.neq(3)).rename(f"c_{_key(d)}")
        valid = state.neq(3).unmask(0).rename(f"v_{_key(d)}")  # outside the swath counts as not valid
        bands += [cloud, valid]
    rows = _reduce(ee.Image.cat(bands), fcs)
    out = []
    for r in rows:
        lon = grid.get_cell(r["cell_id"]).centroid[1]
        for d in days:
            utc_h = NOMINAL_LST_H[source] - lon / 15
            out.append(
                {
                    "cell_id": r["cell_id"],
                    "date": d,
                    "cloud_frac": r.get(f"c_{_key(d)}"),
                    "valid_frac": r.get(f"v_{_key(d)}"),
                    "overpass_utc": pd.Timestamp(d, tz=UTC) + pd.Timedelta(hours=utc_h),
                }
            )
    return pd.DataFrame(out)


# ---------------------------------------------------------------- ingest


def _store(df: pd.DataFrame, source: str, data_dir: Path) -> None:
    out_dir = data_dir / "obs" / source
    out_dir.mkdir(parents=True, exist_ok=True)
    for d, part in df.groupby("date"):
        part.assign(grid_version=grid.GRID_VERSION).to_parquet(out_dir / f"{d.isoformat()}.parquet", index=False)


def missing_days(source: str, today: date, n_days: int, data_dir: Path) -> list[date]:
    end = today - timedelta(days=LAG_DAYS[source])
    days = [end - timedelta(days=k) for k in range(n_days)][::-1]
    return [d for d in days if not (data_dir / "obs" / source / f"{d.isoformat()}.parquet").exists()]


def run(today: date, n_days: int = 31, data_dir: Path = DATA_DIR) -> dict:
    fcs = _cell_collections(grid.poland_cells())
    summary = {}
    for source in ("imerg", *MODIS):
        todo = missing_days(source, today, n_days, data_dir)
        if not todo:
            ready = []
        elif source == "imerg":
            ready = imerg_complete_days(todo)
        else:
            ready = modis_available_days(source, todo)
        for k in range(0, len(ready), DAYS_PER_IMAGE):
            batch = ready[k : k + DAYS_PER_IMAGE]
            df = imerg_rows(batch, fcs) if source == "imerg" else modis_rows(source, batch, fcs)
            _store(df, source, data_dir)
        summary[source] = {"missing": len(todo), "fetched": len(ready), "not_ready": len(todo) - len(ready)}
    return summary


def main() -> None:
    p = argparse.ArgumentParser(description="Satellite observations per cell from Earth Engine")
    p.add_argument("--date", type=date.fromisoformat, default=datetime.now(UTC).date())
    p.add_argument("--days", type=int, default=31)
    a = p.parse_args()
    init_ee()
    print(run(a.date, a.days))


if __name__ == "__main__":
    main()
