"""Verification and ranking (SPEC §12 b, c, e) on synthetic data."""

import hashlib
import json
from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

from pipeline.verify import aggregate, components, ranking
from pipeline.verify import config as cfg

CELL = "522_210"  # Warszawa
END = date(2026, 9, 30)
DAYS = aggregate.window_dates(END, cfg.WINDOW_DAYS)


def hourly_frame(cell, start: date, n_days: int, temp, precip, cloud, lead=1, elev=100.0):
    t = pd.date_range(pd.Timestamp(start, tz="UTC"), periods=24 * n_days, freq="h")
    f = lambda v: v(t) if callable(v) else np.full(len(t), v, dtype=float)  # noqa: E731
    return pd.DataFrame(
        {
            "cell_id": cell,
            "valid_time": t,
            "lead_day": lead,
            "temperature_2m": f(temp),
            "precipitation": f(precip),
            "cloud_cover": f(cloud),
            "model_elevation": elev,
        }
    )


# ---------------------------------------------------------------- daily windows


def test_daily_windows():
    def temp(t):
        v = np.full(len(t), 10.0)
        v[(t.day == 2) & (t.hour == 14)] = 25.0  # Tmax of day 2
        v[(t.day == 2) & (t.hour == 20)] = 30.0  # after 18 UTC: belongs to nobody's Tmax(2)
        v[(t.day == 1) & (t.hour == 22)] = -3.0  # night before day 2 -> Tmin(2)
        return v

    def precip(t):
        v = np.zeros(len(t))
        v[(t.day == 2) & (t.hour == 7)] = 1.0  # first hour of day 2 (06-07 UTC)
        v[(t.day == 3) & (t.hour == 6)] = 2.0  # last hour of day 2 (05-06 UTC on day 3)
        v[(t.day == 2) & (t.hour == 6)] = 4.0  # last hour of day 1
        return v

    h = hourly_frame(CELL, date(2026, 9, 1), 4, temp, precip, 50.0)
    d = aggregate.daily_values(h).set_index("date")
    d2 = d.loc[date(2026, 9, 2)]
    assert d2["tmax"] == 25.0 and d2["tmin"] == -3.0 and d2["precip"] == 3.0
    assert d.loc[date(2026, 9, 1), "precip"] == 4.0
    assert np.isnan(d.loc[date(2026, 9, 1), "tmin"])  # night window starts before the data


def test_cloud_interpolated_at_overpass():
    h = hourly_frame(CELL, date(2026, 9, 1), 1, 10.0, 0.0, lambda t: np.where(t.hour == 9, 20.0, 80.0))
    op = pd.DataFrame(
        {"cell_id": [CELL], "date": [date(2026, 9, 1)], "overpass_utc": [pd.Timestamp("2026-09-01 09:15", tz="UTC")]}
    )
    c = aggregate.cloud_at_overpass(h, op)
    assert c["cloud_fc"].iloc[0] == pytest.approx(20 + 60 * 0.25)


# ---------------------------------------------------------------- metrics (§12 b)


def precip_comp(fc: np.ndarray, ob: np.ndarray, model="m"):
    daily = pd.DataFrame({"cell_id": CELL, "lead_day": 1, "date": DAYS[: len(fc)], "precip": fc})
    obs = pd.DataFrame({"cell_id": CELL, "date": DAYS[: len(ob)], "precip": ob})
    return components.finalize(components.precip_components(daily, obs, model), "cell_id")


def metrics_of(comp):
    return ranking.add_metrics(ranking.pooled(comp, "cell_id", DAYS[0], END, [1])).iloc[0]


def test_perfect_model_mae0_ets1():
    ob = np.array([0, 0, 5, 2, 0, 0.5, 12, 0, 0, 3] * 3, dtype=float)
    m = metrics_of(precip_comp(ob, ob))
    assert m["mae"] == 0 and m["sde"] == 0 and m["ets"] == 1.0


def test_random_model_ets_near_zero():
    rng = np.random.default_rng(0)
    fc, ob = rng.exponential(2, 30_000), rng.exponential(2, 30_000)
    daily = pd.DataFrame({"cell_id": CELL, "lead_day": 1, "date": [DAYS[i % 30] for i in range(30_000)], "precip": fc})
    sums = components.precip_components(
        daily.assign(date=range(30_000)), pd.DataFrame({"cell_id": CELL, "date": range(30_000), "precip": ob}), "m"
    )
    h, m, f, c = (sums[k].sum() for k in ("hits", "misses", "false_alarms", "correct_negatives"))
    assert abs(ranking.ets(h, m, f, c)) < 0.02


