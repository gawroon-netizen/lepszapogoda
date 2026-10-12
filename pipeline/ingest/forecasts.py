"""Daily ingest of archived forecasts (Previous Runs API) for all cells touching Poland (SPEC §7.3).

Budget-driven plan, self-healing after failed or partial runs:
- target range: the last WINDOW_DAYS days ending at today - LAG_DAYS (IMERG is ready for D-2);
- a manifest records which dates are stored for each (model, cell);
- a (model, cell) is fetched when its gap in the target range is >= ROTATION_DAYS days, or when today is
  its rotation slot day (stable hash of cell_id mod ROTATION_DAYS). Requests of up to 14 days cost the same
  as 1 day, so in steady state every cell is fetched once per 14 days with a full 14-day window;
- the initial backfill is the same rule: every cell has a 30-day gap on day one.
When the daily or monthly budget runs out the job stops cleanly; what was fetched is saved and the
manifest updated, the rest is picked up the next day.

Storage (local directory now, R2 later): {data}/forecasts/{model}/{run_date}_{nnn}.parquet, one row per
(cell, valid hour, lead day) with temperature_2m, precipitation, cloud_cover and the model cell metadata.

Usage:
    python -m pipeline.ingest.forecasts [--date YYYY-MM-DD] [--dry-run] [--max-requests N] [--models m1,m2]
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pandas as pd

from lepszapogoda import grid, openmeteo
from pipeline.paths import DATA_DIR

VARIABLES = ("temperature_2m", "precipitation", "cloud_cover")
LEAD_DAYS = tuple(range(1, 8))
WINDOW_DAYS = 30
ROTATION_DAYS = 14
LAG_DAYS = 2
FLUSH_EVERY = 10  # requests per Parquet file (~2.5 M rows, bounded memory, little lost on a crash)


# ---------------------------------------------------------------- manifest


def _merge(ranges: list[tuple[date, date]]) -> list[tuple[date, date]]:
    out: list[tuple[date, date]] = []
    for s, e in sorted(ranges):
        if out and s <= out[-1][1] + timedelta(days=1):
            out[-1] = (out[-1][0], max(out[-1][1], e))
        else:
            out.append((s, e))
    return out


class Manifest:
    """Stored date ranges per (model, cell): {model: {cell_id: [[start, end], ...]}}."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._data: dict[str, dict[str, list[tuple[date, date]]]] = defaultdict(dict)
        if path.exists():
            raw = json.loads(path.read_text(encoding="utf-8"))
            for model, cells in raw.items():
                for cid, rs in cells.items():
                    self._data[model][cid] = [(date.fromisoformat(s), date.fromisoformat(e)) for s, e in rs]

    def ranges(self, model: str, cell_id: str) -> list[tuple[date, date]]:
        return self._data.get(model, {}).get(cell_id, [])

    def add(self, model: str, cell_id: str, start: date, end: date) -> None:
        self._data[model][cell_id] = _merge([*self.ranges(model, cell_id), (start, end)])

    def prune(self, before: date) -> None:
        """Forget coverage older than `before` (data files are kept; this only bounds the manifest size)."""
        for cells in self._data.values():
            for cid, rs in cells.items():
                cells[cid] = [(max(s, before), e) for s, e in rs if e >= before]

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        raw = {
            m: {c: [[s.isoformat(), e.isoformat()] for s, e in rs] for c, rs in sorted(cells.items())}
            for m, cells in sorted(self._data.items())
        }
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(raw, separators=(",", ":")), encoding="utf-8")
        tmp.replace(self.path)


# ---------------------------------------------------------------- plan


def rotation_slot(cell_id: str) -> int:
    """Stable slot 0..ROTATION_DAYS-1, independent of the cell list (hash, not position)."""
    return int(hashlib.sha1(cell_id.encode()).hexdigest(), 16) % ROTATION_DAYS


def target_range(today: date) -> tuple[date, date]:
    end = today - timedelta(days=LAG_DAYS)
    return end - timedelta(days=WINDOW_DAYS - 1), end


def missing_span(ranges: list[tuple[date, date]], start: date, end: date) -> tuple[date, date] | None:
    """Smallest span covering all dates in [start, end] that are not stored, or None if fully covered."""
    missing = []
    d = start
    while d <= end:
        if not any(s <= d <= e for s, e in ranges):
            missing.append(d)
        d += timedelta(days=1)
    return (missing[0], missing[-1]) if missing else None


@dataclass(frozen=True)
class Task:
    model: str
    start: date
    end: date
    cell_ids: tuple[str, ...]

    @property
    def cost(self) -> float:
        n_vars = len(VARIABLES) * min(len(LEAD_DAYS), openmeteo.MAX_LEAD_DAYS[self.model])
        n_days = (self.end - self.start).days + 1
        return openmeteo.call_cost(len(self.cell_ids), n_vars, n_days)


def plan(today: date, cell_ids: list[str], models: list[str], manifest: Manifest) -> list[Task]:
    """Requests to make today, oldest gaps first, batched by identical span."""
    t_start, t_end = target_range(today)
    slot = today.toordinal() % ROTATION_DAYS
    groups: dict[tuple[str, date, date], list[str]] = defaultdict(list)
    for model in models:
        for cid in cell_ids:
            span = missing_span(manifest.ranges(model, cid), t_start, t_end)
            if span is None:
                continue
            gap_days = (span[1] - span[0]).days + 1
            if gap_days >= ROTATION_DAYS or rotation_slot(cid) == slot:
                groups[(model, *span)].append(cid)
    tasks = []
    for (model, s, e), cids in sorted(groups.items(), key=lambda kv: (kv[0][1], kv[0][0])):
        for k in range(0, len(cids), openmeteo.MAX_POINTS_PER_REQUEST):
            tasks.append(Task(model, s, e, tuple(cids[k : k + openmeteo.MAX_POINTS_PER_REQUEST])))
    return tasks


