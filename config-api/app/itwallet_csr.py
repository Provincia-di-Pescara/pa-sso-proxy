"""CSR PKCS#10 per l'onboarding IT-Wallet, firmata con la chiave di federazione EC.

Soggetto come il certificato SPID dell'ente (`spid_cert.py`): CN=<host>, O=<ente>,
2.5.4.97=PA:IT-<IPA>, C=IT, L=<città>; SAN DNS <host>. Funzione isolata per
adattarla al modulo IPZS senza toccare il resto (spec §11).
"""
import base64

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509 import NameAttribute
from cryptography.x509.oid import NameOID

from app.models import EnteSettings


class CsrError(ValueError):
    """Dati mancanti o chiave non valida: messaggio mostrabile all'admin."""


def _b64url_int(value: str) -> int:
    return int.from_bytes(base64.urlsafe_b64decode(value + "=" * (-len(value) % 4)), "big")


def _ec_private_key(jwk: dict) -> ec.EllipticCurvePrivateKey:
    if not isinstance(jwk, dict) or jwk.get("kty") != "EC" or jwk.get("crv") != "P-256" or not jwk.get("d"):
        raise CsrError("chiave di federazione non valida (serve una chiave EC P-256 privata)")
    try:
        return ec.derive_private_key(_b64url_int(jwk["d"]), ec.SECP256R1())
    except (ValueError, TypeError) as e:
        raise CsrError("chiave di federazione non valida") from e


def build_csr(fed_private_jwk: dict, hostname: str, settings: EnteSettings) -> bytes:
    """CSR PEM firmata ECDSA SHA-256 con la chiave di federazione."""
    missing = []
    if not hostname:
        missing.append("hostname del proxy")
    if not getattr(settings, "org_name", ""):
        missing.append("nome ente")
    if not getattr(settings, "ipa_code", ""):
        missing.append("codice IPA")
    if not getattr(settings, "org_city", ""):
        missing.append("città")
    if missing:
        raise CsrError("Impostazioni ente incomplete per la CSR: " + ", ".join(missing))

    key = _ec_private_key(fed_private_jwk)
    subject = x509.Name([
        NameAttribute(NameOID.COMMON_NAME, hostname),
        NameAttribute(NameOID.ORGANIZATION_NAME, settings.org_name),
        NameAttribute(NameOID.ORGANIZATION_IDENTIFIER, f"PA:IT-{settings.ipa_code}"),
        NameAttribute(NameOID.COUNTRY_NAME, "IT"),
        NameAttribute(NameOID.LOCALITY_NAME, settings.org_city),
    ])
    csr = (
        x509.CertificateSigningRequestBuilder()
        .subject_name(subject)
        .add_extension(x509.SubjectAlternativeName([x509.DNSName(hostname)]), critical=False)
        .sign(key, hashes.SHA256())
    )
    return csr.public_bytes(serialization.Encoding.PEM)
