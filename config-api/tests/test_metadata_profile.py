"""Profilo metadata SPID validato (app/metadata_profile.py)."""
from datetime import datetime, timezone
from unittest.mock import patch

import pytest
from sqlalchemy import select

from app.metadata_profile import (
    CertConfirmationRequired,
    CertMissing,
    cert_fingerprint,
    create_validated_profile,
    metadata_fingerprint,
    normalize_metadata_history,
    profile_status,
    restore_profile,
)
from app.models import EnteSettings, SpidCert, SpidIdP, SpidMetadataProfile, SpidMetadataVersion

_MD = "urn:oasis:names:tc:SAML:2.0:metadata"
_DS = "http://www.w3.org/2000/09/xmldsig#"


def _md(prefix="md", sig="x", email="pec@ente.it", acs=("0",), indent=""):
    p = prefix
    acs_xml = "".join(f'{indent}<{p}:AttributeConsumingService index="{i}"/>' for i in acs)
    return (
        f'<{p}:EntityDescriptor xmlns:{p}="{_MD}" xmlns:d="{_DS}" entityID="https://sp/m" ID="{sig}">'
        f'{indent}<d:Signature><d:SignatureValue>{sig}</d:SignatureValue></d:Signature>'
        f'{indent}<{p}:SPSSODescriptor>{acs_xml}</{p}:SPSSODescriptor>'
        f'{indent}<{p}:ContactPerson><{p}:EmailAddress>{email}</{p}:EmailAddress></{p}:ContactPerson>'
        f'</{p}:EntityDescriptor>'
    )


# --- impronta -------------------------------------------------------------------

def test_fingerprint_ignores_prefixes_signature_ids_and_whitespace():
    base = metadata_fingerprint(_md())
    assert metadata_fingerprint(_md(prefix="ns0", sig="other-random-id", indent="\n  ")) == base


@pytest.mark.parametrize("variant", [
    {"acs": ("0", "99")},
    {"email": "altra@ente.it"},
])
def test_fingerprint_changes_with_content(variant):
    assert metadata_fingerprint(_md(**variant)) != metadata_fingerprint(_md())


def test_fingerprint_of_invalid_xml_falls_back_to_text_hash():
    assert metadata_fingerprint("not xml") == metadata_fingerprint("not xml")
    assert metadata_fingerprint("not xml") != metadata_fingerprint("not xml 2")


# --- fixture --------------------------------------------------------------------

def _settings(**kw):
    values = dict(
        id=1, org_display_name="Ente", org_name="Ente", org_url="https://ente.it",
        proxy_hostname="sso.ente.it", ipa_code="c_x", contact_email="pec@ente.it",
        contact_phone="", org_city="Pescara", vat_number="80000000000",
        eidas_enabled=False, eidas_environment="prod", legal_entity_enabled=False,
    )
    values.update(kw)
    return EnteSettings(**values)


def _cert(n, active):
    return SpidCert(
        certificate_pem=f"-----BEGIN CERTIFICATE-----\ncert{n}\n-----END CERTIFICATE-----",
        private_key_pem="k", not_valid_after=datetime(2036, 1, 1, tzinfo=timezone.utc),
        subject_dn=f"CN={n}", is_active=active,
    )


async def _setup(db, **settings_kw):
    old_cert, new_cert = _cert(1, True), _cert(2, False)
    db.add_all([_settings(**settings_kw), old_cert, new_cert])
    db.add(SpidMetadataVersion(source="generated", xml_content=_md(), content_hash=metadata_fingerprint(_md())))
    await db.commit()
    return old_cert, new_cert


# --- stato ----------------------------------------------------------------------

async def test_status_without_profile(db_session):
    status = await profile_status(db_session)
    assert status.profile is None
    assert status.matches is False


async def test_status_matches_right_after_mark_validated(db_session):
    await _setup(db_session)
    await create_validated_profile(db_session, "v1")
    status = await profile_status(db_session)
    assert status.matches
    assert status.differences == []
    assert status.document_matches is True


