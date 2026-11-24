"""Test del modulo oidc_frontend_ext.py generato per SATOSA.

satosa e oic non sono disponibili in config-api: stub in sys.modules, poi si
carica il sorgente generato (_OIDC_FRONTEND_EXT_PY). La verifica con SATOSA
vero è nello smoke/e2e (immagine satosa).
"""
import importlib.util
import json
import sys
import types

import pytest

from app.satosa_config_generator import _OIDC_FRONTEND_EXT_PY, _oidc_frontend_yaml

# Mappatura standard OIDC Core 5.4 (come oic.oic.scope2claims) + extra_scopes.
_STANDARD = {
    "openid": ["sub"],
    "profile": ["name", "given_name", "family_name", "middle_name", "nickname", "profile",
                "picture", "website", "gender", "birthdate", "zoneinfo", "locale",
                "updated_at", "preferred_username"],
    "email": ["email", "email_verified"],
    "address": ["address"],
    "phone": ["phone_number", "phone_number_verified"],
}


def _scope2claims(scopes, extra_scope_dict=None):
    mapping = dict(_STANDARD)
    mapping.update(extra_scope_dict or {})
    return {c: None for s in scopes for c in mapping.get(s, [])}


class _Resp:
    def __init__(self, message="", status="200 OK", **kw):
        self.message, self.status = message, status


class _SeeOther(_Resp):
    def __init__(self, location):
        super().__init__(status="303 See Other")
        self.location = location


class _BaseFrontend:
    def handle_authn_request(self, context):
        return ("super", dict(context.request))


