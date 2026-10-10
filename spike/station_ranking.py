"""Spike (Etap 0a): does a per-location model ranking make sense?

Compares 24/48/72 h forecasts from Open-Meteo Previous Runs API with IMGW synop daily
observations (Tmax, Tmin, precipitation, sunshine duration) at all synop stations,
for July-September 2026, and checks how stable the per-station winner is between months.

Usage: python spike/station_ranking.py
"""

import csv
import io
import json
import math
import os
import time
import zipfile
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

import numpy as np
import requests

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
CACHE = DATA / "openmeteo"
CACHE.mkdir(parents=True, exist_ok=True)

START, END = date(2026, 7, 1), date(2026, 9, 30)
MONTHS = ["07", "08", "09"]
MODELS = [
    "ecmwf_ifs025",
    "ecmwf_aifs025_single",
    "icon_seamless",
    "gfs_seamless",
    "meteofrance_seamless",
]
LEADS = [1, 2, 3]
VARS = ["temperature_2m", "precipitation", "sunshine_duration"]
LAPSE = 0.0065  # K per m
PRECIP_THRESHOLD = 1.0  # mm/day
# VARIANT=nosun drops the sunshine proxy (it is partly derived by Open-Meteo, not a native output of every model)
VARIANT = os.environ.get("VARIANT", "full")
WEIGHTS = {"sun": 0.4, "precip": 0.4, "temp": 0.2} if VARIANT == "full" else {"sun": 0.0, "precip": 0.6, "temp": 0.4}
URL = "https://previous-runs-api.open-meteo.com/v1/forecast"


# ---------------------------------------------------------------- observations


def load_imgw() -> dict:
    """Return {station_code: {"name": str, "obs": {date: dict}}} from IMGW s_d monthly zips."""
    stations: dict = {}
    for m in MONTHS:
        with zipfile.ZipFile(DATA / "imgw" / f"2026_{m}_s.zip") as z:
            raw = z.read(f"s_d_{m}_2026.csv").decode("cp1250")
        for row in csv.reader(io.StringIO(raw)):
            if len(row) < 22:
                continue
            code, name = row[0], row[1]
            d = date(int(row[2]), int(row[3]), int(row[4]))

            def val(i: int, status_i: int, zero_if_9: bool = False) -> float | None:
                status = row[status_i]
                if status == "8":
                    return None
                if status == "9" and zero_if_9:
                    return 0.0
                return float(row[i]) if row[i] else None

            obs = {
                "tmax": val(5, 6),
                "tmin": val(7, 8),
                "precip": val(13, 14, zero_if_9=True),
                "sun": val(20, 21, zero_if_9=True),
            }
            stations.setdefault(code, {"name": name, "obs": {}})["obs"][d] = obs
    return stations


def load_coords() -> dict:
    """WMO id (5 digits) -> (lat, lon, elev) from NOAA ISD station history."""
    coords = {}
    with open(DATA / "isd-history.csv", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row["CTRY"] != "PL" or not row["LAT"]:
                continue
            wmo = row["USAF"][:5]
            end = row["END"]
            # keep the most recently active record per WMO id
            if wmo not in coords or end > coords[wmo][3]:
                coords[wmo] = (float(row["LAT"]), float(row["LON"]), float(row["ELEV(M)"] or "nan"), end)
    return {k: v[:3] for k, v in coords.items()}


# ---------------------------------------------------------------- forecasts


def fetch(model: str, lat: float, lon: float) -> dict | None:
    path = CACHE / f"{model}_{lat:.3f}_{lon:.3f}.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    params = {
        "latitude": lat,
        "longitude": lon,
        "hourly": ",".join(f"{v}_previous_day{d}" for v in VARS for d in LEADS),
        "models": model,
        # one extra day on both sides for 06-06 UTC windows
        "start_date": (START - timedelta(days=1)).isoformat(),
        "end_date": (END + timedelta(days=1)).isoformat(),
        "timezone": "UTC",
        "cell_selection": "nearest",
        "elevation": "nan",
    }
    for attempt in range(5):
        r = requests.get(URL, params=params, timeout=120)
        if r.status_code == 429:
            time.sleep(30 * (attempt + 1))
            continue
        if r.status_code == 400:
            return None
        r.raise_for_status()
        data = r.json()
        path.write_text(json.dumps(data), encoding="utf-8")
        time.sleep(0.5)
        return data
    raise RuntimeError(f"rate limited: {model} {lat} {lon}")


