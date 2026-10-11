"""Spike: how good are 1-7 day forecasts, which model is best at a week ahead, and does it beat climatology?

Also tests SPEC §17 decision (a): skill-weighted multi-model mean vs equal-weight mean.

Data: IMGW synop daily (Jul-Sep 2026) as truth, IMGW 2016-2025 for climatology,
Open-Meteo Previous Runs API leads 1..7 for temperature_2m and precipitation.

Usage: python spike/weekly_skill.py
"""

import csv
import io
import json
import math
import time
import zipfile
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import requests

from station_ranking import (
    END,
    LAPSE,
    PRECIP_THRESHOLD,
    START,
    URL,
    daily_from_hourly,
    haversine_km,
    load_coords,
    load_imgw,
    month_days,
)

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
CACHE = DATA / "openmeteo_weekly"
CACHE.mkdir(parents=True, exist_ok=True)
CLIM_DIR = DATA / "imgw_clim"
CLIM_DIR.mkdir(parents=True, exist_ok=True)

MODELS = ["ecmwf_ifs025", "ecmwf_aifs025_single", "ecmwf_ifs", "gfs_seamless", "icon_seamless", "meteofrance_seamless"]
LEADS = list(range(1, 8))
CLIM_YEARS = range(2016, 2026)
CLIM_HALF_WINDOW = 7  # days around the calendar date
PRECIP_SHIFT = 0  # IMGW SMDB(D) = 06 UTC D .. 06 UTC D+1 (established in Etap 0a)
HEAVY = 10.0  # mm/day, second precipitation threshold
KEYS = ("tmax", "tmin", "precip")


# ---------------------------------------------------------------- climatology


def load_climatology(codes: list[str]) -> dict:
    """{code: {date: obs}} for CLIM_YEARS, from per-station yearly IMGW zips (downloaded once)."""
    base = "https://danepubliczne.imgw.pl/data/dane_pomiarowo_obserwacyjne/dane_meteorologiczne/dobowe/synop"
    out: dict = defaultdict(dict)
    for year in CLIM_YEARS:
        for code in codes:
            short = code[-3:]
            path = CLIM_DIR / f"{year}_{short}_s.zip"
            if not path.exists():
                r = requests.get(f"{base}/{year}/{year}_{short}_s.zip", timeout=60)
                if r.status_code != 200:
                    continue
                path.write_bytes(r.content)
            with zipfile.ZipFile(path) as z:
                names = [n for n in z.namelist() if n.startswith("s_d_") and not n.startswith("s_d_t")]
                for n in names:
                    for row in csv.reader(io.StringIO(z.read(n).decode("cp1250"))):
                        if len(row) < 22:
                            continue
                        d = date(int(row[2]), int(row[3]), int(row[4]))

                        def val(i, si, zero9=False):
                            if row[si] == "8":
                                return None
                            if row[si] == "9" and zero9:
                                return 0.0
                            return float(row[i]) if row[i] else None

                        out[code][d] = {"tmax": val(5, 6), "tmin": val(7, 8), "precip": val(13, 14, True)}
    return out


def clim_forecast(clim: dict, code: str, d: date) -> dict:
    """MAE-optimal climatological forecast: median of all values within ±7 days of the date in CLIM_YEARS."""
    vals = defaultdict(list)
    for year in CLIM_YEARS:
        try:
            centre = d.replace(year=year)
        except ValueError:
            continue
        for k in range(-CLIM_HALF_WINDOW, CLIM_HALF_WINDOW + 1):
            o = clim.get(code, {}).get(centre + timedelta(days=k))
            if o:
                for key in KEYS:
                    if o[key] is not None:
                        vals[key].append(o[key])
    out = {k: (float(np.median(v)) if v else None) for k, v in ((k, vals[k]) for k in KEYS)}
    out["p_wet"] = float(np.mean([x >= PRECIP_THRESHOLD for x in vals["precip"]])) if vals["precip"] else None
    return out


