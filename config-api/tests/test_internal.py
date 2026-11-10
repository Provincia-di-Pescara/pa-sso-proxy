from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from datetime import datetime, timezone
from httpx import AsyncClient, ASGITransport
from sqlalchemy import select

from app.database import get_db
from app.metadata_profile import metadata_fingerprint
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


_MD = "urn:oasis:names:tc:SAML:2.0:metadata"
_DS = "http://www.w3.org/2000/09/xmldsig#"


def _metadata(prefix: str, sig_id: str, extra_acs: bool = False) -> str:
    """Stesso metadata con prefissi e firma variabili (come pysaml2 7.5.4 vs 7.5.5)."""
    p = prefix
    acs = f'<{p}:AttributeConsumingService index="99"/>' if extra_acs else ""
    return (
        f'<{p}:EntityDescriptor xmlns:{p}="{_MD}" xmlns:sig="{_DS}" entityID="https://sp/metadata" ID="{sig_id}">'
        f'<sig:Signature><sig:SignatureValue>{sig_id}</sig:SignatureValue></sig:Signature>'
        f'<{p}:SPSSODescriptor><{p}:AttributeConsumingService index="0"/>{acs}</{p}:SPSSODescriptor>'
        f'</{p}:EntityDescriptor>'
    )


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

    response = await client.post("/internal/spid-metadata-snapshot", json={"xml_content": _metadata("md", "a")})
    assert response.status_code == 200

    rows = (await db_session.execute(select(SpidMetadataVersion))).scalars().all()
    assert len(rows) == 1
    assert rows[0].source == "generated"
    assert rows[0].cert_id == cert.id
    assert rows[0].content_hash == metadata_fingerprint(_metadata("md", "a"))
    assert rows[0].is_exposed is False  # le righe generate non si "espongono" più


async def test_snapshot_dedupes_prefix_and_signature_changes(client, db_session):
    """pysaml2 7.5.5 serializza ns0: invece di md:, la firma ha un ID casuale e
    satosa manda un semantic_hash diverso: stesso contenuto = nessuna riga nuova."""
    await client.post(
        "/internal/spid-metadata-snapshot",
        json={"xml_content": _metadata("md", "id-1"), "semantic_hash": "old-image"},
    )
    await client.post(
        "/internal/spid-metadata-snapshot",
        json={"xml_content": _metadata("ns0", "id-2"), "semantic_hash": "new-image"},
    )
    rows = (await db_session.execute(select(SpidMetadataVersion))).scalars().all()
    assert len(rows) == 1


async def test_snapshot_content_change_creates_new_row(client, db_session):
    await client.post("/internal/spid-metadata-snapshot", json={"xml_content": _metadata("md", "1")})
    await client.post("/internal/spid-metadata-snapshot", json={"xml_content": _metadata("md", "2", extra_acs=True)})
    rows = (await db_session.execute(select(SpidMetadataVersion))).scalars().all()
    assert len(rows) == 2


async def test_snapshot_revert_to_old_content_creates_new_row(client, db_session):
    """A -> B -> A: dedup solo contro l'ultima riga (niente UNIQUE globale)."""
    for xml in (_metadata("md", "1"), _metadata("md", "2", extra_acs=True), _metadata("md", "3")):
        await client.post("/internal/spid-metadata-snapshot", json={"xml_content": xml})
    rows = (
        await db_session.execute(select(SpidMetadataVersion).order_by(SpidMetadataVersion.id))
    ).scalars().all()
    assert len(rows) == 3
    assert rows[0].content_hash == rows[2].content_hash != rows[1].content_hash


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


async def test_snapshot_db_failure_still_returns_ok(client, db_session, monkeypatch):
    monkeypatch.setattr(db_session, "execute", AsyncMock(side_effect=Exception("db down")))

    response = await client.post("/internal/spid-metadata-snapshot", json={"xml_content": "<A/>"})

    assert response.status_code == 200
    assert response.json() == {"ok": True}
