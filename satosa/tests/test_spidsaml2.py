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

import pytest
import json
import os
from unittest.mock import MagicMock, patch

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


class _FakeContext:
    def __init__(self, state):
        self.state = state


def test_legal_entity_requested_true_when_scope_present():
    ctx = _FakeContext({"OIDC": {"oidc_request": "client_id=x&scope=openid+profile+legal_entity&state=y"}})
    assert spidsaml2._legal_entity_requested(ctx) is True


def test_legal_entity_requested_false_when_scope_absent():
    ctx = _FakeContext({"OIDC": {"oidc_request": "client_id=x&scope=openid+profile&state=y"}})
    assert spidsaml2._legal_entity_requested(ctx) is False


def test_legal_entity_requested_false_when_no_oidc_request():
    ctx = _FakeContext({"OIDC": {"oidc_request": None}})
    assert spidsaml2._legal_entity_requested(ctx) is False


def test_legal_entity_requested_false_when_state_has_no_oidc_key():
    ctx = _FakeContext({"some_other_key": {"foo": "bar"}})
    assert spidsaml2._legal_entity_requested(ctx) is False


def test_build_purpose_extension_produces_expected_xml():
    ext = spidsaml2._build_purpose_extension("PG")
    xml = ext.to_string().decode("utf-8") if isinstance(ext.to_string(), bytes) else ext.to_string()
    assert 'https://spid.gov.it/saml-extensions' in xml
    assert '<spid:Purpose' in xml or ':Purpose' in xml
    assert '>PG<' in xml


def test_report_metadata_snapshot_posts_xml(monkeypatch):
    monkeypatch.setenv("CONFIG_API_INTERNAL_URL", "http://config-api:8000")
    captured = {}

    def fake_urlopen(req, timeout):
        captured["url"] = req.full_url
        captured["data"] = req.data
        captured["method"] = req.get_method()
        return MagicMock()

    monkeypatch.setattr("backends.spidsaml2.urllib.request.urlopen", fake_urlopen)
    spidsaml2._report_metadata_snapshot("<EntityDescriptor/>")

    assert captured["url"] == "http://config-api:8000/internal/spid-metadata-snapshot"
    assert captured["method"] == "POST"
    assert b"EntityDescriptor" in captured["data"]


def test_report_metadata_snapshot_includes_semantic_hash_when_given(monkeypatch):
    monkeypatch.setenv("CONFIG_API_INTERNAL_URL", "http://config-api:8000")
    captured = {}

    def fake_urlopen(req, timeout):
        captured["data"] = req.data
        return MagicMock()

    monkeypatch.setattr("backends.spidsaml2.urllib.request.urlopen", fake_urlopen)
    spidsaml2._report_metadata_snapshot("<EntityDescriptor/>", "deadbeef" * 8)

    payload = json.loads(captured["data"])
    assert payload["semantic_hash"] == "deadbeef" * 8
    assert payload["xml_content"] == "<EntityDescriptor/>"


def test_report_metadata_snapshot_omits_semantic_hash_when_none(monkeypatch):
    monkeypatch.setenv("CONFIG_API_INTERNAL_URL", "http://config-api:8000")
    captured = {}

    def fake_urlopen(req, timeout):
        captured["data"] = req.data
        return MagicMock()

    monkeypatch.setattr("backends.spidsaml2.urllib.request.urlopen", fake_urlopen)
    spidsaml2._report_metadata_snapshot("<EntityDescriptor/>")

    payload = json.loads(captured["data"])
    assert "semantic_hash" not in payload


def test_report_metadata_snapshot_swallows_errors(monkeypatch):
    def fake_urlopen(req, timeout):
        raise OSError("connection refused")

    monkeypatch.setattr("backends.spidsaml2.urllib.request.urlopen", fake_urlopen)
    spidsaml2._report_metadata_snapshot("<EntityDescriptor/>")  # non deve sollevare


def test_read_metadata_override_returns_none_if_missing(monkeypatch, tmp_path):
    monkeypatch.setenv("SATOSA_CONF_DIR", str(tmp_path))
    assert spidsaml2._read_metadata_override() is None


