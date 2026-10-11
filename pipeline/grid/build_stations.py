"""Build the IMGW synop station list with coordinates and elevation (SPEC §8.2).

IMGW's API gives station ids (WMO block 12) but no coordinates; they come from NOAA's ISD station history,
which still lists the Polish synop network (its observations stop in 2025, the metadata is what we need).
Run once, or when IMGW adds stations:
    python -m pipeline.grid.build_stations
Writes lepszapogoda/data/imgw_stations.json.
"""

import csv
import io
import json
from datetime import UTC, datetime
from pathlib import Path

import requests

from lepszapogoda import grid

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "lepszapogoda" / "data" / "imgw_stations.json"
IMGW_SYNOP = "https://danepubliczne.imgw.pl/api/data/synop"
ISD_HISTORY = "https://www.ncei.noaa.gov/pub/data/noaa/isd-history.csv"


def main() -> None:
    api = requests.get(IMGW_SYNOP, timeout=60).json()
    names = {s["id_stacji"]: s["stacja"] for s in api}
    isd: dict[str, dict] = {}
    for row in csv.DictReader(io.StringIO(requests.get(ISD_HISTORY, timeout=120).text)):
        wmo = row["USAF"][:5]
        if row["CTRY"] != "PL" or wmo not in names or not row["LAT"]:
            continue
        if wmo not in isd or row["END"] > isd[wmo]["_end"]:  # most recent record per station
            isd[wmo] = {
                "lat": float(row["LAT"]),
                "lon": float(row["LON"]),
                "elevation": float(row["ELEV(M)"]) if row["ELEV(M)"] else None,
                "_end": row["END"],
            }
    stations = []
    for sid in sorted(names):
        meta = isd.get(sid)
        if not meta:
            print(f"  no coordinates for {sid} {names[sid]} - skipped")
            continue
        stations.append(
            {
                "id": sid,
                "name": names[sid],
                "lat": meta["lat"],
                "lon": meta["lon"],
                "elevation": meta["elevation"],
                "cell_id": grid.cell_id_for(meta["lat"], meta["lon"]),
            }
        )
    payload = {
        "source": "ids and names: IMGW API synop; coordinates and elevation: NOAA ISD station history",
        "computed": datetime.now(UTC).strftime("%Y-%m-%dT%H:%MZ"),
        "stations": stations,
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"{len(stations)} of {len(names)} stations written to {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
