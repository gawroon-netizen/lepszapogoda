"""Etap 0 GEE test: satellite observations per 0.1° cell over Poland.

1. Data latency: newest image in IMERG V07, GSMaP v8, MODIS Terra/Aqua (MOD09GA/MYD09GA), VIIRS (VNP09GA).
2. Grid 0.1° (bbox, cell_id per SPEC §8.1) built server-side, with fraction of the cell inside Poland.
3. Daily precipitation (06-06 UTC, IMGW convention) from IMERG for September 2026, per cell.
4. Daily cloud fraction from MODIS Terra/Aqua and VIIRS for 3 sample days, per cell.
5. Sanity check: IMERG cell vs IMGW station gauge (September 2026, 57 stations).
6. Cost: wall time per request + EECU of one batch export of the full IMERG table (task status).

Usage: EE_PROJECT=<gcp-project-id> python spike/gee_test.py
"""

import csv
import json
import os
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import ee
import numpy as np

from station_ranking import load_coords, load_imgw

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "data" / "gee"
OUT.mkdir(parents=True, exist_ok=True)

LAT0, LAT1, LON0, LON1 = 48.9, 55.0, 13.9, 24.2
STEP = 0.1
SEPT = [date(2026, 9, 1) + timedelta(days=i) for i in range(30)]
CLOUD_DAYS = [date(2026, 9, 5), date(2026, 9, 15), date(2026, 9, 25)]
SCALE = 1000  # m, reduction scale (IMERG/GSMaP 0.1° are upsampled, MODIS/VIIRS ~1 km / 500 m)


def latest(collection: str) -> str | None:
    try:
        t = ee.ImageCollection(collection).filterDate("2026-01-01", "2027-01-01").aggregate_max("system:time_start").getInfo()
    except ee.EEException as e:
        return f"error: {e}"
    return datetime.fromtimestamp(t / 1000, tz=timezone.utc).isoformat() if t else None


def grid() -> ee.FeatureCollection:
    n_lat = round((LAT1 - LAT0) / STEP)
    n_lon = round((LON1 - LON0) / STEP)

    def row(i):
        i = ee.Number(i)
        lat = ee.Number(LAT0).add(i.multiply(STEP))

        def cell(j):
            j = ee.Number(j)
            lon = ee.Number(LON0).add(j.multiply(STEP))
            # cell_id from lower-left corner in tenths of a degree, e.g. "509_182"
            lat10 = lat.multiply(10).round().format("%03d")
            lon10 = lon.multiply(10).round().format("%03d")
            geom = ee.Geometry.Rectangle([lon, lat, lon.add(STEP), lat.add(STEP)], "EPSG:4326", False)
            return ee.Feature(geom, {"cell_id": lat10.cat("_").cat(lon10)})

        return ee.List.sequence(0, n_lon - 1).map(cell)

    feats = ee.List.sequence(0, n_lat - 1).map(row).flatten()
    return ee.FeatureCollection(feats)


def poland_mask() -> ee.Image:
    pl = ee.FeatureCollection("USDOS/LSIB_SIMPLE/2017").filter(ee.Filter.eq("country_na", "Poland"))
    return ee.Image(0).paint(pl, 1).rename("pl_frac")


def imerg_daily(d: date) -> ee.Image:
    """IMGW-convention day: 06 UTC d .. 06 UTC d+1. IMERG precipitation is mm/h per 30 min."""
    start = datetime(d.year, d.month, d.day, 6, tzinfo=timezone.utc)
    col = ee.ImageCollection("NASA/GPM_L3/IMERG_V07").filterDate(start.isoformat(), (start + timedelta(days=1)).isoformat())
    return col.select("precipitation").sum().multiply(0.5).rename(f"imerg_{d:%m%d}").set("n", col.size())


def cloud_modis(collection: str, d: date, name: str) -> ee.Image:
    """state_1km bits 0-1: 0 clear, 1 cloudy, 2 mixed, 3 not set. Cloud fraction: cloudy=1, mixed=0.5."""
    img = ee.ImageCollection(collection).filterDate(d.isoformat(), (d + timedelta(days=1)).isoformat()).first()
    bits = ee.Image(img).select("state_1km").bitwiseAnd(3)
    frac = bits.eq(1).add(bits.eq(2).multiply(0.5)).updateMask(bits.neq(3))
    return frac.rename(f"{name}_{d:%m%d}")


def cloud_viirs(d: date) -> ee.Image:
    """VNP09GA QF1 bits 2-3 cloud mask confidence: 0 confident clear, 1 probably clear, 2 probably cloudy, 3 confident cloudy."""
    img = ee.ImageCollection("NASA/VIIRS/002/VNP09GA").filterDate(d.isoformat(), (d + timedelta(days=1)).isoformat()).first()
    conf = ee.Image(img).select("QF1").rightShift(2).bitwiseAnd(3)
    return conf.gte(2).rename(f"viirs_{d:%m%d}")


