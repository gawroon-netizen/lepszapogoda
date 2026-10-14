"""Host cron, daily (SPEC §7.4): remove forecast cache files and logs older than 7 days.

python web/cron/cleanup.py
"""

import os
import time
from pathlib import Path

WEB_DIR = Path(__file__).resolve().parents[1]
VAR_DIR = Path(os.environ.get("WEB_VAR_DIR", WEB_DIR / "var"))
MAX_AGE_S = 7 * 86400


def cleanup(var_dir: Path = VAR_DIR, now: float | None = None) -> dict[str, int]:
    now = now or time.time()
    removed = {}
    for sub, pattern in (("cache", "fc_*.json"), ("log", "*.log*")):
        n = 0
        for p in (var_dir / sub).glob(pattern):
            if now - p.stat().st_mtime > MAX_AGE_S:
                p.unlink(missing_ok=True)
                n += 1
        removed[sub] = n
    return removed


if __name__ == "__main__":
    print(cleanup())
