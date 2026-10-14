"""Read published rankings on the web host (SPEC §7.4): web/data/rankings/{cells/<cell_id>.json, meta.json}."""

from __future__ import annotations

import json
from pathlib import Path

from lepszapogoda import grid


def load_cell(rankings_dir: Path, cell_id: str | None) -> dict | None:
    """The cell's ranking JSON, or None when the cell has no ranking (yet) or the file is unreadable."""
    if not cell_id or not grid.is_valid_cell_id(cell_id):
        return None
    path = rankings_dir / "cells" / f"{cell_id}.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if data.get("grid_version") == grid.GRID_VERSION and data.get("accurate") else None


def load_meta(rankings_dir: Path) -> dict | None:
    try:
        return json.loads((rankings_dir / "meta.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
