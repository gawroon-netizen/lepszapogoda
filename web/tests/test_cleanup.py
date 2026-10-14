import os
import time

from web.cron.cleanup import cleanup


def test_cleanup_removes_only_old_files(tmp_path):
    (tmp_path / "cache").mkdir()
    (tmp_path / "log").mkdir()
    old, new = tmp_path / "cache" / "fc_52.00_21.00.json", tmp_path / "cache" / "fc_50.00_19.00.json"
    other = tmp_path / "cache" / "keep.txt"
    for p in (old, new, other):
        p.write_text("{}")
    week_ago = time.time() - 8 * 86400
    os.utime(old, (week_ago, week_ago))
    os.utime(other, (week_ago, week_ago))
    assert cleanup(tmp_path) == {"cache": 1, "log": 0}
    assert not old.exists() and new.exists() and other.exists()
