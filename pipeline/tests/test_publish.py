"""Publication: deterministic archive, data-quality gate (SPEC §12), pointer written last, pruning."""

import json
from datetime import UTC, datetime, timedelta

import pytest

from lepszapogoda import grid, publication
from pipeline import publish


def write_rankings(d, cells, computed="2026-10-13T05:00Z"):
    (d / "cells").mkdir(parents=True, exist_ok=True)
    for cid in cells:
        j = {"grid_version": grid.GRID_VERSION, "cell": cid, "accurate": [{"model": "ecmwf_ifs", "score": 100}]}
        (d / "cells" / f"{cid}.json").write_text(json.dumps(j), encoding="utf-8")
    meta = {"grid_version": grid.GRID_VERSION, "computed": computed, "cells_ranked": len(cells)}
    (d / "meta.json").write_text(json.dumps(meta), encoding="utf-8")


CELLS = [c.cell_id for c in grid.poland_cells()[:100]]
NOW = datetime(2026, 10, 13, 6, 0, tzinfo=UTC)


def test_archive_is_deterministic(tmp_path):
    write_rankings(tmp_path / "a", CELLS)
    write_rankings(tmp_path / "b", CELLS[::-1])
    assert publication.sha256(publication.build_archive(tmp_path / "a")) == publication.sha256(
        publication.build_archive(tmp_path / "b")
    )


def test_gate():
    publish.check_gate({"cells_ranked": 100, "grid_version": "latlon01"}, None)  # first publication
    publish.check_gate(
        {"cells_ranked": 81, "grid_version": "latlon01"}, {"cells_ranked": 100, "grid_version": "latlon01"}
    )
    with pytest.raises(publish.GateError, match="dropped"):
        publish.check_gate(
            {"cells_ranked": 79, "grid_version": "latlon01"}, {"cells_ranked": 100, "grid_version": "latlon01"}
        )
    with pytest.raises(publish.GateError, match="no ranked"):
        publish.check_gate({"cells_ranked": 0, "grid_version": "latlon01"}, None)
    # a new grid version is a different product: no comparison
    publish.check_gate(
        {"cells_ranked": 10, "grid_version": "healpix8"}, {"cells_ranked": 100, "grid_version": "latlon01"}
    )


def test_publish_writes_archive_then_pointer(tmp_path, fake_s3):
    write_rankings(tmp_path, CELLS)
    r = publish.publish(tmp_path, fake_s3, "b", now=NOW)
    assert r["status"] == "published" and r["files"] == 100
    assert fake_s3.puts == [publication.archive_key("20261013T060000Z"), publication.META_KEY]
    meta = json.loads(fake_s3.objects[publication.META_KEY])
    assert meta["archive"] == r["archive"] and meta["sha256"] == r["sha256"] and meta["cells_ranked"] == 100


def test_publish_refuses_big_drop_and_keeps_previous(tmp_path, fake_s3):
    write_rankings(tmp_path / "a", CELLS)
    publish.publish(tmp_path / "a", fake_s3, "b", now=NOW)
    before = dict(fake_s3.objects)
    write_rankings(tmp_path / "b", CELLS[:50])
    with pytest.raises(publish.GateError):
        publish.publish(tmp_path / "b", fake_s3, "b", now=NOW + timedelta(days=1))
    assert fake_s3.objects == before
    assert (
        publish.publish(tmp_path / "b", fake_s3, "b", force=True, now=NOW + timedelta(days=1))["status"] == "published"
    )


def test_bootstrap_without_rankings_is_skipped_not_failed(tmp_path, fake_s3):
    write_rankings(tmp_path, [])
    assert publish.publish(tmp_path, fake_s3, "b", now=NOW)["status"] == "skipped"
    assert fake_s3.objects == {}


def test_unchanged_is_not_republished(tmp_path, fake_s3):
    write_rankings(tmp_path, CELLS)
    publish.publish(tmp_path, fake_s3, "b", now=NOW)
    assert publish.publish(tmp_path, fake_s3, "b", now=NOW + timedelta(hours=1))["status"] == "unchanged"


def test_old_archives_are_pruned(tmp_path, fake_s3):
    for k in range(10):
        write_rankings(tmp_path, CELLS, computed=f"2026-10-{k + 1:02d}T05:00Z")
        publish.publish(tmp_path, fake_s3, "b", now=NOW + timedelta(days=k))
    archives = [k for k in fake_s3.objects if k.startswith(publication.ARCHIVE_DIR)]
    assert len(archives) == publish.KEEP_ARCHIVES
    assert json.loads(fake_s3.objects[publication.META_KEY])["archive"] in archives