async def test_status_lists_parameter_differences(db_session):
    await _setup(db_session)
    await create_validated_profile(db_session)
    settings = (await db_session.execute(select(EnteSettings))).scalar_one()
    settings.eidas_enabled = True
    settings.contact_email = "nuova@ente.it"
    await db_session.commit()

    status = await profile_status(db_session)

    labels = {d.label: (d.current, d.validated) for d in status.differences}
    assert labels["eIDAS"] == ("on", "off")
    assert labels["Email contatto"] == ("nuova@ente.it", "pec@ente.it")
    assert not status.matches


async def test_status_ignores_eidas_environment_when_eidas_off_in_both(db_session):
    await _setup(db_session)
    await create_validated_profile(db_session)
    settings = (await db_session.execute(select(EnteSettings))).scalar_one()
    settings.eidas_environment = "qa"
    await db_session.commit()
    assert (await profile_status(db_session)).matches


async def test_status_flags_document_change_with_same_parameters(db_session):
    """Parametri uguali, metadata diverso: una nuova immagine ha cambiato il documento."""
    await _setup(db_session)
    await create_validated_profile(db_session)
    db_session.add(SpidMetadataVersion(
        source="generated", xml_content=_md(acs=("0", "5")), content_hash=metadata_fingerprint(_md(acs=("0", "5")))
    ))
    await db_session.commit()
    status = await profile_status(db_session)
    assert status.differences == []
    assert status.document_matches is False
    assert not status.matches


async def test_status_reports_entity_id_change(db_session):
    await _setup(db_session)
    await create_validated_profile(db_session)
    settings = (await db_session.execute(select(EnteSettings))).scalar_one()
    settings.proxy_hostname = "nuovo.ente.it"
    await db_session.commit()
    status = await profile_status(db_session)
    assert status.entity_id_differs


async def test_mark_validated_archives_previous(db_session):
    await _setup(db_session)
    first = await create_validated_profile(db_session, "v1")
    second = await create_validated_profile(db_session, "v2")
    await db_session.refresh(first)
    assert first.status == "archived"
    assert second.status == "validated"


# --- ripristino -----------------------------------------------------------------

async def test_restore_reapplies_parameters_and_eidas_idps(db_session):
    await _setup(db_session, eidas_enabled=True, eidas_environment="qa")
    db_session.add_all([
        SpidIdP(alias="eidas-qa", display_name="QA", metadata_url="u1", enabled=False),
        SpidIdP(alias="eidas-prod", display_name="Prod", metadata_url="u2", enabled=True),
    ])
    await db_session.commit()
    profile = await create_validated_profile(db_session)
    settings = (await db_session.execute(select(EnteSettings))).scalar_one()
    settings.eidas_environment = "prod"
    settings.legal_entity_enabled = True
    settings.org_url = "https://altro.it"
    await db_session.commit()

    cert_changed = await restore_profile(db_session, profile, confirm_cert=False)

    assert cert_changed is False
    await db_session.refresh(settings)
    assert (settings.eidas_environment, settings.legal_entity_enabled, settings.org_url) == ("qa", False, "https://ente.it")
    idps = {i.alias: i.enabled for i in (await db_session.execute(select(SpidIdP))).scalars()}
    assert idps == {"eidas-qa": True, "eidas-prod": False}
    assert (await profile_status(db_session)).differences == []


async def test_restore_with_other_cert_requires_confirmation(db_session):
    old_cert, new_cert = await _setup(db_session)
    profile = await create_validated_profile(db_session)
    old_cert.is_active, new_cert.is_active = False, True
    await db_session.commit()

    with pytest.raises(CertConfirmationRequired):
        await restore_profile(db_session, profile, confirm_cert=False)
    await db_session.refresh(new_cert)
    assert new_cert.is_active is True

    with patch("app.spid_cert_writer.write_spid_cert") as write:
        assert await restore_profile(db_session, profile, confirm_cert=True) is True
    write.assert_called_once()
    await db_session.refresh(old_cert)
    await db_session.refresh(new_cert)
    assert (old_cert.is_active, new_cert.is_active) == (True, False)


