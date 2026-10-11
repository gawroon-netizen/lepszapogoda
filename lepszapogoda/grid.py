"""Verification grid. The ONLY module that knows a cell is a 0.1° lat-lon rectangle (SPEC §0 pt 12, §8.1).

Everything else gets a cell's id, centroid, geometry, area and Poland fraction from here.
Changing the grid (e.g. to HEALPix) means a new GRID_VERSION and a new implementation of this module.

Cell id: lower-left corner in tenths of a degree, "LLL_OOO", e.g. "509_182" = 50.9-51.0 N, 18.2-18.3 E.
A point on a cell edge belongs to the cell to its north/east (lower and left edges are inclusive).
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from functools import cache
from importlib import resources

GRID_VERSION = "latlon01"

# Grid extent in tenths of a degree (SPEC §4: bbox 48.9-55.0 N, 13.9-24.2 E)
_LAT10_MIN, _LAT10_MAX = 489, 550  # exclusive max
_LON10_MIN, _LON10_MAX = 139, 242
_EPS = 1e-9  # guards floor() against binary representation error, e.g. 52.3 * 10 = 522.9999...
_EARTH_RADIUS_KM = 6371.0088  # mean radius (IUGG)
_CELL_ID_RE = re.compile(r"^(\d{3})_(\d{3})$")

BBOX = (_LAT10_MIN / 10, _LON10_MIN / 10, _LAT10_MAX / 10, _LON10_MAX / 10)  # lat_min, lon_min, lat_max, lon_max
N_CELLS = (_LAT10_MAX - _LAT10_MIN) * (_LON10_MAX - _LON10_MIN)


@dataclass(frozen=True, slots=True)
class Cell:
    cell_id: str
    lat_min: float
    lon_min: float
    lat_max: float
    lon_max: float

    @property
    def centroid(self) -> tuple[float, float]:
        """(lat, lon) of the cell centre."""
        return (round((self.lat_min + self.lat_max) / 2, 6), round((self.lon_min + self.lon_max) / 2, 6))

    @property
    def area_km2(self) -> float:
        """Area on a sphere: R^2 * dlon * (sin(lat2) - sin(lat1))."""
        dlon = math.radians(self.lon_max - self.lon_min)
        return (
            _EARTH_RADIUS_KM**2 * dlon * (math.sin(math.radians(self.lat_max)) - math.sin(math.radians(self.lat_min)))
        )

    @property
    def pl_frac(self) -> float:
        """Fraction of the cell inside Poland (0..1)."""
        return pl_frac(self.cell_id)

    def geometry(self) -> dict:
        """GeoJSON Polygon (lon, lat order, counter-clockwise exterior ring)."""
        ring = [
            [self.lon_min, self.lat_min],
            [self.lon_max, self.lat_min],
            [self.lon_max, self.lat_max],
            [self.lon_min, self.lat_max],
            [self.lon_min, self.lat_min],
        ]
        return {"type": "Polygon", "coordinates": [ring]}

    def wkt(self) -> str:
        pts = ", ".join(f"{lon:.1f} {lat:.1f}" for lon, lat in self.geometry()["coordinates"][0])
        return f"POLYGON(({pts}))"


def _make_cell(lat10: int, lon10: int) -> Cell:
    return Cell(f"{lat10:03d}_{lon10:03d}", lat10 / 10, lon10 / 10, (lat10 + 1) / 10, (lon10 + 1) / 10)


def _parse(cell_id: str) -> tuple[int, int] | None:
    m = _CELL_ID_RE.match(cell_id) if isinstance(cell_id, str) else None
    if not m:
        return None
    lat10, lon10 = int(m.group(1)), int(m.group(2))
    if not (_LAT10_MIN <= lat10 < _LAT10_MAX and _LON10_MIN <= lon10 < _LON10_MAX):
        return None
    return lat10, lon10


def is_valid_cell_id(cell_id: str) -> bool:
    return _parse(cell_id) is not None


def cell_id_for(lat: float, lon: float) -> str | None:
    """Id of the cell containing the point, or None when the point is outside the grid."""
    if not (math.isfinite(lat) and math.isfinite(lon)):
        return None
    lat10 = math.floor(lat * 10 + _EPS)
    lon10 = math.floor(lon * 10 + _EPS)
    if not (_LAT10_MIN <= lat10 < _LAT10_MAX and _LON10_MIN <= lon10 < _LON10_MAX):
        return None
    return f"{lat10:03d}_{lon10:03d}"


def get_cell(cell_id: str) -> Cell:
    parsed = _parse(cell_id)
    if parsed is None:
        raise ValueError(f"invalid or out-of-grid cell id: {cell_id!r}")
    return _make_cell(*parsed)


def all_cells() -> list[Cell]:
    """All grid cells in the bbox, ordered south to north, then west to east."""
    return [_make_cell(a, o) for a in range(_LAT10_MIN, _LAT10_MAX) for o in range(_LON10_MIN, _LON10_MAX)]


def neighbours(cell_id: str, radius: int = 1) -> list[str]:
    """Ids of cells within `radius` steps (Chebyshev distance), excluding the cell itself, clipped to the grid."""
    parsed = _parse(cell_id)
    if parsed is None:
        raise ValueError(f"invalid or out-of-grid cell id: {cell_id!r}")
    lat10, lon10 = parsed
    out = []
    for da in range(-radius, radius + 1):
        for do in range(-radius, radius + 1):
            if da == do == 0:
                continue
            a, o = lat10 + da, lon10 + do
            if _LAT10_MIN <= a < _LAT10_MAX and _LON10_MIN <= o < _LON10_MAX:
                out.append(f"{a:03d}_{o:03d}")
    return out


@cache
def _poland_fractions() -> dict[str, float]:
    path = resources.files("lepszapogoda") / "data" / "poland_cells.json"
    if not path.is_file():
        raise FileNotFoundError("lepszapogoda/data/poland_cells.json missing - run pipeline/grid/build_cells.py")
    data = json.loads(path.read_text(encoding="utf-8"))
    if data["grid_version"] != GRID_VERSION:
        raise ValueError(f"poland_cells.json is for grid {data['grid_version']}, expected {GRID_VERSION}")
    return data["pl_frac"]


def pl_frac(cell_id: str) -> float:
    """Fraction of the cell inside Poland; 0 for valid cells outside Poland."""
    if not is_valid_cell_id(cell_id):
        raise ValueError(f"invalid or out-of-grid cell id: {cell_id!r}")
    return _poland_fractions().get(cell_id, 0.0)


def poland_cells() -> list[Cell]:
    """Cells with any part inside Poland - the set that is verified and ranked (SPEC §4)."""
    fr = _poland_fractions()
    return [c for c in all_cells() if fr.get(c.cell_id, 0.0) > 0]
