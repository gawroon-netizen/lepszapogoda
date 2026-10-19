"""Polish cities and towns with population for the map labels (SPEC §5, places-pl.json). Run rarely:

    python -m tools.build_places

OpenFreeMap's low-zoom tiles carry only a handful of metropolises, so Poznań or Wrocław are missing at the
country view; this file lets the map label them itself. Data © OpenStreetMap contributors (ODbL), via Overpass.
"""

import json
from pathlib import Path

import requests

from lepszapogoda import grid

OVERPASS = (
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
)
OUT = Path(__file__).resolve().parents[1] / "web" / "app" / "static" / "data" / "places-pl.json"
# A bbox is much cheaper for Overpass than the "Poland" area; places outside Poland are dropped with the grid
QUERY = """
[out:json][timeout:90];
nwr[place~"^(city|town)$"](48.9,13.9,55.0,24.2);
out center tags;
"""


def population(tags: dict) -> int:
    raw = (tags.get("population") or "").replace(" ", "").replace(",", "").replace(".", "")
    return int(raw) if raw.isdigit() else 0


def main() -> None:
    for url in OVERPASS:  # public instances are often overloaded (502/504): try the next one
        r = requests.post(
            url, data={"data": QUERY}, timeout=120, headers={"User-Agent": "lepszapogoda.pl build_places"}
        )
        if r.ok:
            break
        print(f"{url}: HTTP {r.status_code}")
    r.raise_for_status()
    places, seen = [], set()
    for e in r.json()["elements"]:
        t = e.get("tags", {})
        if "lat" not in e:  # ways and relations (e.g. Zgorzelec) come with their centre
            e["lat"], e["lon"] = e["center"]["lat"], e["center"]["lon"]
        name = t.get("name:pl") or t.get("name")
        cell = grid.cell_id_for(e["lat"], e["lon"])
        # border cells also hold foreign towns (Brześć, Frankfurt nad Odrą): Polish places carry a TERYT id
        if not name or cell is None or grid.pl_frac(cell) == 0 or "teryt:simc" not in t:
            continue
        if t.get("teryt:simc") in seen:  # a place mapped both as a node and as an area
            continue
        seen.add(t.get("teryt:simc"))
        places.append(
            {"n": name, "lat": round(e["lat"], 4), "lon": round(e["lon"], 4), "p": population(t), "k": t["place"]}
        )
    places.sort(key=lambda p: -p["p"])
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(
        json.dumps(
            {"source": "© OpenStreetMap contributors (ODbL), Overpass API", "places": places},
            ensure_ascii=False,
            separators=(",", ":"),
        ),
        encoding="utf-8",
    )
    with_pop = sum(1 for p in places if p["p"])
    print(f"{len(places)} places ({with_pop} with population) -> {OUT}")
    print("largest:", ", ".join(f"{p['n']} {p['p']}" for p in places[:8]))


if __name__ == "__main__":
    main()
