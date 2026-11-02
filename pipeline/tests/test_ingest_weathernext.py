"""WeatherNext 3 ingest without Earth Engine: lead mapping, units, run files, verification compatibility."""

from datetime import UTC, date, datetime, timedelta

import pandas as pd

from pipeline.ingest import weathernext as wn
from pipeline.verify import aggregate
from pipeline.verify import config as cfg

START = datetime(2026, 10, 10, 6, tzinfo=UTC)


def features(cell="522_210", temp_k=283.15, precip_m=0.0005, cloud=0.4, elev=87.0):
    props = {"cell_id": cell, "elev": elev}
    for fh in wn.FORECAST_HOURS:
        props |= {f"t_{fh:03d}": temp_k, f"p_{fh:03d}": precip_m, f"c_{fh:03d}": cloud}
    return [{"properties": props}]


def test_forecast_hours_match_open_meteo_leads():
    # lead N: the newest 6-hourly run at least 24 N h before the valid time -> forecast hours 24N .. 24N+5
    assert [*range(24, 30), *range(48, 54), *range(72, 78)] == wn.FORECAST_HOURS


def test_rows_units_and_leads():
    df = wn.rows_for_run(START, features())
    assert len(df) == 18 and set(df["lead_day"]) == {1, 2, 3}
    first = df.iloc[0]
    assert first["valid_time"] == START + timedelta(hours=24) and first["lead_day"] == 1
    assert abs(first["temperature_2m"] - 10.0) < 1e-4  # K -> °C
    assert abs(first["precipitation"] - 0.5) < 1e-6  # m -> mm
    assert abs(first["cloud_cover"] - 40.0) < 1e-4  # fraction -> %
    assert first["model"] == wn.MODEL and first["model_elevation"] == 87.0
    assert list(df.columns) == wn.COLUMNS
    assert set(aggregate.HOURLY_COLUMNS) <= set(df.columns)  # read by pipeline.verify unchanged


def test_four_runs_give_complete_daily_values(tmp_path):
    # runs 00/06/12/18 of one day cover lead 1 for every hour of the next day
    out = wn.out_dir(tmp_path)
    out.mkdir(parents=True)
    for h in (0, 6, 12, 18):
        start = datetime(2026, 10, 10, h, tzinfo=UTC)
        wn.rows_for_run(start, features()).to_parquet(wn.run_file(tmp_path, start))
    for h in (0, 6):  # the 06-06 precipitation day also needs the next morning
        start = datetime(2026, 10, 11, h, tzinfo=UTC)
        wn.rows_for_run(start, features()).to_parquet(wn.run_file(tmp_path, start))
    daily = aggregate.daily_values(aggregate.load_hourly(tmp_path, wn.MODEL, date(2026, 10, 11), date(2026, 10, 11)))
    d = daily[(daily["lead_day"] == 1) & (daily["date"] == date(2026, 10, 11))].iloc[0]
    assert abs(d["precip"] - 24 * 0.5) < 1e-3 and abs(d["tmax"] - 10.0) < 1e-3


def test_run_skips_stored_runs_and_respects_the_limit(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(wn, "complete_runs", lambda starts: list(starts))
    monkeypatch.setattr(wn, "_cell_collections", lambda cells: [])
    monkeypatch.setattr(wn, "fetch_run", lambda t, fcs: calls.append(t) or wn.rows_for_run(t, features()))
    today = date(2026, 10, 12)
    out = wn.run(today, days=2, max_runs=3, data_dir=tmp_path)
    assert out["missing_runs"] == 8 and out["fetched"] == 3
    assert calls == sorted(calls) and calls[0] == datetime(2026, 10, 10, tzinfo=UTC)  # oldest first
    out = wn.run(today, days=2, max_runs=10, data_dir=tmp_path)
    assert out["missing_runs"] == 5 and out["fetched"] == 5
    assert len(list(wn.out_dir(tmp_path).glob("*.parquet"))) == 8


def test_weathernext_is_verified_but_not_required():
    assert wn.MODEL in cfg.VERIFY_MODELS and wn.MODEL not in cfg.REQUIRED_MODELS
    assert pd.Timestamp(wn.candidate_runs(date(2026, 10, 12), 1)[-1]) == pd.Timestamp("2026-10-11T18:00Z")


def test_unreadable_run_is_skipped_not_fatal(tmp_path, monkeypatch):
    import ee

    def fetch(t, fcs):
        if t.hour == 6:
            raise ee.EEException("Permission denied attempting to access 'projects/.../202609180600_202609200600'.")
        return wn.rows_for_run(t, features())

    monkeypatch.setattr(wn, "complete_runs", lambda starts: list(starts))
    monkeypatch.setattr(wn, "_cell_collections", lambda cells: [])
    monkeypatch.setattr(wn, "fetch_run", fetch)
    out = wn.run(date(2026, 10, 11), days=1, max_runs=10, data_dir=tmp_path)
    assert out["fetched"] == 3 and len(out["failed"]) == 1 and "Permission denied" in out["failed"][0]
    assert not wn.run_file(tmp_path, datetime(2026, 10, 10, 6, tzinfo=UTC)).exists()  # retried next time
