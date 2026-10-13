"""IMGW synop observations for the temperature ranking (SPEC §8.2).

Two sources:
- real time: the public API returns only the latest hourly observation per station, so `poll` must run
  every hour (GitHub Actions / hosting cron) and appends to obs/imgw_hourly/{date}.parquet;
- archive: monthly zips of official daily values (published with up to ~5 weeks delay), used for history
  and to replace hourly-derived values once available.

Daily Tmax/Tmin from hourly data use the synop convention established in Etap 0a and the same hours as the
model side (hourly values, not true extremes), so both sides are compared like for like:
    Tmax(D) = max over 06..18 UTC of day D, Tmin(D) = min over 18 UTC D-1 .. 06 UTC D (13 hourly values each).
A day needs at least MIN_HOURS of the 13 hours, otherwise it is missing.

Usage:
    python -m pipeline.ingest.imgw poll
    python -m pipeline.ingest.imgw daily --date YYYY-MM-DD
    python -m pipeline.ingest.imgw archive --year 2026 --month 9
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import zipfile
from datetime import UTC, date, datetime, timedelta
from importlib import resources
from pathlib import Path

import pandas as pd
import requests

from pipeline.paths import DATA_DIR

API_URL = "https://danepubliczne.imgw.pl/api/data/synop"
ARCHIVE_URL = (
    "https://danepubliczne.imgw.pl/data/dane_pomiarowo_obserwacyjne/dane_meteorologiczne/dobowe/synop"
    "/{year}/{year}_{month:02d}_s.zip"
)
MIN_HOURS = 10
HOURLY_COLUMNS = ["station_id", "time", "temperature", "precip_sum", "wind_speed", "wind_dir", "humidity", "pressure"]


def stations() -> dict[str, dict]:
    """Station metadata keyed by id, from lepszapogoda/data/imgw_stations.json."""
    path = resources.files("lepszapogoda") / "data" / "imgw_stations.json"
    return {s["id"]: s for s in json.loads(path.read_text(encoding="utf-8"))["stations"]}


def _num(x) -> float | None:
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------- real time


def parse_api(payload: list[dict]) -> pd.DataFrame:
    rows = []
    for s in payload:
        try:
            t = datetime.strptime(f"{s['data_pomiaru']} {int(s['godzina_pomiaru']):02d}", "%Y-%m-%d %H").replace(
                tzinfo=UTC
            )
        except (KeyError, TypeError, ValueError):
            continue
        rows.append(
            {
                "station_id": s["id_stacji"],
                "time": t,
                "temperature": _num(s.get("temperatura")),
                "precip_sum": _num(s.get("suma_opadu")),
                "wind_speed": _num(s.get("predkosc_wiatru")),
                "wind_dir": _num(s.get("kierunek_wiatru")),
                "humidity": _num(s.get("wilgotnosc_wzgledna")),
                "pressure": _num(s.get("cisnienie")),
            }
        )
    return pd.DataFrame(rows, columns=HOURLY_COLUMNS)


def store_hourly(df: pd.DataFrame, data_dir: Path = DATA_DIR) -> int:
    """Append to per-day files, de-duplicated on (station, time). Returns the number of new rows."""
    out_dir = data_dir / "obs" / "imgw_hourly"
    out_dir.mkdir(parents=True, exist_ok=True)
    new = 0
    for day, part in df.groupby(df["time"].dt.date):
        path = out_dir / f"{day.isoformat()}.parquet"
        old = pd.read_parquet(path) if path.exists() else pd.DataFrame(columns=HOURLY_COLUMNS)
        merged = pd.concat([old, part], ignore_index=True).drop_duplicates(["station_id", "time"], keep="first")
        new += len(merged) - len(old)
        merged.sort_values(["station_id", "time"]).to_parquet(path, index=False)
    return new


def poll(session: requests.Session | None = None, data_dir: Path = DATA_DIR) -> int:
    payload = (session or requests).get(API_URL, timeout=60).json()
    return store_hourly(parse_api(payload), data_dir)


def ingest_raw(data_dir: Path = DATA_DIR) -> tuple[int, int]:
    """Convert raw API responses saved by the Cloudflare Worker (obs/imgw_raw/{date}/{HHMM}.json, workers/imgw-poller)
    into the hourly store. Idempotent: rows already stored are skipped. Returns (files read, new rows)."""
    files = sorted((data_dir / "obs" / "imgw_raw").glob("*/*.json"))
    frames = []
    for f in files:
        try:
            frames.append(parse_api(json.loads(f.read_text(encoding="utf-8"))))
        except (ValueError, TypeError):
            continue  # a truncated or non-JSON file must not stop the rest
    if not frames:
        return len(files), 0
    return len(files), store_hourly(pd.concat(frames, ignore_index=True), data_dir)


def daily_from_hourly(day: date, data_dir: Path = DATA_DIR) -> pd.DataFrame:
    """Tmax/Tmin per station for `day` from stored hourly observations (see module docstring)."""
    frames = []
    for d in (day - timedelta(days=1), day):
        path = data_dir / "obs" / "imgw_hourly" / f"{d.isoformat()}.parquet"
        if path.exists():
            frames.append(pd.read_parquet(path))
    cols = ["station_id", "date", "tmax", "tmin", "n_tmax", "n_tmin", "source"]
    if not frames:
        return pd.DataFrame(columns=cols)
    h = pd.concat(frames).dropna(subset=["temperature"])
    d0 = pd.Timestamp(day, tz=UTC)
    day_win = h[(h["time"] >= d0 + pd.Timedelta(hours=6)) & (h["time"] <= d0 + pd.Timedelta(hours=18))]
    night_win = h[(h["time"] >= d0 - pd.Timedelta(hours=6)) & (h["time"] <= d0 + pd.Timedelta(hours=6))]
    tx = day_win.groupby("station_id")["temperature"].agg(["max", "count"])
    tn = night_win.groupby("station_id")["temperature"].agg(["min", "count"])
    out = tx.join(tn, how="outer", lsuffix="_x", rsuffix="_n").reset_index()
    out = pd.DataFrame(
        {
            "station_id": out["station_id"],
            "date": day,
            "tmax": out["max"].where(out["count_x"] >= MIN_HOURS),
            "tmin": out["min"].where(out["count_n"] >= MIN_HOURS),
            "n_tmax": out["count_x"].fillna(0).astype(int),
            "n_tmin": out["count_n"].fillna(0).astype(int),
            "source": "api_hourly",
        }
    )
    return out[cols]


# ---------------------------------------------------------------- archive


def _archive_value(row: list[str], i: int, status_i: int, zero_if_9: bool = False) -> float | None:
    """Status 8 = not measured, 9 = phenomenon absent (0 for precipitation)."""
    if row[status_i] == "8":
        return None
    if row[status_i] == "9" and zero_if_9:
        return 0.0
    return _num(row[i])


def parse_archive(raw_csv: str) -> pd.DataFrame:
    """Daily synop file s_d_MM_YYYY.csv (CP1250)."""
    rows = []
    for r in csv.reader(io.StringIO(raw_csv)):
        if len(r) < 15:
            continue
        rows.append(
            {
                # archive codes are 9 digits, e.g. 352200375; the WMO id is "12" + the last three
                "station_id": "12" + r[0][-3:],
                "date": date(int(r[2]), int(r[3]), int(r[4])),
                "tmax": _archive_value(r, 5, 6),
                "tmin": _archive_value(r, 7, 8),
                "precip": _archive_value(r, 13, 14, zero_if_9=True),  # 06 UTC D .. 06 UTC D+1 (Etap 0a)
                "source": "archive",
            }
        )
    return pd.DataFrame(rows)


def archive(year: int, month: int, session: requests.Session | None = None) -> pd.DataFrame | None:
    """Official daily values for one month, or None if IMGW has not published it yet."""
    r = (session or requests).get(ARCHIVE_URL.format(year=year, month=month), timeout=120)
    if r.status_code == 404:
        return None
    r.raise_for_status()
    with zipfile.ZipFile(io.BytesIO(r.content)) as z:
        name = next(n for n in z.namelist() if n.startswith("s_d_") and not n.startswith("s_d_t"))
        return parse_archive(z.read(name).decode("cp1250"))


def store_daily(df: pd.DataFrame, data_dir: Path = DATA_DIR) -> None:
    """obs/imgw_daily/{date}.parquet; archive rows replace hourly-derived rows of the same station and day."""
    out_dir = data_dir / "obs" / "imgw_daily"
    out_dir.mkdir(parents=True, exist_ok=True)
    rank = {"archive": 0, "api_hourly": 1}
    for day, part in df.groupby("date"):
        path = out_dir / f"{day.isoformat()}.parquet"
        old = pd.read_parquet(path) if path.exists() else None
        merged = pd.concat([x for x in (part, old) if x is not None and len(x)], ignore_index=True)
        merged = (
            merged.assign(_r=merged["source"].map(rank))
            .sort_values(["station_id", "_r"])
            .drop_duplicates("station_id", keep="first")
            .drop(columns="_r")
        )
        merged.to_parquet(path, index=False)


def main() -> None:
    p = argparse.ArgumentParser(description="IMGW synop observations")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("poll")
    sub.add_parser("ingest-raw")
    d = sub.add_parser("daily")
    d.add_argument("--date", type=date.fromisoformat, default=datetime.now(UTC).date() - timedelta(days=1))
    a = sub.add_parser("archive")
    a.add_argument("--year", type=int, required=True)
    a.add_argument("--month", type=int, required=True)
    args = p.parse_args()
    if args.cmd == "poll":
        print(f"new hourly rows: {poll()}")
    elif args.cmd == "ingest-raw":
        n_files, n_rows = ingest_raw()
        print(f"raw files: {n_files}, new hourly rows: {n_rows}")
    elif args.cmd == "daily":
        df = daily_from_hourly(args.date)
        store_daily(df)
        print(f"{args.date}: {df['tmax'].notna().sum()} stations with Tmax, {df['tmin'].notna().sum()} with Tmin")
    else:
        df = archive(args.year, args.month)
        if df is None:
            print("not published yet")
            return
        store_daily(df)
        print(f"{len(df)} station-days stored")


if __name__ == "__main__":
    main()
