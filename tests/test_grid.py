"""Grid tests (SPEC §12 a, plus cell id edge cases)."""

import math

import pytest

from lepszapogoda import grid

POLAND_AREA_KM2 = 312_696  # GUS, incl. internal waters


def bbox_area_km2() -> float:
    lat_min, lon_min, lat_max, lon_max = grid.BBOX
    r = 6371.0088
    return r**2 * math.radians(lon_max - lon_min) * (math.sin(math.radians(lat_max)) - math.sin(math.radians(lat_min)))


# ---------------------------------------------------------------- grid shape


def test_cell_count_and_unique_ids():
    cells = grid.all_cells()
    assert len(cells) == grid.N_CELLS == 6283
    assert len({c.cell_id for c in cells}) == len(cells)


def test_cells_tile_the_bbox_exactly():
    assert sum(c.area_km2 for c in grid.all_cells()) == pytest.approx(bbox_area_km2(), rel=1e-9)
    cells = grid.all_cells()
    assert min(c.lat_min for c in cells) == 48.9 and max(c.lat_max for c in cells) == 55.0
    assert min(c.lon_min for c in cells) == 13.9 and max(c.lon_max for c in cells) == 24.2


def test_area_shrinks_northwards():
    south, north = grid.get_cell("489_200"), grid.get_cell("549_200")
    assert north.area_km2 < south.area_km2
    # ratio follows cos(latitude); north-south difference over Poland is ~13 % (SPEC §8.1)
    assert north.area_km2 / south.area_km2 == pytest.approx(
        math.cos(math.radians(54.95)) / math.cos(math.radians(48.95)), rel=1e-3
    )


# ---------------------------------------------------------------- point -> cell


@pytest.mark.parametrize(
    ("lat", "lon", "expected"),
    [
        (52.2297, 21.0122, "522_210"),  # Warszawa
        (50.97, 18.22, "509_182"),  # Kluczbork, SPEC example
        (48.9, 13.9, "489_139"),  # south-west corner is inside
        (52.3, 21.7, "523_217"),  # 52.3 * 10 == 522.999... in binary
        (49.0, 19.0, "490_190"),  # point on edges belongs to the cell north/east
        (54.99999, 24.19999, "549_241"),  # just inside north-east corner
    ],
)
def test_cell_id_for(lat, lon, expected):
    assert grid.cell_id_for(lat, lon) == expected


@pytest.mark.parametrize(
    ("lat", "lon"),
    [(55.0, 20.0), (52.0, 24.2), (48.89, 20.0), (52.0, 13.89), (math.nan, 20.0), (52.0, math.inf), (-52.0, -21.0)],
)
def test_cell_id_for_outside_grid(lat, lon):
    assert grid.cell_id_for(lat, lon) is None


def test_centroid_maps_back_to_its_cell():
    for c in grid.all_cells():
        assert grid.cell_id_for(*c.centroid) == c.cell_id


# ---------------------------------------------------------------- cell ids


@pytest.mark.parametrize(
    "bad",
    ["", "abc", "52_210", "0522_210", "522-210", "522_210 ", "488_200", "550_200", "500_138", "500_242", None, 522210],
)
def test_invalid_cell_ids(bad):
    assert not grid.is_valid_cell_id(bad)
    with pytest.raises(ValueError):
        grid.get_cell(bad)


def test_get_cell_and_geometry():
    c = grid.get_cell("509_182")
    assert (c.lat_min, c.lon_min, c.lat_max, c.lon_max) == (50.9, 18.2, 51.0, 18.3)
    assert c.centroid == (50.95, 18.25)
    ring = c.geometry()["coordinates"][0]
    assert ring[0] == ring[-1] and len(ring) == 5
    assert c.wkt() == "POLYGON((18.2 50.9, 18.3 50.9, 18.3 51.0, 18.2 51.0, 18.2 50.9))"


# ---------------------------------------------------------------- neighbours


def test_neighbours():
    assert len(grid.neighbours("520_200")) == 8
    assert len(grid.neighbours("520_200", radius=2)) == 24
    assert sorted(grid.neighbours("489_139")) == ["489_140", "490_139", "490_140"]  # corner
    assert "520_200" not in grid.neighbours("520_200")
    with pytest.raises(ValueError):
        grid.neighbours("999_999")


# ---------------------------------------------------------------- Poland fraction


def test_poland_cells_count_and_area():
    cells = grid.poland_cells()
    assert 4313 - 20 <= len(cells) <= 4313 + 20
    assert all(0 < c.pl_frac <= 1 for c in cells)
    area_in_pl = sum(c.area_km2 * c.pl_frac for c in cells)
    assert area_in_pl == pytest.approx(POLAND_AREA_KM2, rel=0.01)


@pytest.mark.parametrize(
    ("cell_id", "expected"),
    [
        ("522_210", 1.0),  # Warszawa
        ("509_182", 1.0),  # Kluczbork
        ("547_205", 0.0),  # Kaliningrad (Russia)
        ("510_140", 0.0),  # Saxony (Germany)
        ("549_160", 0.0),  # Baltic Sea
    ],
)
def test_pl_frac_known_cells(cell_id, expected):
    assert grid.pl_frac(cell_id) == pytest.approx(expected, abs=1e-6)


def test_border_cells_are_partial():
    # Odra/Nysa border near Słubice (52.35 N, 14.56 E) and the Hel peninsula are split by land/sea or border
    assert 0 < grid.pl_frac(grid.cell_id_for(52.35, 14.56)) < 1
    assert 0 < grid.pl_frac(grid.cell_id_for(54.61, 18.80)) < 1