def test_read_metadata_override_returns_bytes_if_present(monkeypatch, tmp_path):
    monkeypatch.setenv("SATOSA_CONF_DIR", str(tmp_path))
    override_path = tmp_path / "spid_sp_metadata_override.xml"
    override_path.write_text("<Overridden/>")
    assert spidsaml2._read_metadata_override() == b"<Overridden/>"


def test_read_metadata_override_returns_none_if_symlink(monkeypatch, tmp_path):
    # os.O_NOFOLLOW makes the open() itself refuse a symlinked override file
    # atomically (no separate os.path.islink() TOCTOU window). This exercises
    # the ELOOP path of the single try/except in _read_metadata_override.
    monkeypatch.setenv("SATOSA_CONF_DIR", str(tmp_path))
    secret_path = tmp_path / "spid_sp_key.pem"
    secret_path.write_text("-----BEGIN PRIVATE KEY-----\nSECRET\n-----END PRIVATE KEY-----")
    override_path = tmp_path / "spid_sp_metadata_override.xml"
    os.symlink(secret_path, override_path)
    assert spidsaml2._read_metadata_override() is None


def test_read_metadata_override_returns_none_if_unreadable(monkeypatch, tmp_path):
    # A permission error (or any other OSError raised by os.open — file
    # removed mid-request in a race, etc.) is caught by the same broad
    # `except Exception` branch as the symlink case above: any failure to
    # open falls back to None (dynamic metadata) instead of raising and
    # 500-ing the public /spidSaml2/metadata endpoint.
    monkeypatch.setenv("SATOSA_CONF_DIR", str(tmp_path))
    override_path = tmp_path / "spid_sp_metadata_override.xml"
    override_path.write_text("<Overridden/>")

    def fake_open(path, flags):
        raise PermissionError("Permission denied")

    monkeypatch.setattr("backends.spidsaml2.os.open", fake_open)
    assert spidsaml2._read_metadata_override() is None


def test_read_metadata_override_round_trips_atomic_write(monkeypatch, tmp_path):
    # Mirrors the write side in config-api/app/routes/metadata.py: write to
    # a temp file then os.replace() into place. The read side must still
    # see the final content after that atomic swap.
    monkeypatch.setenv("SATOSA_CONF_DIR", str(tmp_path))
    override_path = tmp_path / "spid_sp_metadata_override.xml"
    tmp_write_path = str(override_path) + ".tmp"
    with open(tmp_write_path, "w", encoding="utf-8") as f:
        f.write("<AtomicallyWritten/>")
    os.replace(tmp_write_path, str(override_path))

    assert spidsaml2._read_metadata_override() == b"<AtomicallyWritten/>"


# --- Persona giuridica: solo SPID (CIE/eIDAS esclusi) ------------------------

_LEGAL_ENTITY_STATE = {"OIDC": {"oidc_request": "client_id=x&scope=openid+legal_entity&state=y"}}
_CITIZEN_STATE = {"OIDC": {"oidc_request": "client_id=x&scope=openid+profile&state=y"}}
_FICEP_ID = "https://sp-proxy.eid.gov.it/spproxy/idpitmetadata"


def test_legal_entity_requested_false_when_state_is_none():
    assert spidsaml2._legal_entity_requested(_FakeContext(None)) is False


def test_add_disco_params_without_query():
    assert spidsaml2._add_disco_params("https://sso/disco.html", {"legal_entity": "1"}) == "https://sso/disco.html?legal_entity=1"


def test_add_disco_params_keeps_existing_query():
    url = spidsaml2._add_disco_params(
        "https://sso.example.org/static/disco.html?entityID=sp&return=https%3A%2F%2Fsso%2Fdisco",
        {"legal_entity": "1", "lang": "de"},
    )
    assert url.startswith("https://sso.example.org/static/disco.html?entityID=sp&return=")
    assert url.endswith("&legal_entity=1&lang=de")


def _disco_location(response):
    return dict(response.headers)["Location"]


