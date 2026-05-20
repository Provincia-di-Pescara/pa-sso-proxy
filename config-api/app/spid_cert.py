from datetime import datetime, timezone, timedelta

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509 import NameAttribute, ObjectIdentifier
from cryptography.x509.extensions import BasicConstraints, KeyUsage

from app.models import EnteSettings, SpidCert

OID_ENTITY_ID = ObjectIdentifier("2.5.4.83")
OID_ORG_IDENTIFIER = ObjectIdentifier("2.5.4.97")
OID_AGID_ROOT = ObjectIdentifier("1.3.76.16")
OID_AGID_CERT = ObjectIdentifier("1.3.76.16.6")
OID_CERT_SP_PUB = ObjectIdentifier("1.3.76.16.4.2.1")


def generate_spid_cert(settings: EnteSettings) -> SpidCert:
    """Generate RSA 2048 + X.509 with AgID-compliant SubjectDN. Returns SpidCert (not committed)."""
    missing = [f for f in ("proxy_hostname", "org_name", "ipa_code", "org_city") if not getattr(settings, f, "")]
    if missing:
        raise ValueError(f"Impostazioni ente incomplete: {', '.join(missing)} obbligatori per generare il certificato")

    privkey = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    subject = x509.Name([
        NameAttribute(x509.oid.NameOID.COMMON_NAME, settings.proxy_hostname),
        NameAttribute(x509.oid.NameOID.ORGANIZATION_NAME, settings.org_name),
        NameAttribute(OID_ENTITY_ID, f"https://{settings.proxy_hostname}"),
        NameAttribute(OID_ORG_IDENTIFIER, f"PA:IT-{settings.ipa_code}"),
        NameAttribute(x509.oid.NameOID.COUNTRY_NAME, "IT"),
        NameAttribute(x509.oid.NameOID.LOCALITY_NAME, settings.org_city),
    ])

    now = datetime.now(timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
        .public_key(privkey.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(seconds=60))
        .not_valid_after(now + timedelta(days=3650))
        .add_extension(BasicConstraints(ca=False, path_length=None), critical=False)
        .add_extension(
            KeyUsage(
                digital_signature=True, content_commitment=True,
                key_encipherment=False, data_encipherment=False,
                key_agreement=False, key_cert_sign=False,
                crl_sign=False, encipher_only=False, decipher_only=False,
            ),
            critical=True,
        )
        .add_extension(
            x509.CertificatePolicies([
                x509.PolicyInformation(OID_AGID_ROOT, None),
                x509.PolicyInformation(OID_AGID_CERT, None),
                x509.PolicyInformation(OID_CERT_SP_PUB, None),
            ]),
            critical=False,
        )
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(privkey.public_key()), critical=False)
        .sign(privkey, hashes.SHA256())
    )

    return SpidCert(
        certificate_pem=cert.public_bytes(serialization.Encoding.PEM).decode(),
        private_key_pem=privkey.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        ).decode(),
        not_valid_after=cert.not_valid_after_utc,
        subject_dn=cert.subject.rfc4514_string(),
    )
