"""Routes (SPEC §7.4): /, /prognoza/<slug>/<lat>,<lon>/<tryb>, /api/forecast, /o-projekcie, /healthz."""

from __future__ import annotations

import re
from datetime import UTC, datetime

from flask import Blueprint, abort, current_app, jsonify, redirect, render_template, request

from lepszapogoda import grid
from lepszapogoda import ranking as rankings
from lepszapogoda.forecast import ForecastUnavailable
from web.app import slug as slugs
from web.app import view
from web.app.i18n import pl

bp = Blueprint("main", __name__)

COORDS_RE = re.compile(r"^(-?\d{1,2}(?:\.\d{1,6})?),(-?\d{1,3}(?:\.\d{1,6})?)$")
MARGIN = 0.5  # degrees around the Polish bbox accepted in URLs (SPEC §0 pt 8)
NAME_MAX = 80


def parse_coords(text: str) -> tuple[float, float] | None:
    m = COORDS_RE.match(text)
    if not m:
        return None
    lat, lon = float(m.group(1)), float(m.group(2))
    lat0, lon0, lat1, lon1 = grid.BBOX
    if not (lat0 - MARGIN <= lat <= lat1 + MARGIN and lon0 - MARGIN <= lon <= lon1 + MARGIN):
        return None
    return lat, lon


def _place_name(slug: str) -> str:
    """Display name: ?n= from the search box when given, otherwise the slug made readable."""
    n = (request.args.get("n") or "").strip()[:NAME_MAX]
    return n or slug.replace("-", " ").title()


@bp.get("/")
def index():
    return render_template("index.html", T=pl.T, modes=pl.MODES)


@bp.get("/prognoza/<slug>/<coords>/<mode>")
def forecast(slug: str, coords: str, mode: str):
    if not slugs.is_valid(slug) or mode not in pl.MODES:
        abort(404)
    point = parse_coords(coords)
    if point is None:
        abort(400)
    lat, lon = point
    canonical = f"{lat:.3f},{lon:.3f}"
    if coords != canonical:
        # built by hand: url_for would percent-encode the comma
        qs = ("?" + request.query_string.decode()) if request.query_string else ""
        return redirect(f"/prognoza/{slug}/{canonical}/{mode}{qs}", 301)
    cell_id = grid.cell_id_for(lat, lon)
    cell = rankings.load_cell(current_app.config["RANKINGS_DIR"], cell_id)
    try:
        fc = current_app.config["FORECAST_SERVICE"].get(lat, lon)
    except ForecastUnavailable:
        return render_template("error.html", T=pl.T, message=pl.T["unavailable"]), 503
    v = view.build(fc, mode, cell, int(current_app.config["CLOCK"]()))
    fetched = datetime.fromtimestamp(fc["fetched"], view.TZ).strftime("%d.%m %H:%M")
    return render_template(
        "forecast.html",
        T=pl.T,
        modes=pl.MODES,
        models=pl.MODELS,
        v=v,
        place=_place_name(slug),
        slug=slug,
        coords=canonical,
        lat=lat,
        lon=lon,
        stale=fc.get("stale", False),
        fetched=fetched,
        n_arg=request.args.get("n", "")[:NAME_MAX],
    )


@bp.get("/api/forecast")
def api_forecast():
    try:
        lat, lon = float(request.args["lat"]), float(request.args["lon"])
    except (KeyError, ValueError):
        abort(400)
    mode = request.args.get("tryb", "trafna")
    if mode not in pl.MODES or parse_coords(f"{lat},{lon}") is None:
        abort(400)
    cell = rankings.load_cell(current_app.config["RANKINGS_DIR"], grid.cell_id_for(lat, lon))
    try:
        fc = current_app.config["FORECAST_SERVICE"].get(lat, lon)
    except ForecastUnavailable:
        abort(503)
    return jsonify(view.build(fc, mode, cell, int(current_app.config["CLOCK"]())))


@bp.get("/o-projekcie")
def about():
    return render_template("about.html", T=pl.T, models=pl.MODELS)


@bp.get("/healthz")
def healthz():
    meta = rankings.load_meta(current_app.config["RANKINGS_DIR"])
    age_h = None
    if meta and meta.get("published"):
        published = datetime.strptime(meta["published"], "%Y-%m-%dT%H:%MZ").replace(tzinfo=UTC)
        age_h = round((datetime.now(UTC) - published).total_seconds() / 3600, 1)
    return jsonify(
        {
            "status": "ok",
            "rankings_published": meta.get("published") if meta else None,
            "rankings_age_hours": age_h,
            "cells_ranked": meta.get("cells_ranked") if meta else 0,
        }
    )


@bp.app_errorhandler(400)
@bp.app_errorhandler(404)
def not_found(e):
    return render_template(
        "error.html", T=pl.T, message="Nie ma takiej strony." if e.code == 404 else "Nieprawidłowy adres."
    ), e.code
