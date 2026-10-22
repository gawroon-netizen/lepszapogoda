"""Host cron pull_rankings: round trip with the pipeline publisher, idempotence, integrity checks."""

import io
import json
import tarfile
from datetime import UTC, datetime

import pytest

from lepszapogoda import grid, publication
from pipeline import publish
from pipeline.tests.test_publish import CELLS, write_rankings
from web.cron import pull_rankings

NOW = datetime(2026, 10, 13, 6, 0, tzinfo=UTC)


@pytest.fixture
def published(tmp_path, fake_s3):
    write_rankings(tmp_path / "pipeline", CELLS)
    publish.publish(tmp_path / "pipeline", fake_s3, "b", now=NOW)
    return fake_s3


def test_round_trip_and_idempotence(tmp_path, published):
    web = tmp_path / "web"
    assert pull_rankings.pull(published, "b", web).startswith("updated: 100 cells")
    assert len(list((web / "rankings" / "cells").glob("*.json"))) == 100
    meta = json.loads((web / "rankings" / "meta.json").read_text(encoding="utf-8"))
    assert meta["sha256"] == json.loads(published.objects[publication.META_KEY])["sha256"]
    assert pull_rankings.pull(published, "b", web) == "up-to-date"
    assert not (web / "rankings.tmp").exists() and not (web / "rankings.old").exists()


def test_nothing_published_yet_is_not_an_error(tmp_path, fake_s3):
    assert pull_rankings.pull(fake_s3, "b", tmp_path / "web") == "nothing published yet"
    assert not (tmp_path / "web" / "rankings").exists()


def test_corrupted_archive_keeps_current_rankings(tmp_path, published):
    web = tmp_path / "web"
    pull_rankings.pull(published, "b", web)
    meta = json.loads(published.objects[publication.META_KEY])
    meta["sha256"] = "0" * 64  # pretend a new publication whose archive does not match
    published.objects[publication.META_KEY] = json.dumps(meta).encode()
    with pytest.raises(pull_rankings.PullError, match="sha256"):
        pull_rankings.pull(published, "b", web)
    assert len(list((web / "rankings" / "cells").glob("*.json"))) == 100


def malicious_archive(name: str) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        data = b"{}"
        info = tarfile.TarInfo(name)
        info.size = len(data)
        tar.addfile(info, io.BytesIO(data))
    return buf.getvalue()


@pytest.mark.parametrize("name", ["../evil.json", "/etc/passwd", "cells/../../x.json", "other/a.json"])
def test_unexpected_members_are_rejected(tmp_path, fake_s3, name):
    data = malicious_archive(name)
    fake_s3.objects["publish/archives/x.tar.gz"] = data
    meta = {"archive": "publish/archives/x.tar.gz", "sha256": publication.sha256(data), "files": 1}
    fake_s3.objects[publication.META_KEY] = json.dumps(meta).encode()
    with pytest.raises(pull_rankings.PullError, match="unexpected"):
        pull_rankings.pull(fake_s3, "b", tmp_path / "web")
    assert not (tmp_path / "web" / "rankings").exists()


def test_file_count_mismatch_is_rejected(tmp_path, published):
    meta = json.loads(published.objects[publication.META_KEY])
    meta["files"] = 101
    published.objects[publication.META_KEY] = json.dumps(meta).encode()
    with pytest.raises(pull_rankings.PullError, match="cell files"):
        pull_rankings.pull(published, "b", tmp_path / "web")


def test_validate_detects_wrong_grid(tmp_path):
    d = tmp_path / "x"
    (d / "cells").mkdir(parents=True)
    (d / "cells" / "522_210.json").write_text(json.dumps({"grid_version": "old", "cell": "522_210", "accurate": [1]}))
    assert publication.validate_extracted(d, {"files": 1}) == ["522_210.json: grid_version old"]
    assert grid.GRID_VERSION == "latlon01"


def test_status_is_copied_and_a_broken_one_keeps_the_old(tmp_path, fake_s3):
    web = tmp_path / "web"
    assert pull_rankings.pull_status(fake_s3, "b", web) == "status: none yet"
    fake_s3.objects[publication.STATUS_KEY] = json.dumps({"generated": "2026-10-22T08:10Z"}).encode()
    assert pull_rankings.pull_status(fake_s3, "b", web) == "status: updated"
    fake_s3.objects[publication.STATUS_KEY] = b"[1, 2"
    with pytest.raises(ValueError):
        pull_rankings.pull_status(fake_s3, "b", web)
    assert json.loads((web / "status.json").read_text(encoding="utf-8"))["generated"] == "2026-10-22T08:10Z"
