"""Publish the rankings to R2 for the web host (SPEC §7.2) with the data-quality gate of §12.

Gate: no publication when there are no ranked cells, or when the number of ranked cells drops by more than
MAX_DROP against the currently published meta. The job then fails with a GitHub annotation and the host keeps
serving the previous rankings. `--force` overrides the gate (for intended changes, e.g. a new grid).

    python -m pipeline.publish [--force]
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

from lepszapogoda import publication
from pipeline.paths import DATA_DIR
from pipeline.storage import bucket_name, client

MAX_DROP = 0.20
KEEP_ARCHIVES = 7


class GateError(RuntimeError):
    pass


def check_gate(new_meta: dict, prev_meta: dict | None) -> None:
    n = new_meta.get("cells_ranked", 0)
    if n == 0:
        raise GateError("no ranked cells")
    if prev_meta and prev_meta.get("grid_version") == new_meta.get("grid_version"):
        prev = prev_meta.get("cells_ranked", 0)
        if prev and n < (1 - MAX_DROP) * prev:
            raise GateError(f"ranked cells dropped from {prev} to {n} (more than {MAX_DROP:.0%})")


def get_published_meta(s3, bucket: str) -> dict | None:
    try:
        return json.loads(s3.get_object(Bucket=bucket, Key=publication.META_KEY)["Body"].read())
    except Exception as e:  # noqa: BLE001
        if "NoSuchKey" in str(e) or "404" in str(e):
            return None
        raise


def publish(rankings_dir: Path, s3, bucket: str, force: bool = False, now: datetime | None = None) -> dict:
    meta = json.loads((rankings_dir / "meta.json").read_text(encoding="utf-8"))
    prev = get_published_meta(s3, bucket)
    if prev is None and meta.get("cells_ranked", 0) == 0:
        # Bootstrap (forecast backfill still running): nothing to publish yet, and nothing published to protect
        return {"status": "skipped", "reason": "no ranked cells yet, nothing published before"}
    if not force:
        check_gate(meta, prev)
    data = publication.build_archive(rankings_dir)
    digest = publication.sha256(data)
    if prev and prev.get("sha256") == digest:
        return {"status": "unchanged", **{k: prev[k] for k in ("archive", "sha256", "files")}}
    now = now or datetime.now(UTC)
    key = publication.archive_key(now.strftime("%Y%m%dT%H%M%SZ"))
    n_files = len(list((rankings_dir / "cells").glob("*.json")))
    s3.put_object(Bucket=bucket, Key=key, Body=data, ContentType="application/gzip")
    pub_meta = {
        **meta,
        "archive": key,
        "sha256": digest,
        "files": n_files,
        "published": now.strftime("%Y-%m-%dT%H:%MZ"),
    }
    # The pointer goes last: until it is written, consumers keep seeing the previous, complete publication
    s3.put_object(
        Bucket=bucket,
        Key=publication.META_KEY,
        Body=json.dumps(pub_meta, ensure_ascii=False, indent=1).encode(),
        ContentType="application/json",
    )
    prune_archives(s3, bucket, keep=KEEP_ARCHIVES)
    return {"status": "published", "archive": key, "sha256": digest, "files": n_files, "bytes": len(data)}


def prune_archives(s3, bucket: str, keep: int) -> None:
    keys = []
    for page in s3.get_paginator("list_objects_v2").paginate(Bucket=bucket, Prefix=publication.ARCHIVE_DIR):
        keys += [o["Key"] for o in page.get("Contents", [])]
    for k in sorted(keys)[:-keep]:  # names sort by timestamp
        s3.delete_object(Bucket=bucket, Key=k)


def main() -> None:
    p = argparse.ArgumentParser(description="Publish rankings to R2")
    p.add_argument("--force", action="store_true", help="skip the data-quality gate")
    a = p.parse_args()
    try:
        result = publish(DATA_DIR / "rankings", client(), bucket_name(), force=a.force)
    except GateError as e:
        print(f"::error title=Rankings not published::{e}")
        sys.exit(2)
    print(json.dumps(result, indent=1))


if __name__ == "__main__":
    main()
