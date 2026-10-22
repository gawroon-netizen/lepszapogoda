"""Pipeline status for the public status page (/stan-danych): publish/status.json in R2.

Built from what is in R2 (not from the local data directory), so the hourly and the daily job produce the same
picture no matter what they pulled:
- ranking: the published meta.json;
- forecasts: the manifest -> per model, how many cells have the full target window and >= MIN_DAYS days, and
  the weighted Open-Meteo cost still to fetch (the same plan the ingest would make today);
- Open-Meteo budget: the ledger;
- observations: the newest date file of each source;
- pollers (Cloudflare Worker): time of the newest raw IMGW file;
- GitHub Actions: the latest runs (GITHUB_TOKEN in CI; skipped without it).

    python -m pipeline.status [--print]
"""

from __future__ import annotations

import argparse
import json
import os
import re
import tempfile
from dataclasses import asdict
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import requests

from lepszapogoda import grid, openmeteo, publication
from pipeline import storage
from pipeline.ingest import forecasts
from pipeline.verify import config as vcfg

# (key, R2 prefix under pipeline/, expected lag in days of the newest complete day)
OBSERVATIONS = (
    ("imerg", "obs/imerg/", 2),
    ("modis_terra", "obs/modis_terra/", 4),
    ("modis_aqua", "obs/modis_aqua/", 4),
    ("imgw_daily", "obs/imgw_daily/", 1),
    ("imgw_meteo_daily", "obs/imgw_meteo_daily/", 1),
)
# (key, R2 prefix of the Worker's raw files, minutes between polls)
POLLERS = (("imgw_synop", "obs/imgw_raw/", 30), ("imgw_meteo", "obs/imgw_meteo_raw/", 5))
DAILY_BUDGET = openmeteo.FREE_TIER.per_day * 0.8  # what the ingest may use per day (--safety 0.8)
DATE_RE = re.compile(r"(\d{4}-\d{2}-\d{2})")
GITHUB_API = "https://api.github.com/repos/{repo}/actions/runs?per_page=15"


def _keys(s3, bucket: str, prefix: str) -> list[dict]:
    out = []
    for page in s3.get_paginator("list_objects_v2").paginate(Bucket=bucket, Prefix=storage.PREFIX + prefix):
        out += page.get("Contents", [])
    return out


def _get_json(s3, bucket: str, key: str):
    try:
        return json.loads(s3.get_object(Bucket=bucket, Key=key)["Body"].read())
    except Exception as e:  # noqa: BLE001 - boto3's NoSuchKey class lives on the client
        if "NoSuchKey" in str(e) or "404" in str(e):
            return None
        raise


def _iso(t: datetime) -> str:
    return t.astimezone(UTC).strftime("%Y-%m-%dT%H:%MZ")


def forecast_status(manifest: forecasts.Manifest, today: date) -> dict:
    t_start, t_end = forecasts.target_range(today)
    cells = [c.cell_id for c in grid.poland_cells()]
    tasks = forecasts.plan(today, cells, list(openmeteo.MODELS), manifest)
    remaining: dict[str, float] = {}
    for t in tasks:
        remaining[t.model] = remaining.get(t.model, 0.0) + t.cost
    models = []
    for m in openmeteo.MODELS:
        complete = with_min = 0
        for cid in cells:
            rs = manifest.ranges(m, cid)
            days = sum(max(0, (min(e, t_end) - max(s, t_start)).days + 1) for s, e in rs)
            complete += forecasts.missing_span(rs, t_start, t_end) is None
            with_min += days >= vcfg.MIN_DAYS
        models.append(
            {
                "model": m,
                "core": m in openmeteo.CORE_MODELS,
                "cells_complete": complete,
                "cells_min_days": with_min,
                "remaining_cost": round(remaining.get(m, 0.0)),
            }
        )
    total = sum(remaining.values())
    return {
        "target": {"from": t_start.isoformat(), "to": t_end.isoformat()},
        "cells_total": len(cells),
        "min_days": vcfg.MIN_DAYS,
        "models": models,
        "remaining_cost": round(total),
        "daily_budget": DAILY_BUDGET,
    }


def newest_date(keys: list[dict]) -> str | None:
    dates = [m.group(1) for k in keys if (m := DATE_RE.search(k["Key"].rsplit("/", 1)[-1]))]
    return max(dates) if dates else None


