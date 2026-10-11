"""List Earth Engine catalog datasets relevant to cloud/precipitation verification over Europe (public STAC, no auth)."""

import re
from concurrent.futures import ThreadPoolExecutor

import requests

ROOT = "https://earthengine-stac.storage.googleapis.com/catalog/catalog.json"
PATTERN = re.compile(r"eumetsat|meteosat|seviri|claas|cloud|imerg|gpm|mod09ga|myd09ga|vnp09ga|mod35|mtg", re.I)


def children(url: str) -> list[dict]:
    return [l for l in requests.get(url, timeout=60).json().get("links", []) if l.get("rel") == "child"]


def main() -> None:
    providers = children(ROOT)
    with ThreadPoolExecutor(16) as ex:
        all_sets = sum(ex.map(children, [p["href"] for p in providers]), [])
    print(f"{len(providers)} providers, {len(all_sets)} datasets")
    for d in all_sets:
        text = f"{d.get('title', '')} {d['href']}"
        if PATTERN.search(text):
            print(f"  {d['href'].split('/catalog/')[-1]:70s} {d.get('title', '')}")


if __name__ == "__main__":
    main()
