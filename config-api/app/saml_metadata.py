"""Controllo dei metadata SAML scaricati prima che arrivino a SATOSA.

pysaml2 carica i metadata locali all'avvio del backend: un file XML troncato
fa fallire con SAMLError l'avvio di tutto SATOSA (anche CIE e frontend OIDC),
una pagina HTML (es. manutenzione del registro servita con 200) carica 0 IdP
e blocca ogni login SPID. Si scrive/salva solo contenuto che supera questo
controllo; altrimenti resta la versione precedente.
"""
from defusedxml import ElementTree as ET

MD_NS = "urn:oasis:names:tc:SAML:2.0:metadata"
DS_NS = "http://www.w3.org/2000/09/xmldsig#"
MAX_METADATA_BYTES = 20 * 1024 * 1024


class InvalidMetadata(ValueError):
    pass


def check_idp_metadata(content: bytes | str) -> int:
    """Numero di IdP con certificato nel documento; InvalidMetadata se non valido."""
    data = content.encode("utf-8") if isinstance(content, str) else content
    if not data:
        raise InvalidMetadata("vuoto")
    if len(data) > MAX_METADATA_BYTES:
        raise InvalidMetadata(f"troppo grande ({len(data)} byte)")
    try:
        root = ET.fromstring(data)
    except Exception as exc:  # ParseError, entità/DTD vietate da defusedxml
        raise InvalidMetadata(f"XML non valido: {exc}") from exc

    if root.tag == f"{{{MD_NS}}}EntityDescriptor":
        entities = [root]
    elif root.tag == f"{{{MD_NS}}}EntitiesDescriptor":
        entities = root.iter(f"{{{MD_NS}}}EntityDescriptor")
    else:
        raise InvalidMetadata(f"radice inattesa: {root.tag[:80]}")

    idps = 0
    for entity in entities:
        if not entity.get("entityID"):
            continue
        for sso in entity.findall(f"{{{MD_NS}}}IDPSSODescriptor"):
            if sso.find(f".//{{{DS_NS}}}X509Certificate") is not None:
                idps += 1
                break
    if idps == 0:
        raise InvalidMetadata("nessun IdP con certificato")
    return idps


# --- firma del metadata aggregato SPID ----------------------------------------
# AgID firma la radice EntitiesDescriptor (enveloped, rsa-sha256, exc-c14n).
# Senza verifica la fiducia stava tutta nel TLS del registro: chi riesce a
# servire un aggregato alterato (CA compromessa, DNS/proxy in uscita) inserisce
# un IdP con il proprio certificato e firma asserzioni per qualunque cittadino.
import os as _os
from pathlib import Path as _Path

AGID_CERT_PATH = _Path(__file__).parent / "certs" / "agid-spid-metadata.pem"


def aggregate_signing_cert() -> str:
    """PEM del certificato AgID (SPID_AGGREGATE_SIGNING_CERT = percorso alternativo,
    per un rinnovo AgID prima di aggiornare l'immagine)."""
    path = _os.environ.get("SPID_AGGREGATE_SIGNING_CERT") or AGID_CERT_PATH
    text = _Path(path).read_text(encoding="utf-8")
    start = text.find("-----BEGIN CERTIFICATE-----")
    if start < 0:
        raise InvalidMetadata(f"certificato AgID non trovato in {path}")
    return text[start:]


def verify_aggregate_signature(data: bytes, cert_pem: str | None = None) -> bytes:
    """Verifica la firma AgID e restituisce SOLO il contenuto firmato (radice
    EntitiesDescriptor serializzata da ciò che la firma copre: niente signature
    wrapping). InvalidMetadata se firma assente, non valida o di altro cert."""
    from lxml import etree
    from signxml import SignatureConfiguration, XMLVerifier

    if len(data) > MAX_METADATA_BYTES:
        raise InvalidMetadata(f"troppo grande ({len(data)} byte)")
    cert_pem = cert_pem or aggregate_signing_cert()
    try:
        parser = etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=False)
        result = XMLVerifier().verify(
            etree.fromstring(data, parser=parser),
            x509_cert=cert_pem,
            expect_config=SignatureConfiguration(expect_references=1),
        )
    except Exception as exc:
        raise InvalidMetadata(f"firma AgID non valida: {type(exc).__name__}: {exc}") from exc
    signed = result.signed_xml
    if signed is None or signed.tag != f"{{{MD_NS}}}EntitiesDescriptor":
        raise InvalidMetadata("la firma non copre un EntitiesDescriptor")
    return etree.tostring(signed, xml_declaration=True, encoding="UTF-8")
