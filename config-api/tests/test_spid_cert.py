import pytest
from datetime import datetime, timezone, timedelta

from app.models import EnteSettings, SpidCert


def make_settings(**overrides):
    defaults = dict(
        proxy_hostname="login.test.it",
        org_name="Ente Test",
        org_display_name="Ente Test",
        org_url="https://test.it",
        ipa_code="TEST",
        contact_email="test@test.it",
        contact_phone="+39",
        org_city="Pescara",
    )
    defaults.update(overrides)
    return EnteSettings(**defaults)


def test_generate_cert_returns_spid_cert_instance():
    from app.spid_cert import generate_spid_cert
    settings = make_settings()
    cert = generate_spid_cert(settings)
    assert isinstance(cert, SpidCert)
    assert cert.certificate_pem.startswith("-----BEGIN CERTIFICATE-----")
    assert cert.private_key_pem.startswith("-----BEGIN PRIVATE KEY-----")
    assert "login.test.it" in cert.subject_dn


def test_generate_cert_expires_in_10_years():
    from app.spid_cert import generate_spid_cert
    settings = make_settings()
    cert = generate_spid_cert(settings)
    now = datetime.now(timezone.utc)
    delta = cert.not_valid_after - now
    assert 3640 < delta.days < 3660


def test_generate_cert_missing_fields_raises():
    from app.spid_cert import generate_spid_cert
    settings = make_settings(proxy_hostname="")
    with pytest.raises(ValueError, match="proxy_hostname"):
        generate_spid_cert(settings)
