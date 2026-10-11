"""Open-Meteo client and budget tests (no network: fake session and clock)."""

from datetime import date

import pytest

from lepszapogoda import openmeteo
from lepszapogoda.openmeteo import Budget, BudgetExceeded, Limits, OpenMeteoClient, call_cost


class FakeClock:
    def __init__(self, t: float = 1_000_000.0) -> None:
        self.t = t
        self.slept: list[float] = []

    def __call__(self) -> float:
        return self.t

    def sleep(self, s: float) -> None:
        self.slept.append(s)
        self.t += s


class FakeResponse:
    def __init__(self, status: int, payload):
        self.status_code = status
        self._payload = payload
        self.text = str(payload)

    def json(self):
        return self._payload


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls: list[tuple[str, dict]] = []

    def get(self, url, params=None, timeout=None):
        self.calls.append((url, params))
        r = self.responses.pop(0)
        return r(params) if callable(r) else r


def location(lat, lon, hourly, elevation=100.0):
    return {"latitude": lat, "longitude": lon, "elevation": elevation, "hourly": hourly}


# ---------------------------------------------------------------- cost


@pytest.mark.parametrize(
    ("locs", "nvars", "days", "expected"),
    [
        (1, 1, 1, 1.0),
        (1, 10, 14, 1.0),
        (1, 15, 14, 1.5),  # pricing page example
        (1, 10, 28, 2.0),
        (1, 21, 30, 2.1 * 30 / 14),
        (50, 21, 14, 105.0),  # multi-location counted per location (conservative)
    ],
)
def test_call_cost(locs, nvars, days, expected):
    assert call_cost(locs, nvars, days) == pytest.approx(expected)


def test_call_cost_rejects_empty():
    with pytest.raises(ValueError):
        call_cost(0, 1, 1)


# ---------------------------------------------------------------- budget


def test_budget_waits_out_the_hourly_window():
    clk = FakeClock()
    b = Budget(
        limits=Limits(per_minute=1e9, per_hour=100, per_day=1e9, per_month=1e9), safety=1.0, clock=clk, sleep=clk.sleep
    )
    b.reserve(60)
    clk.t += 600
    b.reserve(40)  # exactly at the limit, no wait
    assert clk.slept == []
    b.reserve(10)  # must wait until the first 60 leave the window
    assert len(clk.slept) == 1
    assert clk.slept[0] == pytest.approx(3_600 - 600 + 1)
    assert b.used(3_600) == pytest.approx(50)


def test_budget_raises_on_daily_limit_instead_of_waiting():
    clk = FakeClock()
    b = Budget(limits=Limits(per_day=100), safety=0.8, clock=clk, sleep=clk.sleep)
    b.reserve(80)
    with pytest.raises(BudgetExceeded, match="per_day"):
        b.reserve(1)
    assert clk.slept == []


def test_budget_raises_when_wait_too_long():
    clk = FakeClock()
    b = Budget(
        limits=Limits(per_hour=10, per_day=1e9, per_month=1e9), safety=1.0, max_wait_s=60, clock=clk, sleep=clk.sleep
    )
    b.reserve(10)
    with pytest.raises(BudgetExceeded, match="wait"):
        b.reserve(1)


def test_budget_ledger_persists(tmp_path):
    clk = FakeClock()
    path = tmp_path / "ledger.json"
    Budget(ledger_path=path, clock=clk, sleep=clk.sleep).reserve(7.5)
    clk.t += 120
    b2 = Budget(ledger_path=path, clock=clk, sleep=clk.sleep)
    assert b2.used(3_600) == 7.5
    assert b2.used(60) == 0


def test_budget_ledger_forgets_entries_older_than_a_month(tmp_path):
    clk = FakeClock()
    path = tmp_path / "ledger.json"
    Budget(ledger_path=path, clock=clk, sleep=clk.sleep).reserve(5)
    clk.t += 31 * 86_400
    assert Budget(ledger_path=path, clock=clk, sleep=clk.sleep).usage()["per_month"] == 0


# ---------------------------------------------------------------- previous runs


def test_previous_runs_drops_leads_beyond_horizon_and_parses():
    def respond(params):
        assert params["models"] == "meteofrance_seamless"
        assert params["elevation"] == "nan" and params["timezone"] == "UTC" and params["cell_selection"] == "nearest"
        names = params["hourly"].split(",")
        assert names == [f"temperature_2m_previous_day{d}" for d in (1, 2, 3)]  # horizon 3 days
        return FakeResponse(200, location(52.2, 21.0, {"time": [0, 3600], **{n: [1.0, None] for n in names}}, 92.0))

    clk = FakeClock()
    client = OpenMeteoClient(Budget(clock=clk, sleep=clk.sleep), session=FakeSession([respond]))
    (s,) = client.previous_runs(
        "meteofrance_seamless", [(52.25, 21.05)], date(2026, 9, 1), date(2026, 9, 14), ["temperature_2m"], range(1, 8)
    )
    assert (s.lat, s.lon, s.cell_lat, s.cell_lon, s.elevation) == (52.25, 21.05, 52.2, 21.0, 92.0)
    assert s.times == [0, 3600]
    assert s.values["temperature_2m_previous_day2"] == [1.0, None]
    assert client.budget.used(60) == pytest.approx(1.0)


