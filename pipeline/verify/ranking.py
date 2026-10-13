"""Per-cell ranking (SPEC §8.4) and blend weights (§8.10) from daily verification components.

Everything here is a pure function of the component tables and the configuration, so the same Parquet always
yields the same JSON (§0 pt 9, §12 e).
"""

from __future__ import annotations

import math
from datetime import date, timedelta

import numpy as np
import pandas as pd

from lepszapogoda import grid
from lepszapogoda.openmeteo import MAX_LEAD_DAYS
from pipeline.verify import config as cfg

SUMS = ["n", "sum_err", "sum_abs", "sum_sq", "hits", "misses", "false_alarms", "correct_negatives", "class_hits"]
BLEND_METHOD = "temp_inverse_mse_30d_by_lead_group; precip_cloud_wind_equal"


# ---------------------------------------------------------------- metrics from sums


def ets(h: float, m: float, f: float, c: float) -> float | None:
    n = h + m + f + c
    if n == 0 or h + m == 0:
        return None  # no observed events: ETS undefined, never a division by zero
    r = (h + f) * (h + m) / n
    den = h + m + f - r
    return None if den == 0 else (h - r) / den


def pooled(comp: pd.DataFrame, key: str, start: date, end: date, leads) -> pd.DataFrame:
    """Sum components per (key, model, var) over the date window and leads; n_days = distinct dates."""
    c = comp[(comp["date"] >= start) & (comp["date"] <= end) & comp["lead_day"].isin(list(leads))]
    if c.empty:
        return pd.DataFrame(columns=[key, "model", "var", *SUMS, "n_days"])
    g = c.groupby([key, "model", "var"])
    out = g[SUMS].sum()
    out["n_days"] = g["date"].nunique()
    return out.reset_index()


def add_metrics(p: pd.DataFrame) -> pd.DataFrame:
    p = p.copy()
    p["mae"] = p["sum_abs"] / p["n"]
    p["bias"] = p["sum_err"] / p["n"]
    p["sde"] = np.sqrt(np.maximum(p["sum_sq"] / p["n"] - p["bias"] ** 2, 0))
    p["mse"] = p["sum_sq"] / p["n"]
    p["class_acc"] = p["class_hits"] / p["n"]
    p["ets"] = [ets(*r) for r in p[["hits", "misses", "false_alarms", "correct_negatives"]].itertuples(index=False)]
    return p


def norm(values: dict[str, float], higher_better: bool) -> dict[str, float]:
    """Min-max between models in one cell, 1 = best. Equal values (or one model) -> 1 for all."""
    lo, hi = min(values.values()), max(values.values())
    if hi == lo:
        return {m: 1.0 for m in values}
    return {m: (v - lo) / (hi - lo) if higher_better else (hi - v) / (hi - lo) for m, v in values.items()}


# ---------------------------------------------------------------- stations -> cells


def haversine_km(a: tuple[float, float], b: tuple[float, float]) -> float:
    la1, lo1, la2, lo2 = map(math.radians, (*a, *b))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 2 * 6371.0088 * math.asin(math.sqrt(h))


def station_map(cell_ids: list[str], stations: dict[str, dict]) -> pd.DataFrame:
    """Stations within STATION_RADIUS_KM of each cell centroid, weight 1/d normalised per cell (§8.2)."""
    rows = []
    st = [s for s in stations.values() if s.get("cell_id")]
    for cid in cell_ids:
        c = grid.get_cell(cid).centroid
        near = [(s["id"], haversine_km(c, (s["lat"], s["lon"]))) for s in st]
        near = [(sid, d) for sid, d in near if d <= cfg.STATION_RADIUS_KM]
        tot = sum(1 / max(d, cfg.MIN_STATION_DIST_KM) for _, d in near)
        rows += [
            {"cell_id": cid, "station_id": sid, "dist_km": d, "w": 1 / max(d, cfg.MIN_STATION_DIST_KM) / tot}
            for sid, d in near
        ]
    return pd.DataFrame(rows, columns=["cell_id", "station_id", "dist_km", "w"])