def test_disco_query_adds_legal_entity_param_when_requested():
    from satosa.response import SeeOther
    base = "https://sso.example.org/static/disco.html?entityID=sp&return=r"
    with patch.object(spidsaml2.SAMLBackend, "disco_query", return_value=SeeOther(base)):
        resp = spidsaml2.SpidSAMLBackend.disco_query(MagicMock(spec=spidsaml2.SpidSAMLBackend), _FakeContext(_LEGAL_ENTITY_STATE))
    assert _disco_location(resp) == base + "&legal_entity=1"
    assert resp.status.startswith("303")


def test_disco_query_unchanged_for_citizen_flow():
    from satosa.response import SeeOther
    base = "https://sso.example.org/static/disco.html?entityID=sp&return=r"
    original = SeeOther(base)
    with patch.object(spidsaml2.SAMLBackend, "disco_query", return_value=original):
        resp = spidsaml2.SpidSAMLBackend.disco_query(MagicMock(spec=spidsaml2.SpidSAMLBackend), _FakeContext(_CITIZEN_STATE))
    assert resp is original


def _fake_backend():
    backend = MagicMock()
    backend.config = {"sp_config": {"ficep_entity_id": _FICEP_ID}}
    backend.handle_error.return_value = "ERROR_PAGE"
    return backend


def test_authn_request_rejects_eidas_for_legal_entity():
    backend = _fake_backend()
    res = spidsaml2.SpidSAMLBackend.authn_request(backend, _FakeContext(_LEGAL_ENTITY_STATE), _FICEP_ID)
    assert res == "ERROR_PAGE"
    kwargs = backend.handle_error.call_args.kwargs
    assert kwargs["message_key"] == spidsaml2.LEGAL_ENTITY_SPID_ONLY_ERROR["message_key"]
    # nessun context → pagina di errore del proxy, non redirect al client;
    # lang_context solo per la lingua
    assert "context" not in kwargs
    assert kwargs["lang_context"] is not None
    backend.check_blacklist.assert_not_called()


def test_authn_request_allows_spid_idp_for_legal_entity():
    backend = _fake_backend()
    # Oltre il guard l'implementazione reale prosegue: basta verificare che il
    # guard non intervenga (check_blacklist è la prima istruzione successiva).
    backend.check_blacklist.side_effect = RuntimeError("past guard")
    with pytest.raises(RuntimeError, match="past guard"):
        spidsaml2.SpidSAMLBackend.authn_request(
            backend, _FakeContext(_LEGAL_ENTITY_STATE), "https://idp.spid.example.org"
        )
    backend.handle_error.assert_not_called()


def test_authn_request_allows_eidas_for_citizen():
    backend = _fake_backend()
    backend.check_blacklist.side_effect = RuntimeError("past guard")
    with pytest.raises(RuntimeError, match="past guard"):
        spidsaml2.SpidSAMLBackend.authn_request(backend, _FakeContext(_CITIZEN_STATE), _FICEP_ID)
    backend.handle_error.assert_not_called()


# --- i18n ---------------------------------------------------------------------

def test_disco_query_adds_lang_from_ui_locales():
    from satosa.response import SeeOther
    base = "https://sso.example.org/static/disco.html?entityID=sp&return=r"
    state = {"OIDC": {"oidc_request": "client_id=x&scope=openid&ui_locales=fr-CA&state=y"}}
    with patch.object(spidsaml2.SAMLBackend, "disco_query", return_value=SeeOther(base)):
        resp = spidsaml2.SpidSAMLBackend.disco_query(MagicMock(spec=spidsaml2.SpidSAMLBackend), _FakeContext(state))
    assert _disco_location(resp) == base + "&lang=fr"


def test_disco_query_adds_lang_and_legal_entity():
    from satosa.response import SeeOther
    base = "https://sso.example.org/static/disco.html?entityID=sp&return=r"
    state = {"OIDC": {"oidc_request": "client_id=x&scope=openid+legal_entity&ui_locales=de&state=y"}}
    with patch.object(spidsaml2.SAMLBackend, "disco_query", return_value=SeeOther(base)):
        resp = spidsaml2.SpidSAMLBackend.disco_query(MagicMock(spec=spidsaml2.SpidSAMLBackend), _FakeContext(state))
    assert _disco_location(resp) == base + "&legal_entity=1&lang=de"


