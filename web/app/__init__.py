"""Flask application for lepszapogoda.pl (SPEC §5, §6, §7.4)."""

from __future__ import annotations

import hashlib
import os
import time
from functools import lru_cache
from pathlib import Path

from flask import Flask, url_for

from lepszapogoda import openmeteo
from lepszapogoda.forecast import ForecastService

WEB_DIR = Path(__file__).resolve().parents[1]

# MapLibre needs blob: workers; tiles, glyphs and the geocoder are fetched from the browser (SPEC §5)
CSP = "; ".join(
    [
        "default-src 'self'",
        "script-src 'self'",
        "style-src 'self'",
        "img-src 'self' data: blob: https://tiles.openfreemap.org https://tiles.maps.eox.at",
        "connect-src 'self' https://tiles.openfreemap.org https://tiles.maps.eox.at https://photon.komoot.io",
        "worker-src 'self' blob:",
        "child-src blob:",
        "font-src 'self'",
        "frame-ancestors 'none'",
        "base-uri 'self'",
        "form-action 'self'",
    ]
)


def create_app(config: dict | None = None) -> Flask:
    app = Flask(__name__, static_folder="static", template_folder="templates")
    data_dir = Path(os.environ.get("WEB_DATA_DIR", WEB_DIR / "data"))
    var_dir = Path(os.environ.get("WEB_VAR_DIR", WEB_DIR / "var"))
    app.config.update(
        RANKINGS_DIR=data_dir / "rankings",
        STATUS_PATH=data_dir / "status.json",  # pipeline status, copied by web/cron/pull_rankings.py
        CACHE_DIR=var_dir / "cache",
        SEND_FILE_MAX_AGE_DEFAULT=86400,  # SPEC §14: static files cached for a day
        JSON_AS_ASCII=False,
        CLOCK=time.time,  # injectable for tests
    )
    if config:
        app.config.update(config)
    if "FORECAST_SERVICE" not in app.config:
        budget = openmeteo.Budget(ledger_path=var_dir / "openmeteo_ledger.json", safety=0.9, max_wait_s=5)
        client = openmeteo.OpenMeteoClient(budget=budget, timeout_s=20, retries=1)
        app.config["FORECAST_SERVICE"] = ForecastService(client, app.config["CACHE_DIR"])

    @lru_cache(maxsize=256)
    def _version(filename: str) -> str:
        path = Path(app.static_folder) / filename
        return hashlib.sha256(path.read_bytes()).hexdigest()[:10] if path.is_file() else "0"

    @app.context_processor
    def asset_helper():
        # Static files are cached for a day; the content hash in the URL makes a changed file a new URL
        def asset(filename: str) -> str:
            return url_for("static", filename=filename, v=_version(filename))

        return {"asset": asset}

    @app.after_request
    def security_headers(resp):
        resp.headers.setdefault("Content-Security-Policy", CSP)
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        resp.headers.setdefault("X-Frame-Options", "DENY")
        resp.headers.setdefault("Permissions-Policy", "geolocation=(self), camera=(), microphone=()")
        return resp

    from web.app.routes import bp

    app.register_blueprint(bp)
    return app
