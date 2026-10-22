"""Sync of the pipeline data directory with Cloudflare R2 (SPEC §7.2).

A CI run starts on an empty machine: `pull` brings the state and inputs it needs from R2 into DATA_DIR,
the job works on local files as usual, `push` uploads every file created or changed during the run.
Keys in the bucket mirror paths under DATA_DIR, under the prefix `pipeline/`.

    python -m pipeline.storage pull forecasts/manifest.json openmeteo_ledger.json obs/imgw_hourly/
    python -m pipeline.storage push            # files changed since the last pull/snapshot
    python -m pipeline.storage push --all      # everything (one-off migration of local data)
    python -m pipeline.storage prune obs/imgw_meteo_raw/ --keep-days 14   # delete old {date}/ folders in R2

Credentials from R2_ENDPOINT, R2_KEY, R2_SECRET, R2_BUCKET (SPEC §9).
"""

from __future__ import annotations

import argparse
import json
import os
from datetime import UTC, date, datetime, timedelta
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


def _mark_synced(data_dir: Path, rels: list[str]) -> None:
    """Record the current state of just these files in the snapshot. A pull in the middle of a run must not mark
    files the run created or changed earlier as synced (2026-10-22: the daily job's second pull did exactly that,
    and two weeks of observations were never pushed)."""
    path = data_dir / SNAPSHOT
    state = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    for rel in rels:
        p = data_dir / rel
        if p.is_file():
            state[rel] = [p.stat().st_size, p.stat().st_mtime]
    data_dir.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state), encoding="utf-8")


def changed_files(data_dir: Path = DATA_DIR) -> list[str]:
    path = data_dir / SNAPSHOT
    before = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    return sorted(k for k, v in _local_state(data_dir).items() if before.get(k) != v)


def pull(paths: list[str], data_dir: Path = DATA_DIR, s3=None) -> int:
    """Download keys; a path ending in '/' is a prefix (all objects under it). Missing keys are fine."""
    s3 = s3 or client()
    bucket = bucket_name()
    pulled: list[str] = []
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
                pulled.append(key[len(PREFIX) :])
            except Exception as e:  # noqa: BLE001
                if "404" in str(e) or "Not Found" in str(e):
                    continue  # first run: state does not exist yet
                raise
    _mark_synced(data_dir, pulled)
    return len(pulled)


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


def prune(prefix: str, keep_days: int, today: date | None = None, s3=None) -> int:
    """Delete objects under `prefix` whose next path segment is a date older than `keep_days` (raw polls that
    were already converted to Parquet). Keys without a date segment are left alone. Returns objects deleted."""
    s3 = s3 or client()
    bucket = bucket_name()
    cutoff = (today or datetime.now(UTC).date()) - timedelta(days=keep_days)
    old = []
    for page in s3.get_paginator("list_objects_v2").paginate(Bucket=bucket, Prefix=PREFIX + prefix):
        for o in page.get("Contents", []):
            segment = o["Key"][len(PREFIX + prefix) :].split("/")[0]
            try:
                if date.fromisoformat(segment) < cutoff:
                    old.append(o["Key"])
            except ValueError:
                continue
    for i in range(0, len(old), 1000):  # DeleteObjects takes at most 1000 keys
        s3.delete_objects(Bucket=bucket, Delete={"Objects": [{"Key": k} for k in old[i : i + 1000]], "Quiet": True})
    return len(old)


def main() -> None:
    p = argparse.ArgumentParser(description="Sync DATA_DIR with R2")
    sub = p.add_subparsers(dest="cmd", required=True)
    pl = sub.add_parser("pull")
    pl.add_argument("paths", nargs="+")
    ps = sub.add_parser("push")
    ps.add_argument("--all", action="store_true")
    pr = sub.add_parser("prune")
    pr.add_argument("prefix")
    pr.add_argument("--keep-days", type=int, required=True)
    a = p.parse_args()
    if a.cmd == "pull":
        print(f"pulled {pull(a.paths)} files")
    elif a.cmd == "prune":
        print(f"deleted {prune(a.prefix, a.keep_days)} objects older than {a.keep_days} days under {a.prefix}")
    else:
        print(f"pushed {push(everything=a.all)} files")


if __name__ == "__main__":
    main()
