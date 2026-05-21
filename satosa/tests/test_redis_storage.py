import sys
import os

import fakeredis
import pytest
from pydantic import BaseModel
from typing import Optional

# Minimal stub matching iam-proxy-italia OidcAuthentication — used when running outside container
class OidcAuthentication(BaseModel):
    id: str
    client_id: str = ""
    state: str = ""
    endpoint: str = ""
    data: Optional[dict] = None
    provider_id: str = ""
    provider_configuration: Optional[dict] = None
    user: Optional[dict] = None
    access_token: Optional[str] = None
    code: Optional[str] = None
    id_token: Optional[str] = None
    refresh_token: Optional[str] = None
    scope: Optional[str] = None
    token_type: Optional[str] = None
    expires_in: Optional[int] = None
    revoked: bool = False


sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "plugins"))

# Patch the model loader so redis_storage uses the stub above
import importlib
import unittest.mock as mock


def _make_storage():
    with mock.patch.dict("sys.modules", {"backends.cieoidc.models.oidc_auth": mock.MagicMock(OidcAuthentication=OidcAuthentication)}):
        import redis_storage as rs
        importlib.reload(rs)
    storage = rs.RedisStorage(url="redis://localhost", ttl=3600)
    storage._client = fakeredis.FakeRedis()
    storage._model = OidcAuthentication
    return storage


def test_add_and_get_session():
    storage = _make_storage()
    entity = OidcAuthentication(id="abc123", state="state-xyz", client_id="c1")
    storage.add_session(entity)
    result = storage.get_sessions("state-xyz")
    assert len(result) == 1
    assert result[0].id == "abc123"


def test_get_sessions_missing_state_returns_empty():
    storage = _make_storage()
    assert storage.get_sessions("nonexistent") == []


def test_update_session_changes_value():
    storage = _make_storage()
    entity = OidcAuthentication(id="abc123", state="state-xyz", client_id="c1")
    storage.add_session(entity)
    entity.access_token = "tok123"
    storage.update_session(entity)
    result = storage.get_sessions("state-xyz")
    assert result[0].access_token == "tok123"


def test_is_connected_returns_true():
    storage = _make_storage()
    assert storage.is_connected() is True


def test_close_sets_client_none():
    storage = _make_storage()
    storage.close()
    assert storage._client is None


def test_update_session_preserves_ttl():
    storage = _make_storage()
    entity = OidcAuthentication(id="abc123", state="state-xyz", client_id="c1")
    storage.add_session(entity)
    ttl_before = storage._client.ttl(b"cie:sess:abc123")
    entity.access_token = "tok"
    storage.update_session(entity)
    ttl_after = storage._client.ttl(b"cie:sess:abc123")
    assert ttl_after <= ttl_before
