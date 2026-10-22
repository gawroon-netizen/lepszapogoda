"""Publication contract between the pipeline (producer) and the web host (consumer), SPEC §7.2, §7.4.

R2 layout:
    publish/meta.json                              pointer to the current archive, written last
    publish/archives/rankings-{stamp}.tar.gz       cells/{cell_id}.json + meta.json
    publish/status.json                            pipeline status for the /stan-danych page (pipeline.status)

meta.json: the ranking meta (pipeline.verify.ranking) plus
    {"archive": "<key>", "sha256": "<hex>", "files": <number of cell files>, "published": "<UTC time>"}

Archives are versioned and never overwritten, so a consumer that read meta.json always downloads the archive it
describes. gzip (stdlib) rather than zstd: the host runs FreeBSD where compiled extensions are a risk (SPEC §14).
"""

from __future__ import annotations

import gzip
import hashlib
import io
import json
import tarfile
from pathlib import Path

from lepszapogoda import grid

PREFIX = "publish/"
META_KEY = PREFIX + "meta.json"
ARCHIVE_DIR = PREFIX + "archives/"
STATUS_KEY = PREFIX + "status.json"


def archive_key(stamp: str) -> str:
    return f"{ARCHIVE_DIR}rankings-{stamp}.tar.gz"


def build_archive(rankings_dir: Path) -> bytes:
    """Deterministic tar.gz of cells/*.json and meta.json: same files -> same bytes (sorted, mtime 0, no owners)."""
    buf = io.BytesIO()
    paths = sorted((rankings_dir / "cells").glob("*.json")) + [rankings_dir / "meta.json"]
    # mtime=0 in the gzip header too, otherwise the archive hash changes on every run
    with gzip.GzipFile(fileobj=buf, mode="wb", mtime=0) as gz, tarfile.open(fileobj=gz, mode="w") as tar:
        for p in paths:
            data = p.read_bytes()
            info = tarfile.TarInfo(name=p.relative_to(rankings_dir).as_posix())
            info.size = len(data)
            info.mtime = 0
            info.mode = 0o644
            tar.addfile(info, io.BytesIO(data))
    return buf.getvalue()


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def validate_extracted(directory: Path, meta: dict) -> list[str]:
    """Problems found in an extracted archive; empty list = OK. Used by the host before swapping directories."""
    problems = []
    files = sorted((directory / "cells").glob("*.json"))
    if len(files) != meta.get("files"):
        problems.append(f"{len(files)} cell files, meta says {meta.get('files')}")
    for f in files:
        try:
            j = json.loads(f.read_text(encoding="utf-8"))
        except ValueError:
            problems.append(f"{f.name}: not JSON")
            continue
        if j.get("grid_version") != grid.GRID_VERSION:
            problems.append(f"{f.name}: grid_version {j.get('grid_version')}")
        if f.stem != j.get("cell") or not grid.is_valid_cell_id(f.stem):
            problems.append(f"{f.name}: cell id mismatch")
        if not j.get("accurate"):
            problems.append(f"{f.name}: empty ranking")
        if len(problems) > 20:
            break
    return problems
