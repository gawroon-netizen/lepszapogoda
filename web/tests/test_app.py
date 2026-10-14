"""Web app (SPEC §12 WWW, §12 d): routes, validation, security headers, SSR without JS, modes, blend, cache."""

import json
from datetime import UTC, datetime, timedelta

import pytest

from lepszapogoda import grid, openmeteo
from lepszapogoda.blend import blend, lead_group, mean_direction
from lepszapogoda.forecast import ForecastService, ForecastUnavailable
from lepszapogoda.optimistic import most_optimistic
from web.app import create_app, view
from web.app.slug import slugify

NOW = int(datetime(2026, 10, 14, 10, 0, tzinfo=UTC).timestamp())
START = int(datetime(2026, 10, 13, 22, 0, tzinfo=UTC).timestamp())  # local midnight, Warsaw (CEST)
HOURS = 8 * 24
TIMES = [START + 3600 * h for h in range(HOURS)]


def series(temp, precip=0.0, cloud=50.0, n=HOURS):
    def col(v):
        return [v(h) if callable(v) else v for h in range(n)] + [None] * (HOURS - n)

    return {
        "temperature_2m": col(temp),
        "apparent_temperature": col(lambda h: (temp(h) if callable(temp) else temp) - 2),
        "precipitation": col(precip),
        "snowfall": col(0.0),
        "cloud_cover": col(cloud),
        "wind_speed_10m": col(10.0),
        "wind_gusts_10m": col(20.0),
        "wind_direction_10m": col(270.0),
        "cape": col(0.0),
    }


def fc():
    return {
        "fetched": NOW,
        "lat": 52.23,
        "lon": 21.01,
        "elevation": 100.0,
        "times": TIMES,
        "models": {
            "ecmwf_ifs": series(10.0, 0.0, 20.0),
            "gfs_seamless": series(14.0, 0.5, 60.0),
            "meteofrance_seamless": series(12.0, 0.0, 40.0, n=4 * 24),  # ends after 4 days
        },
    }


class FakeService:
    def __init__(self, data=None, fail=False):
        self.data, self.fail, self.calls = data or fc(), fail, 0

    def get(self, lat, lon):
        self.calls += 1
        if self.fail:
            raise ForecastUnavailable("down")
        return self.data


@pytest.fixture
def app(tmp_path):
    rankings = tmp_path / "rankings"
    (rankings / "cells").mkdir(parents=True)
    return create_app({"FORECAST_SERVICE": FakeService(), "RANKINGS_DIR": rankings, "TESTING": True})


@pytest.fixture
def client(app):
    return app.test_client()


def write_cell(app, cell_id, accurate, temp_weights=None):
    j = {
        "grid_version": grid.GRID_VERSION,
        "cell": cell_id,
        "accurate": accurate,
        "temp_source": "station:12375:8km",
        "blend": {"temp": temp_weights or {}},
    }
    (app.config["RANKINGS_DIR"] / "cells" / f"{cell_id}.json").write_text(json.dumps(j), encoding="utf-8")


# ---------------------------------------------------------------- routes and validation


def test_index_and_about(client):
    assert client.get("/").status_code == 200
    r = client.get("/o-projekcie")
    assert r.status_code == 200 and "IMGW" in r.get_data(as_text=True)


@pytest.mark.parametrize(
    ("url", "code"),
    [
        ("/prognoza/warszawa/52.230,21.010/trafna", 200),
        ("/prognoza/warszawa/52.230,21.010/nieznany", 404),
        ("/prognoza/Warszawa!/52.230,21.010/trafna", 404),
        ("/prognoza/warszawa/40.000,21.010/trafna", 400),  # outside Poland + margin
        ("/prognoza/warszawa/52.2;drop,21.0/trafna", 400),
        ("/prognoza/warszawa/52.230,121.010/trafna", 400),
    ],
)
def test_forecast_route_validation(client, url, code):
    assert client.get(url).status_code == code


def test_non_canonical_coordinates_redirect(client):
    r = client.get("/prognoza/warszawa/52.23,21.01/trafna?n=Warszawa")
    assert r.status_code == 301
    assert r.headers["Location"].endswith("/prognoza/warszawa/52.230,21.010/trafna?n=Warszawa")


def test_security_headers(client):
    h = client.get("/").headers
    assert "default-src 'self'" in h["Content-Security-Policy"]
    assert h["X-Content-Type-Options"] == "nosniff" and h["X-Frame-Options"] == "DENY"


def test_place_name_is_escaped(client):
    html = client.get("/prognoza/x/52.230,21.010/trafna?n=<script>alert(1)</script>").get_data(as_text=True)
    assert "<script>alert(1)</script>" not in html and "&lt;script&gt;" in html


def test_healthz_without_rankings(client):
    j = client.get("/healthz").get_json()
    assert j["status"] == "ok" and j["cells_ranked"] == 0 and j["rankings_published"] is None


def test_forecast_unavailable_gives_503(tmp_path):
    app = create_app({"FORECAST_SERVICE": FakeService(fail=True), "RANKINGS_DIR": tmp_path, "TESTING": True})
    assert app.test_client().get("/prognoza/x/52.230,21.010/trafna").status_code == 503


# ---------------------------------------------------------------- SSR and modes


def test_server_rendered_days_without_js(client):
    html = client.get("/prognoza/warszawa/52.230,21.010/trafna").get_data(as_text=True)
    assert html.count("data-date=") == 7
    assert "dziś" in html and "zbieramy dane" in html  # no ranking for this cell yet -> equal weights


