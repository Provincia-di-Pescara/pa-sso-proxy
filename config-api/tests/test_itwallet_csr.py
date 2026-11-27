import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

from app.jwk_generator import generate_ec_jwk
from app.models import EnteSettings


def _settings(**kw):
    values = dict(id=1, org_name="Comune di Prova", ipa_code="c_x000", org_city="Pescara",
                  proxy_hostname="sso.example.org")
    values.update(kw)
    return EnteSettings(**values)


def _public_key(jwk: dict) -> ec.EllipticCurvePublicKey:
    import base64

    def b(v):
        return int.from_bytes(base64.urlsafe_b64decode(v + "=" * (-len(v) % 4)), "big")

    return ec.EllipticCurvePublicNumbers(b(jwk["x"]), b(jwk["y"]), ec.SECP256R1()).public_key()


def test_csr_subject_and_signature():
    from app.itwallet_csr import build_csr

    key = generate_ec_jwk("itwallet-federation-t", "federation")
    pem = build_csr(key.private_jwk, "sso.example.org", _settings())
    assert pem.startswith(b"-----BEGIN CERTIFICATE REQUEST-----")

    csr = x509.load_pem_x509_csr(pem)
    subject = csr.subject
    assert subject.get_attributes_for_oid(NameOID.COMMON_NAME)[0].value == "sso.example.org"
    assert subject.get_attributes_for_oid(NameOID.ORGANIZATION_NAME)[0].value == "Comune di Prova"
    assert subject.get_attributes_for_oid(NameOID.ORGANIZATION_IDENTIFIER)[0].value == "PA:IT-c_x000"
    assert subject.get_attributes_for_oid(NameOID.COUNTRY_NAME)[0].value == "IT"
    assert subject.get_attributes_for_oid(NameOID.LOCALITY_NAME)[0].value == "Pescara"
    assert "2.5.4.97=PA:IT-c_x000" in subject.rfc4514_string()

    san = csr.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
    assert san.get_values_for_type(x509.DNSName) == ["sso.example.org"]

    assert csr.is_signature_valid
    assert isinstance(csr.signature_hash_algorithm, hashes.SHA256)
    # La chiave nella CSR è quella pubblica di federazione
    expected = _public_key(key.public_jwk).public_numbers()
    assert csr.public_key().public_numbers() == expected
    _public_key(key.public_jwk).verify(
        csr.signature, csr.tbs_certrequest_bytes, ec.ECDSA(hashes.SHA256())
    )


@pytest.mark.parametrize("field", ["org_name", "ipa_code", "org_city"])
def test_csr_refused_when_settings_incomplete(field):
    from app.itwallet_csr import CsrError, build_csr

    key = generate_ec_jwk("itwallet-federation-t", "federation")
    with pytest.raises(CsrError):
        build_csr(key.private_jwk, "sso.example.org", _settings(**{field: ""}))


def test_csr_refused_without_hostname():
    from app.itwallet_csr import CsrError, build_csr

    key = generate_ec_jwk("itwallet-federation-t", "federation")
    with pytest.raises(CsrError):
        build_csr(key.private_jwk, "", _settings())


def test_csr_refused_with_non_ec_key():
    from app.itwallet_csr import CsrError, build_csr

    with pytest.raises(CsrError):
        build_csr({"kty": "RSA", "n": "x", "e": "AQAB"}, "sso.example.org", _settings())