def daily_from_hourly(data: dict, lead: int, precip_shift: int) -> dict:
    """Aggregate hourly forecast for one lead into IMGW-like daily values.

    Tmax: max over 06-18 UTC of day D; Tmin: min over 18 UTC D-1 .. 06 UTC D (synop convention).
    Precip: 24 h sum 06 UTC (D+shift) .. 06 UTC (D+shift+1); shift is chosen empirically.
    Sunshine: calendar-day sum (UTC), hours.
    """
    h = data["hourly"]
    times = [datetime.fromisoformat(t) for t in h["time"]]
    idx = {t: i for i, t in enumerate(times)}
    temp = h[f"temperature_2m_previous_day{lead}"]
    prec = h[f"precipitation_previous_day{lead}"]
    sun = h[f"sunshine_duration_previous_day{lead}"]

    def window(series, start: datetime, hours: int):
        vals = [series[idx[start + timedelta(hours=k)]] for k in range(hours) if (start + timedelta(hours=k)) in idx]
        if len(vals) < hours or any(v is None for v in vals):
            return None
        return vals

    out = {}
    d = START
    while d <= END:
        day0 = datetime(d.year, d.month, d.day)
        tx = window(temp, day0 + timedelta(hours=6), 13)
        tn = window(temp, day0 - timedelta(hours=6), 13)
        pr = window(prec, day0 + timedelta(days=precip_shift, hours=7), 24)  # hourly sums are for the preceding hour
        su = window(sun, day0 + timedelta(hours=1), 24)
        out[d] = {
            "tmax": max(tx) if tx else None,
            "tmin": min(tn) if tn else None,
            "precip": sum(pr) if pr else None,
            "sun": sum(su) / 3600 if su else None,
        }
        d += timedelta(days=1)
    return out


# ---------------------------------------------------------------- metrics


def ets(fc: list[float], ob: list[float], thr: float) -> float | None:
    hits = sum(1 for f, o in zip(fc, ob) if f >= thr and o >= thr)
    fa = sum(1 for f, o in zip(fc, ob) if f >= thr and o < thr)
    miss = sum(1 for f, o in zip(fc, ob) if f < thr and o >= thr)
    n = len(fc)
    if n == 0 or hits + miss == 0:
        return None
    random_hits = (hits + fa) * (hits + miss) / n
    denom = hits + fa + miss - random_hits
    return (hits - random_hits) / denom if denom else None


def metrics(fc_daily: dict, obs: dict, days: list[date], temp_corr: float) -> dict | None:
    pairs = defaultdict(lambda: ([], []))
    for d in days:
        o, f = obs.get(d), fc_daily.get(d)
        if not o or not f:
            continue
        for k in ("tmax", "tmin", "precip", "sun"):
            if o[k] is not None and f[k] is not None:
                fv = f[k] + temp_corr if k in ("tmax", "tmin") else f[k]
                pairs[k][0].append(fv)
                pairs[k][1].append(o[k])
    if min((len(pairs[k][0]) for k in ("tmax", "tmin", "precip")), default=0) < 20:
        return None
    mae = {k: float(np.mean(np.abs(np.array(f) - np.array(o)))) for k, (f, o) in pairs.items() if f}
    bias = {k: float(np.mean(np.array(f) - np.array(o))) for k, (f, o) in pairs.items() if f}
    return {
        "temp_mae": (mae["tmax"] + mae["tmin"]) / 2,
        "tmax_bias": bias["tmax"],
        "tmin_bias": bias["tmin"],
        "precip_mae": mae["precip"],
        "precip_bias": bias["precip"],
        "precip_ets": ets(*pairs["precip"], PRECIP_THRESHOLD),
        "sun_mae": mae.get("sun"),
        "sun_bias": bias.get("sun"),
        "n": len(pairs["tmax"][0]),
    }


def norm(values: dict, higher_better: bool) -> dict:
    """Min-max normalise {model: value} to 0..1, 1 = best. Missing -> excluded."""
    vals = {m: v for m, v in values.items() if v is not None}
    if not vals:
        return {}
    lo, hi = min(vals.values()), max(vals.values())
    if hi == lo:
        return {m: 1.0 for m in vals}
    return {m: ((v - lo) / (hi - lo) if higher_better else (hi - v) / (hi - lo)) for m, v in vals.items()}


