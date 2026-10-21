"""IMGW automatic stations (api/data/meteo): ~790 stations, 10-minute values, collected for denser
temperature and gauge precipitation verification (docs/DECISIONS.md, 2026-10-21). Not used in the ranking yet.

The API returns only the latest value of each variable per station, each with its own timestamp (UTC).
The Cloudflare Worker (workers/imgw-poller) stores every 5-minute poll as
obs/imgw_meteo_raw/{date}/{HHMM}.json.gz; this module turns the polls into
obs/imgw_meteo_10min/{date}.parquet (one row per station and 10-minute timestamp) and daily values:
- Tmax/Tmin from full-hour temperatures with the synop windows (pipeline.ingest.imgw.tmax_tmin);
- precipitation 06 UTC D .. 06 UTC D+1 (IMGW convention), the sum of 10-minute values whose timestamp
  (end of the interval) lies in (06:00 D, 06:00 D+1]; a day needs MIN_PRECIP_INTERVALS of the 144 intervals,
  because an interval missed by the polls cannot be recovered.
Quality control here is only about time: values older than MAX_AGE at poll time are stale (some stations
report a value from months ago) and dropped. Stuck or broken gauges are a task for the verification step.

Usage:
    python -m pipeline.ingest.imgw_meteo ingest-raw
    python -m pipeline.ingest.imgw_meteo daily --date YYYY-MM-DD
"""

from __future__ import annotations

import argparse
import gzip
import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pandas as pd

from lepszapogoda import grid
from pipeline.ingest.imgw import tmax_tmin
from pipeline.paths import DATA_DIR

# API field -> column; each field has a companion "<field>_data" timestamp
FIELDS = {
    "temperatura_powietrza": "temperature",
    "opad_10min": "precip",
    "wilgotnosc_wzgledna": "humidity",
    "wiatr_srednia_predkosc": "wind_speed",
    "wiatr_predkosc_maksymalna": "wind_max",
    "wiatr_poryw_10min": "wind_gust",
    "wiatr_kierunek": "wind_dir",
    "temperatura_gruntu": "ground_temp",
}
VALUE_COLUMNS = list(FIELDS.values())
COLUMNS = ["station_id", "time", *VALUE_COLUMNS]
MAX_AGE = timedelta(hours=3)
MAX_AHEAD = timedelta(minutes=15)  # clock skew between the Worker and IMGW
MIN_PRECIP_INTERVALS = 138  # of 144: at most one hour of missed polls per day
DAILY_COLUMNS = ["station_id", "date", "tmax", "tmin", "n_tmax", "n_tmin", "precip", "n_precip"]


def _num(x) -> float | None:
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def _time(x) -> datetime | None:
    try:
        return datetime.strptime(x, "%Y-%m-%d %H:%M:%S").replace(tzinfo=UTC)
    except (TypeError, ValueError):
        return None


def parse_api(payload: list[dict], polled_at: datetime) -> pd.DataFrame:
    """One row per (station, timestamp) with the variables measured at that timestamp."""
    records = []
    for s in payload:
        sid = s.get("kod_stacji")
        if not sid:
            continue
        for field, col in FIELDS.items():
            v, t = _num(s.get(field)), _time(s.get(f"{field}_data"))
            if v is None or t is None or not (polled_at - MAX_AGE <= t <= polled_at + MAX_AHEAD):
                continue
            records.append({"station_id": sid, "time": t, col: v})
    if not records:
        return pd.DataFrame(columns=COLUMNS)
    df = pd.DataFrame(records).reindex(columns=COLUMNS)
    return _collapse(df)


def _collapse(df: pd.DataFrame) -> pd.DataFrame:
    """Merge rows of the same station and timestamp, keeping the first non-null value of each variable."""
    df = df.astype({c: "float64" for c in VALUE_COLUMNS})
    df["time"] = pd.to_datetime(df["time"], utc=True)
    return df.groupby(["station_id", "time"], as_index=False, sort=True)[VALUE_COLUMNS].first()


def parse_stations(payload: list[dict], polled_at: datetime) -> dict[str, dict]:
    out = {}
    for s in payload:
        lat, lon = _num(s.get("lat")), _num(s.get("lon"))
        if not s.get("kod_stacji") or lat is None or lon is None:
            continue
        out[s["kod_stacji"]] = {
            "name": s.get("nazwa_stacji"),
            "lat": lat,
            "lon": lon,
            "elevation": _num(s.get("wysokosc_npm")),
            "cell_id": grid.cell_id_for(lat, lon),
            "last_seen": polled_at.date().isoformat(),
        }
    return out


def _polled_at(path: Path) -> datetime:
    hhmm = path.name.split(".")[0]
    return datetime.strptime(f"{path.parent.name} {hhmm}", "%Y-%m-%d %H%M").replace(tzinfo=UTC)


def store_10min(df: pd.DataFrame, data_dir: Path = DATA_DIR) -> int:
    """Merge into per-day files. Returns the number of new (station, timestamp) rows."""
    out_dir = data_dir / "obs" / "imgw_meteo_10min"
    out_dir.mkdir(parents=True, exist_ok=True)
    new = 0
    for day, part in df.groupby(df["time"].dt.date):
        path = out_dir / f"{day.isoformat()}.parquet"
        old = pd.read_parquet(path) if path.exists() else pd.DataFrame(columns=COLUMNS)
        merged = _collapse(pd.concat([old, part], ignore_index=True))
        new += len(merged) - len(old)
        merged.to_parquet(path, index=False)
    return new


