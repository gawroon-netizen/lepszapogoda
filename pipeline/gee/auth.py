"""Earth Engine initialisation: service account in CI, personal credentials locally."""

import json
import os

import ee


def init_ee() -> None:
    """Initialise Earth Engine.

    CI: GEE_SERVICE_ACCOUNT_JSON holds the service account key (SPEC §9); the project comes from the key.
    CI, WeatherNext step only: GEE_USER_CREDENTIALS_JSON holds the human's Earth Engine OAuth credentials (the file
    written by `earthengine authenticate`, narrowed to read-only scopes), because WeatherNext access was granted to
    the human's account and the service account can read only part of it (2026-11-02). Set only for that step.
    Local: credentials from `earthengine authenticate`, project from EE_PROJECT.
    """
    key = os.environ.get("GEE_SERVICE_ACCOUNT_JSON")
    user = os.environ.get("GEE_USER_CREDENTIALS_JSON")
    project = os.environ.get("EE_PROJECT") or (json.loads(key)["project_id"] if key else None)
    if user:
        info = json.loads(user)
        if "refresh_token" not in info:
            raise RuntimeError("GEE_USER_CREDENTIALS_JSON has no refresh_token: paste the whole credentials file")
        path = ee.oauth.get_credentials_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(info, f)
        os.chmod(path, 0o600)
        if not project:
            raise RuntimeError("set EE_PROJECT (or GEE_SERVICE_ACCOUNT_JSON for its project id)")
        ee.Initialize(project=project)
        return
    if key:
        info = json.loads(key)
        creds = ee.ServiceAccountCredentials(info["client_email"], key_data=key)
        ee.Initialize(creds, project=project)
        return
    if not project:
        raise RuntimeError("set EE_PROJECT (local run) or GEE_SERVICE_ACCOUNT_JSON (CI)")
    ee.Initialize(project=project)
