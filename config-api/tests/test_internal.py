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
        select(SpidMetadataVersion).order_by(SpidMetadataVersion.created_at)
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
        select(SpidMetadataVersion).order_by(SpidMetadataVersion.created_at)
    )
    rows = result.scalars().all()
    assert len(rows) == 3
    by_hash = {r.content_hash: r for r in rows}
    assert by_hash["pinned-hash"].is_exposed is True
    assert by_hash["a-hash"].is_exposed is False
    new_row = next(r for r in rows if r.content_hash not in ("pinned-hash", "a-hash"))
    assert new_row.is_exposed is False


async def test_concurrent_snapshot_race_results_in_one_row_no_error(client, db_session, monkeypatch):
    """
    Regression test for the uWSGI multi-worker race: two workers can both
    read "no existing row for this hash" before either commits, and both
    then attempt to insert. The DB-level unique constraint on
    (source, content_hash) is what actually prevents the duplicate;
    log_metadata_snapshot must catch the resulting IntegrityError from the
    loser and swallow it without raising (fire-and-forget contract).
    """
    xml = "<Race/>"
    content_hash = hashlib.sha256(xml.encode("utf-8")).hexdigest()

    # Simulate worker A's insert winning the race first.
    winner = SpidMetadataVersion(
        source="generated", xml_content=xml, content_hash=content_hash, is_exposed=True,
    )
    db_session.add(winner)
    await db_session.commit()

    # Simulate worker B: force its "last_row" SELECT to see no existing row
    # (as if it ran before worker A's insert became visible), so it takes
    # the insert branch and collides with worker A's row at commit time.
    orig_execute = db_session.execute
    state = {"patched_once": False}

    class _EmptyResult:
        def scalar_one_or_none(self):
            return None

    async def patched_execute(stmt, *args, **kwargs):
        stmt_text = str(stmt)
        if not state["patched_once"] and "spid_metadata_version" in stmt_text and "SELECT" in stmt_text:
            state["patched_once"] = True
            return _EmptyResult()
        return await orig_execute(stmt, *args, **kwargs)

    monkeypatch.setattr(db_session, "execute", patched_execute)

    response = await client.post("/internal/spid-metadata-snapshot", json={"xml_content": xml})
    assert response.status_code == 200
    assert response.json() == {"ok": True}

    monkeypatch.undo()
    result = await db_session.execute(
        select(SpidMetadataVersion).where(SpidMetadataVersion.content_hash == content_hash)
    )
    rows = result.scalars().all()
    assert len(rows) == 1
    # The winning row's is_exposed must be untouched by the failed loser.
    assert rows[0].is_exposed is True


async def test_snapshot_db_failure_still_returns_ok(client, db_session, monkeypatch):
    monkeypatch.setattr(db_session, "execute", AsyncMock(side_effect=Exception("db down")))

    response = await client.post("/internal/spid-metadata-snapshot", json={"xml_content": "<A/>"})

    assert response.status_code == 200
    assert response.json() == {"ok": True}
