"""Probe Open-Meteo Previous Runs API: which models/variables/lead days are available over Poland.

Saves raw responses to docs/api-samples/ and prints a coverage table.
"""

import json
import sys
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
SAMPLES = ROOT / "docs" / "api-samples"
SAMPLES.mkdir(parents=True, exist_ok=True)

URL = "https://previous-runs-api.open-meteo.com/v1/forecast"
MODELS = [
    "ecmwf_ifs025",
    "ecmwf_aifs025_single",
    "icon_eu",
    "icon_d2",
    "icon_seamless",
    "gfs_global",
    "gfs_seamless",
    "meteofrance_arome_france_hd",
    "meteofrance_seamless",
]
VARIABLES = ["temperature_2m", "precipitation", "cloud_cover", "sunshine_duration", "weather_code", "cape"]
DAYS = [1, 2, 3, 5, 7]
# West edge, centre, east edge, south mountains
POINTS = {"Szczecin": (53.40, 14.62), "Warszawa": (52.17, 20.97), "Bialystok": (53.11, 23.16), "Zakopane": (49.30, 19.97)}
DATE = "2026-09-15"


def probe(model: str) -> dict:
    hourly = [f"{v}_previous_day{d}" for v in VARIABLES for d in DAYS]
    params = {
        "latitude": ",".join(str(p[0]) for p in POINTS.values()),
        "longitude": ",".join(str(p[1]) for p in POINTS.values()),
        "hourly": ",".join(hourly),
        "models": model,
        "start_date": DATE,
        "end_date": DATE,
        "timezone": "UTC",
        "cell_selection": "nearest",
        "elevation": "nan",  # disable DEM downscaling so the response reports the model cell elevation
    }
    r = requests.get(URL, params=params, timeout=60)
    if r.status_code != 200:
        return {"error": f"{r.status_code} {r.text[:200]}"}
    data = r.json()
    tag = "_".join(POINTS)
    (SAMPLES / f"previous_runs_{model}_{tag}.json").write_text(json.dumps(data, indent=1), encoding="utf-8")
    return {"data": data if isinstance(data, list) else [data]}


def main() -> None:
    global POINTS
    all_points = POINTS
    for model in MODELS:
        print(f"\n== {model}")
        for name, point in all_points.items():
            # One point per request: a single out-of-domain point fails the whole request for regional models
            POINTS = {name: point}
            res = probe(model)
            if "error" in res:
                print(f"  {name:10s} ERROR {res['error']}")
                continue
            loc = res["data"][0]
            if loc.get("latitude") is None:
                print(f"  {name:10s} outside domain (null cell)")
                continue
            h = loc.get("hourly", {})
            cells = []
            for v in VARIABLES:
                avail = [d for d in DAYS if any(x is not None for x in h.get(f"{v}_previous_day{d}", []))]
                cells.append(f"{v[:6]}:{','.join(map(str, avail)) or '-'}")
            print(
                f"  {name:10s} cell=({loc['latitude']:.3f},{loc['longitude']:.3f}) elev={loc.get('elevation')} | "
                + " ".join(cells)
            )


if __name__ == "__main__":
    sys.exit(main())
