"""Daily verification components (SPEC §8.8): sums and counts, never finished metrics, so that any window, lead set
or area (v1.1) can be aggregated later without re-verifying.

Cells (satellite truth):   cell_id, model, lead_day, date, var in {precip, cloud}, n, sum_err, sum_abs, sum_sq,
                           hits, misses, false_alarms, correct_negatives (precip >= 1 mm), class_hits (cloud classes)
Stations (IMGW truth):     station_id, model, lead_day, date, var in {tmax, tmin}, n, sum_err, sum_abs, sum_sq
err = forecast - observation.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from pipeline.verify import config as cfg

COUNT_COLS = ["n", "sum_err", "sum_abs", "sum_sq", "hits", "misses", "false_alarms", "correct_negatives", "class_hits"]


def _errors(err: pd.Series) -> dict[str, pd.Series]:
    return {"n": pd.Series(1, index=err.index), "sum_err": err, "sum_abs": err.abs(), "sum_sq": err**2}


def precip_components(daily_fc: pd.DataFrame, imerg: pd.DataFrame, model: str) -> pd.DataFrame:
    """daily_fc: cell_id, lead_day, date, precip; imerg: cell_id, date, precip (mm per 06-06 UTC day)."""
    m = daily_fc.dropna(subset=["precip"]).merge(
        imerg.dropna(subset=["precip"]), on=["cell_id", "date"], suffixes=("_fc", "_ob")
    )
    if m.empty:
        return pd.DataFrame()
    f, o = m["precip_fc"], m["precip_ob"]
    thr = cfg.PRECIP_THRESHOLD_MM
    out = pd.DataFrame(
        {
            "cell_id": m["cell_id"],
            "model": model,
            "lead_day": m["lead_day"],
            "date": m["date"],
            "var": "precip",
            **_errors(f - o),
            "hits": ((f >= thr) & (o >= thr)).astype(int),
            "misses": ((f < thr) & (o >= thr)).astype(int),
            "false_alarms": ((f >= thr) & (o < thr)).astype(int),
            "correct_negatives": ((f < thr) & (o < thr)).astype(int),
        }
    )
    return out


def cloud_class(pct: pd.Series) -> pd.Series:
    return pd.Series(np.select([pct < cfg.CLOUD_CLEAR_MAX, pct > cfg.CLOUD_CLOUDY_MIN], [0, 2], 1), index=pct.index)


def cloud_components(cloud_fc: pd.DataFrame, modis: pd.DataFrame, model: str) -> pd.DataFrame:
    """cloud_fc: cell_id, lead_day, date, cloud_fc [%] at the overpass; modis: cell_id, date, cloud_frac, valid_frac."""
    ob = modis[(modis["valid_frac"] >= cfg.MODIS_MIN_VALID)].dropna(subset=["cloud_frac"])
    m = cloud_fc.dropna(subset=["cloud_fc"]).merge(ob[["cell_id", "date", "cloud_frac"]], on=["cell_id", "date"])
    if m.empty:
        return pd.DataFrame()
    f, o = m["cloud_fc"], m["cloud_frac"] * 100
    return pd.DataFrame(
        {
            "cell_id": m["cell_id"],
            "model": model,
            "lead_day": m["lead_day"],
            "date": m["date"],
            "var": "cloud",
            **_errors(f - o),
            "class_hits": (cloud_class(f) == cloud_class(o)).astype(int),
        }
    )


def temp_components(daily_fc: pd.DataFrame, obs: pd.DataFrame, stations: dict[str, dict], model: str) -> pd.DataFrame:
    """Model Tmax/Tmin at each station's cell, corrected to station elevation, against IMGW daily values.

    daily_fc: cell_id, lead_day, date, tmax, tmin, model_elevation; obs: station_id, date, tmax, tmin.
    """
    st = pd.DataFrame(
        [
            {"station_id": s["id"], "cell_id": s["cell_id"], "elevation": s["elevation"]}
            for s in stations.values()
            if s.get("cell_id") and s.get("elevation") is not None
        ]
    )
    m = daily_fc.merge(st, on="cell_id").merge(obs, on=["station_id", "date"], suffixes=("_fc", "_ob"))
    if m.empty:
        return pd.DataFrame()
    corr = (m["model_elevation"] - m["elevation"]).fillna(0) * cfg.LAPSE_RATE
    frames = []
    for var in ("tmax", "tmin"):
        ok = m[f"{var}_fc"].notna() & m[f"{var}_ob"].notna()
        err = (m[f"{var}_fc"] + corr - m[f"{var}_ob"])[ok]
        frames.append(
            pd.DataFrame(
                {
                    "station_id": m.loc[ok, "station_id"],
                    "model": model,
                    "lead_day": m.loc[ok, "lead_day"],
                    "date": m.loc[ok, "date"],
                    "var": var,
                    **_errors(err),
                }
            )
        )
    return pd.concat(frames, ignore_index=True)


def finalize(df: pd.DataFrame, key: str) -> pd.DataFrame:
    """Fill absent counters with 0, fix dtypes and order: identical inputs give byte-identical Parquet."""
    if df.empty:
        return df
    for c in COUNT_COLS:
        if c not in df:
            df[c] = 0
    df[COUNT_COLS] = df[COUNT_COLS].fillna(0)
    ints = ["n", "hits", "misses", "false_alarms", "correct_negatives", "class_hits"]
    df[ints] = df[ints].astype("int32")
    df["lead_day"] = df["lead_day"].astype("int8")
    df[["sum_err", "sum_abs", "sum_sq"]] = df[["sum_err", "sum_abs", "sum_sq"]].astype("float64")
    cols = [key, "model", "lead_day", "date", "var", *COUNT_COLS]
    return df[cols].sort_values([key, "model", "var", "lead_day", "date"]).reset_index(drop=True)
