"""R2 sync with an in-memory fake S3 client."""

import time

import pytest

from pipeline import storage


class FakeS3:
    def __init__(self):
        self.objects: dict[str, bytes] = {}

    def upload_file(self, filename, bucket, key):
        with open(filename, "rb") as f:
            self.objects[key] = f.read()

    def download_file(self, bucket, key, filename):
        if key not in self.objects:
            raise RuntimeError("An error occurred (404) when calling the HeadObject operation: Not Found")
        with open(filename, "wb") as f:
            f.write(self.objects[key])

    def delete_objects(self, Bucket, Delete):  # noqa: N803 - boto3 signature
        for o in Delete["Objects"]:
            self.objects.pop(o["Key"], None)

    def get_paginator(self, name):
        objects = self.objects

        class P:
            def paginate(self, Bucket, Prefix):  # noqa: N803 - boto3 signature
                yield {"Contents": [{"Key": k} for k in sorted(objects) if k.startswith(Prefix)]}

        return P()


@pytest.fixture(autouse=True)
def bucket_env(monkeypatch):
    monkeypatch.setenv("R2_BUCKET", "test")


def test_push_uploads_only_changed_files(tmp_path):
    s3 = FakeS3()
    (tmp_path / "a.txt").write_text("1")
    storage.snapshot(tmp_path)
    (tmp_path / "obs").mkdir()
    (tmp_path / "obs" / "b.parquet").write_bytes(b"x")
    assert storage.push(tmp_path, s3=s3) == 1
    assert set(s3.objects) == {"pipeline/obs/b.parquet"}
    time.sleep(0.01)
    (tmp_path / "a.txt").write_text("22")
    assert storage.push(tmp_path, s3=s3) == 1
    assert s3.objects["pipeline/a.txt"] == b"22"
    assert storage.push(tmp_path, s3=s3) == 0


def test_pull_files_and_prefixes_then_nothing_to_push(tmp_path):
    s3 = FakeS3()
    s3.objects = {
        "pipeline/forecasts/manifest.json": b"{}",
        "pipeline/obs/imgw_hourly/2026-10-11.parquet": b"p1",
        "pipeline/obs/imgw_hourly/2026-10-12.parquet": b"p2",
        "pipeline/obs/imerg/2026-10-09.parquet": b"other",
    }
    n = storage.pull(["forecasts/manifest.json", "openmeteo_ledger.json", "obs/imgw_hourly/"], tmp_path, s3=s3)
    assert n == 3  # the missing ledger is not an error (first run)
    assert (tmp_path / "obs" / "imgw_hourly" / "2026-10-12.parquet").read_bytes() == b"p2"
    assert not (tmp_path / "obs" / "imerg").exists()
    assert storage.push(tmp_path, s3=s3) == 0


def test_push_all(tmp_path):
    s3 = FakeS3()
    (tmp_path / "x").write_text("x")
    storage.snapshot(tmp_path)
    assert storage.push(tmp_path, everything=True, s3=s3) == 1


def test_prune_deletes_only_old_date_folders():
    from datetime import date

    s3 = FakeS3()
    s3.objects = {
        "pipeline/obs/imgw_meteo_raw/2026-10-01/0000.json.gz": b"old",
        "pipeline/obs/imgw_meteo_raw/2026-10-06/0005.json.gz": b"kept: exactly keep_days old",
        "pipeline/obs/imgw_meteo_raw/2026-10-20/0005.json.gz": b"new",
        "pipeline/obs/imgw_meteo_raw/README": b"no date segment",
        "pipeline/obs/imgw_raw/2026-09-01/0005.json": b"other prefix",
    }
    assert storage.prune("obs/imgw_meteo_raw/", 14, today=date(2026, 10, 20), s3=s3) == 1
    assert "pipeline/obs/imgw_meteo_raw/2026-10-01/0000.json.gz" not in s3.objects
    assert len(s3.objects) == 4


def test_pull_mid_run_keeps_earlier_changes_pending(tmp_path):
    # the daily job: pull inputs, compute observations, pull forecasts for verification, push everything new
    s3 = FakeS3()
    s3.objects = {"pipeline/obs/imerg/2026-10-01.parquet": b"old", "pipeline/forecasts/manifest.json": b"{}"}
    storage.pull(["obs/imerg/"], tmp_path, s3=s3)
    (tmp_path / "obs" / "imerg" / "2026-10-20.parquet").write_bytes(b"new day")
    storage.pull(["forecasts/"], tmp_path, s3=s3)
    assert storage.push(tmp_path, s3=s3) == 1
    assert s3.objects["pipeline/obs/imerg/2026-10-20.parquet"] == b"new day"
