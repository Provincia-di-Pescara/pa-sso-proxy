import hashlib
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.models import SpidIdP


def _md(entity_id):
    return ('<md:EntityDescriptor xmlns:md="urn:oasis:names:tc:SAML:2.0:metadata" entityID="' + entity_id + '">'
            '<md:IDPSSODescriptor protocolSupportEnumeration="urn:oasis:names:tc:SAML:2.0:protocol"><md:KeyDescriptor use="signing"><ds:KeyInfo xmlns:ds="http://www.w3.org/2000/09/xmldsig#"><ds:X509Data><ds:X509Certificate>MIIB</ds:X509Certificate></ds:X509Data></ds:KeyInfo></md:KeyDescriptor></md:IDPSSODescriptor></md:EntityDescriptor>')


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

    new_xml = _md("https://new.example")
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
    xml = _md("https://stable.example")
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


# --- metadata non validi: mai scritti/salvati ---------------------------------

def _mock_client(resp):
    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=resp)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    return mock_client


async def test_fetch_rejects_invalid_metadata_keeps_cache(db_session):
    good = _md("https://ok.example")
    idp = SpidIdP(alias="eidas-prod", display_name="eIDAS", metadata_url="https://x.example/md",
                  enabled=True, metadata_cache=good, metadata_hash="h")
    db_session.add(idp)
    await db_session.commit()
    resp = MagicMock(text="<html><body>Manutenzione</body></html>", raise_for_status=MagicMock())
    with patch("app.metadata_watcher.httpx.AsyncClient", return_value=_mock_client(resp)):
        from app.metadata_watcher import fetch_idp_metadata
        assert await fetch_idp_metadata(db_session, idp) is False
    await db_session.refresh(idp)
    assert idp.metadata_cache == good and idp.metadata_hash == "h"


@pytest.mark.parametrize("body", [
    b"<html><body>Manutenzione</body></html>",
    b'<?xml version="1.0"?><md:EntitiesDescriptor xmlns:md="urn:oasis:names:tc:SAML:2.0:metadata"><md:EntityDesc',
    b'<md:EntitiesDescriptor xmlns:md="urn:oasis:names:tc:SAML:2.0:metadata"/>',
    b"",
])
async def test_aggregate_invalid_keeps_previous_file(tmp_path, monkeypatch, body):
    from app import metadata_watcher as mw
    path, hash_path = tmp_path / "agg.xml", tmp_path / ".hash"
    previous = ('<md:EntitiesDescriptor xmlns:md="urn:oasis:names:tc:SAML:2.0:metadata">'
                + _md("https://idp.example") + "</md:EntitiesDescriptor>").encode()
    path.write_bytes(previous)
    hash_path.write_text(hashlib.sha256(previous).hexdigest())
    monkeypatch.setattr(mw, "SPID_AGGREGATE_PATH", str(path))
    monkeypatch.setattr(mw, "_AGGREGATE_HASH_PATH", str(hash_path))
    resp = MagicMock(content=body, raise_for_status=MagicMock())
    with patch("app.metadata_watcher.httpx.AsyncClient", return_value=_mock_client(resp)):
        assert await mw.fetch_spid_aggregate() is False
    assert path.read_bytes() == previous


async def test_aggregate_valid_written_atomically(tmp_path, monkeypatch):
    from app import metadata_watcher as mw
    path, hash_path = tmp_path / "agg.xml", tmp_path / ".hash"
    monkeypatch.setattr(mw, "SPID_AGGREGATE_PATH", str(path))
    monkeypatch.setattr(mw, "_AGGREGATE_HASH_PATH", str(hash_path))
    body = ('<md:EntitiesDescriptor xmlns:md="urn:oasis:names:tc:SAML:2.0:metadata">'
            + _md("https://a.example") + _md("https://b.example") + "</md:EntitiesDescriptor>").encode()
    resp = MagicMock(content=body, raise_for_status=MagicMock())
    with patch("app.metadata_watcher.httpx.AsyncClient", return_value=_mock_client(resp)):
        assert await mw.fetch_spid_aggregate() is True
    assert path.read_bytes() == body
    assert not (tmp_path / "agg.xml.tmp").exists()


def test_check_idp_metadata_rules():
    from app.saml_metadata import InvalidMetadata, check_idp_metadata
    assert check_idp_metadata(_md("https://a.example")) == 1
    for bad in ['<md:EntityDescriptor xmlns:md="urn:oasis:names:tc:SAML:2.0:metadata" entityID="x"/>',
                '<!DOCTYPE x [<!ENTITY a "b">]><x>&a;</x>',
                _md("https://a.example").replace("urn:oasis:names:tc:SAML:2.0:metadata", "urn:altro")]:
        with pytest.raises(InvalidMetadata):
            check_idp_metadata(bad)
