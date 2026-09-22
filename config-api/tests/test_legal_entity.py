import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy import select

from app.database import get_db
from app.models import EnteSettings


@pytest.fixture
def app_env(monkeypatch):
    monkeypatch.setenv("ADMIN_USER", "admin")
    monkeypatch.setenv("ADMIN_PASSWORD", "secret")
    monkeypatch.setenv("SESSION_SECRET", "test-secret-32-chars-minimum-pad")
    monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
    monkeypatch.setenv("SATOSA_CONF_DIR", "/tmp/satosa-test-legal-entity")
    monkeypatch.setenv("SATOSA_CONTAINER_NAME", "test-satosa")


@pytest_asyncio.fixture
async def auth_client(db_session, app_env):
    from app.main import app

    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        await client.post("/admin/login", data={"username": "admin", "password": "secret"})
        yield client

    app.dependency_overrides.clear()


async def test_legal_entity_get_page_redirects_to_idps(auth_client, db_session):
    """La pagina dedicata /admin/legal-entity non esiste più: è una sezione di /admin/idps."""
    response = await auth_client.get("/admin/legal-entity", follow_redirects=False)
    assert response.status_code == 301
    assert response.headers["location"] == "/admin/idps#persona-giuridica"


async def test_legal_entity_enable_flow(auth_client, db_session):
    db_session.add(EnteSettings(
        id=1, org_display_name="Test Ente", org_name="Test Ente",
        org_url="https://test.it", proxy_hostname="sso.test.it",
        ipa_code="TEST", contact_email="test@test.it", contact_phone="+39",
        org_city="Pescara",
        legal_entity_enabled=False,
    ))
    await db_session.commit()

    response = await auth_client.post(
        "/admin/legal-entity/toggle",
        data={"legal_entity_enabled": "yes", "confirmed": "yes"},
        follow_redirects=False,
    )
    assert response.status_code == 302
    assert response.headers["location"] == "/admin/idps?saved=1#persona-giuridica"

    s = (await db_session.execute(select(EnteSettings).where(EnteSettings.id == 1))).scalar_one()
    assert s.legal_entity_enabled is True


async def test_legal_entity_disable_flow(auth_client, db_session):
    db_session.add(EnteSettings(
        id=1, org_display_name="Test Ente", org_name="Test Ente",
        org_url="https://test.it", proxy_hostname="sso.test.it",
        ipa_code="TEST", contact_email="test@test.it", contact_phone="+39",
        org_city="Pescara",
        legal_entity_enabled=True,
    ))
    await db_session.commit()

    response = await auth_client.post(
        "/admin/legal-entity/toggle",
        data={"confirmed": "yes"},
        follow_redirects=False,
    )
    assert response.status_code == 302

    s = (await db_session.execute(select(EnteSettings).where(EnteSettings.id == 1))).scalar_one()
    assert s.legal_entity_enabled is False
