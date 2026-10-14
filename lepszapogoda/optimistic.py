"""'Najbardziej optymistyczna' (SPEC §8.5): the model promising the warmest and driest next three days.

Days 1-3 from tomorrow in local time (Europe/Warsaw). t = mean of daily Tmax, p = sum of precipitation.
Min-max normalisation between models; score = 0.5 * t_norm + 0.5 * (1 - p_norm); tie -> lower mean cloud cover.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Europe/Warsaw")


def daily(values: Sequence[float | None], times: Sequence[int], agg: str) -> dict[date, float]:
    """Aggregate hourly values per local date ('max', 'sum', 'mean'); only complete days (24 values, 23/25 on DST)."""
    by_day: dict[date, list[float]] = defaultdict(list)
    count: dict[date, int] = defaultdict(int)
    for v, t in zip(values, times, strict=True):
        d = datetime.fromtimestamp(t, TZ).date()
        count[d] += 1
        if v is not None:
            by_day[d].append(v)
    out = {}
    for d, vals in by_day.items():
        if len(vals) < count[d] or count[d] < 23:
            continue
        out[d] = max(vals) if agg == "max" else sum(vals) if agg == "sum" else sum(vals) / len(vals)
    return out


def scores(models: dict[str, dict[str, list]], times: Sequence[int], today: date) -> dict[str, float]:
    days = [today + timedelta(days=k) for k in (1, 2, 3)]
    stats = {}
    for m, s in models.items():
        tx = daily(s["temperature_2m"], times, "max")
        pr = daily(s["precipitation"], times, "sum")
        cl = daily(s.get("cloud_cover", [None] * len(times)), times, "mean")
        if all(d in tx and d in pr for d in days):
            stats[m] = (
                sum(tx[d] for d in days) / 3,
                sum(pr[d] for d in days),
                sum(cl.get(d, 0) for d in days) / 3,
            )
    if not stats:
        return {}

    def norm(vals: dict[str, float]) -> dict[str, float]:
        lo, hi = min(vals.values()), max(vals.values())
        return {k: 0.5 if hi == lo else (v - lo) / (hi - lo) for k, v in vals.items()}

    t_n = norm({m: s[0] for m, s in stats.items()})
    p_n = norm({m: s[1] for m, s in stats.items()})
    return {m: 0.5 * t_n[m] + 0.5 * (1 - p_n[m]) for m in stats}


def most_optimistic(models: dict[str, dict[str, list]], times: Sequence[int], today: date) -> str | None:
    sc = scores(models, times, today)
    if not sc:
        return None
    clouds = {m: sum(daily(models[m].get("cloud_cover", [0] * len(times)), times, "mean").values()) for m in sc}
    return min(sc, key=lambda m: (-round(sc[m], 9), clouds[m], m))
