"""Hourly archived forecasts -> daily values comparable with observations (conventions from Etap 0a/0b).

- precipitation of day D: hourly sums stamped D 07:00 .. D+1 06:00 UTC (each covers the preceding hour),
  i.e. 06 UTC D -> 06 UTC D+1, like IMGW's SMDB and our IMERG day; all 24 hours required;
- Tmax(D): max of hourly temperature 06..18 UTC of D; Tmin(D): min over 18 UTC D-1 .. 06 UTC D; 13 hours each;
- cloud at a satellite overpass: model cloud_cover linearly interpolated between the two surrounding hours.
"""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

HOURLY_COLUMNS = [
    "cell_id",
    "valid_time",
    "lead_day",
    "temperature_2m",
    "precipitation",
    "cloud_cover",
    "model_elevation",
]


def load_hourly(data_dir: Path, model: str, start: date, end: date, cells: set[str] | None = None) -> pd.DataFrame:
    """Hourly forecasts of one model covering days start..end (plus the margins the daily windows need)."""
    files = sorted((data_dir / "forecasts" / model).glob("*.parquet"))
    lo = pd.Timestamp(start - timedelta(days=1), tz="UTC")
    hi = pd.Timestamp(end + timedelta(days=2), tz="UTC")
    frames = []
    for f in files:
        df = pd.read_parquet(f, columns=HOURLY_COLUMNS)
        df = df[(df["valid_time"] >= lo) & (df["valid_time"] < hi)]
        if cells is not None:
            df = df[df["cell_id"].isin(cells)]
        if len(df):
            frames.append(df)
    if not frames:
        return pd.DataFrame(columns=HOURLY_COLUMNS)
    df = pd.concat(frames, ignore_index=True)
    # A refetch may store the same hour twice; values are identical, keep one
    return df.drop_duplicates(["cell_id", "valid_time", "lead_day"], keep="last").reset_index(drop=True)


def daily_values(hourly: pd.DataFrame) -> pd.DataFrame:
    """Per (cell_id, lead_day, date): precip, tmax, tmin, model_elevation. Incomplete windows give NaN."""
    if hourly.empty:
        return pd.DataFrame(columns=["cell_id", "lead_day", "date", "precip", "tmax", "tmin", "model_elevation"])
    h = hourly
    hour = h["valid_time"].dt.hour
    keys = ["cell_id", "lead_day", "date"]

    p = h.assign(date=(h["valid_time"] - pd.Timedelta(hours=7)).dt.date)
    p = p.groupby(keys)["precipitation"].agg(["sum", "count"])
    precip = p["sum"].where(p["count"] == 24).rename("precip")

    d = h[(hour >= 6) & (hour <= 18)].assign(date=lambda x: x["valid_time"].dt.date)
    d = d.groupby(keys)["temperature_2m"].agg(["max", "count"])
    tmax = d["max"].where(d["count"] == 13).rename("tmax")

    n = h[(hour >= 18) | (hour <= 6)].assign(date=lambda x: (x["valid_time"] + pd.Timedelta(hours=6)).dt.date)
    n = n.groupby(keys)["temperature_2m"].agg(["min", "count"])
    tmin = n["min"].where(n["count"] == 13).rename("tmin")

    elev = h.groupby(["cell_id"])["model_elevation"].first()
    out = pd.concat([precip, tmax, tmin], axis=1).reset_index()
    out["model_elevation"] = out["cell_id"].map(elev)
    return out


def cloud_at_overpass(hourly: pd.DataFrame, overpasses: pd.DataFrame) -> pd.DataFrame:
    """Model cloud cover [%] at each (cell_id, date, overpass_utc) of `overpasses`, per lead_day."""
    cols = ["cell_id", "lead_day", "date", "cloud_fc"]
    if hourly.empty or overpasses.empty:
        return pd.DataFrame(columns=cols)
    op = overpasses[["cell_id", "date", "overpass_utc"]].copy()
    op["t0"] = op["overpass_utc"].dt.floor("h")
    op["t1"] = op["t0"] + pd.Timedelta(hours=1)
    op["frac"] = (op["overpass_utc"] - op["t0"]) / pd.Timedelta(hours=1)
    c = hourly[["cell_id", "valid_time", "lead_day", "cloud_cover"]]
    a = op.merge(c.rename(columns={"valid_time": "t0", "cloud_cover": "c0"}), on=["cell_id", "t0"])
    a = a.merge(c.rename(columns={"valid_time": "t1", "cloud_cover": "c1"}), on=["cell_id", "t1", "lead_day"])
    a["cloud_fc"] = a["c0"] + (a["c1"] - a["c0"]) * a["frac"]
    return a[cols]


def window_dates(end: date, days: int) -> list[date]:
    return [end - timedelta(days=k) for k in range(days)][::-1]


def nan_to_none(x):
    return None if x is None or (isinstance(x, float) and np.isnan(x)) else x