def test_spid_anomalies_are_keys():
    for n, entry in spidsaml2.SPID_ANOMALIES.items():
        assert entry["message_key"] == f"error.spid.{n}"


class _LangCtx(_FakeContext):
    def __init__(self, state, accept_language):
        super().__init__(state)
        self.http_headers = {"HTTP_ACCEPT_LANGUAGE": accept_language}
        self.cookie = ""


def _render_backend(tmp_path):
    from jinja2 import Environment, FileSystemLoader
    (tmp_path / "e.html").write_text(
        "{{ lang }}|{{ message }}|{{ troubleshoot }}|{{ detail }}|{{ t('error.button.retry') }}",
        encoding="utf-8",
    )
    backend = MagicMock()
    backend.error_page = Environment(loader=FileSystemLoader(str(tmp_path))).get_template("e.html")
    return backend


def _body(resp):
    return resp.message.decode() if isinstance(resp.message, bytes) else resp.message


def test_handle_error_renders_page_in_browser_language(tmp_path):
    backend = _render_backend(tmp_path)
    ctx = _LangCtx({}, "de-DE,de;q=0.9")
    resp = spidsaml2.SpidSAMLBackend.handle_error(
        backend, **spidsaml2.SPID_ANOMALIES[19], lang_context=ctx, detail="nr19"
    )
    lang, message, troubleshoot, detail, retry = _body(resp).split("|")
    assert lang == "de"
    assert message == spidsaml2.i18n.t("de", "error.spid.19")
    assert troubleshoot == spidsaml2.i18n.t("de", "error.spid.19.troubleshoot")
    assert detail == "nr19"
    assert retry == spidsaml2.i18n.t("de", "error.button.retry")
    assert message != spidsaml2.i18n.t("it", "error.spid.19")
    assert resp.status.startswith("403")


@patch.object(spidsaml2, "_post_access_log")
def test_handle_error_redirect_description_translated(_log):
    import urllib.parse as up
    ctx = _LangCtx(
        {"OIDC": {"oidc_request": "client_id=c&redirect_uri=https%3A%2F%2Fapp%2Fcb&state=s&ui_locales=es"}},
        "fr",
    )
    resp = spidsaml2.SpidSAMLBackend.handle_error(MagicMock(), **spidsaml2.SPID_ANOMALIES[22], context=ctx)
    body = _body(resp)
    assert "error=access_denied" in body
    assert up.urlencode({"error_description": spidsaml2.i18n.t("es", "error.spid.22")}) in body


@pytest.mark.parametrize("lang", ["it", "en", "fr", "de", "es"])
def test_real_error_template_renders_in_language(lang):
    from jinja2 import Environment, FileSystemLoader, select_autoescape
    env = Environment(loader=FileSystemLoader("/satosa_proxy/templates"), autoescape=select_autoescape(["html"]))
    env.globals.update({"static": "/static/"})
    backend = MagicMock()
    backend.error_page = env.get_template("spid_login_error.html")
    ctx = _LangCtx({}, lang)
    body = _body(spidsaml2.SpidSAMLBackend.handle_error(backend, **spidsaml2.SPID_ANOMALIES[25], lang_context=ctx))
    t = spidsaml2.i18n.template_vars(lang)["t"]
    assert f'<html lang="{lang}">' in body
    assert f"eid-{lang}.json" in body
    from markupsafe import escape
    for key in ("error.title.generic", "error.button.retry", "error.button.cancel", "error.spid.25"):
        assert str(escape(t(key))) in body


def test_authn_request_remembers_language_for_acs():
    backend = _fake_backend()
    backend.check_blacklist.side_effect = RuntimeError("past guard")
    ctx = _LangCtx({"OIDC": {"oidc_request": "client_id=x&scope=openid&state=y"}}, "de")
    ctx.cookie = "sso_lang=fr"
    with pytest.raises(RuntimeError, match="past guard"):
        spidsaml2.SpidSAMLBackend.authn_request(backend, ctx, "https://idp.spid.example.org")
    assert ctx.state[spidsaml2.i18n.STATE_KEY] == "fr"