def clim_week_precip(clim: dict, code: str, d0: date) -> float | None:
    """Median of historical 7-day precipitation sums starting within ±7 days of d0."""
    sums = []
    for year in CLIM_YEARS:
        try:
            centre = d0.replace(year=year)
        except ValueError:
            continue
        for k in range(-CLIM_HALF_WINDOW, CLIM_HALF_WINDOW + 1):
            s = [clim.get(code, {}).get(centre + timedelta(days=k + j), {}).get("precip") for j in range(7)]
            if all(x is not None for x in s):
                sums.append(sum(s))
    return float(np.median(sums)) if sums else None


# ---------------------------------------------------------------- forecasts


def fetch(model: str, lat: float, lon: float) -> dict | None:
    path = CACHE / f"{model}_{lat:.3f}_{lon:.3f}.json"
    if path.exists():
        data = json.loads(path.read_text(encoding="utf-8"))
        return data or None
    params = {
        "latitude": lat,
        "longitude": lon,
        "hourly": ",".join(f"{v}_previous_day{d}" for v in ("temperature_2m", "precipitation") for d in LEADS),
        "models": model,
        "start_date": (START - timedelta(days=1)).isoformat(),
        "end_date": (END + timedelta(days=1)).isoformat(),
        "timezone": "UTC",
        "cell_selection": "nearest",
        "elevation": "nan",
    }
    for attempt in range(30):
        r = requests.get(URL, params=params, timeout=120)
        if r.status_code == 429:
            # hourly limit (5000 weighted calls/h) resets within the hour
            print(f"  429 ({r.json().get('reason', '')}), waiting 120 s", flush=True)
            time.sleep(120)
            continue
        if r.status_code == 400:
            path.write_text("{}", encoding="utf-8")
            print(f"  {model}: 400 {r.text[:120]}")
            return None
        r.raise_for_status()
        data = r.json()
        path.write_text(json.dumps(data), encoding="utf-8")
        time.sleep(0.4)
        return data
    raise RuntimeError("rate limited")


# ---------------------------------------------------------------- scoring helpers


class Cont:
    """2x2 contingency counts pooled over stations."""

    def __init__(self):
        self.h = self.m = self.f = self.c = 0

    def add(self, fc: float, ob: float, thr: float) -> None:
        if fc >= thr and ob >= thr:
            self.h += 1
        elif fc >= thr:
            self.f += 1
        elif ob >= thr:
            self.m += 1
        else:
            self.c += 1

    def ets(self) -> float | None:
        n = self.h + self.m + self.f + self.c
        if n == 0 or self.h + self.m == 0:
            return None
        r = (self.h + self.f) * (self.h + self.m) / n
        den = self.h + self.f + self.m - r
        return round((self.h - r) / den, 3) if den else None

    def pod_far(self) -> tuple:
        pod = self.h / (self.h + self.m) if self.h + self.m else None
        far = self.f / (self.h + self.f) if self.h + self.f else None
        return (round(pod, 3) if pod is not None else None, round(far, 3) if far is not None else None)


