"""Spike: forecast horizon per model (Forecast API) and error correlation between models (cached Etap 0b data).

Answers SPEC §17 pt 3: which models end before 7 days, and which "models" are really the same model.
Usage: python spike/model_families.py
"""

import json
from datetime import timedelta
from itertools import combinations

import numpy as np
import requests

import weekly_skill as ws
from station_ranking import LAPSE, daily_from_hourly, load_coords, load_imgw

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"


def horizons() -> dict:
    out = {}
    for model in ws.MODELS:
        r = requests.get(
            FORECAST_URL,
            params={
                "latitude": 52.17,
                "longitude": 20.97,
                "hourly": "temperature_2m,precipitation",
                "models": model,
                "forecast_days": 16,
                "timezone": "UTC",
            },
            timeout=60,
        )
        r.raise_for_status()
        h = r.json()["hourly"]
        valid = [t for t, v in zip(h["time"], h["temperature_2m"]) if v is not None]
        out[model] = {"first": valid[0], "last": valid[-1], "hours": len(valid)}
    return out


def error_correlation() -> dict:
    stations = load_imgw()
    coords = load_coords()
    days = [ws.START + timedelta(days=i) for i in range((ws.END - ws.START).days + 1)]
    res = {}
    for lead in (1, 3, 5):
        errs = {m: {"tmax": [], "precip": []} for m in ws.MODELS}
        keys = []
        for code, st in stations.items():
            wmo = "12" + code[-3:]
            if wmo not in coords:
                continue
            lat, lon, elev = coords[wmo]
            series = {}
            for m in ws.MODELS:
                data = ws.fetch(m, lat, lon)  # cached
                if not data:
                    continue
                dly = daily_from_hourly(data, lead, ws.PRECIP_SHIFT)
                corr = (data["elevation"] - elev) * LAPSE
                series[m] = (dly, corr)
            for d in days:
                o = st["obs"].get(d)
                if not o or o["tmax"] is None or o["precip"] is None:
                    continue
                vals = {m: s[0].get(d) for m, s in series.items()}
                if len(vals) < len(ws.MODELS) or any(v is None or v["tmax"] is None or v["precip"] is None for v in vals.values()):
                    continue
                keys.append((code, d))
                for m, v in vals.items():
                    errs[m]["tmax"].append(v["tmax"] + series[m][1] - o["tmax"])
                    errs[m]["precip"].append(v["precip"] - o["precip"])
        if not keys:
            continue
        pairs = {}
        for a, b in combinations([m for m in ws.MODELS if errs[m]["tmax"]], 2):
            pairs[f"{a} ~ {b}"] = {
                k: round(float(np.corrcoef(errs[a][k], errs[b][k])[0, 1]), 3) for k in ("tmax", "precip")
            }
        res[f"lead{lead}"] = {"n": len(keys), "pairs": dict(sorted(pairs.items(), key=lambda kv: -kv[1]["tmax"]))}
    return res


def member_set_test() -> dict:
    """Equal-weight mean with all 6 models vs without ecmwf_ifs025 (same IFS model at coarser output)."""
    stations = load_imgw()
    coords = load_coords()
    days = [ws.START + timedelta(days=i) for i in range((ws.END - ws.START).days + 1)]
    sets = {"all6": ws.MODELS, "no_ifs025": [m for m in ws.MODELS if m != "ecmwf_ifs025"]}
    res = {}
    for lead in ws.LEADS:
        acc = {s: {"tmax": [], "tmin": [], "precip": [], "cont": ws.Cont()} for s in sets}
        for code, st in stations.items():
            wmo = "12" + code[-3:]
            if wmo not in coords:
                continue
            lat, lon, elev = coords[wmo]
            series = {}
            for m in ws.MODELS:
                data = ws.fetch(m, lat, lon)
                if data:
                    dly = daily_from_hourly(data, lead, ws.PRECIP_SHIFT)
                    if any(x["tmax"] is not None for x in dly.values()):
                        series[m] = (dly, (data["elevation"] - elev) * LAPSE)
            for d in days:
                o = st["obs"].get(d)
                if not o:
                    continue
                for s, members in sets.items():
                    mem = [m for m in members if m in series and series[m][0].get(d)]
                    for k in ("tmax", "tmin", "precip"):
                        v = [series[m][0][d][k] + (series[m][1] if k != "precip" else 0) for m in mem if series[m][0][d][k] is not None]
                        if o[k] is None or len(v) < 2:
                            continue
                        f = float(np.mean(v))
                        acc[s][k].append(abs(f - o[k]))
                        if k == "precip":
                            acc[s]["cont"].add(f, o[k], 1.0)
        res[lead] = {
            s: {k: round(float(np.mean(a[k])), 3) for k in ("tmax", "tmin", "precip")} | {"ets_1mm": a["cont"].ets()}
            for s, a in acc.items()
        }
    return res


def main() -> None:
    mst = member_set_test()
    print("Equal-weight mean, all 6 vs without ecmwf_ifs025:")
    for lead, x in mst.items():
        print(f"  lead {lead}: " + " | ".join(f"{s}: " + " ".join(f"{k}={v}" for k, v in y.items()) for s, y in x.items()))
    hz = horizons()
    print("Forecast API horizon (Warszawa):")
    for m, x in hz.items():
        print(f"  {m:24s} {x['hours']:4d} h  last={x['last']}")
    ec = error_correlation()
    for lead, x in ec.items():
        print(f"\nError correlation {lead} (n={x['n']}), top pairs:")
        for p, v in list(x["pairs"].items())[:8]:
            print(f"  {p:50s} tmax={v['tmax']:.2f} precip={v['precip']:.2f}")
    (ws.ROOT / "model_families_results.json").write_text(json.dumps({"horizons": hz, "error_corr": ec, "member_set_test": mst}, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
