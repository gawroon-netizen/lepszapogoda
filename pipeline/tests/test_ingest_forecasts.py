"""Ingest planning: rotation, gap filling, backfill, manifest (no network)."""

from collections import Counter
from datetime import date, timedelta

import pytest

from lepszapogoda import grid, openmeteo
from pipeline.ingest import forecasts as fc

CELLS = [c.cell_id for c in grid.poland_cells()]
TODAY = date(2026, 10, 11)


def test_rotation_slots_are_balanced_and_stable():
    counts = Counter(fc.rotation_slot(c) for c in CELLS)
    assert set(counts) == set(range(fc.ROTATION_DAYS))
    mean = len(CELLS) / fc.ROTATION_DAYS
    assert all(abs(n - mean) < 0.2 * mean for n in counts.values())
    assert fc.rotation_slot("522_210") == fc.rotation_slot("522_210")


def test_target_range():
    assert fc.target_range(TODAY) == (date(2026, 9, 10), date(2026, 10, 9))


def test_missing_span():
    s, e = date(2026, 9, 1), date(2026, 9, 30)
    assert fc.missing_span([], s, e) == (s, e)
    assert fc.missing_span([(s, e)], s, e) is None
    assert fc.missing_span([(s, date(2026, 9, 20))], s, e) == (date(2026, 9, 21), e)
    assert fc.missing_span([(date(2026, 9, 5), e)], s, e) == (s, date(2026, 9, 4))


def test_manifest_merges_and_persists(tmp_path):
    m = fc.Manifest(tmp_path / "m.json")
    m.add("gfs_seamless", "522_210", date(2026, 9, 1), date(2026, 9, 10))
    m.add("gfs_seamless", "522_210", date(2026, 9, 11), date(2026, 9, 11))  # adjacent -> merged
    m.add("gfs_seamless", "522_210", date(2026, 9, 20), date(2026, 9, 25))
    m.save()
    m2 = fc.Manifest(tmp_path / "m.json")
    assert m2.ranges("gfs_seamless", "522_210") == [
        (date(2026, 9, 1), date(2026, 9, 11)),
        (date(2026, 9, 20), date(2026, 9, 25)),
    ]


def test_initial_backfill_fetches_every_cell_and_model_once(tmp_path):
    m = fc.Manifest(tmp_path / "m.json")
    models = list(openmeteo.MODELS)
    tasks = fc.plan(TODAY, CELLS, models, m)
    fetched = Counter((t.model, c) for t in tasks for c in t.cell_ids)
    assert len(fetched) == len(CELLS) * len(models) and set(fetched.values()) == {1}
    assert {(t.start, t.end) for t in tasks} == {fc.target_range(TODAY)}
    assert all(len(t.cell_ids) <= openmeteo.MAX_POINTS_PER_REQUEST for t in tasks)
    total = sum(t.cost for t in tasks)
    # ~100k weighted calls: about 12 days at 80 % of the 10k daily limit (SPEC §7.3)
    assert 80_000 < total < 110_000


def simulate(days: int, start: date, tmp_path) -> list[float]:
    """Run the planner day by day assuming every planned task succeeds; return daily cost."""
    m = fc.Manifest(tmp_path / "sim.json")
    costs = []
    for k in range(days):
        today = start + timedelta(days=k)
        tasks = fc.plan(today, CELLS, ["ecmwf_ifs"], m)
        costs.append(sum(t.cost for t in tasks))
        for t in tasks:
            for c in t.cell_ids:
                m.add(t.model, c, t.start, t.end)
    return costs


def test_steady_state_cost_and_full_coverage(tmp_path):
    costs = simulate(60, TODAY, tmp_path)
    steady = costs[30:]
    # one model: ~4313/14 cells per day x 2.1 (21 variables, 14 days) ~ 650 weighted calls
    assert max(steady) < 900
    assert sum(steady) / len(steady) == pytest.approx(len(CELLS) / 14 * 2.1, rel=0.15)


def test_cells_never_lag_more_than_rotation(tmp_path):
    m = fc.Manifest(tmp_path / "lag.json")
    for k in range(45):
        today = TODAY + timedelta(days=k)
        for t in fc.plan(today, CELLS[:300], ["gfs_seamless"], m):
            for c in t.cell_ids:
                m.add(t.model, c, t.start, t.end)
        if k >= 20:
            t_end = fc.target_range(today)[1]
            for c in CELLS[:300]:
                last = max(e for _, e in m.ranges("gfs_seamless", c))
                assert (t_end - last).days < fc.ROTATION_DAYS


def test_to_frame_long_format():
    task = fc.Task("meteofrance_seamless", date(2026, 9, 1), date(2026, 9, 1), ("522_210",))
    names = {openmeteo.previous_day_var(v, d): [1.0, 2.0] for v in fc.VARIABLES for d in (1, 2, 3)}
    s = openmeteo.PointSeries(52.25, 21.05, 52.2, 21.0, 92.0, [0, 3600], names)
    df = fc.to_frame(task, [s])
    assert len(df) == 2 * 3  # 2 hours x 3 leads (model horizon)
    assert set(df["lead_day"]) == {1, 2, 3}
    assert set(df.columns) >= {"grid_version", "model", "cell_id", "valid_time", "lead_day", *fc.VARIABLES}
    assert str(df["valid_time"].dt.tz) == "UTC"
