"""Earth Engine initialisation paths (no network: ee.Initialize is replaced)."""

import json

import ee
import pytest

from pipeline.gee import auth


@pytest.fixture
def calls(monkeypatch, tmp_path):
    seen = []
    monkeypatch.setattr(ee, "Initialize", lambda creds=None, project=None: seen.append((creds, project)))
    monkeypatch.setattr(ee.oauth, "get_credentials_path", lambda: str(tmp_path / "ee" / "credentials"))
    for var in ("GEE_SERVICE_ACCOUNT_JSON", "GEE_USER_CREDENTIALS_JSON", "EE_PROJECT"):
        monkeypatch.delenv(var, raising=False)
    return seen


def test_user_token_is_written_and_used_with_the_service_account_project(calls, monkeypatch, tmp_path):
    monkeypatch.setenv("GEE_SERVICE_ACCOUNT_JSON", json.dumps({"project_id": "p-123", "client_email": "x"}))
    token = {"refresh_token": "r", "scopes": ["https://www.googleapis.com/auth/earthengine.readonly"]}
    monkeypatch.setenv("GEE_USER_CREDENTIALS_JSON", json.dumps(token))
    auth.init_ee()
    assert calls == [(None, "p-123")]  # default (persistent) credentials, not the service account
    assert json.loads((tmp_path / "ee" / "credentials").read_text()) == token


def test_incomplete_user_token_is_refused(calls, monkeypatch):
    monkeypatch.setenv("EE_PROJECT", "p")
    monkeypatch.setenv("GEE_USER_CREDENTIALS_JSON", json.dumps({"scopes": []}))
    with pytest.raises(RuntimeError, match="refresh_token"):
        auth.init_ee()
