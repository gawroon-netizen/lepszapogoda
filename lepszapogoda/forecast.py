"""Current forecasts of all models for a point, with a file cache (SPEC §7.4; Redis not available on the host).

One Forecast API request returns all models (counted by our budget as one call per model). Cache key: the point
rounded to 0.01° (about 1 km), TTL 1 h. When Open-Meteo is unavailable or the budget is exhausted a stale cache
entry is served (marked `stale`), otherwise ForecastUnavailable is raised.
"""

from __future__ import annotations

import json
import os
import time
from collections.abc import Callable
from pathlib import Path

from lepszapogoda import openmeteo

HOURLY = (
    "temperature_2m",
    "apparent_temperature",
    "precipitation",
    "snowfall",
    "cloud_cover",
    "wind_speed_10m",
    "wind_gusts_10m",
    "wind_direction_10m",
    "cape",
)
FORECAST_DAYS = 8  # 7 local days from today, plus the hours of the first one already gone
TTL_S = 3600


class ForecastUnavailable(RuntimeError):
    pass


class ForecastService:
    def __init__(
        self,
        client: openmeteo.OpenMeteoClient,
        cache_dir: Path,
        ttl_s: float = TTL_S,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.client = client
        self.cache_dir = cache_dir
        self.ttl_s = ttl_s
        self._clock = clock

    def _path(self, lat: float, lon: float) -> Path:
        return self.cache_dir / f"fc_{lat:.2f}_{lon:.2f}.json"

    def get(self, lat: float, lon: float) -> dict:
        lat, lon = round(lat, 2), round(lon, 2)
        path = self._path(lat, lon)
        cached = None
        if path.exists():
            try:
                cached = json.loads(path.read_text(encoding="utf-8"))
            except ValueError:
                cached = None
        if cached and self._clock() - cached["fetched"] < self.ttl_s:
            return cached
        try:
            series = self.client.forecast(list(openmeteo.MODELS), lat, lon, list(HOURLY), FORECAST_DAYS)
        except (openmeteo.BudgetExceeded, openmeteo.OpenMeteoError) as e:
            if cached:
                return {**cached, "stale": True}
            raise ForecastUnavailable(str(e)) from e
        first = next(iter(series.values()))
        data = {
            "fetched": self._clock(),
            "lat": lat,
            "lon": lon,
            "elevation": first.elevation,
            "times": first.times,
            "models": {
                m: s.values for m, s in series.items() if any(v is not None for v in s.values["temperature_2m"])
            },
        }
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(f".{os.getpid()}.tmp")
        tmp.write_text(json.dumps(data, separators=(",", ":")), encoding="utf-8")
        tmp.replace(path)
        return data

    def cleanup(self, max_age_s: float = 7 * 86400) -> int:
        """Remove cache files older than max_age_s (cron, SPEC §7.4). Returns the number removed."""
        n = 0
        for p in self.cache_dir.glob("fc_*.json"):
            if self._clock() - p.stat().st_mtime > max_age_s:
                p.unlink(missing_ok=True)
                n += 1
        return n