def test_ets_undefined_without_events():
    m = metrics_of(precip_comp(np.zeros(30), np.zeros(30)))
    assert m["ets"] is None


def test_constant_bias_has_zero_error_sd():
    ob = np.linspace(0, 90, 30)
    cf = pd.DataFrame({"cell_id": CELL, "lead_day": 1, "date": DAYS, "cloud_fc": ob + 10})
    modis = pd.DataFrame({"cell_id": CELL, "date": DAYS, "cloud_frac": ob / 100, "valid_frac": 1.0})
    m = metrics_of(components.finalize(components.cloud_components(cf, modis, "m"), "cell_id"))
    assert m["bias"] == pytest.approx(10) and m["mae"] == pytest.approx(10) and m["sde"] == pytest.approx(0, abs=1e-6)


def test_modis_with_low_valid_fraction_is_ignored():
    cf = pd.DataFrame({"cell_id": CELL, "lead_day": 1, "date": DAYS[:2], "cloud_fc": [50.0, 50.0]})
    modis = pd.DataFrame({"cell_id": CELL, "date": DAYS[:2], "cloud_frac": [0.5, 0.5], "valid_frac": [1.0, 0.2]})
    assert len(components.cloud_components(cf, modis, "m")) == 1


# ---------------------------------------------------------------- normalisation and score (§12 c)


def test_rank_cell_weights_and_bounds():
    metrics = {
        "a": {"precip_ets": 0.5, "precip_mae": 1.0, "cloud_class_acc": 0.7, "cloud_sde": 20, "temp_mae": 1.0},
        "b": {"precip_ets": 0.3, "precip_mae": 2.0, "cloud_class_acc": 0.5, "cloud_sde": 30, "temp_mae": 2.0},
        "c": {"precip_ets": 0.4, "precip_mae": 1.5, "cloud_class_acc": 0.6, "cloud_sde": 25, "temp_mae": 1.5},
    }
    r = ranking.rank_cell(metrics)
    assert [x["model"] for x in r] == ["a", "c", "b"]
    assert r[0]["score"] == 100 and r[-1]["score"] == 0 and r[1]["score"] == 50
    assert sum(cfg.WEIGHTS.values()) == pytest.approx(1)


def test_without_temperature_weights_renormalise():
    metrics = {
        "a": {"precip_ets": 0.5, "precip_mae": 1.0, "cloud_class_acc": 0.5, "cloud_sde": 30},
        "b": {"precip_ets": 0.3, "precip_mae": 2.0, "cloud_class_acc": 0.7, "cloud_sde": 20},
    }
    r = {x["model"]: x["score"] for x in ranking.rank_cell(metrics)}
    assert r == {"a": 50, "b": 50}  # precipitation and cloud each 0.5


def test_ets_missing_falls_back_to_mae():
    r = ranking.rank_cell({"a": {"precip_ets": None, "precip_mae": 1.0}, "b": {"precip_ets": 0.2, "precip_mae": 2.0}})
    assert [x["model"] for x in r] == ["a", "b"]


# ---------------------------------------------------------------- stations and blend


def test_station_map_radius_and_weights():
    stations = {
        "12375": {"id": "12375", "cell_id": "521_209", "lat": 52.166, "lon": 20.967, "elevation": 110.0},
        "12001": {"id": "12001", "cell_id": None, "lat": 55.48, "lon": 18.17, "elevation": 0.0},
        "12205": {"id": "12205", "cell_id": "533_146", "lat": 53.4, "lon": 14.617, "elevation": 7.0},
    }
    m = ranking.station_map([CELL, "500_190"], stations)
    w = m[m["cell_id"] == CELL]
    assert list(w["station_id"]) == ["12375"] and w["w"].sum() == pytest.approx(1)
    assert m[m["cell_id"] == "500_190"].empty  # nothing within 60 km


def test_blend_weights_inverse_mse_and_equal_fallback():
    groups = {
        "1-2": pd.DataFrame({"cell_id": [CELL, CELL], "model": ["a", "b"], "temp_mse": [1.0, 3.0]}),
        "3-4": pd.DataFrame(columns=["cell_id", "model", "temp_mse"]),
    }
    b = ranking.blend_weights(groups, CELL, ["ecmwf_ifs", "meteofrance_seamless"])
    assert b["temp"]["1-2"] == {"a": 0.75, "b": 0.25}
    assert b["temp"]["3-4"] == {"ecmwf_ifs": 0.5, "meteofrance_seamless": 0.5}
    assert b["temp"]["5-7"] == {"ecmwf_ifs": 1.0}  # Météo-France ends at 3 days
    assert b["precip"] == "equal"


# ---------------------------------------------------------------- end to end and reproducibility (§12 e)