def reduce_to_rows(image: ee.Image, cells: ee.FeatureCollection, chunks: int = 7) -> tuple[list[dict], float]:
    """reduceRegions(mean) in chunks to stay under interactive limits. Returns rows and wall time."""
    t0 = time.time()
    rows = []
    n = cells.size().getInfo()
    size = -(-n // chunks)
    lst = cells.toList(n)
    for k in range(chunks):
        part = ee.FeatureCollection(lst.slice(k * size, min(n, (k + 1) * size)))
        fc = image.reduceRegions(collection=part, reducer=ee.Reducer.mean(), scale=SCALE, crs="EPSG:4326")
        info = fc.getInfo()
        rows += [f["properties"] for f in info["features"]]
    return rows, time.time() - t0


def export_eecu(image: ee.Image, cells: ee.FeatureCollection, project: str) -> dict:
    """One batch export to an EE table asset to read the EECU cost from task status; the asset is deleted after."""
    asset = f"projects/{project}/assets/lepszapogoda_gee_test_{int(time.time())}"
    fc = image.reduceRegions(collection=cells, reducer=ee.Reducer.mean(), scale=SCALE, crs="EPSG:4326")
    task = ee.batch.Export.table.toAsset(collection=fc, description="lepszapogoda_gee_test", assetId=asset)
    task.start()
    while True:
        st = task.status()
        if st["state"] in ("COMPLETED", "FAILED", "CANCELLED"):
            break
        time.sleep(15)
    if st["state"] == "COMPLETED":
        try:
            ee.data.deleteAsset(asset)
        except ee.EEException as e:
            st["delete_error"] = str(e)
    return {k: st.get(k) for k in ("state", "batch_eecu_usage_seconds", "start_timestamp_ms", "update_timestamp_ms", "error_message", "delete_error")}


def main() -> None:
    project = os.environ["EE_PROJECT"]
    ee.Initialize(project=project)
    report: dict = {"project_used": True}

    print("1. latency")
    report["latest"] = {
        c: latest(c)
        for c in (
            "NASA/GPM_L3/IMERG_V07",
            "JAXA/GPM_L3/GSMaP/v8/operational",
            "MODIS/061/MOD09GA",
            "MODIS/061/MYD09GA",
            "NASA/VIIRS/002/VNP09GA",
        )
    }
    for c, t in report["latest"].items():
        print(f"   {c:36s} {t}")

    print("2. grid")
    cells = grid()
    n_cells = cells.size().getInfo()
    report["cells_bbox"] = n_cells
    print(f"   cells in bbox: {n_cells}")

    print("3. IMERG September 2026")
    imerg = ee.Image.cat([imerg_daily(d) for d in SEPT]).addBands(poland_mask())
    rows, secs = reduce_to_rows(imerg, cells)
    report["imerg_interactive_seconds"] = round(secs, 1)
    in_pl = [r for r in rows if r.get("pl_frac", 0) > 0]
    report["cells_touching_poland"] = len(in_pl)
    report["cells_mostly_poland"] = sum(1 for r in rows if r.get("pl_frac", 0) >= 0.5)
    print(f"   {secs:.0f} s, cells touching PL: {len(in_pl)}, >=50% in PL: {report['cells_mostly_poland']}")
    with open(OUT / "imerg_2026_09.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=sorted(rows[0]))
        w.writeheader()
        w.writerows(rows)

    print("4. clouds, 3 sample days")
    cloud = ee.Image.cat(
        [cloud_modis("MODIS/061/MOD09GA", d, "terra") for d in CLOUD_DAYS]
        + [cloud_modis("MODIS/061/MYD09GA", d, "aqua") for d in CLOUD_DAYS]
        + [cloud_viirs(d) for d in CLOUD_DAYS]
    )
    crows, csecs = reduce_to_rows(cloud, cells)
    report["cloud_interactive_seconds"] = round(csecs, 1)
    with open(OUT / "cloud_samples.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=sorted({k for r in crows for k in r}))
        w.writeheader()
        w.writerows(crows)
    cov = {}
    for b in [k for k in crows[0] if k != "cell_id"]:
        vals = [r.get(b) for r in crows]
        cov[b] = {
            "coverage": round(sum(v is not None for v in vals) / len(vals), 3),
            "mean": round(float(np.mean([v for v in vals if v is not None])), 3) if any(v is not None for v in vals) else None,
        }
    report["cloud_bands"] = cov
    print(f"   {csecs:.0f} s")
    for b, x in cov.items():
        print(f"   {b:12s} coverage={x['coverage']} mean_cloud={x['mean']}")

    print("5. IMERG vs IMGW gauges")
    report["imerg_vs_gauge"] = imerg_vs_gauge({r["cell_id"]: r for r in rows})
    print("  ", report["imerg_vs_gauge"])

    print("6. EECU of a batch export (IMERG, full grid, 30 days)")
    report["export"] = export_eecu(imerg, cells, project)
    print("  ", report["export"])

    (ROOT / "gee_test_results.json").write_text(json.dumps(report, indent=1), encoding="utf-8")


def imerg_vs_gauge(cells: dict) -> dict:
    stations = load_imgw()
    coords = load_coords()
    f_all, o_all = [], []
    h = m = fa = c = 0
    for code, st in stations.items():
        wmo = "12" + code[-3:]
        if wmo not in coords:
            continue
        lat, lon, _ = coords[wmo]
        cid = f"{int(lat * 10):03d}_{int(lon * 10):03d}"  # floor -> lower-left corner of the containing cell
        cell = cells.get(cid)
        if not cell:
            continue
        for d in SEPT:
            o = st["obs"].get(d, {}).get("precip")
            f = cell.get(f"imerg_{d:%m%d}")
            if o is None or f is None:
                continue
            f_all.append(f)
            o_all.append(o)
            if f >= 1 and o >= 1:
                h += 1
            elif f >= 1:
                fa += 1
            elif o >= 1:
                m += 1
            else:
                c += 1
    n = h + m + fa + c
    r = (h + fa) * (h + m) / n
    return {
        "pairs": n,
        "corr": round(float(np.corrcoef(f_all, o_all)[0, 1]), 3),
        "bias_mm_per_day": round(float(np.mean(np.array(f_all) - np.array(o_all))), 3),
        "mae": round(float(np.mean(np.abs(np.array(f_all) - np.array(o_all)))), 3),
        "ets_1mm": round((h - r) / (h + m + fa - r), 3),
        "pod_1mm": round(h / (h + m), 3),
        "far_1mm": round(fa / (h + fa), 3),
    }


if __name__ == "__main__":
    main()