def test_least_accurate_uses_ranking(app, client):
    cell = grid.cell_id_for(52.23, 21.01)
    write_cell(app, cell, [{"model": "ecmwf_ifs", "score": 100}, {"model": "gfs_seamless", "score": 0}])
    html = client.get("/prognoza/warszawa/52.230,21.010/najmniej-trafna").get_data(as_text=True)
    assert "NOAA GFS przewidywał" in html


def test_view_uncertain_days_and_precip_chance():
    v = view.build(fc(), "trafna", None, NOW)
    assert [d["uncertain"] for d in v["days"]] == [False] * 4 + [True] * 3
    # only GFS (1 of 3 models) gives >= 1 mm a day (0.5 mm/h x 24 h)
    assert v["days"][0]["precip_chance"] == 33


def test_view_single_model_horizon_note():
    v = view.build(fc(), "optymistyczna", None, NOW)
    # scores: ECMWF (10 °C, dry) 0.5, GFS (14 °C, 36 mm) 0.5, Météo-France (12 °C, dry) 0.75
    assert v["model"] == "meteofrance_seamless"
    assert not v["blend"]
    assert any("tylko na 4 dni" in t for t in v["texts"])


# ---------------------------------------------------------------- blend (SPEC §8.10)


def test_blend_equal_and_renormalised_after_horizon():
    b = blend(fc()["models"], TIMES, NOW)
    assert b["temperature_2m"][0] == pytest.approx(12.0)  # (10 + 14 + 12) / 3
    assert b["temperature_2m"][-1] == pytest.approx(12.0)  # (10 + 14) / 2: Météo-France ended
    assert b["temperature_2m_min"][0] == 10.0 and b["temperature_2m_max"][0] == 14.0
    assert b["members"][0] == 3 and b["members"][-1] == 2


def test_blend_temperature_weights_by_lead_group():
    w = {"1-2": {"ecmwf_ifs": 0.75, "gfs_seamless": 0.25, "meteofrance_seamless": 0.0}}
    b = blend(fc()["models"], TIMES, NOW, w)
    i = TIMES.index(NOW + 3600)
    assert b["temperature_2m"][i] == pytest.approx(0.75 * 10 + 0.25 * 14)
    assert b["precipitation"][i] == pytest.approx(0.5 / 3)  # precipitation: equal weights
    assert lead_group(30) == "1-2" and lead_group(60) == "3-4" and lead_group(170) == "5-7"


def test_wind_direction_vector_mean():
    assert mean_direction([350.0, 10.0]) == pytest.approx(0.0, abs=1e-6) or mean_direction([350.0, 10.0]) == 360.0
    assert mean_direction([90.0, 270.0]) is None  # opposite directions cancel out


# ---------------------------------------------------------------- optimistic (SPEC §12 d)


def test_optimistic_hand_computed():
    # A: Tmax 20, 9 mm in 3 days; B: Tmax 18, dry; C: Tmax 22, 30 mm.
    # t_norm: A .5, B 0, C 1; p_norm: A .3, B 0, C 1 -> score A .6, B .5, C .5 -> A
    today = datetime.fromtimestamp(NOW, view.TZ).date()
    models = {
        "A": series(20.0, 9 / 72),
        "B": series(18.0, 0.0),
        "C": series(22.0, 30 / 72),
    }
    assert most_optimistic(models, TIMES, today) == "A"


def test_optimistic_tie_goes_to_less_cloud():
    today = datetime.fromtimestamp(NOW, view.TZ).date()
    models = {"A": series(20.0, 0.0, 80.0), "B": series(20.0, 0.0, 10.0)}
    assert most_optimistic(models, TIMES, today) == "B"


# ---------------------------------------------------------------- cache (SPEC §7.4)


class FakeClient:
    def __init__(self, fail=False):
        self.calls, self.fail = 0, fail

    def forecast(self, models, lat, lon, variables, days):
        self.calls += 1
        if self.fail:
            raise openmeteo.OpenMeteoError("down")
        return {
            m: openmeteo.PointSeries(lat, lon, lat, lon, 100.0, TIMES[:2], {v: [1.0, 2.0] for v in variables})
            for m in models
        }


def test_cache_ttl_and_stale_fallback(tmp_path):
    t = [1000.0]
    client = FakeClient()
    svc = ForecastService(client, tmp_path, ttl_s=3600, clock=lambda: t[0])
    a = svc.get(52.2311, 21.0122)
    svc.get(52.2349, 21.0149)  # same 0.01 degree point
    assert client.calls == 1 and set(a["models"]) == set(openmeteo.MODELS)
    t[0] += 3601
    client.fail = True
    stale = svc.get(52.23, 21.01)
    assert stale["stale"] is True and client.calls == 2
    with pytest.raises(ForecastUnavailable):
        ForecastService(FakeClient(fail=True), tmp_path / "empty").get(50.0, 20.0)


def test_cache_cleanup(tmp_path):
    t = [1000.0]
    svc = ForecastService(FakeClient(), tmp_path, clock=lambda: t[0])
    svc.get(52.0, 21.0)
    t[0] += 8 * 86400 + (datetime.now().timestamp() - 1000)
    assert svc.cleanup() == 1


def test_slugify():
    assert slugify("Łódź Bałuty") == "lodz-baluty"
    assert slugify("Kędzierzyn-Koźle") == "kedzierzyn-kozle"
    assert slugify("!!!") == "punkt"
    assert len(slugify("a" * 200)) == 80


def test_now_is_inside_forecast():
    assert TIMES[0] <= NOW <= TIMES[-1] and timedelta(hours=HOURS) == timedelta(days=8)
