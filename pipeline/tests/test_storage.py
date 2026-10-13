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
