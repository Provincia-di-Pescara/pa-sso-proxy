"""Avviso in dashboard per scope/claim tolti dal filtro per client (#154).

Un applicativo che chiede `legal_entity` senza averlo abilitato faceva login
come persona fisica senza nessun errore: ora satosa lo segnala e la dashboard
lo mostra.
"""
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app import scope_rejections
from app.database import get_db
from app.models import OIDCClient

T0 = datetime(2026, 11, 26, 10, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def _clean_store():
    scope_rejections.reset()
    yield
    scope_rejections.reset()


# --- archivio -------------------------------------------------------------------

def test_record_and_recent_counts():
    scope_rejections.record("app-a", ["legal_entity"], [], now=T0)
    scope_rejections.record("app-a", ["legal_entity"], ["company_name"], now=T0 + timedelta(minutes=5))
    [entry] = scope_rejections.recent(now=T0 + timedelta(minutes=6))
    assert entry["client_id"] == "app-a"
    assert entry["last_seen"] == T0 + timedelta(minutes=5)
    items = {(i["kind"], i["name"]): i["count"] for i in entry["items"]}
    assert items == {("scope", "legal_entity"): 2, ("claim", "company_name"): 1}
    assert entry["items"][0]["kind"] == "scope"  # scope prima dei claim


def test_recent_sorted_by_last_seen():
    scope_rejections.record("old", ["email"], [], now=T0)
    scope_rejections.record("new", ["profile"], [], now=T0 + timedelta(hours=1))
    assert [e["client_id"] for e in scope_rejections.recent(now=T0 + timedelta(hours=2))] == ["new", "old"]


def test_entries_older_than_window_pruned():
    scope_rejections.record("app-a", ["email"], [], now=T0)
    assert scope_rejections.recent(now=T0 + scope_rejections.WINDOW + timedelta(seconds=1)) == []


def test_clear_removes_client():
    scope_rejections.record("app-a", ["email"], [], now=T0)
    scope_rejections.record("app-b", ["email"], [], now=T0)
    scope_rejections.clear("app-a")
    assert [e["client_id"] for e in scope_rejections.recent(now=T0)] == ["app-b"]


def test_empty_or_invalid_input_ignored():
    scope_rejections.record("", ["email"], [], now=T0)
    scope_rejections.record("app-a", [], [], now=T0)
    scope_rejections.record("app-a", ["  ", 5, None], [], now=T0)
    assert scope_rejections.recent(now=T0) == []


def test_limits():
    scope_rejections.record("app-a", ["x" * 500], [], now=T0)
    [entry] = scope_rejections.recent(now=T0)
    assert len(entry["items"][0]["name"]) == 64

    scope_rejections.reset()
    scope_rejections.record("app-a", [f"s{i}" for i in range(100)], [], now=T0)
    assert len(scope_rejections.recent(now=T0)[0]["items"]) == 20  # per segnalazione

    scope_rejections.reset()
    for i in range(scope_rejections._MAX_CLIENTS + 10):
        scope_rejections.record(f"c{i}", ["email"], [], now=T0)
    assert len(scope_rejections.recent(now=T0)) == scope_rejections._MAX_CLIENTS


# --- endpoint e dashboard ---------------------------------------------------------

@pytest.fixture
def app_env(monkeypatch):
    monkeypatch.setenv("ADMIN_USER", "admin")
    monkeypatch.setenv("ADMIN_PASSWORD", "secret")
    monkeypatch.setenv("SESSION_SECRET", "test-secret-32-chars-minimum-pad")
    monkeypatch.setenv("SATOSA_INTERNAL_URL", "http://127.0.0.1:9")


@pytest_asyncio.fixture
async def client(db_session, app_env):
    from app.main import app

    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()


async def test_internal_endpoint_records(client):
    r = await client.post("/internal/scope-rejected",
                          json={"client_id": "app-a", "scopes": ["legal_entity"], "claims": ["company_name"]})
    assert r.status_code == 200
    [entry] = scope_rejections.recent()
    assert entry["client_id"] == "app-a"


async def test_dashboard_banner(client, db_session):
    db_session.add(OIDCClient(client_id="app-a", name="Portale Tributi", client_secret_hash="x",
                              redirect_uris=["https://a.example.it/cb"], allowed_scopes=["openid", "profile"]))
    await db_session.commit()
    await client.post("/admin/login", data={"username": "admin", "password": "secret"})

    r = await client.get("/admin/")
    assert "dati non consentiti" not in r.text

    scope_rejections.record("app-a", ["legal_entity"], [])
    scope_rejections.record("sconosciuto", ["email"], [])
    r = await client.get("/admin/")
    assert "Applicativi che chiedono dati non consentiti" in r.text
    assert "Portale Tributi" in r.text and "/edit" in r.text
    assert "legal_entity" in r.text and "sconosciuto" in r.text


async def test_client_save_clears_alert(client, db_session, monkeypatch):
    import app.routes.clients as clients_routes

    async def _noop(*a, **kw):
        return None

    monkeypatch.setattr(clients_routes, "generate_and_write", _noop)
    monkeypatch.setattr(clients_routes, "reload_satosa", lambda: None)
    row = OIDCClient(client_id="app-a", name="A", client_secret_hash="x",
                     redirect_uris=["https://a.example.it/cb"], allowed_scopes=["openid"])
    db_session.add(row)
    await db_session.commit()
    scope_rejections.record("app-a", ["legal_entity"], [])
    await client.post("/admin/login", data={"username": "admin", "password": "secret"})

    r = await client.post(f"/admin/clients/{row.id}/edit", data={
        "name": "A", "redirect_uris": "https://a.example.it/cb",
        "scopes": ["openid", "legal_entity"], "enabled": "1",
    })
    assert r.status_code == 302
    assert scope_rejections.recent() == []