def main() -> None:
    stations = load_imgw()
    coords = load_coords()
    meta = {}
    for code, st in stations.items():
        wmo = "12" + code[-3:]
        if wmo in coords:
            meta[code] = (st["name"], *coords[wmo])
    days = [START + timedelta(days=i) for i in range((END - START).days + 1)]
    print(f"stations: {len(meta)}, days: {len(days)}")

    print("climatology download/parse...")
    clim = load_climatology(list(meta))
    clim_fc = {code: {d: clim_forecast(clim, code, d) for d in days} for code in meta}

    print("forecasts...")
    # fc[code][model][lead][date] = {"tmax","tmin","precip"} (elevation-corrected)
    fc: dict = defaultdict(lambda: defaultdict(dict))
    available = set()
    for code, (name, lat, lon, elev) in meta.items():
        for model in MODELS:
            data = fetch(model, lat, lon)
            if not data:
                continue
            corr = (data["elevation"] - elev) * LAPSE if not math.isnan(elev) else 0.0
            for lead in LEADS:
                dly = daily_from_hourly(data, lead, PRECIP_SHIFT)
                if not any(x["tmax"] is not None for x in dly.values()):
                    continue
                available.add((model, lead))
                fc[code][model][lead] = {
                    d: {k: (x[k] + corr if k != "precip" and x[k] is not None else x[k]) for k in KEYS}
                    for d, x in dly.items()
                }
    models = [m for m in MODELS if any((m, ld) in available for ld in LEADS)]
    print("models with data:", models)

    # Multi-model means: "mean_ecmwf_gfs" (models with all 7 leads) and "mean_all" (whatever is available per lead)
    full_range = [m for m in models if all((m, ld) in available for ld in LEADS)]
    for code in meta:
        for lead in LEADS:
            for name, members in (("mean_7d_models", full_range), ("mean_all", models)):
                mem = [m for m in members if lead in fc[code].get(m, {})]
                if len(mem) < 2:
                    continue
                fc[code][name][lead] = {
                    d: {
                        k: (
                            None
                            if any(fc[code][m][lead][d][k] is None for m in mem)
                            else float(np.mean([fc[code][m][lead][d][k] for m in mem]))
                        )
                        for k in KEYS
                    }
                    for d in days
                }
    all_names = models + ["mean_7d_models", "mean_all"]

    # -------- 1. Skill by lead (pooled over stations and Jul-Sep)
    table = {}
    for name in all_names + ["climatology", "persistence"]:
        for lead in LEADS:
            err = defaultdict(list)
            cont1, cont10 = Cont(), Cont()
            for code in meta:
                obs = stations[code]["obs"]
                for d in days:
                    o = obs.get(d)
                    if not o:
                        continue
                    if name == "climatology":
                        f = clim_fc[code][d]
                    elif name == "persistence":
                        f = obs.get(d - timedelta(days=lead))
                    else:
                        f = fc[code].get(name, {}).get(lead, {}).get(d)
                    if not f:
                        continue
                    for k in KEYS:
                        if o[k] is not None and f.get(k) is not None:
                            err[k].append(f[k] - o[k])
                    if o["precip"] is not None and f.get("precip") is not None:
                        cont1.add(f["precip"], o["precip"], PRECIP_THRESHOLD)
                        cont10.add(f["precip"], o["precip"], HEAVY)
            if not err["tmax"]:
                continue
            table[(name, lead)] = {
                "tmax_mae": round(float(np.mean(np.abs(err["tmax"]))), 3),
                "tmin_mae": round(float(np.mean(np.abs(err["tmin"]))), 3),
                "tmax_bias": round(float(np.mean(err["tmax"])), 3),
                "precip_mae": round(float(np.mean(np.abs(err["precip"]))), 3),
                "ets_1mm": cont1.ets(),
                "pod_far_1mm": cont1.pod_far(),
                "ets_10mm": cont10.ets(),
                "pod_far_10mm": cont10.pod_far(),
                "n": len(err["tmax"]),
            }

    # -------- 2. Week-ahead totals: forecast "issued" on day D0 for D0+1..D0+7
    week = defaultdict(lambda: defaultdict(list))
    for code in meta:
        obs = stations[code]["obs"]
        d0 = START
        while d0 + timedelta(days=7) <= END:
            wdays = [d0 + timedelta(days=k) for k in LEADS]
            o_p = [obs.get(d, {}).get("precip") for d in wdays]
            o_t = [obs.get(d, {}).get("tmax") for d in wdays]
            if all(x is not None for x in o_p + o_t):
                o_sum, o_tmean = sum(o_p), float(np.mean(o_t))
                cl = clim_week_precip(clim, code, wdays[0])
                cl_t = [clim_fc[code][d]["tmax"] for d in wdays]
                if cl is not None and all(x is not None for x in cl_t):
                    week["climatology"]["precip_sum_ae"].append(abs(cl - o_sum))
                    week["climatology"]["tmax_mean_ae"].append(abs(float(np.mean(cl_t)) - o_tmean))
                for name in all_names:
                    vals = [fc[code].get(name, {}).get(k, {}).get(d) for k, d in zip(LEADS, wdays)]
                    if any(v is None or v["precip"] is None or v["tmax"] is None for v in vals):
                        continue
                    week[name]["precip_sum_ae"].append(abs(sum(v["precip"] for v in vals) - o_sum))
                    week[name]["tmax_mean_ae"].append(abs(float(np.mean([v["tmax"] for v in vals])) - o_tmean))
            d0 += timedelta(days=1)
    week_table = {n: {k: round(float(np.mean(v)), 3) for k, v in d.items()} | {"n": len(d["tmax_mean_ae"])} for n, d in week.items()}

    # -------- 3. Who wins at day 7 per station and month (stability)
    winners = defaultdict(dict)
    for code in meta:
        obs = stations[code]["obs"]
        for mon in (7, 8, 9):
            mdays = month_days(mon)
            sc = {}
            for m in full_range:
                e = [
                    abs(fc[code][m][7][d]["tmax"] - obs[d]["tmax"])
                    for d in mdays
                    if d in obs and obs[d]["tmax"] is not None and fc[code][m][7].get(d, {}).get("tmax") is not None
                ]
                if len(e) >= 20:
                    sc[m] = float(np.mean(e))
            if sc:
                winners[code][mon] = min(sc, key=sc.get)
    win_counts = {mon: dict(sorted(((m, sum(1 for c in winners if winners[c].get(mon) == m)) for m in full_range), key=lambda x: -x[1])) for mon in (7, 8, 9)}
    same = [winners[c][a] == winners[c][b] for c in winners for a, b in ((7, 8), (8, 9)) if a in winners[c] and b in winners[c]]

    # -------- 4. Decision (a): skill-weighted mean vs equal mean, weights from previous month
    weighting = weighting_test(meta, stations, fc, models)

    result = {
        "period": f"{START}..{END}",
        "stations": len(meta),
        "models": models,
        "models_all_7_leads": full_range,
        "by_lead": {f"{n}|{ld}": v for (n, ld), v in table.items()},
        "week_ahead": week_table,
        "day7_tmax_winners_per_month": win_counts,
        "day7_same_winner_next_month": round(float(np.mean(same)), 3) if same else None,
        "weighting_test": weighting,
    }
    (ROOT / "weekly_skill_results.json").write_text(json.dumps(result, indent=1, ensure_ascii=False), encoding="utf-8")
    print_report(result, all_names)


