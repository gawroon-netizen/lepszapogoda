"""Open-Meteo client with an API budget (SPEC §7.3, §7.4). Shared by the pipeline runner and the web app.

Budget facts (free tier, open-meteo.com/en/pricing, checked 2026-10-11):
- limits: 600 calls/min, 5 000/h, 10 000/day, 300 000/month;
- a request with > 10 variables or > 2 weeks of data counts as more than one call, fractionally
  (e.g. 15 variables = 1.5); how multi-location requests count is undocumented, so we assume one call
  per location (conservative);
- exceeding a limit returns HTTP 429 with a reason such as "Hourly API request limit exceeded".

The Budget keeps a ledger of weighted calls and checks rolling windows. A rolling window is never more
permissive than a calendar window of the same length, so staying under it also satisfies Open-Meteo.
"""

from __future__ import annotations

import json
import math
import time
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import requests

PREVIOUS_RUNS_URL = "https://previous-runs-api.open-meteo.com/v1/forecast"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"

# Models in the MVP (SPEC §4) and the longest lead (days) each one has in the Previous Runs API (Etap 0b)
MODELS = ("ecmwf_ifs", "ecmwf_aifs025_single", "icon_seamless", "gfs_seamless", "meteofrance_seamless")
MAX_LEAD_DAYS = {
    "ecmwf_ifs": 7,
    "ecmwf_aifs025_single": 7,
    "icon_seamless": 6,
    "gfs_seamless": 7,
    "meteofrance_seamless": 3,
}

# Verification requests (SPEC §7.3): UTC, nearest cell, no elevation downscaling (the response then
# reports the model cell elevation, needed for our own lapse-rate correction against stations)
ARCHIVE_PARAMS = {"timezone": "UTC", "timeformat": "unixtime", "cell_selection": "nearest", "elevation": "nan"}
# Forecasts shown to users keep Open-Meteo's default downscaling to the point's terrain height (90 m DEM),
# which is what a user at that point experiences; cell_selection=land avoids sea cells at the coast
FORECAST_PARAMS = {"timezone": "UTC", "timeformat": "unixtime", "cell_selection": "land"}

MAX_POINTS_PER_REQUEST = 50


class BudgetExceeded(RuntimeError):
    """The daily or monthly limit would be exceeded; the job must stop and continue another day."""


class OpenMeteoError(RuntimeError):
    pass


def call_cost(n_locations: int, n_variables: int, n_days: int) -> float:
    """Weighted call count of one request, per Open-Meteo's pricing rules (see module docstring)."""
    if n_locations < 1 or n_variables < 1 or n_days < 1:
        raise ValueError("locations, variables and days must be >= 1")
    return n_locations * max(1.0, n_variables / 10) * max(1.0, n_days / 14)


# ---------------------------------------------------------------- budget


@dataclass(frozen=True)
class Limits:
    per_minute: float = 600
    per_hour: float = 5_000
    per_day: float = 10_000
    per_month: float = 300_000


FREE_TIER = Limits()
_WINDOWS = (("per_minute", 60), ("per_hour", 3_600), ("per_day", 86_400), ("per_month", 30 * 86_400))
_BLOCKING = {"per_day", "per_month"}  # waiting makes no sense within one job: stop instead