def cell_temperature(station_pooled: pd.DataFrame, smap: pd.DataFrame) -> pd.DataFrame:
    """Per (cell, model): temp MAE and MSE as 1/d-weighted means over the cell's stations (Tmax and Tmin pooled)."""
    if station_pooled.empty or smap.empty:
        return pd.DataFrame(columns=["cell_id", "model", "temp_mae", "temp_mse", "temp_days"])
    s = station_pooled.groupby(["station_id", "model"])[["n", "sum_abs", "sum_sq", "n_days"]].agg(
        {"n": "sum", "sum_abs": "sum", "sum_sq": "sum", "n_days": "min"}
    )
    s = s[s["n_days"] >= cfg.MIN_DAYS].reset_index()
    s["mae"] = s["sum_abs"] / s["n"]
    s["mse"] = s["sum_sq"] / s["n"]
    m = smap.merge(s, on="station_id")
    if m.empty:
        return pd.DataFrame(columns=["cell_id", "model", "temp_mae", "temp_mse", "temp_days"])
    m["wm"] = m["w"] * m["mae"]
    m["ws"] = m["w"] * m["mse"]
    g = m.groupby(["cell_id", "model"]).agg(w=("w", "sum"), wm=("wm", "sum"), ws=("ws", "sum"), d=("n_days", "min"))
    return pd.DataFrame({"temp_mae": g["wm"] / g["w"], "temp_mse": g["ws"] / g["w"], "temp_days": g["d"]}).reset_index()


# ---------------------------------------------------------------- ranking


def _r(x: float | None, nd: int) -> float | None:
    return None if x is None or (isinstance(x, float) and math.isnan(x)) else round(float(x), nd)


def rank_cell(cell_metrics: dict[str, dict]) -> list[dict]:
    """cell_metrics: {model: {precip_ets, precip_mae, cloud_class_acc, cloud_sde, temp_mae (opt.), ...}}.

    Components present for every model enter the score; weights renormalised over them (§8.4).
    """
    models = sorted(cell_metrics)
    parts: dict[str, dict[str, float]] = {}
    if all(cell_metrics[m].get("precip_mae") is not None for m in models):
        mae_n = norm({m: cell_metrics[m]["precip_mae"] for m in models}, higher_better=False)
        if all(cell_metrics[m].get("precip_ets") is not None for m in models):
            ets_n = norm({m: cell_metrics[m]["precip_ets"] for m in models}, higher_better=True)
            w = cfg.PRECIP_ETS_WEIGHT
            parts["precip"] = {m: w * ets_n[m] + (1 - w) * mae_n[m] for m in models}
        else:
            parts["precip"] = mae_n
    if all(cell_metrics[m].get("cloud_class_acc") is not None for m in models):
        acc_n = norm({m: cell_metrics[m]["cloud_class_acc"] for m in models}, higher_better=True)
        sde_n = norm({m: cell_metrics[m]["cloud_sde"] for m in models}, higher_better=False)
        w = cfg.CLOUD_CLASS_WEIGHT
        parts["cloud"] = {m: w * acc_n[m] + (1 - w) * sde_n[m] for m in models}
    if all(cell_metrics[m].get("temp_mae") is not None for m in models):
        parts["temp"] = norm({m: cell_metrics[m]["temp_mae"] for m in models}, higher_better=False)
    if not parts:
        return []
    wsum = sum(cfg.WEIGHTS[k] for k in parts)
    out = []
    for m in models:
        score = sum(cfg.WEIGHTS[k] / wsum * parts[k][m] for k in parts)
        out.append({"model": m, "score": round(100 * score), **cell_metrics[m]})
    return sorted(out, key=lambda r: (-r["score"], r["model"]))


def blend_weights(temp_by_group: dict[str, pd.DataFrame], cell_id: str, models: list[str]) -> dict:
    """Temperature: 1/MSE per lead group, normalised; groups without data -> equal over models with that lead."""
    out = {}
    for gname, leads in cfg.LEAD_GROUPS.items():
        df = temp_by_group.get(gname)
        rows = df[df["cell_id"] == cell_id] if df is not None and not df.empty else pd.DataFrame()
        present = sorted(rows["model"]) if not rows.empty else []
        if present:
            inv = {r.model: 1 / max(r.temp_mse, 1e-6) for r in rows.itertuples()}
            tot = sum(inv.values())
            out[gname] = {m: round(inv[m] / tot, 4) for m in present}
        else:
            avail = [m for m in models if MAX_LEAD_DAYS.get(m, 7) >= min(leads)]
            out[gname] = {m: round(1 / len(avail), 4) for m in avail} if avail else {}
    return {"method": BLEND_METHOD, "temp": out, "precip": "equal", "cloud": "equal", "wind": "equal"}


