"""Backup for the IMGW synop hourly store: raw SYNOP messages from Ogimet (ogimet.com, GTS relay).

The IMGW API keeps only the latest observation, so an hour the Cloudflare Worker missed is lost there; IMGW's
monthly archive comes up to ~5 weeks late. Ogimet keeps the SYNOP messages the same stations send to the WMO
network, so missing hours can be filled the next day (2026-10-28: 1-12 October were missing because hourly
collection started on 13 October). NOAA ISD, the first choice, is no longer updated (last data August 2025).

Only the air temperature (section 1 group 1snTTT) at full hours is taken, for the stations in imgw_stations.json.
Rows go to obs/imgw_hourly through pipeline.ingest.imgw.store_hourly, which keeps a row already stored for the same
station and hour: values from the IMGW API win, Ogimet only fills gaps.

    python -m pipeline.ingest.ogimet                    # fill days of the last FILL_DAYS that have gaps
    python -m pipeline.ingest.ogimet --start 2026-10-01 --end 2026-10-12
"""

from __future__ import annotations

import argparse
import re
import time
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pandas as pd
import requests

from pipeline.ingest import imgw
from pipeline.paths import DATA_DIR

URL = "https://www.ogimet.com/cgi-bin/getsynop"
WMO_BLOCK = "12"  # Poland
FILL_DAYS = 45  # the ranking window reaches back 44 days (pipeline.verify.config)
COMPLETE_SHARE = 0.95  # a day is complete when it has this share of station-hours of the known stations
PAUSE_S = 5.0  # between requests: Ogimet asks scripts not to overload it
LINE_RE = re.compile(r"^(\d{5}),(\d{4}),(\d{2}),(\d{2}),(\d{2}),(\d{2}),(.*)$")


def temperature(message: str) -> float | None:
    """Air temperature [°C] from section 1 of a SYNOP message (AAXX YYGGi IIiii iRiXhVV Nddff [00fff] 1snTTT ...)."""
    groups = message.replace("=", " ").split()
    try:
        start = groups.index("AAXX") + 3  # skip YYGGi and the station id
    except ValueError:
        return None
    body = groups[start:]
    if len(body) < 3:
        return None
    rest = body[2:]  # after iRiXhVV and Nddff
    if rest and rest[0].startswith("00"):
        rest = rest[1:]  # wind speed >= 99 units
    for g in rest:
        if g == "333" or g == "555":
            return None  # end of section 1 without a temperature group
        if len(g) == 5 and g[0] == "1":
            sign, digits = g[1], g[2:]
            if sign not in "01" or not digits.isdigit():
                return None  # e.g. 1////: not measured
            value = int(digits) / 10
            return -value if sign == "1" else value
    return None


def parse(text: str, stations: set[str]) -> pd.DataFrame:
    rows = {}
    for line in text.splitlines():
        m = LINE_RE.match(line.strip())
        if not m or m.group(1) not in stations or m.group(6) != "00":
            continue
        t = temperature(m.group(7))
        if t is None:
            continue
        sid = m.group(1)
        when = datetime(int(m.group(2)), int(m.group(3)), int(m.group(4)), int(m.group(5)), tzinfo=UTC)
        rows[(sid, when)] = t  # a later message for the same hour (correction, CCA) replaces the earlier one
    df = pd.DataFrame(
        [{"station_id": s, "time": t, "temperature": v} for (s, t), v in rows.items()], columns=imgw.HOURLY_COLUMNS
    )
    return df.astype({c: "float64" for c in imgw.HOURLY_COLUMNS if c not in ("station_id", "time")})


def fetch_day(day: date, session=requests) -> str:
    r = session.get(
        URL,
        params={"block": WMO_BLOCK, "begin": f"{day:%Y%m%d}0000", "end": f"{day:%Y%m%d}2300"},
        headers={"User-Agent": "lepszapogoda.pl (pipeline backup for IMGW synop)"},
        timeout=120,
    )
    r.raise_for_status()
    if "quota" in r.text.lower() or "cuota" in r.text.lower():
        raise RuntimeError("Ogimet download quota exceeded; try again later")
    return r.text


def days_with_gaps(days: list[date], stations: set[str], data_dir: Path = DATA_DIR) -> list[date]:
    expected = len(stations) * 24 * COMPLETE_SHARE
    out = []
    for d in days:
        path = data_dir / "obs" / "imgw_hourly" / f"{d.isoformat()}.parquet"
        if not path.exists():
            out.append(d)
            continue
        h = pd.read_parquet(path).dropna(subset=["temperature"])
        if (h["station_id"].isin(stations) & (h["time"].dt.minute == 0)).sum() < expected:
            out.append(d)
    return out


def fill(days: list[date], data_dir: Path = DATA_DIR, session=requests, pause_s: float = PAUSE_S) -> dict:
    stations = {sid for sid, s in imgw.stations().items() if s.get("cell_id")}
    todo = days_with_gaps(days, stations, data_dir)
    added = 0
    for k, d in enumerate(todo):
        if k:
            time.sleep(pause_s)
        added += imgw.store_hourly(parse(fetch_day(d, session), stations), data_dir)
    return {"days_checked": len(days), "days_fetched": len(todo), "new_rows": added}


def main() -> None:
    p = argparse.ArgumentParser(description="Fill gaps in the IMGW hourly store from Ogimet SYNOP messages")
    p.add_argument("--start", type=date.fromisoformat)
    p.add_argument("--end", type=date.fromisoformat)
    a = p.parse_args()
    today = datetime.now(UTC).date()
    end = a.end or today - timedelta(days=1)  # today is still incomplete
    start = a.start or end - timedelta(days=FILL_DAYS - 1)
    days = [start + timedelta(days=k) for k in range((end - start).days + 1)]
    print(fill(days))


if __name__ == "__main__":
    main()