class Budget:
    """Ledger of weighted calls with rolling-window limits.

    `safety` scales all limits (0.8 = use at most 80 %), leaving room for the web app and other jobs.
    Short windows (minute, hour) are waited out up to `max_wait_s`; long ones raise BudgetExceeded.
    The ledger is optionally persisted to a JSON file, so consecutive runs share it.
    """

    def __init__(
        self,
        ledger_path: Path | None = None,
        limits: Limits = FREE_TIER,
        safety: float = 0.8,
        max_wait_s: float = 3_700,
        clock: Callable[[], float] = time.time,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.ledger_path = ledger_path
        self.limits = limits
        self.safety = safety
        self.max_wait_s = max_wait_s
        self._clock = clock
        self._sleep = sleep
        self._entries: list[tuple[float, float]] = []  # (timestamp, cost), ascending
        if ledger_path and ledger_path.exists():
            self._entries = [tuple(e) for e in json.loads(ledger_path.read_text(encoding="utf-8"))["entries"]]
        self._prune()

    def _limit(self, name: str) -> float:
        return getattr(self.limits, name) * self.safety

    def _prune(self) -> None:
        horizon = self._clock() - _WINDOWS[-1][1]
        self._entries = [e for e in self._entries if e[0] > horizon]

    def used(self, window_s: float) -> float:
        start = self._clock() - window_s
        return sum(c for t, c in self._entries if t > start)

    def usage(self) -> dict[str, float]:
        return {name: round(self.used(sec), 2) for name, sec in _WINDOWS}

    def _wait_needed(self, name: str, window_s: float, cost: float) -> float:
        """Seconds until enough old entries leave the window for `cost` to fit; 0 if it fits now."""
        now = self._clock()
        in_window = [(t, c) for t, c in self._entries if t > now - window_s]
        excess = sum(c for _, c in in_window) + cost - self._limit(name)
        if excess <= 0:
            return 0.0
        freed = 0.0
        for t, c in in_window:
            freed += c
            if freed >= excess:
                return t + window_s - now + 1
        return math.inf  # cost alone is larger than the limit

    def reserve(self, cost: float) -> None:
        """Block until `cost` fits all windows, then record it. Raises BudgetExceeded for day/month."""
        while True:
            self._prune()
            waits = {name: self._wait_needed(name, sec, cost) for name, sec in _WINDOWS}
            blocking = [n for n in _BLOCKING if waits[n] > 0]
            if blocking:
                raise BudgetExceeded(f"{', '.join(sorted(blocking))} limit would be exceeded; usage={self.usage()}")
            wait = max(waits.values())
            if wait == 0:
                break
            if wait > self.max_wait_s:
                raise BudgetExceeded(f"would need to wait {wait:.0f} s; usage={self.usage()}")
            self._sleep(wait)
        self._entries.append((self._clock(), cost))
        self.save()

    def save(self) -> None:
        if self.ledger_path:
            self.ledger_path.parent.mkdir(parents=True, exist_ok=True)
            self.ledger_path.write_text(json.dumps({"entries": self._entries}), encoding="utf-8")


# ---------------------------------------------------------------- responses


@dataclass
class PointSeries:
    """Hourly series for one requested point from one model."""

    lat: float  # requested
    lon: float
    cell_lat: float  # model grid point actually used
    cell_lon: float
    elevation: float | None  # model cell elevation [m] (elevation=nan in the request)
    times: list[int]  # unix seconds, UTC, start of hour
    values: dict[str, list[float | None]] = field(default_factory=dict)  # by API variable name


def _parse_locations(payload: dict | list, points: Sequence[tuple[float, float]]) -> list[PointSeries]:
    locs = payload if isinstance(payload, list) else [payload]
    if len(locs) != len(points):
        raise OpenMeteoError(f"expected {len(points)} locations, got {len(locs)}")
    out = []
    for (lat, lon), loc in zip(points, locs, strict=True):
        hourly = dict(loc.get("hourly") or {})
        times = hourly.pop("time", [])
        elev = loc.get("elevation")
        out.append(
            PointSeries(
                lat=lat,
                lon=lon,
                cell_lat=loc["latitude"],
                cell_lon=loc["longitude"],
                elevation=None if elev is None or (isinstance(elev, float) and math.isnan(elev)) else float(elev),
                times=times,
                values=hourly,
            )
        )
    return out


def previous_day_var(variable: str, lead_days: int) -> str:
    """API name of a variable forecast `lead_days` x 24 h before valid time, e.g. temperature_2m_previous_day2."""
    return f"{variable}_previous_day{lead_days}"


# ---------------------------------------------------------------- client


class OpenMeteoClient:
    def __init__(
        self,
        budget: Budget | None = None,
        session: requests.Session | None = None,
        timeout_s: float = 120,
        retries: int = 3,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.budget = budget or Budget()
        self.session = session or requests.Session()
        self.timeout_s = timeout_s
        self.retries = retries
        self._sleep = sleep

    def _get(self, url: str, params: dict, cost: float) -> dict | list:
        """GET with budget reservation, 429 handling and retries on transient errors."""
        self.budget.reserve(cost)
        attempt = 0
        while True:
            try:
                r = self.session.get(url, params=params, timeout=self.timeout_s)
            except (requests.ConnectionError, requests.Timeout) as e:
                attempt += 1
                if attempt > self.retries:
                    raise OpenMeteoError(f"network error after {attempt} attempts: {e}") from e
                self._sleep(10 * attempt)
                continue
            if r.status_code == 200:
                return r.json()
            reason = _reason(r)
            if r.status_code == 429:
                # Our ledger disagrees with Open-Meteo (other users of the same IP, unknown counting rules)
                if "daily" in reason.lower() or "monthly" in reason.lower():
                    raise BudgetExceeded(f"Open-Meteo: {reason}")
                attempt += 1
                if attempt > self.retries:
                    raise BudgetExceeded(f"Open-Meteo still rate limiting after {attempt} attempts: {reason}")
                self._sleep(65 if "minut" in reason.lower() else 3_600 - time.time() % 3_600 + 30)
                continue
            if r.status_code >= 500 and attempt < self.retries:
                attempt += 1
                self._sleep(10 * attempt)
                continue
            raise OpenMeteoError(f"HTTP {r.status_code}: {reason}")

    def previous_runs(
        self,
        model: str,
        points: Sequence[tuple[float, float]],
        start: date,
        end: date,
        variables: Iterable[str],
        lead_days: Iterable[int],
    ) -> list[PointSeries]:
        """Archived forecasts at fixed lead times: value valid at t as forecast lead x 24 h earlier.

        Leads beyond the model's horizon (MAX_LEAD_DAYS) are dropped from the request, they only cost budget.
        """
        max_lead = MAX_LEAD_DAYS.get(model, 7)
        leads = [d for d in lead_days if 1 <= d <= max_lead]
        if not leads:
            raise ValueError(f"no requested lead within {model}'s horizon of {max_lead} days")
        hourly = [previous_day_var(v, d) for v in variables for d in leads]
        n_days = (end - start).days + 1
        out: list[PointSeries] = []
        for k in range(0, len(points), MAX_POINTS_PER_REQUEST):
            chunk = points[k : k + MAX_POINTS_PER_REQUEST]
            params = {
                **ARCHIVE_PARAMS,
                "latitude": ",".join(f"{lat:.4f}" for lat, _ in chunk),
                "longitude": ",".join(f"{lon:.4f}" for _, lon in chunk),
                "hourly": ",".join(hourly),
                # the API requires one elevation value per coordinate (HTTP 400 otherwise)
                "elevation": ",".join(["nan"] * len(chunk)),
                "models": model,
                "start_date": start.isoformat(),
                "end_date": end.isoformat(),
            }
            payload = self._get(PREVIOUS_RUNS_URL, params, call_cost(len(chunk), len(hourly), n_days))
            out.extend(_parse_locations(payload, chunk))
        return out

    def forecast(
        self, models: Sequence[str], lat: float, lon: float, variables: Sequence[str], forecast_days: int = 7
    ) -> dict[str, PointSeries]:
        """Current forecast of several models for one point (web view, SPEC §7.4). Cost counted per model."""
        params = {
            **FORECAST_PARAMS,
            "latitude": f"{lat:.4f}",
            "longitude": f"{lon:.4f}",
            "hourly": ",".join(variables),
            "models": ",".join(models),
            "forecast_days": forecast_days,
        }
        cost = len(models) * call_cost(1, len(variables), forecast_days)
        payload = self._get(FORECAST_URL, params, cost)
        (series,) = _parse_locations(payload, [(lat, lon)])
        # With several models the API suffixes each variable with the model id
        out = {}
        for m in models:
            vals = {
                v: series.values.get(f"{v}_{m}", series.values.get(v) if len(models) == 1 else None) for v in variables
            }
            out[m] = PointSeries(
                series.lat, series.lon, series.cell_lat, series.cell_lon, series.elevation, series.times, vals
            )
        return out


def _reason(r: requests.Response) -> str:
    try:
        body = r.json()
    except ValueError:  # not JSON, e.g. an HTML page from a proxy
        return r.text[:200]
    return str(body.get("reason", r.text[:200])) if isinstance(body, dict) else r.text[:200]