# ---------------------------------------------------------------- fetch and store


def to_frame(task: Task, series: list[openmeteo.PointSeries]) -> pd.DataFrame:
    leads = [d for d in LEAD_DAYS if d <= openmeteo.MAX_LEAD_DAYS[task.model]]
    frames = []
    for cid, s in zip(task.cell_ids, series, strict=True):
        n = len(s.times)
        base = {
            "cell_id": cid,
            "valid_time": pd.to_datetime(s.times, unit="s", utc=True),
            "model_lat": s.cell_lat,
            "model_lon": s.cell_lon,
            "model_elevation": s.elevation,
        }
        for d in leads:
            cols = {v: s.values.get(openmeteo.previous_day_var(v, d), [None] * n) for v in VARIABLES}
            frames.append(pd.DataFrame({**base, "lead_day": d, **cols}))
    df = pd.concat(frames, ignore_index=True)
    df = df.dropna(subset=list(VARIABLES), how="all")
    df.insert(0, "grid_version", grid.GRID_VERSION)
    df.insert(1, "model", task.model)
    df["lead_day"] = df["lead_day"].astype("int8")
    for v in VARIABLES:
        df[v] = df[v].astype("float32")
    return df


def run(
    today: date,
    models: list[str],
    client: openmeteo.OpenMeteoClient,
    data_dir: Path = DATA_DIR,
    max_requests: int | None = None,
    dry_run: bool = False,
    cell_ids: list[str] | None = None,
) -> dict:
    manifest = Manifest(data_dir / "forecasts" / "manifest.json")
    cells = cell_ids or [c.cell_id for c in grid.poland_cells()]
    tasks = plan(today, cells, models, manifest)
    summary = {
        "date": today.isoformat(),
        "planned_requests": len(tasks),
        "planned_cost": round(sum(t.cost for t in tasks), 1),
        "done_requests": 0,
        "done_cost": 0.0,
        "rows": 0,
        "stopped": None,
    }
    if dry_run:
        return summary
    buffers: dict[str, list[pd.DataFrame]] = defaultdict(list)
    pending: list[tuple[str, str, date]] = []  # manifest entries, applied only after their data is on disk

    def flush() -> None:
        # Data first, manifest second: a crash in between means a refetch, never a silent gap
        for model, frames in buffers.items():
            out_dir = data_dir / "forecasts" / model
            out_dir.mkdir(parents=True, exist_ok=True)
            k = len(list(out_dir.glob(f"{today.isoformat()}_*.parquet")))
            df = pd.concat(frames, ignore_index=True)
            df.to_parquet(out_dir / f"{today.isoformat()}_{k:03d}.parquet", index=False)
            summary["rows"] += len(df)
        buffers.clear()
        for model, cid, d in pending:
            manifest.add(model, cid, d, d)
        pending.clear()
        manifest.prune(target_range(today)[0] - timedelta(days=WINDOW_DAYS))
        manifest.save()

    try:
        for i, task in enumerate(tasks):
            if max_requests is not None and i >= max_requests:
                summary["stopped"] = f"max_requests={max_requests}"
                break
            points = [grid.get_cell(c).centroid for c in task.cell_ids]
            series = client.previous_runs(task.model, points, task.start, task.end, VARIABLES, LEAD_DAYS)
            df = to_frame(task, series)
            buffers[task.model].append(df)
            # Mark only dates that actually came back with data (an upstream outage must stay a gap)
            got = df.assign(d=df["valid_time"].dt.date).groupby("cell_id")["d"].unique()
            pending.extend((task.model, cid, d) for cid, days in got.items() for d in days)
            summary["done_requests"] += 1
            summary["done_cost"] += task.cost
            if summary["done_requests"] % FLUSH_EVERY == 0:
                flush()
                print(
                    f"  {summary['done_requests']}/{len(tasks)} requests, cost {summary['done_cost']:.0f}", flush=True
                )
    except openmeteo.BudgetExceeded as e:
        summary["stopped"] = f"budget: {e}"
    finally:
        flush()
    summary["done_cost"] = round(summary["done_cost"], 1)
    summary["remaining_requests"] = len(tasks) - summary["done_requests"]
    return summary


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--date", type=date.fromisoformat, default=datetime.now(UTC).date())
    p.add_argument("--models", default=",".join(openmeteo.MODELS))
    p.add_argument("--max-requests", type=int)
    p.add_argument("--safety", type=float, default=0.8, help="fraction of Open-Meteo limits this job may use")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument(
        "--max-wait",
        type=float,
        default=3_700,
        help="seconds to wait for a rate-limit window; in CI use a small value and let the next run continue",
    )
    a = p.parse_args()
    budget = openmeteo.Budget(ledger_path=DATA_DIR / "openmeteo_ledger.json", safety=a.safety, max_wait_s=a.max_wait)
    client = openmeteo.OpenMeteoClient(budget=budget)
    summary = run(a.date, a.models.split(","), client, max_requests=a.max_requests, dry_run=a.dry_run)
    summary["budget_usage"] = budget.usage()
    print(json.dumps(summary, indent=1))


if __name__ == "__main__":
    main()
