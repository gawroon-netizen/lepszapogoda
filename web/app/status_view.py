"""Data for the /stan-danych page: publish/status.json (pipeline.status) made readable.

The file is copied to the host by web/cron/pull_rankings.py every 30 minutes; the pipeline rewrites it at the end
of every hourly and daily run.
"""

from __future__ import annotations

import json
import math
from datetime import UTC, date, datetime
from pathlib import Path

from web.app.i18n import pl
from web.app.view import TZ

STALE_AFTER_H = 3  # the hourly job runs 4-7 times a day (GitHub schedule), so allow a gap


def load(path: Path) -> dict | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _parse(t: str | None) -> datetime | None:
    if not t:
        return None
    for fmt in ("%Y-%m-%dT%H:%MZ", "%Y-%m-%dT%H:%M:%SZ"):
        try:
            return datetime.strptime(t, fmt).replace(tzinfo=UTC)
        except ValueError:
            continue
    return None


def local(t: str | None) -> str:
    dt = _parse(t)
    return dt.astimezone(TZ).strftime("%d.%m, %H:%M") if dt else "–"


def ago(t: str | None, now: datetime) -> str:
    dt = _parse(t)
    if not dt:
        return ""
    minutes = max(0, int((now - dt).total_seconds() // 60))
    if minutes < 60:
        return f"{minutes} min temu"
    if minutes < 48 * 60:
        return f"{minutes // 60} h temu"
    return f"{minutes // 1440} dni temu"


def day(d: str | None) -> str:
    return date.fromisoformat(d).strftime("%d.%m") if d else "–"


def pct(n: float, total: float) -> int:
    return round(100 * n / total) if total else 0


def build(status: dict | None, now: datetime) -> dict:
    if not status:
        return {"available": False}
    gen = _parse(status.get("generated"))
    out: dict = {
        "available": True,
        "generated": local(status.get("generated")),
        "generated_ago": ago(status.get("generated"), now),
        "stale": gen is None or (now - gen).total_seconds() > STALE_AFTER_H * 3600,
        "run_url": (status.get("run") or {}).get("url"),
    }

    r = status.get("ranking")
    out["ranking"] = (
        {
            "published": local(r.get("published")),
            "window": f"{day(r['window']['from'])}–{day(r['window']['to'])}" if r.get("window") else "–",
            "cells_ranked": r.get("cells_ranked") or 0,
            "cells_total": r.get("cells_total") or 0,
            "pct": pct(r.get("cells_ranked") or 0, r.get("cells_total") or 0),
        }
        if r and r.get("cells_ranked")
        else None
    )

    fc = status.get("forecasts") or {}
    total = fc.get("cells_total") or 0
    out["forecasts"] = {
        "window": f"{day(fc['target']['from'])}–{day(fc['target']['to'])}" if fc.get("target") else "–",
        "min_days": fc.get("min_days", 20),
        "cells_total": total,
        "models": [
            {
                "name": pl.MODELS.get(m["model"], (m["model"],))[0],
                "core": m.get("core", True),
                "ready_pct": pct(m.get("cells_min_days", 0), total),
                "remaining": m.get("remaining_cost", 0),
            }
            for m in fc.get("models", [])
        ],
        "remaining": fc.get("remaining_cost", 0),
        # whole days of the pipeline's daily Open-Meteo allowance still needed
        "eta_days": math.ceil(fc["remaining_cost"] / fc["daily_budget"]) if fc.get("daily_budget") else None,
    }

    b = status.get("budget") or {}
    usage, limits = b.get("usage", {}), b.get("limits", {})
    out["budget"] = [
        {
            "label": label,
            "used": round(usage.get(key, 0)),
            "limit": round(limits.get(key, 0)),
            "pct": pct(usage.get(key, 0), limits.get(key, 0)),
        }
        for key, label in (
            ("per_hour", "ostatnia godzina"),
            ("per_day", "ostatnie 24 h"),
            ("per_month", "ostatnie 30 dni"),
        )
        if limits.get(key)
    ]

    out["observations"] = [
        {
            "label": pl.STATUS_SOURCES.get(o["key"], o["key"]),
            "latest": day(o.get("latest")),
            "lag_days": (now.date() - date.fromisoformat(o["latest"])).days if o.get("latest") else None,
            "ok": bool(o.get("ok")),
        }
        for o in status.get("observations", [])
    ]
    out["pollers"] = [
        {
            "label": pl.STATUS_SOURCES.get(p["key"], p["key"]),
            "last": local(p.get("last")),
            "last_ago": ago(p.get("last"), now),
            "polls_today": p.get("polls_today", 0),
            "ok": bool(p.get("ok")),
        }
        for p in status.get("pollers", [])
    ]
    runs = status.get("runs")
    out["runs"] = (
        [
            {
                # GitHub names a run of an unparsable workflow file after its path
                "label": pl.STATUS_WORKFLOWS.get(x["workflow"])
                or (pl.STATUS_INVALID_WORKFLOW if x["workflow"].startswith(".github/") else x["workflow"]),
                "started": local(x.get("started")),
                "result": pl.STATUS_RESULTS.get(x.get("conclusion") or x.get("status"), x.get("conclusion") or "–"),
                "ok": x.get("conclusion") == "success",
                "running": x.get("status") != "completed",
                "url": x.get("url"),
            }
            for x in runs
        ]
        if runs is not None
        else None
    )
    return out
