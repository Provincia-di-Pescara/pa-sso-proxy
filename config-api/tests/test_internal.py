import hashlib
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from datetime import datetime, timezone
from httpx import AsyncClient, ASGITransport
from sqlalchemy import select

from app.database import get_db
from app.models import SpidCert, SpidMetadataVersion


@pytest.fixture
def app_env(monkeypatch):
    monkeypatch.setenv("ADMIN_USER", "admin")
    monkeypatch.setenv("ADMIN_PASSWORD", "secret")
    monkeypatch.setenv("SESSION_SECRET", "test-secret-32-chars-minimum-pad")
    monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
    monkeypatch.setenv("SATOSA_CONF_DIR", "/tmp/satosa-test-internal")
    monkeypatch.setenv("SATOSA_CONTAINER_NAME", "test-satosa")


@pytest_asyncio.fixture
async def client(db_session, app_env):
    from app.main import app

    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()


async def test_snapshot_creates_row_with_active_cert_id(client, db_session):
    cert = SpidCert(
        certificate_pem="-----BEGIN CERTIFICATE-----\nc\n-----END CERTIFICATE-----",
        private_key_pem="-----BEGIN PRIVATE KEY-----\nk\n-----END PRIVATE KEY-----",
        not_valid_after=datetime(2036, 1, 1, tzinfo=timezone.utc),
        subject_dn="CN=test.it",
        is_active=True,
    )
    db_session.add(cert)
    await db_session.commit()
    await db_session.refresh(cert)

    response = await client.post("/internal/spid-metadata-snapshot", json={"xml_content": "<A/>"})
    assert response.status_code == 200

    result = await db_session.execute(select(SpidMetadataVersion))
    rows = result.scalars().all()
    assert len(rows) == 1
    assert rows[0].source == "generated"
    assert rows[0].cert_id == cert.id
    assert rows[0].content_hash == hashlib.sha256(b"<A/>").hexdigest()


async def test_snapshot_first_row_is_exposed_by_default(client, db_session):
    response = await client.post("/internal/spid-metadata-snapshot", json={"xml_content": "<A/>"})
    assert response.status_code == 200
    result = await db_session.execute(select(SpidMetadataVersion))
    row = result.scalar_one()
    assert row.is_exposed is True


async def test_snapshot_dedupes_identical_content(client, db_session):
    await client.post("/internal/spid-metadata-snapshot", json={"xml_content": "<A/>"})
    await client.post("/internal/spid-metadata-snapshot", json={"xml_content": "<A/>"})
    result = await db_session.execute(select(SpidMetadataVersion))
    rows = result.scalars().all()
    assert len(rows) == 1


async def test_snapshot_new_content_creates_second_row_not_exposed(client, db_session):
    await client.post("/internal/spid-metadata-snapshot", json={"xml_content": "<A/>"})
    await client.post("/internal/spid-metadata-snapshot", json={"xml_content": "<B/>"})
    result = await db_session.execute(
        select(SpidMetadataVersion).order_by(SpidMetadataVersion.created_at)
    )
    rows = result.scalars().all()
    assert len(rows) == 2
    assert rows[1].is_exposed is False


async def test_snapshot_db_failure_still_returns_ok(client, db_session, monkeypatch):
    monkeypatch.setattr(db_session, "execute", AsyncMock(side_effect=Exception("db down")))

    response = await client.post("/internal/spid-metadata-snapshot", json={"xml_content": "<A/>"})

    assert response.status_code == 200
    assert response.json() == {"ok": True}