def test_previous_runs_chunks_points_and_charges_per_location():
    points = [(50 + i * 0.01, 20.0) for i in range(120)]

    def respond(params):
        lats = params["latitude"].split(",")
        return FakeResponse(
            200, [location(float(la), 20.0, {"time": [0], "precipitation_previous_day1": [0.0]}) for la in lats]
        )

    clk = FakeClock()
    session = FakeSession([respond] * 3)
    client = OpenMeteoClient(Budget(clock=clk, sleep=clk.sleep), session=session)
    out = client.previous_runs("gfs_seamless", points, date(2026, 9, 1), date(2026, 9, 30), ["precipitation"], [1])
    assert len(session.calls) == 3
    assert [len(c[1]["latitude"].split(",")) for c in session.calls] == [50, 50, 20]
    # one elevation value per coordinate, otherwise the API answers 400
    assert [c[1]["elevation"].split(",") for c in session.calls][2] == ["nan"] * 20
    assert len(out) == 120 and out[119].lat == points[119][0]
    assert client.budget.used(60) == pytest.approx(120 * 30 / 14)


def test_single_location_response_is_an_object_not_a_list():
    clk = FakeClock()
    session = FakeSession([FakeResponse(200, location(52.0, 21.0, {"time": [0], "cloud_cover_previous_day1": [50]}))])
    client = OpenMeteoClient(Budget(clock=clk, sleep=clk.sleep), session=session)
    (s,) = client.previous_runs(
        "gfs_seamless", [(52.0, 21.0)], date(2026, 9, 1), date(2026, 9, 1), ["cloud_cover"], [1]
    )
    assert s.values["cloud_cover_previous_day1"] == [50]


def test_nan_elevation_becomes_none():
    clk = FakeClock()
    session = FakeSession([FakeResponse(200, location(52.0, 21.0, {"time": []}, float("nan")))])
    client = OpenMeteoClient(Budget(clock=clk, sleep=clk.sleep), session=session)
    (s,) = client.previous_runs(
        "gfs_seamless", [(52.0, 21.0)], date(2026, 9, 1), date(2026, 9, 1), ["cloud_cover"], [1]
    )
    assert s.elevation is None


# ---------------------------------------------------------------- errors


def test_hourly_429_waits_and_retries():
    clk = FakeClock()
    session = FakeSession(
        [
            FakeResponse(
                429, {"error": True, "reason": "Hourly API request limit exceeded. Please try again in the next hour."}
            ),
            FakeResponse(200, location(52.0, 21.0, {"time": [0], "cloud_cover_previous_day1": [1]})),
        ]
    )
    client = OpenMeteoClient(Budget(clock=clk, sleep=clk.sleep), session=session, sleep=clk.sleep)
    client.previous_runs("gfs_seamless", [(52.0, 21.0)], date(2026, 9, 1), date(2026, 9, 1), ["cloud_cover"], [1])
    assert len(session.calls) == 2
    assert 30 < clk.slept[-1] <= 3_630


def test_daily_429_raises_budget_exceeded():
    clk = FakeClock()
    session = FakeSession([FakeResponse(429, {"error": True, "reason": "Daily API request limit exceeded."})])
    client = OpenMeteoClient(Budget(clock=clk, sleep=clk.sleep), session=session, sleep=clk.sleep)
    with pytest.raises(BudgetExceeded, match="Daily"):
        client.previous_runs("gfs_seamless", [(52.0, 21.0)], date(2026, 9, 1), date(2026, 9, 1), ["cloud_cover"], [1])


def test_400_raises_with_reason():
    clk = FakeClock()
    session = FakeSession([FakeResponse(400, {"error": True, "reason": "No data is available for this location"})])
    client = OpenMeteoClient(Budget(clock=clk, sleep=clk.sleep), session=session)
    with pytest.raises(openmeteo.OpenMeteoError, match="No data"):
        client.previous_runs("gfs_seamless", [(60.0, 21.0)], date(2026, 9, 1), date(2026, 9, 1), ["cloud_cover"], [1])


def test_5xx_is_retried():
    clk = FakeClock()
    session = FakeSession([FakeResponse(502, "bad gateway"), FakeResponse(200, location(52.0, 21.0, {"time": []}))])
    client = OpenMeteoClient(Budget(clock=clk, sleep=clk.sleep), session=session, sleep=clk.sleep)
    client.previous_runs("gfs_seamless", [(52.0, 21.0)], date(2026, 9, 1), date(2026, 9, 1), ["cloud_cover"], [1])
    assert len(session.calls) == 2


# ---------------------------------------------------------------- forecast (web)


def test_forecast_splits_model_suffixed_variables_and_keeps_downscaling():
    def respond(params):
        assert "elevation" not in params and params["cell_selection"] == "land"
        assert params["models"] == "ecmwf_ifs,gfs_seamless"
        return FakeResponse(
            200,
            location(
                52.2, 21.0, {"time": [0], "temperature_2m_ecmwf_ifs": [10.0], "temperature_2m_gfs_seamless": [11.0]}
            ),
        )

    clk = FakeClock()
    client = OpenMeteoClient(Budget(clock=clk, sleep=clk.sleep), session=FakeSession([respond]))
    out = client.forecast(["ecmwf_ifs", "gfs_seamless"], 52.23, 21.01, ["temperature_2m"], forecast_days=7)
    assert out["ecmwf_ifs"].values["temperature_2m"] == [10.0]
    assert out["gfs_seamless"].values["temperature_2m"] == [11.0]
    assert client.budget.used(60) == pytest.approx(2.0)
