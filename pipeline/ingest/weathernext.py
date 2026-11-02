"""Google DeepMind WeatherNext 3 forecasts from Earth Engine, for the ranking only.

Reconnaissance and licence: docs/reports/rozpoznanie-weathernext-3.md.

The forecasts are verified like the Open-Meteo models: the files have the same columns and live next to them,
in forecasts/weathernext_3/, so pipeline.verify reads them unchanged. The site never shows a WeatherNext forecast:
real-time data is under the GDM Real-Time Experimental Data Terms; past forecasts (what we verify) are CC BY 4.0.

Leads as in Open-Meteo's Previous Runs API: lead N for valid time V comes from the newest 6-hourly run started at
or before V - 24 N h, i.e. forecast hours 24N..24N+5 of the 00/06/12/18 UTC runs (the hourly interim runs would
give WeatherNext a fresher start than the other models). Only leads 1-3: the ranking uses 24/48/72 h, and
WeatherNext is not part of the blend, whose temperature weights need the longer leads.

Values per cell: ensemble mean, area-weighted over the cell (the 0.1° WeatherNext pixels are offset by half a pixel
from our cells, so each cell covers quarters of four pixels). Precipitation: `total_precipitation_1hr` (the model's
own field; `imerg_tp_1hr` is calibrated to IMERG, our precipitation truth, and would win by construction).
model_elevation: mean terrain height of the cell (GMTED2010), used for the station lapse-rate correction.

One file per run, named after its start time: rerunning never overwrites other data, and the files themselves say
which runs are done. Usage (needs `storage pull forecasts/weathernext_3/` first in CI):
    python -m pipeline.ingest.weathernext [--days 45] [--max-runs 40]
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
from pipeline.ingest.satellite import _cell_collections
from pipeline.paths import DATA_DIR

MODEL = "weathernext_3"
COLLECTION = "projects/gcp-public-data-weathernext/assets/weathernext_3_0_0_0p1deg"
LEADS = (1, 2, 3)
FORECAST_HOURS = [24 * n + k for n in LEADS for k in range(6)]
RUN_HOURS = (0, 6, 12, 18)
BANDS = {"temperature_2m_mean": "t", "total_precipitation_1hr_mean": "p", "total_cloud_cover_mean": "c"}
DEM = ("USGS/GMTED2010_FULL", "mea")
SCALE_M = 5000  # 0.1° pixels; ~4 samples per pixel quarter gives the area weights
BACKFILL_DAYS = 45  # the ranking window reaches 44 days back (pipeline.verify.config)
MAX_RUNS = 40  # per job: ~25 s per run, so the backfill spreads over a few daily jobs
COLUMNS = [
    "grid_version",
    "model",
    "cell_id",
    "valid_time",
    "model_lat",
    "model_lon",
    "model_elevation",
    "lead_day",
    "temperature_2m",
    "precipitation",
    "cloud_cover",
]


def out_dir(data_dir: Path) -> Path:
    return data_dir / "forecasts" / MODEL


def run_file(data_dir: Path, start: datetime) -> Path:
    return out_dir(data_dir) / f"{start:%Y%m%dT%H}.parquet"


def candidate_runs(today: date, days: int) -> list[datetime]:
    """6-hourly run start times from `days` ago up to yesterday 18 UTC (Earth Engine gets a run ~8 h after start)."""
    first = datetime(today.year, today.month, today.day, tzinfo=UTC) - timedelta(days=days)
    out, t = [], first
    while t.date() < today:
        out.append(t)
        t += timedelta(hours=6)
    return out


def _iso(t: datetime) -> str:
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


def complete_runs(starts: Sequence[datetime]) -> list[datetime]:
    """Runs whose images for all FORECAST_HOURS are in Earth Engine."""
    if not starts:
        return []
    col = (
        ee.ImageCollection(COLLECTION)
        .filter(ee.Filter.inList("start_time", [_iso(t) for t in starts]))
        .filter(ee.Filter.inList("forecast_hour", FORECAST_HOURS))
    )
    counts = col.aggregate_histogram("start_time").getInfo()
    return [t for t in starts if counts.get(_iso(t), 0) >= len(FORECAST_HOURS)]


def _stack(start: datetime) -> ee.Image:
    col = (
        ee.ImageCollection(COLLECTION)
        .filter(ee.Filter.eq("start_time", _iso(start)))
        .filter(ee.Filter.inList("forecast_hour", FORECAST_HOURS))
    )
    images = []
    for fh in FORECAST_HOURS:
        img = col.filter(ee.Filter.eq("forecast_hour", fh)).first()
        images.append(img.select(list(BANDS), [f"{short}_{fh:03d}" for short in BANDS.values()]))
    dem = ee.Image(DEM[0]).select(DEM[1]).rename("elev")
    return ee.Image.cat([*images, dem])


def rows_for_run(start: datetime, features: list[dict]) -> pd.DataFrame:
    """Long table (one row per cell, forecast hour) from reduceRegions properties t_/p_/c_{fh:03d} and elev."""
    recs = []
    for f in features:
        p = f["properties"]
        cell = grid.get_cell(p["cell_id"])
        lat, lon = cell.centroid
        for fh in FORECAST_HOURS:
            t, pr, c = p.get(f"t_{fh:03d}"), p.get(f"p_{fh:03d}"), p.get(f"c_{fh:03d}")
            if t is None and pr is None and c is None:
                continue
            recs.append(
                {
                    "cell_id": p["cell_id"],
                    "valid_time": start + timedelta(hours=fh),
                    "model_lat": lat,
                    "model_lon": lon,
                    "model_elevation": p.get("elev"),
                    "lead_day": fh // 24,
                    "temperature_2m": None if t is None else t - 273.15,
                    "precipitation": None if pr is None else max(0.0, pr * 1000.0),  # m -> mm
                    "cloud_cover": None if c is None else c * 100.0,  # fraction -> %
                }
            )
    df = pd.DataFrame(recs)
    if df.empty:
        return pd.DataFrame(columns=COLUMNS)
    df.insert(0, "grid_version", grid.GRID_VERSION)
    df.insert(1, "model", MODEL)
    df["valid_time"] = pd.to_datetime(df["valid_time"], utc=True)
    df["lead_day"] = df["lead_day"].astype("int8")
    for v in ("temperature_2m", "precipitation", "cloud_cover"):
        df[v] = df[v].astype("float32")
    return df[COLUMNS]


def fetch_run(start: datetime, fcs: list[ee.FeatureCollection]) -> pd.DataFrame:
    image = _stack(start)
    features = []
    for fc in fcs:
        res = image.reduceRegions(collection=fc, reducer=ee.Reducer.mean(), scale=SCALE_M, crs="EPSG:4326")
        features += res.getInfo()["features"]
    return rows_for_run(start, features)


def run(today: date, days: int = BACKFILL_DAYS, max_runs: int = MAX_RUNS, data_dir: Path = DATA_DIR) -> dict:
    todo = [t for t in candidate_runs(today, days) if not run_file(data_dir, t).exists()]
    available = sorted(complete_runs(todo))
    ready = available[:max_runs]  # oldest first: the ranking window lies in the past
    fcs = _cell_collections(grid.poland_cells()) if ready else []
    out_dir(data_dir).mkdir(parents=True, exist_ok=True)
    rows, denied = 0, []
    for t in ready:
        try:
            df = fetch_run(t, fcs)
        except ee.EEException as e:
            # 2026-11-02: the service account could read only some images of a run (access still being granted);
            # skip the run, it is tried again next time
            denied.append(f"{t:%Y-%m-%dT%H}: {str(e).splitlines()[0][:120]}")
            continue
        df.to_parquet(run_file(data_dir, t), index=False)
        rows += len(df)
    return {
        "missing_runs": len(todo),
        "fetched": len(ready) - len(denied),
        "not_ready": len(todo) - len(available),
        "left_for_next_run": len(available) - len(ready),
        "failed": denied[:5] + ([f"... and {len(denied) - 5} more"] if len(denied) > 5 else []),
        "rows": rows,
    }


def main() -> None:
    p = argparse.ArgumentParser(description="WeatherNext 3 forecasts per cell from Earth Engine (ranking only)")
    p.add_argument("--date", type=date.fromisoformat, default=datetime.now(UTC).date())
    p.add_argument("--days", type=int, default=BACKFILL_DAYS)
    p.add_argument("--max-runs", type=int, default=MAX_RUNS)
    a = p.parse_args()
    init_ee()
    print(run(a.date, a.days, a.max_runs))


if __name__ == "__main__":
    main()
