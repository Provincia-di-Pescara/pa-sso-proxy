import hashlib
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from datetime import datetime, timezone
from httpx import AsyncClient, ASGITransport
from sqlalchemy import select

from app.database import get_db
from app.models import EnteSettings, SpidCert, SpidMetadataVersion


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


async def test_snapshot_captures_settings_toggles(client, db_session):
    settings = EnteSettings(
        id=1, org_display_name="Test", org_name="Test Ente", org_url="https://test.it",
        proxy_hostname="sso.test.it", ipa_code="TEST", contact_email="t@t.it",
        contact_phone="+39", org_city="Pescara",
        eidas_enabled=True, eidas_environment="qa", legal_entity_enabled=False,
    )
    db_session.add(settings)
    await db_session.commit()

    response = await client.post("/internal/spid-metadata-snapshot", json={"xml_content": "<A/>"})
    assert response.status_code == 200

    row = (await db_session.execute(select(SpidMetadataVersion))).scalar_one()
    assert row.eidas_enabled is True
    assert row.eidas_environment == "qa"
    assert row.legal_entity_enabled is False


async def test_snapshot_dedupes_by_semantic_hash_not_signed_content(client, db_session):
    """
    pysaml2 firma con un ID XML casuale ad ogni chiamata, quindi due snapshot
    con lo STESSO contenuto semantico (stessa config) hanno comunque XML
    firmato diverso — es. reload del cron IdP che non tocca il metadata SP.
    Il dedup deve usare semantic_hash quando fornito, non hash(xml_content).
    """
    await client.post(
        "/internal/spid-metadata-snapshot",
        json={"xml_content": "<A signed=\"1\"/>", "semantic_hash": "same-config-hash"},
    )
    await client.post(
        "/internal/spid-metadata-snapshot",
        json={"xml_content": "<A signed=\"2\"/>", "semantic_hash": "same-config-hash"},
    )
    result = await db_session.execute(select(SpidMetadataVersion))
    rows = result.scalars().all()
    assert len(rows) == 1
    assert rows[0].content_hash == "same-config-hash"
    # La prima versione firmata resta quella storicizzata/esposta — il
    # secondo reload (stessa config) non la sovrascrive.
    assert rows[0].xml_content == '<A signed="1"/>'


async def test_snapshot_semantic_hash_change_creates_new_row(client, db_session):
    """Config realmente diversa (hash semantico diverso) -> nuova riga, checkpoint vero."""
    await client.post(
        "/internal/spid-metadata-snapshot",
        json={"xml_content": "<A/>", "semantic_hash": "config-v1"},
    )
    await client.post(
        "/internal/spid-metadata-snapshot",
        json={"xml_content": "<B/>", "semantic_hash": "config-v2"},
    )
    result = await db_session.execute(select(SpidMetadataVersion))
    rows = result.scalars().all()
    assert len(rows) == 2


async def test_snapshot_without_semantic_hash_falls_back_to_content_hash(client, db_session):
    """Retrocompatibilità: satosa image vecchia senza semantic_hash -> comportamento invariato."""
    response = await client.post("/internal/spid-metadata-snapshot", json={"xml_content": "<A/>"})
    assert response.status_code == 200
    result = await db_session.execute(select(SpidMetadataVersion))
    row = result.scalar_one()
    assert row.content_hash == hashlib.sha256(b"<A/>").hexdigest()


async def test_snapshot_dedupes_identical_content(client, db_session):
    await client.post("/internal/spid-metadata-snapshot", json={"xml_content": "<A/>"})
    await client.post("/internal/spid-metadata-snapshot", json={"xml_content": "<A/>"})
    result = await db_session.execute(select(SpidMetadataVersion))
    rows = result.scalars().all()
    assert len(rows) == 1


