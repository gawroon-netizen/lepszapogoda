"""Host cron (every 30 min, SPEC §7.4): fetch the published rankings from R2 and swap them in.

Idempotent and safe to interrupt:
- compares the published meta.json sha256 with the local one, does nothing when equal;
- downloads the archive the meta points to, checks its sha256, extracts to rankings.tmp, validates the files
  (count, JSON, grid version, cell ids), and only then replaces web/data/rankings;
- on any problem the current rankings stay untouched and the exit code is non-zero (visible in the cron log).

Environment (read-only R2 token, SPEC §9): R2_ENDPOINT, R2_BUCKET, R2_KEY_RO, R2_SECRET_RO; WEB_DATA_DIR optional.

    python web/cron/pull_rankings.py
"""

from __future__ import annotations

import io
import json
import os
import shutil
import sys
import tarfile
from pathlib import Path

from lepszapogoda import publication

WEB_DATA_DIR = Path(os.environ.get("WEB_DATA_DIR", Path(__file__).resolve().parents[1] / "data"))


class PullError(RuntimeError):
    pass


def _client():
    import boto3

    return boto3.client(
        "s3",
        endpoint_url=os.environ["R2_ENDPOINT"].strip(),
        aws_access_key_id=os.environ["R2_KEY_RO"].strip(),
        aws_secret_access_key=os.environ["R2_SECRET_RO"].strip(),
        region_name="auto",
    )


def _safe_extract(data: bytes, dest: Path) -> None:
    """Extract only regular files named cells/*.json or meta.json (no absolute paths, no '..', no links)."""
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tar:
        for m in tar.getmembers():
            parts = Path(m.name).parts
            ok_name = m.name == "meta.json" or (len(parts) == 2 and parts[0] == "cells" and m.name.endswith(".json"))
            if not m.isfile() or not ok_name or ".." in parts or Path(m.name).is_absolute():
                raise PullError(f"unexpected archive member: {m.name!r}")
            target = dest / m.name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(tar.extractfile(m).read())


def pull(s3, bucket: str, web_data: Path = WEB_DATA_DIR) -> str:
    current = web_data / "rankings"
    local_meta = current / "meta.json"
    remote = json.loads(s3.get_object(Bucket=bucket, Key=publication.META_KEY)["Body"].read())
    if local_meta.exists() and json.loads(local_meta.read_text(encoding="utf-8")).get("sha256") == remote["sha256"]:
        return "up-to-date"
    data = s3.get_object(Bucket=bucket, Key=remote["archive"])["Body"].read()
    if publication.sha256(data) != remote["sha256"]:
        raise PullError("archive sha256 does not match meta.json")
    tmp = web_data / "rankings.tmp"
    if tmp.exists():
        shutil.rmtree(tmp)
    tmp.mkdir(parents=True)
    try:
        _safe_extract(data, tmp)
        problems = publication.validate_extracted(tmp, remote)
        if problems:
            raise PullError("; ".join(problems[:5]))
        # The published meta (with archive, sha256, files) replaces the one inside the archive
        (tmp / "meta.json").write_text(json.dumps(remote, ensure_ascii=False, indent=1), encoding="utf-8")
    except Exception:
        shutil.rmtree(tmp, ignore_errors=True)
        raise
    old = web_data / "rankings.old"
    if old.exists():
        shutil.rmtree(old)
    if current.exists():
        current.rename(old)
    tmp.rename(current)
    shutil.rmtree(old, ignore_errors=True)
    return f"updated: {remote['files']} cells, published {remote.get('published')}"


def main() -> None:
    try:
        print(pull(_client(), os.environ["R2_BUCKET"].strip()))
    except PullError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