def score(per_model: dict) -> dict:
    """Combined 0-100 score per model, following SPEC §8.4 with sunshine as the cloud proxy."""
    n_sun = norm({m: x["sun_mae"] for m, x in per_model.items()}, higher_better=False)
    n_ets = norm({m: x["precip_ets"] for m, x in per_model.items()}, higher_better=True)
    n_pmae = norm({m: x["precip_mae"] for m, x in per_model.items()}, higher_better=False)
    n_temp = norm({m: x["temp_mae"] for m, x in per_model.items()}, higher_better=False)
    out = {}
    for m in per_model:
        precip = 0.7 * n_ets.get(m, 0) + 0.3 * n_pmae.get(m, 0) if m in n_ets else n_pmae.get(m, 0)
        out[m] = round(
            100 * (WEIGHTS["sun"] * n_sun.get(m, 0) + WEIGHTS["precip"] * precip + WEIGHTS["temp"] * n_temp.get(m, 0))
        )
    return out


# ---------------------------------------------------------------- main


def month_days(month: int) -> list[date]:
    d, out = date(2026, month, 1), []
    while d.month == month:
        out.append(d)
        d += timedelta(days=1)
    return out


def main() -> None:
    stations = load_imgw()
    coords = load_coords()
    print(f"IMGW stations: {len(stations)}")

    # Station metadata
    meta = {}
    for code, st in stations.items():
        wmo = "12" + code[-3:]
        if wmo in coords:
            meta[code] = (st["name"], *coords[wmo])
        else:
            print(f"  no coords for {code} {st['name']}")
    print(f"with coords: {len(meta)}")

    # Fetch forecasts
    fc_raw: dict = {}
    n_req = 0
    for code, (name, lat, lon, elev) in meta.items():
        for model in MODELS:
            path = CACHE / f"{model}_{lat:.3f}_{lon:.3f}.json"
            if not path.exists():
                n_req += 1
            fc_raw[(code, model)] = fetch(model, lat, lon)
    print(f"new API requests: {n_req}")

    # Pick the precipitation alignment empirically (IMGW daily sum: which 06-06 window?)
    corr = {}
    for shift in (-1, 0):
        f_all, o_all = [], []
        for code in meta:
            data = fc_raw[(code, "ecmwf_ifs025")]
            if not data:
                continue
            dly = daily_from_hourly(data, 1, shift)
            for d, o in stations[code]["obs"].items():
                if o["precip"] is not None and dly.get(d) and dly[d]["precip"] is not None:
                    f_all.append(dly[d]["precip"])
                    o_all.append(o["precip"])
        corr[shift] = float(np.corrcoef(f_all, o_all)[0, 1])
    shift = max(corr, key=corr.get)
    print(f"precip alignment correlation: {corr} -> using shift {shift}")

    # Daily aggregates and metrics
    results = {}  # (code, window, lead) -> {model: metrics}
    reference = {}  # same, for the multi-model mean
    windows = {"07": month_days(7), "08": month_days(8), "09": month_days(9)}
    for code, (name, lat, lon, elev) in meta.items():
        for lead in LEADS:
            dlys = {}
            for model in MODELS:
                data = fc_raw[(code, model)]
                if not data:
                    continue
                temp_corr = (data["elevation"] - elev) * LAPSE if not math.isnan(elev) else 0.0
                dly = daily_from_hourly(data, lead, shift)
                # apply the elevation correction here so the multi-model mean below uses corrected values
                dlys[model] = {
                    d: {k: (v + temp_corr if k in ("tmax", "tmin") and v is not None else v) for k, v in x.items()}
                    for d, x in dly.items()
                }
            # Multi-model mean as a reference "model" (not ranked against the others)
            if len(dlys) == len(MODELS):
                dlys["mean_all"] = {
                    d: {
                        k: (None if any(dlys[m][d][k] is None for m in MODELS) else float(np.mean([dlys[m][d][k] for m in MODELS])))
                        for k in ("tmax", "tmin", "precip", "sun")
                    }
                    for d in dlys[MODELS[0]]
                }
            for model, dly in dlys.items():
                for wname, wdays in windows.items():
                    m = metrics(dly, stations[code]["obs"], wdays, 0.0)
                    if m:
                        key = (code, wname, lead)
                        target = results if model != "mean_all" else reference
                        target.setdefault(key, {})[model] = m

    # Lead-averaged scores per station and window (SPEC: leads 24/48/72 averaged)
    scores = defaultdict(dict)  # (code, window) -> {model: score}
    for code in meta:
        for wname in windows:
            acc = defaultdict(list)
            for lead in LEADS:
                per_model = results.get((code, wname, lead), {})
                if len(per_model) < 3:
                    continue
                for m, s in score(per_model).items():
                    acc[m].append(s)
            if acc:
                scores[(code, wname)] = {m: float(np.mean(v)) for m, v in acc.items() if len(v) == len(LEADS)}

    summary = build_summary(meta, scores, results, windows, corr, shift)
    summary["selection_test"] = selection_test(meta, scores, results)
    # Raw metrics of the multi-model mean, same averaging as selection_test (lead-averaged, per target month)
    for target in ("08", "09"):
        acc = defaultdict(list)
        for code in meta:
            vals = [reference.get((code, target, ld), {}).get("mean_all") for ld in LEADS]
            if any(v is None for v in vals):
                continue
            acc["temp_mae"].append(np.mean([v["temp_mae"] for v in vals]))
            acc["precip_mae"].append(np.mean([v["precip_mae"] for v in vals]))
            e = [v["precip_ets"] for v in vals if v["precip_ets"] is not None]
            if e:
                acc["precip_ets"].append(np.mean(e))
        summary["selection_test"][f"{target}|mean_all_models"] = {k: round(float(np.mean(v)), 3) for k, v in acc.items()} | {
            "n": len(acc["temp_mae"])
        }
    (ROOT / f"station_ranking_results_{VARIANT}.json").write_text(json.dumps(summary, indent=1, ensure_ascii=False), encoding="utf-8")
    print_summary(summary)


