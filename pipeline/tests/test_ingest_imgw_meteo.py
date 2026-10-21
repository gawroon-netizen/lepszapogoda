"""IMGW automatic stations: API parsing, stale values, 10-minute store, daily values."""

import gzip
import json
from datetime import UTC, date, datetime, timedelta

import pandas as pd

from pipeline.ingest import imgw_meteo

POLL = datetime(2026, 10, 21, 19, 25, tzinfo=UTC)


def station(sid="351230497", temp=None, temp_t=None, precip=None, precip_t=None, **extra):
    return {
        "kod_stacji": sid,
        "nazwa_stacji": "WŁODAWA",
        "lat": "51.553333",
        "lon": "23.529444",
        "wysokosc_npm": "177",
        "temperatura_powietrza": temp,
        "temperatura_powietrza_data": temp_t,
        "opad_10min": precip,
        "opad_10min_data": precip_t,
        **extra,
    }


def test_parse_merges_timestamps_and_drops_stale_values():
    payload = [
        station(
            temp="13.1",
            temp_t="2026-10-21 19:10:00",
            precip="0",
            precip_t="2026-10-21 19:00:00",
            wilgotnosc_wzgledna="80.4",
            wilgotnosc_wzgledna_data="2026-10-21 19:10:00",
        ),
        station(
            "250180010",
            temp="7.0",
            temp_t="2026-06-24 11:10:00",  # stale: months old
            precip="0.2",
            precip_t="2026-10-21 19:00:00",
        ),
        station("250180020"),  # no data at all
        {"nazwa_stacji": "no id"},
    ]
    df = imgw_meteo.parse_api(payload, POLL).set_index(["station_id", "time"])
    t1910, t1900 = pd.Timestamp("2026-10-21 19:10", tz=UTC), pd.Timestamp("2026-10-21 19:00", tz=UTC)
    assert df.loc[("351230497", t1910), "temperature"] == 13.1
    assert df.loc[("351230497", t1910), "humidity"] == 80.4
    assert df.loc[("351230497", t1900), "precip"] == 0.0 and pd.isna(df.loc[("351230497", t1900), "temperature"])
    assert df.loc[("250180010", t1900), "precip"] == 0.2
    assert len(df) == 3  # the stale temperature is gone


def write_poll(root, polled_at: datetime, payload):
    d = root / "obs" / "imgw_meteo_raw" / polled_at.date().isoformat()
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{polled_at:%H%M}.json.gz").write_bytes(gzip.compress(json.dumps(payload).encode("utf-8")))


def test_ingest_raw_is_idempotent_and_keeps_stations(tmp_path):
    p = [station(temp="13.1", temp_t="2026-10-21 19:10:00", precip="0", precip_t="2026-10-21 19:00:00")]
    write_poll(tmp_path, POLL, p)
    write_poll(tmp_path, POLL + timedelta(minutes=5), p)  # the next poll often repeats the same values
    bad = tmp_path / "obs" / "imgw_meteo_raw" / "2026-10-21" / "1935.json.gz"
    bad.write_bytes(b"not gzip")
    assert imgw_meteo.ingest_raw(tmp_path) == (3, 2, 1)
    assert imgw_meteo.ingest_raw(tmp_path) == (3, 0, 1)
    st = json.loads((tmp_path / "obs" / "imgw_meteo_stations.json").read_text(encoding="utf-8"))
    assert st["351230497"]["name"] == "WŁODAWA" and st["351230497"]["cell_id"] == "515_235"


def ten_minute_rows(sid, start, end, precip=0.0, temp=None):
    rows, t = [], start
    while t <= end:
        rows.append({"station_id": sid, "time": t, "precip": precip, "temperature": temp})
        t += timedelta(minutes=10)
    return rows


def test_daily_precip_window_and_completeness(tmp_path):
    d0 = datetime(2026, 10, 20, 6, tzinfo=UTC)
    rows = ten_minute_rows("A", d0, d0 + timedelta(days=1), precip=0.1)  # 06:00 is the previous day's last
    rows += ten_minute_rows("B", d0 + timedelta(hours=2), d0 + timedelta(days=1), precip=0.1)  # 06:10-07:50 missing
    df = pd.DataFrame(rows).reindex(columns=imgw_meteo.COLUMNS)
    imgw_meteo.store_10min(imgw_meteo._collapse(df), tmp_path)
    got = imgw_meteo.daily(date(2026, 10, 20), tmp_path).set_index("station_id")
    assert got.loc["A", "n_precip"] == 144 and got.loc["A", "precip"] == 14.4
    assert got.loc["B", "n_precip"] == 133 and pd.isna(got.loc["B", "precip"])


def test_daily_temperature_uses_full_hours_only(tmp_path):
    day = datetime(2026, 10, 20, tzinfo=UTC)
    rows = ten_minute_rows("A", day - timedelta(hours=6), day + timedelta(hours=18), temp=10.0)
    rows.append({"station_id": "A", "time": day + timedelta(hours=12, minutes=10), "temperature": 25.0})
    df = imgw_meteo._collapse(pd.DataFrame(rows).reindex(columns=imgw_meteo.COLUMNS))
    imgw_meteo.store_10min(df, tmp_path)
    got = imgw_meteo.daily(date(2026, 10, 20), tmp_path).set_index("station_id").loc["A"]
    assert got["tmax"] == 10.0 and got["n_tmax"] == 13 and got["n_tmin"] == 13


def test_store_daily_keeps_the_better_value(tmp_path):
    day = date(2026, 10, 20)
    good = pd.DataFrame(
        [
            {
                "station_id": "A",
                "date": day,
                "tmax": 12.0,
                "tmin": 3.0,
                "n_tmax": 13,
                "n_tmin": 13,
                "precip": 4.2,
                "n_precip": 144,
            }
        ]
    )
    worse = good.assign(precip=float("nan"), n_precip=70, tmax=11.0)
    imgw_meteo.store_daily(good, day, tmp_path)
    imgw_meteo.store_daily(worse, day, tmp_path)  # rerun with the next day's 10-minute file missing
    got = pd.read_parquet(tmp_path / "obs" / "imgw_meteo_daily" / "2026-10-20.parquet").set_index("station_id")
    assert got.loc["A", "precip"] == 4.2 and got.loc["A", "n_precip"] == 144
    assert got.loc["A", "tmax"] == 11.0  # same number of hours: the newer value wins
