"""Pipeline data location: local directory now, synced with R2 later (SPEC §7.2)."""

import os
from pathlib import Path

DATA_DIR = Path(os.environ.get("LP_DATA_DIR", Path(__file__).resolve().parents[1] / "data"))
