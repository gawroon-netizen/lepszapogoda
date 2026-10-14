"""Multi-model blend for the "Najbardziej trafna" view (SPEC §8.10).

Temperature (and apparent temperature) uses the cell's skill weights per lead group, everything else equal
weights. At every hour only models with a value take part and weights are renormalised over them, so a model
that ends its horizon (Météo-France after ~4 days) simply drops out. Wind direction is averaged as a vector.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

LEAD_GROUPS: dict[str, tuple[int, ...]] = {"1-2": (1, 2), "3-4": (3, 4), "5-7": (5, 6, 7)}
WEIGHTED_VARS = {"temperature_2m", "apparent_temperature"}
SPREAD_VARS = ("temperature_2m", "precipitation")


def lead_group(hours_ahead: float) -> str:
    day = max(1, math.ceil(hours_ahead / 24))
    for name, days in LEAD_GROUPS.items():
        if day in days:
            return name
    return "5-7"


def _weights(models: Sequence[str], var: str, group: str, temp_weights: dict | None) -> dict[str, float]:
    if var in WEIGHTED_VARS and temp_weights and temp_weights.get(group):
        w = {m: temp_weights[group].get(m, 0.0) for m in models}
        tot = sum(w.values())
        if tot > 0:
            return {m: v / tot for m, v in w.items()}
    return {m: 1 / len(models) for m in models}


def blend(
    models: dict[str, dict[str, list[float | None]]],
    times: Sequence[int],
    now: int,
    temp_weights: dict[str, dict[str, float]] | None = None,
) -> dict[str, list[float | None]]:
    """models: {model: {variable: hourly values}}, times: unix seconds. Returns blended hourly series plus
    `{var}_min`/`{var}_max` (spread between models) for SPREAD_VARS and `members` (models used per hour)."""
    names = sorted(models)
    variables = sorted({v for m in names for v in models[m]} - {"wind_direction_10m"})
    out: dict[str, list] = {v: [] for v in variables}
    for v in SPREAD_VARS:
        out[f"{v}_min"], out[f"{v}_max"] = [], []
    out["wind_direction_10m"] = []
    out["members"] = []
    for i, t in enumerate(times):
        group = lead_group((t - now) / 3600)
        present = [m for m in names if models[m].get("temperature_2m", [None] * len(times))[i] is not None]
        out["members"].append(len(present))
        for v in variables:
            vals = {m: models[m][v][i] for m in present if v in models[m] and models[m][v][i] is not None}
            if not vals:
                out[v].append(None)
                continue
            w = _weights(list(vals), v, group, temp_weights)
            out[v].append(sum(w[m] * vals[m] for m in vals))
        for v in SPREAD_VARS:
            vals = [models[m][v][i] for m in present if v in models[m] and models[m][v][i] is not None]
            out[f"{v}_min"].append(min(vals) if vals else None)
            out[f"{v}_max"].append(max(vals) if vals else None)
        out["wind_direction_10m"].append(
            mean_direction(
                [models[m].get("wind_direction_10m", [None] * len(times))[i] for m in present],
                [models[m].get("wind_speed_10m", [None] * len(times))[i] for m in present],
            )
        )
    return out


def mean_direction(directions: Sequence[float | None], speeds: Sequence[float | None] | None = None) -> float | None:
    """Vector mean of directions in degrees (weighted by speed when given): 350 and 10 -> 0, never 180."""
    u = v = 0.0
    n = 0
    for k, d in enumerate(directions):
        if d is None:
            continue
        s = speeds[k] if speeds is not None and speeds[k] is not None else 1.0
        u += s * math.sin(math.radians(d))
        v += s * math.cos(math.radians(d))
        n += 1
    if n == 0 or (abs(u) < 1e-9 and abs(v) < 1e-9):
        return None
    return round(math.degrees(math.atan2(u, v)) % 360, 1)