async def test_snapshot_new_content_follows_previously_live_exposed_row(client, db_session):
    """
    When the previously-latest "generated" row was exposed (i.e. SATOSA is
    serving live/dynamic metadata, no override file pinning an older
    version), a new distinct snapshot must inherit is_exposed=True and the
    old row must flip to False — otherwise the "Esposto" badge in the UI
    would keep pointing at metadata SATOSA no longer actually serves.
    """
    await client.post("/internal/spid-metadata-snapshot", json={"xml_content": "<A/>"})
    await client.post("/internal/spid-metadata-snapshot", json={"xml_content": "<B/>"})
    result = await db_session.execute(
        select(SpidMetadataVersion).order_by(SpidMetadataVersion.id)
    )
    rows = result.scalars().all()
    assert len(rows) == 2
    assert rows[0].is_exposed is False
    assert rows[1].is_exposed is True


async def test_snapshot_new_content_does_not_flip_pinned_older_version(client, db_session):
    """
    When an admin has pinned (exposed) an older version via the metadata
    history page, the "latest generated" row's is_exposed is already False.
    A new snapshot arriving must NOT steal exposure from the pinned older
    version — only the previously-latest row's exposed flag matters.
    """
    older_pinned = SpidMetadataVersion(
        source="generated", xml_content="<Pinned/>", content_hash="pinned-hash", is_exposed=True,
    )
    db_session.add(older_pinned)
    await db_session.commit()
    latest_not_exposed = SpidMetadataVersion(
        source="generated", xml_content="<A/>", content_hash="a-hash", is_exposed=False,
    )
    db_session.add(latest_not_exposed)
    await db_session.commit()

    await client.post("/internal/spid-metadata-snapshot", json={"xml_content": "<B/>"})

    result = await db_session.execute(
        select(SpidMetadataVersion).order_by(SpidMetadataVersion.id)
    )
    rows = result.scalars().all()
    assert len(rows) == 3
    by_hash = {r.content_hash: r for r in rows}
    assert by_hash["pinned-hash"].is_exposed is True
    assert by_hash["a-hash"].is_exposed is False
    new_row = next(r for r in rows if r.content_hash not in ("pinned-hash", "a-hash"))
    assert new_row.is_exposed is False


async def test_snapshot_hash_matching_old_non_last_row_still_creates_new_row(client, db_session):
    """
    Regression test: a toggle-revert cycle (A -> B -> A) makes the semantic
    hash of the CURRENT state match an OLD row that is not the immediately
    preceding one. A global UNIQUE(source, content_hash) constraint used to
    silently block this insert (IntegrityError swallowed as "concurrent
    worker race already handled"), leaving is_exposed stuck on a row SATOSA
    no longer actually serves. Dedup must only ever compare against the
    single most-recent row.
    """
    await client.post(
        "/internal/spid-metadata-snapshot",
        json={"xml_content": "<A/>", "semantic_hash": "config-a"},
    )
    await client.post(
        "/internal/spid-metadata-snapshot",
        json={"xml_content": "<B/>", "semantic_hash": "config-b"},
    )
    # Revert back to config A's semantic hash - must create a THIRD row,
    # not be silently dropped because "config-a" already exists on row 1.
    response = await client.post(
        "/internal/spid-metadata-snapshot",
        json={"xml_content": "<A/>", "semantic_hash": "config-a"},
    )
    assert response.status_code == 200

    result = await db_session.execute(
        select(SpidMetadataVersion).order_by(SpidMetadataVersion.id)
    )
    rows = result.scalars().all()
    assert len(rows) == 3
    assert [r.content_hash for r in rows] == ["config-a", "config-b", "config-a"]
    assert [r.is_exposed for r in rows] == [False, False, True]


async def test_snapshot_db_failure_still_returns_ok(client, db_session, monkeypatch):
    monkeypatch.setattr(db_session, "execute", AsyncMock(side_effect=Exception("db down")))

    response = await client.post("/internal/spid-metadata-snapshot", json={"xml_content": "<A/>"})

    assert response.status_code == 200
    assert response.json() == {"ok": True}
