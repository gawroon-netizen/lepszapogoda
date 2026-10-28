"""Ogimet SYNOP backup for the IMGW hourly store: decoding, gap detection, IMGW precedence."""

from datetime import UTC, date, datetime

import pandas as pd
import pytest

from pipeline.ingest import imgw, ogimet

WARSAW = "12375"


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("AAXX 01001 12375 12970 61103 10124 20075 30192 40323 53002 60001 80008==", 12.4),
        ("AAXX 01061 12375 12982 71004 11035 21042 30196 333 10153==", -3.5),
        ("AAXX 01061 12375 12982 71104 00105 10021 20013==", 2.1),  # wind >= 99: extra 00fff group
        ("AAXX 01061 12375 12982 71004 1//// 20075==", None),  # not measured
        ("AAXX 01061 12375 12982 71004 20075 30192 333 10153==", None),  # 1snTTT only in section 3 (Tmax)
        ("NIL", None),
    ],
)
def test_temperature_group(message, expected):
    assert ogimet.temperature(message) == expected


def test_parse_keeps_full_hours_known_stations_and_latest_correction():
    text = "\n".join(
        [
            "12375,2026,10,01,06,00,AAXX 01061 12375 12982 71004 10118 20075==",
            "12375,2026,10,01,06,00,AAXX 01061 12375 12982 71004 10120 20075==",  # correction (CCA)
            "12375,2026,10,01,06,30,AAXX 01063 12375 12982 71004 10125 20075==",  # not a full hour
            "12999,2026,10,01,06,00,AAXX 01061 12999 12982 71004 10100 20075==",  # not our station
            "Status: OK",
        ]
    )
    df = ogimet.parse(text, {WARSAW})
    assert len(df) == 1 and df.loc[0, "temperature"] == 12.0
    assert df.loc[0, "time"] == datetime(2026, 10, 1, 6, tzinfo=UTC)


class FakeSession:
    def __init__(self, text):
        self.text, self.calls = text, []

    def get(self, url, params, headers, timeout):
        self.calls.append(params["begin"][:8])

        class R:
            text = self.text

            def raise_for_status(self):
                pass

        return R()


def day_text(day: str, temp: float) -> str:
    y, m, d = day.split("-")
    return "\n".join(
        f"{sid},{y},{m},{d},{h:02d},00,AAXX {d}{h:02d}1 {sid} 12982 71004 1{int(temp * 10):04d} 20075=="
        for sid in imgw.stations()
        for h in range(24)
    )


def test_fill_fetches_only_days_with_gaps_and_imgw_values_win(tmp_path):
    complete = date(2026, 10, 14)
    rows = [
        {"station_id": sid, "time": datetime(2026, 10, 14, h, tzinfo=UTC), "temperature": 5.0}
        for sid, s in imgw.stations().items()
        if s.get("cell_id")
        for h in range(24)
    ]
    imgw.store_hourly(pd.DataFrame(rows, columns=imgw.HOURLY_COLUMNS), tmp_path)
    s = FakeSession(day_text("2026-10-13", 7.0))
    out = ogimet.fill([date(2026, 10, 13), complete], tmp_path, session=s, pause_s=0)
    assert s.calls == ["20261013"] and out["days_fetched"] == 1 and out["new_rows"] == 61 * 24
    got = pd.read_parquet(tmp_path / "obs" / "imgw_hourly" / "2026-10-13.parquet")
    assert set(got["temperature"]) == {7.0}
    # a day the Worker already stored keeps the IMGW API values
    s2 = FakeSession(day_text("2026-10-14", 9.0))
    imgw.store_hourly(ogimet.parse(s2.text, {WARSAW}), tmp_path)
    kept = pd.read_parquet(tmp_path / "obs" / "imgw_hourly" / "2026-10-14.parquet")
    assert set(kept["temperature"]) == {5.0}