THREE = ("ecmwf_ifs", "gfs_seamless", "icon_seamless")


def synthetic_components():
    rng = np.random.default_rng(1)
    ob = rng.exponential(2, 30) * (rng.random(30) > 0.5)
    parts = []
    for model, noise in (("ecmwf_ifs", 0.2), ("gfs_seamless", 2.0), ("icon_seamless", 1.0)):
        fc = np.clip(ob + rng.normal(0, noise, 30), 0, None)
        parts.append(precip_comp(fc, ob, model))
        cf = pd.DataFrame(
            {"cell_id": CELL, "lead_day": 1, "date": DAYS, "cloud_fc": np.clip(rng.normal(50, 10 * noise, 30), 0, 100)}
        )
        modis = pd.DataFrame({"cell_id": CELL, "date": DAYS, "cloud_frac": 0.5, "valid_frac": 1.0})
        parts.append(components.finalize(components.cloud_components(cf, modis, model), "cell_id"))
    return pd.concat(parts, ignore_index=True)


def test_build_end_to_end_and_reproducible():
    comp = synthetic_components()
    empty = pd.DataFrame(columns=["station_id", "model", "lead_day", "date", "var", *components.COUNT_COLS])
    cells1, meta1 = ranking.build(comp, empty, {}, END, "2026-10-01T05:00Z", THREE)
    cells2, _ = ranking.build(comp.sample(frac=1, random_state=3), empty, {}, END, "2026-10-01T05:00Z", THREE)
    j = cells1[CELL]
    assert [x["model"] for x in j["accurate"]][0] == "ecmwf_ifs"
    assert j["temp_source"] is None and j["window"] == {"from": "2026-09-01", "to": "2026-09-30", "days": 30}
    assert meta1["cells_ranked"] == 1
    h = lambda d: hashlib.sha256(json.dumps(d, sort_keys=True).encode()).hexdigest()  # noqa: E731
    assert h(cells1) == h(cells2)


def test_model_with_only_24h_archive_is_compared_at_24h_only():
    # KNMI is archived only at +24 h. Here it is the worst model at +24 h, but its pooled error (24 h only) is
    # smaller than the others' pooled 24-72 h error: pooling across leads would wrongly favour it.
    rng = np.random.default_rng(5)
    ob = rng.exponential(2, 30) * (rng.random(30) > 0.4)
    noise = {("a", 1): 0.1, ("a", 2): 2.0, ("a", 3): 3.0, ("b", 1): 0.3, ("b", 2): 2.5, ("b", 3): 3.5, ("knmi", 1): 0.6}
    parts = []
    for (model, lead), sd in noise.items():
        fc = np.clip(ob + rng.normal(0, sd, 30), 0, None)
        daily = pd.DataFrame({"cell_id": CELL, "lead_day": lead, "date": DAYS, "precip": fc})
        obs = pd.DataFrame({"cell_id": CELL, "date": DAYS, "precip": ob})
        parts.append(components.finalize(components.precip_components(daily, obs, model), "cell_id"))
    comp = pd.concat(parts, ignore_index=True)
    empty = pd.DataFrame(columns=["station_id", "model", "lead_day", "date", "var", *components.COUNT_COLS])
    cells, _ = ranking.build(comp, empty, {}, END, "x", ("a", "b", "knmi"))
    acc = {r["model"]: r for r in cells[CELL]["accurate"]}
    assert acc["knmi"]["leads_days"] == [1] and acc["a"]["leads_days"] == [1, 2, 3]
    assert acc["knmi"]["precip_mae"] < acc["b"]["precip_mae"]  # pooled MAE flatters KNMI...
    assert acc["knmi"]["score"] == min(r["score"] for r in acc.values())  # ...the lead-by-lead score does not


def test_minimum_days():
    comp = synthetic_components()
    short = comp[comp["date"] >= END - timedelta(days=cfg.MIN_DAYS - 2)]  # 19 days
    empty = pd.DataFrame(columns=["station_id", "model", "lead_day", "date", "var", *components.COUNT_COLS])
    cells, _ = ranking.build(short, empty, {}, END, "x", THREE)
    assert cells == {}


def test_cell_without_all_models_is_not_ranked():
    comp = synthetic_components()
    empty = pd.DataFrame(columns=["station_id", "model", "lead_day", "date", "var", *components.COUNT_COLS])
    cells, meta = ranking.build(comp[comp["model"] != "icon_seamless"], empty, {}, END, "x", THREE)
    assert cells == {} and meta["cells_ranked"] == 0
    assert ranking.build(comp, empty, {}, END, "x", THREE)[1]["cells_ranked"] == 1
