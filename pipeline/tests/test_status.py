"""Pipeline status (publish/status.json) from an in-memory fake R2."""

import io
import json
from datetime import UTC, date, datetime, timedelta

import pytest

from lepszapogoda import grid, openmeteo, publication
from pipeline import status
from pipeline.ingest import forecasts

NOW = datetime(2026, 10, 22, 8, 10, tzinfo=UTC)


class FakeS3:
    def __init__(self):
        self.objects: dict[str, tuple[bytes, datetime]] = {}

    def add(self, key, body=b"x", modified=NOW):
        self.objects[key] = (body if isinstance(body, bytes) else json.dumps(body).encode(), modified)

    def get_object(self, Bucket, Key):  # noqa: N803 - boto3 signature
        if Key not in self.objects:
            raise RuntimeError("An error occurred (NoSuchKey) when calling the GetObject operation")
        return {"Body": io.BytesIO(self.objects[Key][0])}

    def put_object(self, Bucket, Key, Body, ContentType=None):  # noqa: N803
        self.add(Key, Body)

    def get_paginator(self, name):
        objects = self.objects

        class P:
            def paginate(self, Bucket, Prefix):  # noqa: N803
                yield {
                    "Contents": [
                        {"Key": k, "LastModified": m} for k, (_, m) in sorted(objects.items()) if k.startswith(Prefix)
                    ]
                }

        return P()


def test_forecast_status_counts_cells_and_remaining_cost(tmp_path):
    m = forecasts.Manifest(tmp_path / "m.json")
    t_start, t_end = forecasts.target_range(NOW.date())
    cells = [c.cell_id for c in grid.poland_cells()]
    for cid in cells:
        m.add("ecmwf_ifs", cid, t_start, t_end)  # complete
        m.add("gfs_seamless", cid, t_start + timedelta(days=9), t_end)  # 21 days: enough to rank, not complete
    st = status.forecast_status(m, NOW.date())
    by = {x["model"]: x for x in st["models"]}
    assert by["ecmwf_ifs"]["cells_complete"] == len(cells) and by["ecmwf_ifs"]["remaining_cost"] == 0
    assert by["gfs_seamless"]["cells_complete"] == 0 and by["gfs_seamless"]["cells_min_days"] == len(cells)
    assert by["icon_seamless"]["cells_min_days"] == 0 and by["icon_seamless"]["remaining_cost"] > 0
    assert by["ncep_aigfs025"]["core"] is False and by["ecmwf_ifs"]["core"] is True
    assert st["remaining_cost"] == pytest.approx(sum(x["remaining_cost"] for x in st["models"]), abs=len(st["models"]))


def test_observations_and_pollers():
    s3 = FakeS3()
    s3.add("pipeline/obs/imerg/2026-10-19.parquet")
    s3.add("pipeline/obs/imerg/2026-10-20.parquet")
    s3.add("pipeline/obs/modis_terra/2026-10-14.parquet")  # 8 days old: stale
    s3.add("pipeline/obs/imgw_meteo_raw/2026-10-22/0805.json.gz", modified=NOW - timedelta(minutes=5))
    s3.add("pipeline/obs/imgw_meteo_raw/2026-10-21/2355.json.gz", modified=NOW - timedelta(hours=8))
    s3.add("pipeline/obs/imgw_raw/2026-10-22/0635.json", modified=NOW - timedelta(minutes=120))
    obs = {o["key"]: o for o in status.observation_status(s3, "b", NOW.date())}
    assert obs["imerg"]["latest"] == "2026-10-20" and obs["imerg"]["ok"]
    assert not obs["modis_terra"]["ok"] and obs["modis_aqua"]["latest"] is None
    pol = {p["key"]: p for p in status.poller_status(s3, "b", NOW)}
    assert pol["imgw_meteo"]["ok"] and pol["imgw_meteo"]["polls_today"] == 1
    assert pol["imgw_meteo"]["last"] == "2026-10-22T08:05Z"
    assert not pol["imgw_synop"]["ok"]  # 2 h since the last synop poll (every 30 min)


def test_github_runs_skip_ci_and_need_a_token(monkeypatch):
    class R:
        def raise_for_status(self):
            pass

        def json(self):
            run = {
                "event": "schedule",
                "status": "completed",
                "conclusion": "success",
                "created_at": "t",
                "updated_at": "t",
                "html_url": "u",
            }
            return {"workflow_runs": [{**run, "name": "ci"}, {**run, "name": "pipeline-hourly"}]}

    class S:
        def get(self, url, headers, timeout):
            assert headers["Authorization"] == "Bearer tok"
            return R()

    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    assert status.github_runs(S()) is None
    monkeypatch.setenv("GITHUB_REPOSITORY", "o/r")
    monkeypatch.setenv("GITHUB_TOKEN", "tok")
    assert [r["workflow"] for r in status.github_runs(S())] == ["pipeline-hourly"]


def test_build_without_any_state(monkeypatch):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("GITHUB_RUN_ID", raising=False)
    s3 = FakeS3()
    st = status.build(s3, "b", NOW)
    assert st["ranking"] is None and st["runs"] is None
    assert st["budget"]["usage"]["per_day"] == 0 and st["budget"]["limits"]["per_day"] == 10_000
    assert st["forecasts"]["remaining_cost"] > 100_000  # nothing fetched yet: the whole backfill
    json.dumps(st)  # serialisable


def test_build_reads_published_meta_and_ledger(monkeypatch):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    s3 = FakeS3()
    s3.add(
        publication.META_KEY,
        {"published": "2026-10-22T05:50Z", "cells_ranked": 4000, "cells_total": 4313, "sha256": "x", "archive": "a"},
    )
    s3.add("pipeline/openmeteo_ledger.json", {"entries": [[NOW.timestamp() - 3600, 450.0]]})
    st = status.build(s3, "b", NOW)
    assert st["ranking"]["cells_ranked"] == 4000 and "sha256" not in st["ranking"]
    assert st["budget"]["usage"]["per_day"] == pytest.approx(450.0)


def test_newest_date_ignores_other_names():
    keys = [{"Key": "pipeline/obs/imerg/2026-10-01.parquet"}, {"Key": "pipeline/obs/imerg/README"}]
    assert status.newest_date(keys) == "2026-10-01"
    assert date.fromisoformat(status.newest_date(keys))
    assert openmeteo.MODELS  # imported for the model list used above