def weighting_test(meta, stations, fc, models) -> dict:
    """For target months Aug and Sep and each lead, compare (on target-month errors):
    equal mean of available models vs inverse-MSE weights from the previous month (local station, and
    regional = stations within 150 km pooled). Weights per variable group: temperature (tmax+tmin) and precip.
    """
    out = defaultdict(lambda: defaultdict(list))
    conts = defaultdict(Cont)
    for target, prev in ((8, 7), (9, 8)):
        tdays, pdays = month_days(target), month_days(prev)
        for lead in LEADS:
            # previous-month MSE per station/model/group
            mse = {}
            for code in meta:
                obs = stations[code]["obs"]
                for m in models:
                    series = fc[code].get(m, {}).get(lead)
                    if not series:
                        continue
                    for grp, keys in (("t", ("tmax", "tmin")), ("p", ("precip",))):
                        e = [
                            (series[d][k] - obs[d][k]) ** 2
                            for d in pdays
                            for k in keys
                            if d in obs and obs[d][k] is not None and series.get(d, {}).get(k) is not None
                        ]
                        if len(e) >= 20:
                            mse[(code, m, grp)] = float(np.mean(e))
            for code, (name, lat, lon, elev) in meta.items():
                obs = stations[code]["obs"]
                mem = [m for m in models if fc[code].get(m, {}).get(lead)]
                if len(mem) < 2:
                    continue
                neigh = [c for c, mm in meta.items() if haversine_km((lat, lon), mm[1:3]) <= 150]
                weights = {}
                for grp in ("t", "p"):
                    loc = {m: mse.get((code, m, grp)) for m in mem}
                    reg = {m: [mse[(c, m, grp)] for c in neigh if (c, m, grp) in mse] for m in mem}
                    if all(v for v in loc.values()):
                        weights[("local", grp)] = {m: 1 / v for m, v in loc.items()}
                    if all(reg.values()):
                        weights[("regional", grp)] = {m: 1 / float(np.mean(v)) for m, v in reg.items()}
                    weights[("equal", grp)] = {m: 1.0 for m in mem}
                    # best single model by previous-month regional MSE ("pick the winner", variant c)
                    if all(reg.values()):
                        best = min(reg, key=lambda m: float(np.mean(reg[m])))
                        weights[("regional_winner", grp)] = {m: (1.0 if m == best else 0.0) for m in mem}
                for d in tdays:
                    o = obs.get(d)
                    if not o:
                        continue
                    vals = {m: fc[code][m][lead].get(d) for m in mem}
                    if any(v is None for v in vals.values()):
                        continue
                    for strat in ("equal", "local", "regional", "regional_winner"):
                        for grp, keys in (("t", ("tmax", "tmin")), ("p", ("precip",))):
                            w = weights.get((strat, grp))
                            if not w:
                                continue
                            tot = sum(w.values())
                            for k in keys:
                                if o[k] is None or any(vals[m][k] is None for m in mem):
                                    continue
                                f = sum(w[m] * vals[m][k] for m in mem) / tot
                                out[(lead, strat)][f"{k}_ae"].append(abs(f - o[k]))
                                if k == "precip":
                                    conts[(lead, strat)].add(f, o[k], PRECIP_THRESHOLD)
    res = {}
    for (lead, strat), d in sorted(out.items()):
        res[f"{lead}|{strat}"] = {k: round(float(np.mean(v)), 3) for k, v in d.items()} | {
            "ets_1mm": conts[(lead, strat)].ets(),
            "n": len(d["tmax_ae"]),
        }
    return res


