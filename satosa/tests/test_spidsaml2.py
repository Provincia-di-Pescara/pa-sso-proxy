"""
Copertura limitata alle funzioni pure a livello di modulo in spidsaml2.py.

SpidSAMLBackend (la classe) richiede un satosa.backends.saml2.SAMLBackend
completamente inizializzato — Config pysaml2 con SP reale, certificati,
template_folder popolato, ecc. Costruire quel fixture per testare
_metadata_contact_person / __create_metadata / authn_request / authn_response
richiederebbe una configurazione SPID SP completa fuori scope per unit test
(sarebbe più simile a un test di integrazione). Vedi backends/cieoidc/tests/
per fixture analoghe se in futuro si vuole coprire anche questo.
"""
import base64
from unittest.mock import patch

import backends.spidsaml2 as spidsaml2


SAML_RESPONSE_WITH_ATTRS = """<?xml version="1.0"?>
<saml2p:Response xmlns:saml2p="urn:oasis:names:tc:SAML:2.0:protocol"
                  xmlns:saml2="urn:oasis:names:tc:SAML:2.0:assertion">
  <saml2:Signature>keep-me</saml2:Signature>
  <saml2:Assertion>
    <saml2:AttributeStatement>
      <saml2:Attribute Name="fiscalNumber"><saml2:AttributeValue>RSSMRA80A01H501U</saml2:AttributeValue></saml2:Attribute>
      <saml2:Attribute Name="email"><saml2:AttributeValue>mario.rossi@example.org</saml2:AttributeValue></saml2:Attribute>
    </saml2:AttributeStatement>
  </saml2:Assertion>
</saml2p:Response>"""


def _b64(xml: str) -> str:
    return base64.b64encode(xml.encode("utf-8")).decode("ascii")


def test_redact_pii_xml_removes_attribute_statement():
    redacted = spidsaml2._redact_pii_xml(_b64(SAML_RESPONSE_WITH_ATTRS))
    assert "RSSMRA80A01H501U" not in redacted
    assert "mario.rossi@example.org" not in redacted
    assert "[REDACTED AttributeStatement]" in redacted


def test_redact_pii_xml_preserves_signature():
    redacted = spidsaml2._redact_pii_xml(_b64(SAML_RESPONSE_WITH_ATTRS))
    assert "<saml2:Signature>keep-me</saml2:Signature>" in redacted


def test_redact_pii_xml_empty_input_returns_as_is():
    assert spidsaml2._redact_pii_xml(None) is None
    assert spidsaml2._redact_pii_xml("") == ""


def test_redact_pii_xml_handles_undecodable_input():
    result = spidsaml2._redact_pii_xml("not-valid-base64!!!")
    assert "impossibile decodificare" in result


def test_redact_pii_xml_no_attribute_statement_leaves_xml_unchanged():
    xml = '<saml2p:Response xmlns:saml2p="urn:oasis:names:tc:SAML:2.0:protocol"><saml2p:Status/></saml2p:Response>'
    redacted = spidsaml2._redact_pii_xml(_b64(xml))
    assert redacted == xml


@patch("urllib.request.urlopen")
def test_post_access_log_posts_expected_payload(mock_urlopen):
    spidsaml2._post_access_log("spid", "client123", "failure", "19")
    assert mock_urlopen.call_count == 1
    request = mock_urlopen.call_args[0][0]
    assert request.full_url.endswith("/internal/access-log")
    assert request.get_header("Content-type") == "application/json"


@patch("urllib.request.urlopen", side_effect=OSError("connection refused"))
def test_post_access_log_swallows_network_errors(mock_urlopen):
    # Fire-and-forget: un errore di rete verso config-api non deve mai
    # propagare e rompere il flusso di autenticazione SPID.
    spidsaml2._post_access_log("spid", "client123", "failure", "19")
