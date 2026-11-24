"""remote-metadata/<alias>.xml degli IdP di test/eIDAS (letti da pysaml2).

Bug: il file veniva scaricato una volta sola (solo se mancante), quindi né il
refresh manuale/cron (che aggiorna solo metadata_cache in DB) né un cambio di
metadata_url arrivavano mai a SATOSA.
"""
from types import SimpleNamespace

from app import satosa_config_generator as gen

IDP_SSO = ('<md:IDPSSODescriptor protocolSupportEnumeration="urn:oasis:names:tc:SAML:2.0:protocol"><md:KeyDescriptor use="signing"><ds:KeyInfo xmlns:ds="http://www.w3.org/2000/09/xmldsig#"><ds:X509Data><ds:X509Certificate>MIIB</ds:X509Certificate></ds:X509Data></ds:KeyInfo></md:KeyDescriptor></md:IDPSSODescriptor>')
META_A = ('<?xml version="1.0"?><md:EntityDescriptor xmlns:md="urn:oasis:names:tc:SAML:2.0:metadata" entityID="A">'
          + IDP_SSO + '</md:EntityDescriptor>')
META_B = ('<?xml version="1.0"?><md:EntityDescriptor xmlns:md="urn:oasis:names:tc:SAML:2.0:metadata" entityID="B">'
          + IDP_SSO + '</md:EntityDescriptor>')


def _idp(url="https://demo.example/metadata.xml", cache=None, alias="spid-demo"):
    return SimpleNamespace(alias=alias, metadata_url=url, metadata_cache=cache)


def _dest(tmp_path, alias="spid-demo"):
    return tmp_path / "remote-metadata" / f"{alias}.xml"


def _fake_download(monkeypatch, content):
    calls = []

    def fake(url):
        calls.append(url)
        if content is None:
            raise OSError("offline")
        return content.encode()

    monkeypatch.setattr(gen, "_download_metadata", fake)
    return calls


async def test_cache_from_db_overwrites_stale_file(tmp_path, monkeypatch):
    calls = _fake_download(monkeypatch, META_A)
    _dest(tmp_path).parent.mkdir()
    _dest(tmp_path).write_text(META_A)
    await gen._ensure_remote_metadata(str(tmp_path), [_idp(cache=META_B)])
    assert _dest(tmp_path).read_text() == META_B
    assert calls == []


async def test_url_change_triggers_download_without_cache(tmp_path, monkeypatch):
    _fake_download(monkeypatch, META_A)
    await gen._ensure_remote_metadata(str(tmp_path), [_idp(url="https://old/m.xml")])
    calls = _fake_download(monkeypatch, META_B)
    await gen._ensure_remote_metadata(str(tmp_path), [_idp(url="https://new/m.xml")])
    assert calls == ["https://new/m.xml"]
    assert _dest(tmp_path).read_text() == META_B


async def test_same_url_existing_file_no_download(tmp_path, monkeypatch):
    _fake_download(monkeypatch, META_A)
    await gen._ensure_remote_metadata(str(tmp_path), [_idp()])
    calls = _fake_download(monkeypatch, META_B)
    await gen._ensure_remote_metadata(str(tmp_path), [_idp()])
    assert calls == []
    assert _dest(tmp_path).read_text() == META_A


async def test_download_failure_keeps_existing_file(tmp_path, monkeypatch):
    _fake_download(monkeypatch, META_A)
    await gen._ensure_remote_metadata(str(tmp_path), [_idp(url="https://old/m.xml")])
    _fake_download(monkeypatch, None)
    await gen._ensure_remote_metadata(str(tmp_path), [_idp(url="https://new/m.xml")])
    assert _dest(tmp_path).read_text() == META_A


async def test_download_failure_without_file_writes_empty_placeholder(tmp_path, monkeypatch):
    _fake_download(monkeypatch, None)
    await gen._ensure_remote_metadata(str(tmp_path), [_idp()])
    assert _dest(tmp_path).read_text() == gen._EMPTY_META


async def test_invalid_cache_is_ignored(tmp_path, monkeypatch):
    calls = _fake_download(monkeypatch, META_A)
    await gen._ensure_remote_metadata(str(tmp_path), [_idp(cache="<html>errore</html>")])
    assert calls == ["https://demo.example/metadata.xml"]
    assert _dest(tmp_path).read_text() == META_A


async def test_invalid_cache_and_download_never_reach_satosa(tmp_path, monkeypatch):
    """Cache in DB non valida ignorata; download non valido: resta il file precedente."""
    _fake_download(monkeypatch, "<html>Manutenzione</html>")
    _dest(tmp_path).parent.mkdir()
    _dest(tmp_path).write_text(META_A)
    await gen._ensure_remote_metadata(
        str(tmp_path), [_idp(url="https://nuovo.example/md", cache="<EntityDescriptor>troncato")]
    )
    assert _dest(tmp_path).read_text() == META_A


def test_download_metadata_rejects_non_http_schemes():
    import pytest
    for url in ["file:///etc/passwd", "ftp://x/y", "data:,x"]:
        with pytest.raises(ValueError):
            gen._download_metadata(url)
