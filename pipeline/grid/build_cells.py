"""Build the cell list with the fraction of each cell inside Poland (SPEC §8.1).

Run once per grid version (needs Earth Engine):
    EE_PROJECT=<project> python -m pipeline.grid.build_cells

Writes:
    pipeline/grid/poland_cells.parquet   all grid cells: geometry, centroid, area, pl_frac (pipeline side)
    lepszapogoda/data/poland_cells.json  pl_frac of cells touching Poland (shared package, no pyarrow needed)
"""

import json
from datetime import UTC, datetime
from pathlib import Path

import ee
import pandas as pd

from lepszapogoda import grid
from pipeline.gee.auth import init_ee

ROOT = Path(__file__).resolve().parents[2]
PARQUET = ROOT / "pipeline" / "grid" / "poland_cells.parquet"
JSON_OUT = ROOT / "lepszapogoda" / "data" / "poland_cells.json"

BORDERS = "USDOS/LSIB_SIMPLE/2017"
SCALE_M = 100  # mask resolution for the area fraction; ~1 % error on border cells
MIN_FRAC = 0.001  # below this the overlap is rasterisation noise
CHUNK = 1000  # features per interactive request


def compute_pl_frac(cells: list[grid.Cell]) -> dict[str, float]:
    poland = ee.FeatureCollection(BORDERS).filter(ee.Filter.eq("country_na", "Poland"))
    mask = ee.Image(0).paint(poland, 1).rename("pl")
    out: dict[str, float] = {}
    for k in range(0, len(cells), CHUNK):
        feats = [
            ee.Feature(ee.Geometry(c.geometry(), "EPSG:4326", False), {"cell_id": c.cell_id})
            for c in cells[k : k + CHUNK]
        ]
        fc = mask.reduceRegions(
            collection=ee.FeatureCollection(feats), reducer=ee.Reducer.mean(), scale=SCALE_M, crs="EPSG:4326"
        )
        for f in fc.getInfo()["features"]:
            p = f["properties"]
            out[p["cell_id"]] = float(p.get("mean") or 0.0)
        print(f"  {min(k + CHUNK, len(cells))}/{len(cells)}", flush=True)
    return out


def main() -> None:
    init_ee()
    cells = grid.all_cells()
    print(f"grid {grid.GRID_VERSION}: {len(cells)} cells")
    frac = compute_pl_frac(cells)
    frac = {cid: (round(v, 4) if v >= MIN_FRAC else 0.0) for cid, v in frac.items()}

    rows = []
    for c in cells:
        lat, lon = c.centroid
        rows.append(
            {
                "grid_version": grid.GRID_VERSION,
                "cell_id": c.cell_id,
                "lat_min": c.lat_min,
                "lon_min": c.lon_min,
                "lat_max": c.lat_max,
                "lon_max": c.lon_max,
                "centroid_lat": lat,
                "centroid_lon": lon,
                "area_km2": round(c.area_km2, 3),
                "pl_frac": frac[c.cell_id],
                "geometry_wkt": c.wkt(),
            }
        )
    df = pd.DataFrame(rows)
    PARQUET.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(PARQUET, index=False)

    JSON_OUT.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "grid_version": grid.GRID_VERSION,
        "source": f"{BORDERS} (country_na=Poland), mean of a {SCALE_M} m mask per cell, values < {MIN_FRAC} set to 0",
        "computed": datetime.now(UTC).strftime("%Y-%m-%dT%H:%MZ"),
        "pl_frac": {cid: v for cid, v in sorted(frac.items()) if v > 0},
    }
    JSON_OUT.write_text(json.dumps(payload, indent=0, separators=(",", ":")) + "\n", encoding="utf-8")
    n_pl = sum(v > 0 for v in frac.values())
    n_half = sum(v >= 0.5 for v in frac.values())
    print(
        f"cells touching Poland: {n_pl}, >= 50 % inside: {n_half}, total area in PL: "
        f"{sum(c.area_km2 * frac[c.cell_id] for c in cells):,.0f} km2"
    )


if __name__ == "__main__":
    main()