def build_summary(meta, scores, results, windows, corr, shift) -> dict:
    wins = {w: defaultdict(int) for w in windows}
    mean_score = {w: defaultdict(list) for w in windows}
    per_station = {}
    for code, (name, lat, lon, elev) in meta.items():
        row = {"name": name, "lat": lat, "lon": lon, "elev": elev, "windows": {}}
        for w in windows:
            sc = scores.get((code, w))
            if not sc:
                continue
            ranking = sorted(sc, key=sc.get, reverse=True)
            wins[w][ranking[0]] += 1
            for m, s in sc.items():
                mean_score[w][m].append(s)
            row["windows"][w] = {"ranking": ranking, "scores": {m: round(s, 1) for m, s in sc.items()}}
        per_station[code] = row

    # Stability: same winner in consecutive months; Spearman rank correlation between months
    same_winner, rank_corr = [], []
    for row in per_station.values():
        ws = row["windows"]
        for a, b in (("07", "08"), ("08", "09")):
            if a in ws and b in ws:
                same_winner.append(ws[a]["ranking"][0] == ws[b]["ranking"][0])
                common = [m for m in ws[a]["ranking"] if m in ws[b]["ranking"]]
                if len(common) >= 3:
                    ra = [ws[a]["ranking"].index(m) for m in common]
                    rb = [ws[b]["ranking"].index(m) for m in common]
                    rank_corr.append(float(np.corrcoef(ra, rb)[0, 1]))

    # Raw metric means per model (September, lead 1 and 3) for context
    raw = {}
    for lead in (1, 3):
        agg = defaultdict(lambda: defaultdict(list))
        for (code, w, ld), per_model in results.items():
            if w != "09" or ld != lead:
                continue
            for m, x in per_model.items():
                for k in ("temp_mae", "tmax_bias", "tmin_bias", "precip_mae", "precip_bias", "precip_ets", "sun_mae", "sun_bias"):
                    if x[k] is not None:
                        agg[m][k].append(x[k])
        raw[f"lead{lead}"] = {m: {k: round(float(np.mean(v)), 3) for k, v in d.items()} for m, d in agg.items()}

    return {
        "period": f"{START}..{END}",
        "models": MODELS,
        "precip_alignment": {"corr": corr, "shift": shift},
        "stations": len(per_station),
        "wins_per_month": {w: dict(v) for w, v in wins.items()},
        "mean_score_per_month": {w: {m: round(float(np.mean(v)), 1) for m, v in d.items()} for w, d in mean_score.items()},
        "stability": {
            "same_winner_next_month": round(float(np.mean(same_winner)), 3) if same_winner else None,
            "pairs": len(same_winner),
            "mean_rank_corr_next_month": round(float(np.nanmean(rank_corr)), 3) if rank_corr else None,
            "chance_same_winner": round(1 / len(MODELS), 3),
        },
        "raw_metrics_sep": raw,
        "per_station": per_station,
    }


