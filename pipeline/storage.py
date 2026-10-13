"""Sync of the pipeline data directory with Cloudflare R2 (SPEC §7.2).

A CI run starts on an empty machine: `pull` brings the state and inputs it needs from R2 into DATA_DIR,
the job works on local files as usual, `push` uploads every file created or changed during the run.
Keys in the bucket mirror paths under DATA_DIR, under the prefix `pipeline/`.

    python -m pipeline.storage pull forecasts/manifest.json openmeteo_ledger.json obs/imgw_hourly/
    python -m pipeline.storage push            # files changed since the last pull/snapshot
    python -m pipeline.storage push --all      # everything (one-off migration of local data)

Credentials from R2_ENDPOINT, R2_KEY, R2_SECRET, R2_BUCKET (SPEC §9).
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from pipeline.paths import DATA_DIR

PREFIX = "pipeline/"
SNAPSHOT = ".r2_snapshot.json"  # sizes and mtimes of local files at pull time, to find what changed
NOT_PUSHED = ("rankings/", "rankings.tmp/", "logs/")


def client():
    import boto3

    return boto3.client(
        "s3",
        endpoint_url=os.environ["R2_ENDPOINT"].strip(),
        aws_access_key_id=os.environ["R2_KEY"].strip(),
        aws_secret_access_key=os.environ["R2_SECRET"].strip(),
        region_name="auto",
    )


def bucket_name() -> str:
    return os.environ["R2_BUCKET"].strip()


def _local_state(data_dir: Path) -> dict[str, list[float]]:
    return {
        p.relative_to(data_dir).as_posix(): [p.stat().st_size, p.stat().st_mtime]
        for p in data_dir.rglob("*")
        if p.is_file() and p.name != SNAPSHOT
    }


def snapshot(data_dir: Path = DATA_DIR) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / SNAPSHOT).write_text(json.dumps(_local_state(data_dir)), encoding="utf-8")


def changed_files(data_dir: Path = DATA_DIR) -> list[str]:
    path = data_dir / SNAPSHOT
    before = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    return sorted(k for k, v in _local_state(data_dir).items() if before.get(k) != v)


def pull(paths: list[str], data_dir: Path = DATA_DIR, s3=None) -> int:
    """Download keys; a path ending in '/' is a prefix (all objects under it). Missing keys are fine."""
    s3 = s3 or client()
    bucket = bucket_name()
    n = 0
    for p in paths:
        if p.endswith("/"):
            keys = []
            for page in s3.get_paginator("list_objects_v2").paginate(Bucket=bucket, Prefix=PREFIX + p):
                keys += [o["Key"] for o in page.get("Contents", [])]
        else:
            keys = [PREFIX + p]
        for key in keys:
            dest = data_dir / key[len(PREFIX) :]
            dest.parent.mkdir(parents=True, exist_ok=True)
            try:
                s3.download_file(bucket, key, str(dest))
                n += 1
            except Exception as e:  # noqa: BLE001
                if "404" in str(e) or "Not Found" in str(e):
                    continue  # first run: state does not exist yet
                raise
    snapshot(data_dir)
    return n


def push(data_dir: Path = DATA_DIR, everything: bool = False, s3=None) -> int:
    s3 = s3 or client()
    bucket = bucket_name()
    files = sorted(_local_state(data_dir)) if everything else changed_files(data_dir)
    # Rankings are published as one archive (pipeline.publish), not as thousands of objects
    files = [f for f in files if not f.startswith(NOT_PUSHED)]
    for rel in files:
        s3.upload_file(str(data_dir / rel), bucket, PREFIX + rel)
    snapshot(data_dir)
    return len(files)


def main() -> None:
    p = argparse.ArgumentParser(description="Sync DATA_DIR with R2")
    sub = p.add_subparsers(dest="cmd", required=True)
    pl = sub.add_parser("pull")
    pl.add_argument("paths", nargs="+")
    ps = sub.add_parser("push")
    ps.add_argument("--all", action="store_true")
    a = p.parse_args()
    if a.cmd == "pull":
        print(f"pulled {pull(a.paths)} files")
    else:
        print(f"pushed {push(everything=a.all)} files")


if __name__ == "__main__":
    main()