def print_report(r: dict, names: list[str]) -> None:
    print("\n=== Skill by lead (pooled, Jul-Sep 2026) ===")
    print(f"{'model':24s} {'lead':>4s} {'TmaxMAE':>8s} {'TminMAE':>8s} {'PrMAE':>6s} {'ETS1':>6s} {'ETS10':>6s}")
    for name in names + ["climatology", "persistence"]:
        for ld in LEADS:
            x = r["by_lead"].get(f"{name}|{ld}")
            if x:
                print(
                    f"{name:24s} {ld:4d} {x['tmax_mae']:8.2f} {x['tmin_mae']:8.2f} {x['precip_mae']:6.2f} "
                    f"{x['ets_1mm'] if x['ets_1mm'] is not None else '-':>6} {x['ets_10mm'] if x['ets_10mm'] is not None else '-':>6}"
                )
    print("\n=== Week-ahead totals (forecast issued D0 for D0+1..D0+7) ===")
    for n, x in sorted(r["week_ahead"].items(), key=lambda kv: kv[1]["precip_sum_ae"]):
        print(f"  {n:24s} weekly precip sum MAE={x['precip_sum_ae']:.2f} mm  weekly mean Tmax MAE={x['tmax_mean_ae']:.2f}  n={x['n']}")
    print("\n=== Day-7 Tmax winners per month ===", r["day7_tmax_winners_per_month"])
    print("same winner next month:", r["day7_same_winner_next_month"])
    print("\n=== Weighting test (target Aug+Sep) ===")
    for k, v in r["weighting_test"].items():
        print(f"  {k:22s} " + " ".join(f"{a}={b}" for a, b in v.items()))


if __name__ == "__main__":
    main()