@pytest.fixture
def ext(tmp_path, monkeypatch):
    oic = types.ModuleType("oic")
    oic_oic = types.ModuleType("oic.oic")
    oic_oic.scope2claims = _scope2claims
    fe = types.ModuleType("satosa.frontends.openid_connect")
    fe.OpenIDConnectFrontend = _BaseFrontend
    resp = types.ModuleType("satosa.response")
    resp.SeeOther, resp.Response = _SeeOther, _Resp
    for name, mod in {
        "oic": oic, "oic.oic": oic_oic, "satosa": types.ModuleType("satosa"),
        "satosa.frontends": types.ModuleType("satosa.frontends"),
        "satosa.frontends.openid_connect": fe, "satosa.response": resp,
    }.items():
        monkeypatch.setitem(sys.modules, name, mod)
    path = tmp_path / "oidc_frontend_ext.py"
    path.write_text(_OIDC_FRONTEND_EXT_PY, encoding="utf-8")
    spec = importlib.util.spec_from_file_location("oidc_frontend_ext_under_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


EXTRA = _oidc_frontend_yaml("sso.example.it")["config"]["provider"]["extra_scopes"]
CLIENTS = {
    "app-min": {"allowed_scopes": ["openid"], "redirect_uris": ["https://app.example.it/cb"]},
    "app-profile": {"allowed_scopes": ["openid", "profile"], "redirect_uris": ["https://b.example.it:8443/x"]},
}


def _frontend(ext):
    fe = ext.OIDCFrontendWithEndSession()
    fe.provider = types.SimpleNamespace(clients=CLIENTS)
    fe.config = {"provider": {"extra_scopes": EXTRA}}
    return fe


def _ctx(**params):
    return types.SimpleNamespace(request=params)


# --- scope / claims ------------------------------------------------------------

def test_scopes_outside_allowed_are_dropped(ext):
    req = {"client_id": "app-min", "scope": "openid profile email legal_entity"}
    dropped, _ = ext.filter_authn_request(req, CLIENTS["app-min"], EXTRA, _scope2claims)
    assert req["scope"] == "openid"
    assert dropped == ["profile", "email", "legal_entity"]


def test_claims_param_limited_to_allowed_scopes(ext):
    claims = {"userinfo": {"fiscal_number": {"essential": True}, "company_name": None, "sub": None},
              "id_token": {"email": None}}
    req = {"scope": "openid", "claims": json.dumps(claims)}
    _, dropped = ext.filter_authn_request(req, CLIENTS["app-min"], EXTRA, _scope2claims)
    assert json.loads(req["claims"]) == {"userinfo": {"sub": None}}
    assert set(dropped) == {"fiscal_number", "company_name", "email"}


def test_profile_allows_fiscal_number_not_company(ext):
    claims = {"userinfo": {"fiscal_number": None, "company_name": None, "given_name": None}}
    req = {"scope": "openid profile legal_entity", "claims": json.dumps(claims)}
    ext.filter_authn_request(req, CLIENTS["app-profile"], EXTRA, _scope2claims)
    assert req["scope"] == "openid profile"
    assert json.loads(req["claims"]) == {"userinfo": {"fiscal_number": None, "given_name": None}}


def test_claims_fully_dropped_removes_param(ext):
    req = {"scope": "openid", "claims": json.dumps({"userinfo": {"email": None}})}
    ext.filter_authn_request(req, CLIENTS["app-min"], EXTRA, _scope2claims)
    assert "claims" not in req


def test_invalid_claims_removed(ext):
    for raw in ("not json", "[1,2]", '"x"'):
        req = {"scope": "openid", "claims": raw}
        ext.filter_authn_request(req, CLIENTS["app-min"], EXTRA, _scope2claims)
        assert "claims" not in req


def test_client_without_allowed_scopes_untouched(ext):
    req = {"scope": "openid profile", "claims": "{}"}
    assert ext.filter_authn_request(req, {"redirect_uris": []}, EXTRA, _scope2claims) == ([], [])
    assert ext.filter_authn_request(req, None, EXTRA, _scope2claims) == ([], [])
    assert req == {"scope": "openid profile", "claims": "{}"}


def test_list_values_handled(ext):
    req = {"scope": ["openid email"]}
    ext.filter_authn_request(req, CLIENTS["app-min"], EXTRA, _scope2claims)
    assert req["scope"] == "openid"


def test_handle_authn_request_filters_before_super(ext):
    fe = _frontend(ext)
    tag, seen = fe.handle_authn_request(_ctx(client_id="app-min", scope="openid email"))
    assert tag == "super" and seen["scope"] == "openid"


def test_handle_authn_request_unknown_client_passthrough(ext):
    fe = _frontend(ext)
    _, seen = fe.handle_authn_request(_ctx(client_id="nope", scope="openid email"))
    assert seen["scope"] == "openid email"  # pyop rifiuta il client sconosciuto


def test_generated_client_db_has_allowed_scopes():
    """Il filtro legge allowed_scopes dal client db scritto dal generatore."""
    import inspect
    from app import satosa_config_generator as g
    src = inspect.getsource(g.generate_satosa_config)
    assert '"allowed_scopes": list(c.allowed_scopes)' in src


# --- end_session ---------------------------------------------------------------

@pytest.mark.parametrize("uri,ok", [
    ("https://app.example.it/logged-out", True),
    ("https://APP.example.it:443/x?y=1", True),
    ("https://b.example.it:8443/bye", True),
    ("https://b.example.it/bye", False),           # porta diversa
    ("http://app.example.it/x", False),            # schema diverso
    ("https://phishing.example/login", False),
    ("https://app.example.it.evil.com/", False),
    ("https://evil.com@app.example.it.x/", False),
    ("javascript:alert(1)", False),
    ("//app.example.it/x", False),
    ("https://app.example.it:99999/", False),
    ("", False),
])
def test_logout_redirect_allowed(ext, uri, ok):
    assert ext.logout_redirect_allowed(uri, CLIENTS) is ok


def test_end_session_open_redirect_blocked(ext):
    fe = _frontend(ext)
    r = fe.end_session(_ctx(post_logout_redirect_uri="https://phishing.example/login"))
    assert r.status == "200 OK" and not hasattr(r, "location")
    r = fe.end_session(_ctx(post_logout_redirect_uri=["https://app.example.it/bye"]))
    assert r.status == "303 See Other" and r.location == "https://app.example.it/bye"
    assert fe.end_session(_ctx()).status == "200 OK"
