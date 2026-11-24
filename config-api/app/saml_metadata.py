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