def build(
    cell_comp: pd.DataFrame,
    station_comp: pd.DataFrame,
    stations: dict[str, dict],
    end: date,
    computed: str,
) -> tuple[dict[str, dict], dict]:
    """All cell JSONs and meta.json for the window ending at `end`."""
    start = end - timedelta(days=cfg.WINDOW_DAYS - 1)
    cells = [c.cell_id for c in grid.poland_cells()]
    cp = add_metrics(pooled(cell_comp, "cell_id", start, end, cfg.RANK_LEADS))
    sp = pooled(station_comp, "station_id", start, end, cfg.RANK_LEADS)
    smap = station_map(cells, stations)
    temp = cell_temperature(sp, smap)
    temp_groups = {
        g: cell_temperature(pooled(station_comp, "station_id", start, end, leads), smap)
        for g, leads in cfg.LEAD_GROUPS.items()
    }
    nearest = smap.sort_values("dist_km").drop_duplicates("cell_id").set_index("cell_id")

    by_cell: dict[str, dict[str, dict]] = {}
    for r in cp.itertuples():
        d = by_cell.setdefault(r.cell_id, {}).setdefault(r.model, {})
        if r.var == "precip":
            d.update(precip_ets=_r(r.ets, 3), precip_mae=_r(r.mae, 3), n_days=int(r.n_days))
        elif r.var == "cloud" and r.n_days >= cfg.MIN_DAYS:
            d.update(cloud_class_acc=_r(r.class_acc, 3), cloud_sde=_r(r.sde, 2), cloud_bias=_r(r.bias, 2))
    for r in temp.itertuples():
        if r.cell_id in by_cell and r.model in by_cell[r.cell_id]:
            by_cell[r.cell_id][r.model]["temp_mae"] = _r(r.temp_mae, 3)

    out: dict[str, dict] = {}
    for cid, models in sorted(by_cell.items()):
        eligible = {m: v for m, v in models.items() if v.get("n_days", 0) >= cfg.MIN_DAYS}
        if len(eligible) < 2:
            continue  # SPEC §8.4: no file when no model meets the minimum
        ranking = rank_cell(eligible)
        if not ranking:
            continue
        has_temp = all(v.get("temp_mae") is not None for v in eligible.values())
        src = None
        if has_temp and cid in nearest.index:
            n = nearest.loc[cid]
            src = f"station:{n['station_id']}:{round(float(n['dist_km']))}km"
        out[cid] = {
            "grid_version": grid.GRID_VERSION,
            "cell": cid,
            "computed": computed,
            "window": {"from": start.isoformat(), "to": end.isoformat(), "days": cfg.WINDOW_DAYS},
            "leads_days": list(cfg.RANK_LEADS),
            "accurate": ranking,
            "temp_source": src,
            "blend": blend_weights(temp_groups, cid, sorted(eligible)),
        }

    wins: dict[str, int] = {}
    for j in out.values():
        wins[j["accurate"][0]["model"]] = wins.get(j["accurate"][0]["model"], 0) + 1
    top = [j["accurate"][0]["score"] for j in out.values()]
    meta = {
        "grid_version": grid.GRID_VERSION,
        "computed": computed,
        "window": {"from": start.isoformat(), "to": end.isoformat(), "days": cfg.WINDOW_DAYS},
        "weights": cfg.WEIGHTS,
        "cells_total": len(cells),
        "cells_ranked": len(out),
        "cells_with_temp": sum(1 for j in out.values() if j["temp_source"]),
        "median_top_score": float(np.median(top)) if top else None,
        "wins": dict(sorted(wins.items())),
    }
    return out, meta