async def test_restore_with_missing_cert_fails(db_session):
    old_cert, new_cert = await _setup(db_session)
    profile = await create_validated_profile(db_session)
    profile.cert_id = None  # es. bundle di backup senza quel cert
    old_cert.is_active, new_cert.is_active = False, True
    await db_session.commit()
    with pytest.raises(CertMissing):
        await restore_profile(db_session, profile, confirm_cert=True)


# --- normalizzazione all'avvio --------------------------------------------------

async def test_normalize_recomputes_hashes_and_migrates_validated_row(db_session, tmp_path, monkeypatch):
    """Caso reale di produzione: riga validata (eIDAS off, PG off) e la stessa
    configurazione rigenerata da un'immagine nuova con prefissi ns0:."""
    monkeypatch.setenv("SATOSA_CONF_DIR", str(tmp_path))
    cert = _cert(6, True)
    db_session.add_all([_settings(eidas_enabled=True, legal_entity_enabled=True), cert])
    await db_session.commit()
    validated = SpidMetadataVersion(
        source="generated", xml_content=_md(sig="a"), content_hash="old-text-hash-1", cert_id=cert.id,
        is_validated=True, eidas_enabled=False, eidas_environment="prod", legal_entity_enabled=False,
    )
    regenerated = SpidMetadataVersion(
        source="generated", xml_content=_md(prefix="ns0", sig="b"), content_hash="old-text-hash-2",
        cert_id=cert.id, is_exposed=True, eidas_enabled=False, legal_entity_enabled=False,
    )
    db_session.add_all([validated, regenerated])
    await db_session.commit()
    (tmp_path / "spid_sp_metadata_override.xml").write_text("<Pinned/>")

    await normalize_metadata_history(db_session)
    await normalize_metadata_history(db_session)  # idempotente

    await db_session.refresh(validated)
    await db_session.refresh(regenerated)
    assert validated.content_hash == regenerated.content_hash == metadata_fingerprint(_md())
    profiles = (await db_session.execute(select(SpidMetadataProfile))).scalars().all()
    assert len(profiles) == 1
    p = profiles[0]
    assert (p.status, p.eidas_enabled, p.legal_entity_enabled, p.cert_id) == ("validated", False, False, cert.id)
    assert p.cert_fingerprint == cert_fingerprint(cert.certificate_pem)
    assert p.contact_email == "pec@ente.it"
    assert not (tmp_path / "spid_sp_metadata_override.xml").exists()
    assert regenerated.is_exposed is False

    status = await profile_status(db_session)
    assert {d.label for d in status.differences} == {"eIDAS", "Persona giuridica"}


async def test_normalize_keeps_override_of_uploaded_metadata(db_session, tmp_path, monkeypatch):
    monkeypatch.setenv("SATOSA_CONF_DIR", str(tmp_path))
    db_session.add(SpidMetadataVersion(source="uploaded", xml_content="<Manual/>", content_hash="h", is_exposed=True))
    await db_session.commit()
    (tmp_path / "spid_sp_metadata_override.xml").write_text("<Manual/>")

    await normalize_metadata_history(db_session)

    assert (tmp_path / "spid_sp_metadata_override.xml").exists()


async def test_certs_delete_blocked_for_validated_profile_cert(db_session, monkeypatch):
    """Il cert del profilo validato serve per ripristinarlo."""
    monkeypatch.setenv("ADMIN_USER", "admin")
    monkeypatch.setenv("ADMIN_PASSWORD", "secret")
    monkeypatch.setenv("SESSION_SECRET", "test-secret-32-chars-minimum-pad")
    from httpx import AsyncClient, ASGITransport
    from app.database import get_db
    from app.main import app

    old_cert, new_cert = await _setup(db_session)
    await create_validated_profile(db_session)
    old_cert.is_active, new_cert.is_active = False, True
    await db_session.commit()

    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            await client.post("/admin/login", data={"username": "admin", "password": "secret"})
            response = await client.post(f"/admin/certs/{old_cert.id}/delete", follow_redirects=False)
    finally:
        app.dependency_overrides.clear()
    assert "cert_error=" in response.headers["location"]
    assert (await db_session.execute(select(SpidCert).where(SpidCert.id == old_cert.id))).scalar_one_or_none()
