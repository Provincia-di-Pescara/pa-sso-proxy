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
    monkeypatch.setenv("SATOSA_CONF_DIR", "/tmp/satosa-test-plan3")
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


async def test_settings_form_shows_empty(auth_client):
    response = await auth_client.get("/admin/settings")
    assert response.status_code == 200
    assert "Impostazioni Ente" in response.text


async def test_settings_save_creates_row(auth_client, db_session):
    response = await auth_client.post(
        "/admin/settings",
        data={
            "org_display_name": "Ente Test",
            "org_name": "Ente Test",
            "org_url": "https://test.it",
            "proxy_hostname": "sso.test.it",
            "ipa_code": "TEST",
            "contact_email": "test@test.it",
            "contact_phone": "+39000",
            "org_city": "Pescara",
        },
        follow_redirects=False,
    )
    assert response.status_code == 302

    result = await db_session.execute(select(EnteSettings).where(EnteSettings.id == 1))
    s = result.scalar_one_or_none()
    assert s is not None
    assert s.org_name == "Ente Test"
    assert s.proxy_hostname == "sso.test.it"


async def test_settings_save_updates_existing(auth_client, db_session):
    existing = EnteSettings(
        id=1, org_display_name="Old", org_name="Old Ente",
        org_url="https://old.it", proxy_hostname="old.it",
        ipa_code="OLD", contact_email="old@old.it", contact_phone="+39",
        org_city="Roma",
    )
    db_session.add(existing)
    await db_session.commit()

    await auth_client.post(
        "/admin/settings",
        data={
            "org_display_name": "New",
            "org_name": "New Ente",
            "org_url": "https://new.it",
            "proxy_hostname": "new.it",
            "ipa_code": "NEW",
            "contact_email": "new@new.it",
            "contact_phone": "+39111",
            "org_city": "Milano",
        },
        follow_redirects=False,
    )

    await db_session.refresh(existing)
    assert existing.org_name == "New Ente"
    assert existing.org_city == "Milano"
