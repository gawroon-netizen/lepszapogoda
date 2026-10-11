"""Earth Engine initialisation: service account in CI, personal credentials locally."""

import json
import os

import ee


def init_ee() -> None:
    """Initialise Earth Engine.

    CI: GEE_SERVICE_ACCOUNT_JSON holds the service account key (SPEC §9); the project comes from the key.
    Local: credentials from `earthengine authenticate`, project from EE_PROJECT.
    """
    key = os.environ.get("GEE_SERVICE_ACCOUNT_JSON")
    if key:
        info = json.loads(key)
        creds = ee.ServiceAccountCredentials(info["client_email"], key_data=key)
        ee.Initialize(creds, project=os.environ.get("EE_PROJECT", info["project_id"]))
        return
    project = os.environ.get("EE_PROJECT")
    if not project:
        raise RuntimeError("set EE_PROJECT (local run) or GEE_SERVICE_ACCOUNT_JSON (CI)")
    ee.Initialize(project=project)