def haversine_km(a: tuple, b: tuple) -> float:
    la1, lo1, la2, lo2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 6371 * 2 * math.asin(math.sqrt(h))


def selection_test(meta, scores, results) -> dict:
    """The product question: does picking last month's local winner beat always using one fixed model?

    For target months Aug and Sep, choose a model per station using the previous month(s), then measure
    the chosen model's raw errors in the target month (lead-averaged): temp MAE, precip MAE, precip ETS.
    Strategies: fixed model; local winner (prev month); regional winner (mean score of stations <= 150 km,
    prev month); local winner over 2 previous months (Sep only); oracle (best in target month, upper bound).
    """

    def raw(code, month, model):
        vals = [results.get((code, month, ld), {}).get(model) for ld in LEADS]
        if any(v is None for v in vals):
            return None
        out = {k: float(np.mean([v[k] for v in vals])) for k in ("temp_mae", "precip_mae")}
        e = [v["precip_ets"] for v in vals if v["precip_ets"] is not None]
        out["precip_ets"] = float(np.mean(e)) if e else None
        return out

    def best(sc: dict | None):
        return max(sc, key=sc.get) if sc else None

    strategies = defaultdict(lambda: defaultdict(list))
    for target, prev in (("08", ["07"]), ("09", ["08"]), ("09", ["07", "08"])):
        two = len(prev) == 2
        for code, (name, lat, lon, elev) in meta.items():
            target_scores = scores.get((code, target))
            if not target_scores:
                continue
            choices = {}
            if not two:
                for m in MODELS:
                    choices[f"fixed:{m}"] = m
                choices["local_prev_month"] = best(scores.get((code, prev[0])))
                neigh = [c for c, mm in meta.items() if haversine_km((lat, lon), mm[1:3]) <= 150]
                reg = defaultdict(list)
                for c in neigh:
                    for m, s in (scores.get((c, prev[0])) or {}).items():
                        reg[m].append(s)
                choices["regional_150km_prev_month"] = best({m: float(np.mean(v)) for m, v in reg.items()})
                choices["oracle_target_month"] = best(target_scores)
            else:
                acc = defaultdict(list)
                for p in prev:
                    for m, s in (scores.get((code, p)) or {}).items():
                        acc[m].append(s)
                choices["local_prev_2_months"] = best({m: float(np.mean(v)) for m, v in acc.items() if len(v) == 2})
            for strat, model in choices.items():
                if model is None:
                    continue
                r = raw(code, target, model)
                if r is None:
                    continue
                strategies[(target, strat)]["temp_mae"].append(r["temp_mae"])
                strategies[(target, strat)]["precip_mae"].append(r["precip_mae"])
                if r["precip_ets"] is not None:
                    strategies[(target, strat)]["precip_ets"].append(r["precip_ets"])
                strategies[(target, strat)]["score"].append(target_scores.get(model, 0.0))
    return {
        f"{t}|{s}": {k: round(float(np.mean(v)), 3) for k, v in d.items()} | {"n": len(d["score"])}
        for (t, s), d in sorted(strategies.items())
    }


def print_summary(s: dict) -> None:
    print("\nSelection test (target month | strategy -> mean target-month metrics of chosen model):")
    for k, v in s["selection_test"].items():
        print(f"  {k:45s} " + " ".join(f"{a}={b}" for a, b in v.items()))
    print("\nWins per month (station count where model ranks 1st):")
    for w, d in s["wins_per_month"].items():
        print(f"  {w}: " + ", ".join(f"{m}={n}" for m, n in sorted(d.items(), key=lambda x: -x[1])))
    print("\nMean score per month:")
    for w, d in s["mean_score_per_month"].items():
        print(f"  {w}: " + ", ".join(f"{m}={v}" for m, v in sorted(d.items(), key=lambda x: -x[1])))
    print("\nStability:", s["stability"])
    print("\nRaw metrics, September:")
    for lead, d in s["raw_metrics_sep"].items():
        print(f"  {lead}")
        for m, x in d.items():
            print(f"    {m:24s} " + " ".join(f"{k}={v}" for k, v in x.items()))


if __name__ == "__main__":
    main()
