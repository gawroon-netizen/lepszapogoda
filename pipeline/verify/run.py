"""Daily verification and ranking job.

1. daily model values from archived hourly forecasts (pipeline.verify.aggregate),
2. daily components against IMERG, MODIS and IMGW (pipeline.verify.components)
   -> verification/{cells,stations}/{date}.parquet,
3. rankings and blend weights (pipeline.verify.ranking) -> rankings/cells/{cell_id}.json and rankings/meta.json.

The window ends at today - END_LAG_DAYS (config): forecasts arrive up to 14 days late per cell (rotation), and only
there does every cell have them. The whole window is recomputed every day. Usage:
    python -m pipeline.verify.run [--end YYYY-MM-DD]
"""

from __future__ import annotations

import argparse
import json
import shutil
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pandas as pd

from lepszapogoda import openmeteo
from pipeline.ingest import imgw
from pipeline.paths import DATA_DIR
from pipeline.verify import aggregate, components, ranking
from pipeline.verify import config as cfg


def _read_days(folder: Path, days: list[date]) -> pd.DataFrame:
    frames = [
        pd.read_parquet(folder / f"{d.isoformat()}.parquet")
        for d in days
        if (folder / f"{d.isoformat()}.parquet").exists()
    ]
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def compute_components(end: date, data_dir: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    days = aggregate.window_dates(end, cfg.WINDOW_DAYS)
    stations = imgw.stations()
    imerg = _read_days(data_dir / "obs" / "imerg", days)
    modis = {s: _read_days(data_dir / "obs" / s, days) for s in ("modis_terra", "modis_aqua")}
    temp_obs = _read_days(data_dir / "obs" / "imgw_daily", days)
    cell_parts, station_parts = [], []
    for model in openmeteo.MODELS:
        hourly = aggregate.load_hourly(data_dir, model, days[0], days[-1])
        if hourly.empty:
            continue
        daily = aggregate.daily_values(hourly)
        daily = daily[daily["date"].isin(days)]
        if not imerg.empty:
            cell_parts.append(components.precip_components(daily, imerg, model))
        for obs in modis.values():
            if not obs.empty:
                cf = aggregate.cloud_at_overpass(hourly, obs)
                cell_parts.append(components.cloud_components(cf, obs, model))
        if not temp_obs.empty:
            station_parts.append(
                components.temp_components(daily, temp_obs[["station_id", "date", "tmax", "tmin"]], stations, model)
            )
    cells = pd.concat([p for p in cell_parts if not p.empty], ignore_index=True) if cell_parts else pd.DataFrame()
    st = pd.concat([p for p in station_parts if not p.empty], ignore_index=True) if station_parts else pd.DataFrame()
    return components.finalize(cells, "cell_id"), components.finalize(st, "station_id")


def write_components(df: pd.DataFrame, kind: str, data_dir: Path) -> None:
    out = data_dir / "verification" / kind
    out.mkdir(parents=True, exist_ok=True)
    for d, part in df.groupby("date"):
        part.to_parquet(out / f"{d.isoformat()}.parquet", index=False)


def load_components(kind: str, end: date, data_dir: Path) -> pd.DataFrame:
    return _read_days(data_dir / "verification" / kind, aggregate.window_dates(end, cfg.WINDOW_DAYS))


def write_rankings(cells: dict[str, dict], meta: dict, data_dir: Path) -> None:
    out = data_dir / "rankings"
    tmp = data_dir / "rankings.tmp"
    if tmp.exists():
        shutil.rmtree(tmp)
    (tmp / "cells").mkdir(parents=True)
    for cid, j in cells.items():
        (tmp / "cells" / f"{cid}.json").write_text(
            json.dumps(j, ensure_ascii=False, separators=(",", ":")), encoding="utf-8"
        )
    (tmp / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    # Swap the directory as a whole: a reader never sees a half-written ranking
    if out.exists():
        shutil.rmtree(out)
    tmp.rename(out)


def main() -> None:
    p = argparse.ArgumentParser(description="Verification and ranking")
    p.add_argument(
        "--end", type=date.fromisoformat, default=datetime.now(UTC).date() - timedelta(days=cfg.END_LAG_DAYS)
    )
    a = p.parse_args()
    computed = datetime.now(UTC).strftime("%Y-%m-%dT%H:%MZ")
    cells, stations = compute_components(a.end, DATA_DIR)
    write_components(cells, "cells", DATA_DIR)
    write_components(stations, "stations", DATA_DIR)
    # Rankings are built from the stored components only, so they can be reproduced from Parquet (§0 pt 9)
    out, meta = ranking.build(
        load_components("cells", a.end, DATA_DIR),
        load_components("stations", a.end, DATA_DIR),
        imgw.stations(),
        a.end,
        computed,
    )
    write_rankings(out, meta, DATA_DIR)
    print(json.dumps({k: meta[k] for k in ("window", "cells_ranked", "cells_with_temp", "wins")}, indent=1))


if __name__ == "__main__":
    main()