def observation_status(s3, bucket: str, today: date) -> list[dict]:
    out = []
    for key, prefix, lag in OBSERVATIONS:
        latest = newest_date(_keys(s3, bucket, prefix))
        expected = today - timedelta(days=lag)
        out.append(
            {
                "key": key,
                "latest": latest,
                "expected": expected.isoformat(),
                # one day of slack: the daily job runs at 05:30 UTC and sources publish with some jitter
                "ok": latest is not None and date.fromisoformat(latest) >= expected - timedelta(days=1),
            }
        )
    return out


def poller_status(s3, bucket: str, now: datetime) -> list[dict]:
    out = []
    for key, prefix, every_min in POLLERS:
        objs = []
        for d in (now.date(), now.date() - timedelta(days=1)):
            objs += _keys(s3, bucket, f"{prefix}{d.isoformat()}/")
        last = max((o["LastModified"] for o in objs), default=None)
        today_n = sum(1 for o in objs if f"/{now.date().isoformat()}/" in o["Key"])
        out.append(
            {
                "key": key,
                "last": _iso(last) if last else None,
                "polls_today": today_n,
                "every_min": every_min,
                # three missed polls in a row is a problem worth showing
                "ok": last is not None and (now - last) <= timedelta(minutes=3 * every_min + 5),
            }
        )
    return out


def github_runs(session=requests) -> list[dict] | None:
    repo, token = os.environ.get("GITHUB_REPOSITORY"), os.environ.get("GITHUB_TOKEN")
    if not repo or not token:
        return None
    r = session.get(
        GITHUB_API.format(repo=repo),
        headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"},
        timeout=30,
    )
    r.raise_for_status()
    return [
        {
            "workflow": run["name"],
            "event": run["event"],
            "status": run["status"],
            "conclusion": run["conclusion"],
            "started": run.get("run_started_at") or run["created_at"],
            "updated": run["updated_at"],
            "url": run["html_url"],
        }
        for run in r.json().get("workflow_runs", [])
        if run["name"] != "ci"  # code checks, not the data pipeline
    ][:10]


def ranking_status(meta: dict | None) -> dict | None:
    if not meta:
        return None
    keys = ("published", "computed", "window", "cells_ranked", "cells_total", "cells_with_temp", "wins")
    return {k: meta.get(k) for k in keys}


def build(s3, bucket: str, now: datetime) -> dict:
    today = now.date()
    with tempfile.TemporaryDirectory() as tmp:
        mpath, lpath = Path(tmp) / "manifest.json", Path(tmp) / "ledger.json"
        for key, path in (
            (storage.PREFIX + "forecasts/manifest.json", mpath),
            (storage.PREFIX + "openmeteo_ledger.json", lpath),
        ):
            data = _get_json(s3, bucket, key)
            if data is not None:
                path.write_text(json.dumps(data), encoding="utf-8")
        manifest = forecasts.Manifest(mpath)
        budget = openmeteo.Budget(ledger_path=lpath if lpath.exists() else None, clock=now.timestamp)
    return {
        "generated": _iso(now),
        "run": {
            "workflow": os.environ.get("GITHUB_WORKFLOW"),
            "url": (
                f"{os.environ['GITHUB_SERVER_URL']}/{os.environ['GITHUB_REPOSITORY']}/actions/runs/{os.environ['GITHUB_RUN_ID']}"
                if os.environ.get("GITHUB_RUN_ID")
                else None
            ),
        },
        "ranking": ranking_status(_get_json(s3, bucket, publication.META_KEY)),
        "forecasts": forecast_status(manifest, today),
        "budget": {"usage": budget.usage(), "limits": asdict(openmeteo.FREE_TIER), "pipeline_share": 0.8},
        "observations": observation_status(s3, bucket, today),
        "pollers": poller_status(s3, bucket, now),
        "runs": github_runs(),
    }


def main() -> None:
    p = argparse.ArgumentParser(description="Write publish/status.json")
    p.add_argument("--print", action="store_true", help="print instead of uploading")
    a = p.parse_args()
    s3, bucket = storage.client(), storage.bucket_name()
    status = build(s3, bucket, datetime.now(UTC))
    body = json.dumps(status, ensure_ascii=False, indent=1)
    if a.print:
        print(body)
        return
    s3.put_object(Bucket=bucket, Key=publication.STATUS_KEY, Body=body.encode(), ContentType="application/json")
    print(f"status written: {publication.STATUS_KEY}, forecast cost left {status['forecasts']['remaining_cost']}")


if __name__ == "__main__":
    main()
