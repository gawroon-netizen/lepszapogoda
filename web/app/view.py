"""Forecast view model (SPEC §6): series for the chosen mode, 7 local days, texts. Pure functions, no Flask."""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime
from zoneinfo import ZoneInfo

from lepszapogoda.blend import blend
from lepszapogoda.optimistic import most_optimistic
from web.app.i18n import pl

TZ = ZoneInfo("Europe/Warsaw")
DAYS = 7
UNCERTAIN_FROM_DAY = 5  # days 5-7 shown as less certain (Etap 0b)
SNOW_CM_PER_MM = 0.7  # Open-Meteo snowfall [cm] per mm of water


def _day_indices(times: list[int]) -> dict[date, list[int]]:
    out: dict[date, list[int]] = defaultdict(list)
    for i, t in enumerate(times):
        out[datetime.fromtimestamp(t, TZ).date()].append(i)
    return out


def _vals(series: dict, var: str, idx: list[int]) -> list[float]:
    s = series.get(var) or []
    return [s[i] for i in idx if i < len(s) and s[i] is not None]


def day_icon(precip: float, snow_frac: float, cloud: float | None, cape_max: float, gust_max: float) -> str:
    if precip >= 2 and cape_max >= 800:
        return "burza"
    if precip >= 0.5 and snow_frac >= 0.6:
        return "snieg"
    if precip >= 0.5 and snow_frac >= 0.2:
        return "deszcz-snieg"
    if precip >= 10:
        return "ulewa"
    if precip >= 1:
        return "deszcz"
    if precip >= 0.2:
        return "mzawka"
    if gust_max >= 60:
        return "wietrznie"
    c = 50.0 if cloud is None else cloud
    for limit, name in ((20, "slonecznie"), (45, "malo-chmur"), (70, "czesciowe"), (90, "pochmurno")):
        if c < limit:
            return name
    return "zachmurzenie"


def storm_level(cape_max: float, precip: float) -> str | None:
    """Informative storm risk shown in every mode (SPEC §8.9, without the weather code in the MVP)."""
    if cape_max >= 800 and precip >= 0.5:
        return "likely"
    if cape_max >= 400 and precip > 0:
        return "possible"
    return None


def day_summary(series: dict, idx: list[int], times: list[int], d: date, k: int, models: dict | None) -> dict:
    temp = _vals(series, "temperature_2m", idx)
    precip = sum(_vals(series, "precipitation", idx))
    snow_mm = sum(_vals(series, "snowfall", idx)) / SNOW_CM_PER_MM
    # the day's icon describes daylight hours
    day_hours = [i for i in idx if 8 <= datetime.fromtimestamp(times[i], TZ).hour <= 18]
    cloud = _vals(series, "cloud_cover", day_hours or idx)
    cape = _vals(series, "cape", idx)
    gust = _vals(series, "wind_gusts_10m", idx)
    cape_max, gust_max = (max(cape) if cape else 0.0), (max(gust) if gust else 0.0)
    out = {
        "date": d.isoformat(),
        "weekday": pl.WEEKDAYS[d.weekday()],
        "day_of_month": d.day,
        "tmax": round(max(temp)) if temp else None,
        "tmin": round(min(temp)) if temp else None,
        "precip": round(precip, 1),
        "gust": round(gust_max) if gust else None,
        "icon": day_icon(
            precip,
            snow_mm / precip if precip > 0 else 0.0,
            sum(cloud) / len(cloud) if cloud else None,
            cape_max,
            gust_max,
        ),
        "storm": storm_level(cape_max, precip),
        "uncertain": k + 1 >= UNCERTAIN_FROM_DAY,
        "precip_chance": None,
    }
    out["icon_label"] = pl.ICONS[out["icon"]]
    if models:
        # share of models with >= 1 mm that day: shown instead of millimetres for uncertain days
        sums = [sum(_vals(m, "precipitation", idx)) for m in models.values() if _vals(m, "temperature_2m", idx)]
        if sums:
            out["precip_chance"] = round(100 * sum(s >= 1 for s in sums) / len(sums))
    return out


def model_horizon_days(model_series: dict, times: list[int]) -> int:
    t = [times[i] for i, v in enumerate(model_series.get("temperature_2m", [])) if v is not None]
    return round((t[-1] - t[0]) / 86400) if t else 0


def build(fc: dict, mode: str, cell: dict | None, now: int) -> dict:
    times: list[int] = fc["times"]
    models: dict = fc["models"]
    today = datetime.fromtimestamp(now, TZ).date()
    ranking = cell["accurate"] if cell else None
    rank_pos = {r["model"]: k + 1 for k, r in enumerate(ranking or [])}
    info: dict = {"mode": mode, "model": None, "texts": [], "blend": False}

    if mode == "optymistyczna":
        m = most_optimistic(models, times, today)
        if m:
            info["model"] = m
            info["texts"].append(pl.T["optimistic_intro"].format(model=pl.MODELS[m][0]))
            if m in rank_pos:
                info["texts"].append(pl.T["optimistic_rank"].format(n=rank_pos[m], m=len(rank_pos)))
    elif mode == "najmniej-trafna" and ranking:
        m = ranking[-1]["model"]
        if m in models:
            info["model"] = m
            info["texts"].append(pl.T["least_intro"].format(model=pl.MODELS[m][0]))
    elif mode == "najmniej-trafna":
        info["texts"].append(pl.T["least_none"])

    if info["model"]:
        series = models[info["model"]]
        h = model_horizon_days(series, times)
        if h < DAYS:
            info["texts"].append(pl.T["model_horizon"].format(model=pl.MODELS[info["model"]][0], d=h))
    else:
        info["blend"] = True
        weights = (cell or {}).get("blend", {}).get("temp")
        series = blend(models, times, now, weights)
        key = "blend_intro" if cell else "blend_equal"
        info["texts"] = [pl.T[key].format(n=len(models)), *([pl.T["blend_why"]] if cell else []), *info["texts"]]

    by_day = _day_indices(times)
    days = []
    for k in range(DAYS):
        d = date.fromordinal(today.toordinal() + k)
        idx = by_day.get(d, [])
        if idx and series.get("temperature_2m") and any(series["temperature_2m"][i] is not None for i in idx):
            days.append(day_summary(series, idx, times, d, k, models if info["blend"] else None))

    keep = (
        "temperature_2m",
        "apparent_temperature",
        "precipitation",
        "snowfall",
        "cloud_cover",
        "wind_speed_10m",
        "wind_gusts_10m",
        "wind_direction_10m",
    )
    hourly = {"time": times, **{v: series.get(v) for v in keep}}
    if info["blend"]:
        hourly |= {
            v: series.get(v)
            for v in ("temperature_2m_min", "temperature_2m_max", "precipitation_min", "precipitation_max")
        }
    return {
        **info,
        "days": days,
        "hourly": hourly,
        "ranking": ranking,
        "temp_source": cell.get("temp_source") if cell else None,
    }
