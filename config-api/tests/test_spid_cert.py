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


def test_generate_cert_is_agid_compliant():
    from app.spid_cert import generate_spid_cert
    from cryptography import x509

    settings = make_settings()
    cert = generate_spid_cert(settings)

    # Parse cert
    x509_cert = x509.load_pem_x509_certificate(cert.certificate_pem.encode())

    # Check URI matches entityID
    uri_attr = [a for a in x509_cert.subject if a.oid.dotted_string == "2.5.4.83"][0]
    assert uri_attr.value == "https://login.test.it/spidSaml2/metadata"

    # Check organizationIdentifier
    org_id_attr = [a for a in x509_cert.subject if a.oid.dotted_string == "2.5.4.97"][0]
    assert org_id_attr.value == "PA:IT-TEST"

    # Check policies extension
    policies_ext = x509_cert.extensions.get_extension_for_oid(x509.oid.ExtensionOID.CERTIFICATE_POLICIES)
    policies = policies_ext.value
    assert len(policies) == 2

    agid_cert_policy = [p for p in policies if p.policy_identifier.dotted_string == "1.3.76.16.6"][0]
    spid_pub_policy = [p for p in policies if p.policy_identifier.dotted_string == "1.3.76.16.4.2.1"][0]

    assert agid_cert_policy.policy_qualifiers[0].explicit_text == "agIDcert"
    assert spid_pub_policy.policy_qualifiers[0].explicit_text == "cert_SP_Pub"