def store_stations(found: dict[str, dict], data_dir: Path = DATA_DIR) -> int:
    path = data_dir / "obs" / "imgw_meteo_stations.json"
    stations = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    for sid, meta in found.items():
        if meta["last_seen"] >= stations.get(sid, {}).get("last_seen", ""):
            stations[sid] = meta
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(dict(sorted(stations.items())), ensure_ascii=False, indent=1), encoding="utf-8")
    return len(stations)


def ingest_raw(data_dir: Path = DATA_DIR) -> tuple[int, int, int]:
    """Convert the Worker's raw polls into the 10-minute store. Idempotent.
    Returns (files read, new rows, stations known)."""
    files = sorted((data_dir / "obs" / "imgw_meteo_raw").glob("*/*.json.gz"))
    frames, stations = [], {}
    for f in files:
        try:
            payload = json.loads(gzip.decompress(f.read_bytes()).decode("utf-8"))
            polled_at = _polled_at(f)
        except (OSError, ValueError, TypeError):
            continue  # a truncated or malformed file must not stop the rest
        frames.append(parse_api(payload, polled_at))
        stations.update(parse_stations(payload, polled_at))
    frames = [f for f in frames if len(f)]
    new = store_10min(pd.concat(frames, ignore_index=True), data_dir) if frames else 0
    return len(files), new, store_stations(stations, data_dir) if stations else 0


def daily(day: date, data_dir: Path = DATA_DIR) -> pd.DataFrame:
    """Daily values per station for `day` (see module docstring); needs the 10-minute files of D-1..D+1."""
    frames = []
    for d in (day - timedelta(days=1), day, day + timedelta(days=1)):
        path = data_dir / "obs" / "imgw_meteo_10min" / f"{d.isoformat()}.parquet"
        if path.exists():
            frames.append(pd.read_parquet(path))
    if not frames:
        return pd.DataFrame(columns=DAILY_COLUMNS)
    h = pd.concat(frames, ignore_index=True)
    temps = tmax_tmin(h, day)
    d0 = pd.Timestamp(day, tz=UTC) + pd.Timedelta(hours=6)
    p = h[(h["time"] > d0) & (h["time"] <= d0 + pd.Timedelta(days=1)) & (h["time"].dt.minute % 10 == 0)]
    p = p.dropna(subset=["precip"]).groupby("station_id")["precip"].agg(["sum", "count"])
    p = pd.DataFrame(
        {"precip": p["sum"].where(p["count"] >= MIN_PRECIP_INTERVALS).round(1), "n_precip": p["count"]}
    ).reset_index()
    out = temps.merge(p, on="station_id", how="outer")
    out["date"] = day
    for c in ("n_tmax", "n_tmin", "n_precip"):
        out[c] = out[c].fillna(0).astype(int)
    return out[DAILY_COLUMNS].sort_values("station_id", ignore_index=True)


def store_daily(df: pd.DataFrame, day: date, data_dir: Path = DATA_DIR) -> None:
    """obs/imgw_meteo_daily/{date}.parquet. Each value keeps the computation based on more 10-minute data,
    so a rerun with some input files missing cannot replace a good value with a worse one."""
    out_dir = data_dir / "obs" / "imgw_meteo_daily"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{day.isoformat()}.parquet"
    if path.exists():
        old = pd.read_parquet(path).set_index("station_id")
        new = df.set_index("station_id")
        merged = new.combine_first(old)
        for value, n in (("tmax", "n_tmax"), ("tmin", "n_tmin"), ("precip", "n_precip")):
            both = new.index.intersection(old.index)
            keep_old = both[old.loc[both, n] > new.loc[both, n]]
            merged.loc[keep_old, [value, n]] = old.loc[keep_old, [value, n]]
        df = merged.reset_index()
        df["date"] = day
        df = df[DAILY_COLUMNS].astype({"n_tmax": int, "n_tmin": int, "n_precip": int})
    if len(df):
        df.sort_values("station_id", ignore_index=True).to_parquet(path, index=False)


def main() -> None:
    p = argparse.ArgumentParser(description="IMGW automatic stations (10-minute data)")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("ingest-raw")
    d = sub.add_parser("daily")
    d.add_argument("--date", type=date.fromisoformat, default=datetime.now(UTC).date() - timedelta(days=2))
    args = p.parse_args()
    if args.cmd == "ingest-raw":
        n_files, n_rows, n_st = ingest_raw()
        print(f"raw files: {n_files}, new 10-minute rows: {n_rows}, stations known: {n_st}")
    else:
        df = daily(args.date)
        store_daily(df, args.date)
        print(
            f"{args.date}: {df['tmax'].notna().sum()} stations with Tmax, {df['tmin'].notna().sum()} with Tmin, "
            f"{df['precip'].notna().sum()} with precipitation"
        )


if __name__ == "__main__":
    main()
