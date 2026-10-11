"""Satellite ingest: pure parts only (Earth Engine calls are exercised by a live run, see README)."""

from datetime import date

import pandas as pd

from pipeline.ingest import satellite


def test_missing_days_respects_lag_and_existing_files(tmp_path):
    today = date(2026, 10, 12)
    days = satellite.missing_days("imerg", today, 5, tmp_path)
    assert days == [date(2026, 10, d) for d in (6, 7, 8, 9, 10)]
    assert satellite.missing_days("modis_terra", today, 1, tmp_path) == [date(2026, 10, 8)]
    satellite._store(
        pd.DataFrame({"cell_id": ["522_210"], "date": [date(2026, 10, 8)], "precip": [1.0]}), "imerg", tmp_path
    )
    assert date(2026, 10, 8) not in satellite.missing_days("imerg", today, 5, tmp_path)


def test_imerg_window_is_06_to_06_utc():
    assert satellite._imerg_window(date(2026, 9, 3)) == ("2026-09-03T06:00:00+00:00", "2026-09-04T06:00:00+00:00")
