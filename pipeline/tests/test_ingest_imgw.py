"""IMGW observations: API parsing, hourly store, daily Tmax/Tmin, archive parsing and precedence."""

from datetime import UTC, date, datetime

import pandas as pd

from pipeline.ingest import imgw


def api_row(sid, day, hour, temp):
    return {
        "id_stacji": sid,
        "stacja": "X",
        "data_pomiaru": day,
        "godzina_pomiaru": str(hour),
        "temperatura": None if temp is None else str(temp),
        "predkosc_wiatru": "2",
        "kierunek_wiatru": "180",
        "wilgotnosc_wzgledna": "80.0",
        "suma_opadu": "0",
        "cisnienie": "1013.0",
    }


def test_station_list():
    st = imgw.stations()
    assert len(st) >= 60
    assert st["12375"]["name"] == "Warszawa" and st["12375"]["cell_id"] == "521_209"
    assert st["12001"]["cell_id"] is None  # Petrobaltic platform, outside the grid


def test_parse_api_and_store_dedup(tmp_path):
    df = imgw.parse_api([api_row("12375", "2026-10-11", 21, 6.7), api_row("12295", "2026-10-11", 20, None), {"bad": 1}])
    assert len(df) == 2
    assert df.loc[0, "time"] == datetime(2026, 10, 11, 21, tzinfo=UTC)
    assert pd.isna(df.loc[1, "temperature"])
    assert imgw.store_hourly(df, tmp_path) == 2
    assert imgw.store_hourly(df, tmp_path) == 0  # same poll twice adds nothing


def hourly(day_prev: str, day: str, temps_prev: dict[int, float], temps: dict[int, float]) -> list[dict]:
    rows = [api_row("12375", day_prev, h, t) for h, t in temps_prev.items()]
    return rows + [api_row("12375", day, h, t) for h, t in temps.items()]


def test_daily_tmax_tmin_windows(tmp_path):
    # night 18 UTC D-1 .. 06 UTC D, day 06..18 UTC D
    prev = {h: 10.0 for h in range(18, 24)}
    prev[22] = 2.0  # night minimum on D-1 evening
    cur = {h: 12.0 for h in range(0, 24)}
    cur[14] = 20.0  # day maximum
    cur[20] = 30.0  # after 18 UTC: not part of Tmax(D)
    cur[3] = 1.0  # night minimum, inside window
    imgw.store_hourly(imgw.parse_api(hourly("2026-10-10", "2026-10-11", prev, cur)), tmp_path)
    d = imgw.daily_from_hourly(date(2026, 10, 11), tmp_path).set_index("station_id").loc["12375"]
    assert d["tmax"] == 20.0 and d["n_tmax"] == 13
    assert d["tmin"] == 1.0 and d["n_tmin"] == 13


def test_daily_requires_enough_hours(tmp_path):
    cur = {h: 15.0 for h in range(6, 14)}  # only 8 of 13 day hours
    imgw.store_hourly(imgw.parse_api(hourly("2026-10-10", "2026-10-11", {}, cur)), tmp_path)
    d = imgw.daily_from_hourly(date(2026, 10, 11), tmp_path).set_index("station_id").loc["12375"]
    assert pd.isna(d["tmax"]) and d["n_tmax"] == 8


ARCHIVE_LINE = (
    '"352200375",WARSZAWA,"2026","09","03",22.4,,10.6,,17.4,,9.0,,0.1,,W,,"9",,"9",7.3,,,"8",,"8",,"8",,"8",'
    ',"8",,"8",,"8",,"8",,"8",,"8",,"8",,"8",,"8",,"8",,"8",,"8",,"8",,"8",,"8",R,,"9",,"9",,"8"\n'
    '"352200375",WARSZAWA,"2026","09","04",21.0,,9.0,,15.0,,8.0,,,"9",,,"9",,"9",7.3,,,"8"\n'
    '"352200375",WARSZAWA,"2026","09","05",,"8",9.5,,15.0,,8.0,,,"9",,,"9",,"9",7.3,,,"8"\n'
)


def test_parse_archive_status_codes():
    df = imgw.parse_archive(ARCHIVE_LINE).set_index("date")
    assert set(df["station_id"]) == {"12375"}
    assert df.loc[date(2026, 9, 3), "tmax"] == 22.4 and df.loc[date(2026, 9, 3), "precip"] == 0.1
    assert df.loc[date(2026, 9, 4), "precip"] == 0.0  # status 9: no precipitation
    assert pd.isna(df.loc[date(2026, 9, 5), "tmax"])  # status 8: not measured


def test_archive_replaces_hourly_derived_values(tmp_path):
    d = date(2026, 9, 3)
    hourly_df = pd.DataFrame([{"station_id": "12375", "date": d, "tmax": 21.9, "tmin": 11.0, "source": "api_hourly"}])
    imgw.store_daily(hourly_df, tmp_path)
    imgw.store_daily(imgw.parse_archive(ARCHIVE_LINE), tmp_path)
    imgw.store_daily(hourly_df, tmp_path)  # a late hourly rebuild must not overwrite the archive
    got = pd.read_parquet(tmp_path / "obs" / "imgw_daily" / "2026-09-03.parquet").set_index("station_id")
    assert got.loc["12375", "source"] == "archive" and got.loc["12375", "tmax"] == 22.4
