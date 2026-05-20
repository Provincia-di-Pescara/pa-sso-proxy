import hashlib
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.models import SpidIdP


async def test_fetch_updates_when_content_changes(db_session):
    idp = SpidIdP(
        alias="spid-test",
        display_name="Test IdP",
        metadata_url="https://test.example/metadata",
        enabled=True,
        metadata_hash="old-hash",
        metadata_cache="<old/>",
    )
    db_session.add(idp)
    await db_session.commit()
    await db_session.refresh(idp)

    new_xml = "<EntityDescriptor>new content</EntityDescriptor>"
    mock_resp = MagicMock()
    mock_resp.text = new_xml
    mock_resp.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_resp)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    with patch("app.metadata_watcher.httpx.AsyncClient", return_value=mock_client):
        from app.metadata_watcher import fetch_idp_metadata
        result = await fetch_idp_metadata(db_session, idp)

    assert result is True
    await db_session.refresh(idp)
    assert idp.metadata_cache == new_xml
    assert idp.metadata_hash == hashlib.sha256(new_xml.encode()).hexdigest()
    assert idp.last_updated is not None


async def test_fetch_skips_when_unchanged(db_session):
    xml = "<EntityDescriptor>stable</EntityDescriptor>"
    current_hash = hashlib.sha256(xml.encode()).hexdigest()

    idp = SpidIdP(
        alias="spid-stable",
        display_name="Stable IdP",
        metadata_url="https://stable.example/metadata",
        enabled=True,
        metadata_cache=xml,
        metadata_hash=current_hash,
    )
    db_session.add(idp)
    await db_session.commit()
    await db_session.refresh(idp)

    mock_resp = MagicMock()
    mock_resp.text = xml
    mock_resp.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_resp)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    with patch("app.metadata_watcher.httpx.AsyncClient", return_value=mock_client):
        from app.metadata_watcher import fetch_idp_metadata
        result = await fetch_idp_metadata(db_session, idp)

    assert result is False


async def test_fetch_handles_http_error(db_session):
    idp = SpidIdP(
        alias="spid-broken",
        display_name="Broken IdP",
        metadata_url="https://broken.example/metadata",
        enabled=True,
    )
    db_session.add(idp)
    await db_session.commit()
    await db_session.refresh(idp)

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(side_effect=Exception("connection refused"))
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    with patch("app.metadata_watcher.httpx.AsyncClient", return_value=mock_client):
        from app.metadata_watcher import fetch_idp_metadata
        with pytest.raises(Exception):
            await fetch_idp_metadata(db_session, idp)


async def test_fetch_all_enabled_counts_updates(db_session):
    idp1 = SpidIdP(alias="spid-a", display_name="A", metadata_url="https://a.example/metadata", enabled=True, metadata_hash="hash-a")
    idp2 = SpidIdP(alias="spid-b", display_name="B", metadata_url="https://b.example/metadata", enabled=True, metadata_hash="hash-b")
    idp3 = SpidIdP(alias="spid-c", display_name="C", metadata_url="https://c.example/metadata", enabled=False)
    db_session.add_all([idp1, idp2, idp3])
    await db_session.commit()

    async def mock_fetch(db, idp):
        return idp.alias == "spid-a"

    with patch("app.metadata_watcher.fetch_idp_metadata", side_effect=mock_fetch), \
         patch("app.metadata_watcher.generate_and_write", new_callable=AsyncMock), \
         patch("app.metadata_watcher.reload_satosa", return_value=True):
        from app.metadata_watcher import fetch_all_enabled
        count = await fetch_all_enabled(db_session)

    assert count == 1
