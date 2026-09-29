"""Unit test di backends/i18n.py — puro Python, gira sull'host e nel container."""
import importlib.util
from pathlib import Path

import pytest

_REPO_I18N = Path(__file__).resolve().parents[1] / "public" / "static" / "i18n"

try:
    from backends import i18n  # container satosa
except ImportError:  # host: carica il file dal repo
    _spec = importlib.util.spec_from_file_location(
        "i18n", Path(__file__).resolve().parents[1] / "plugins" / "i18n.py"
    )
    i18n = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(i18n)


@pytest.fixture(autouse=True)
def _catalog_dir(monkeypatch):
    if _REPO_I18N.is_dir():
        monkeypatch.setattr(i18n, "I18N_DIR", str(_REPO_I18N))
    i18n._load.cache_clear()
    yield
    i18n._load.cache_clear()


class _Ctx:
    def __init__(self, cookie="", accept_language=None, oidc_request=None):
        self.http_headers = {}
        if cookie:
            self.http_headers["HTTP_COOKIE"] = cookie
        if accept_language is not None:
            self.http_headers["HTTP_ACCEPT_LANGUAGE"] = accept_language
        self.cookie = cookie
        self.state = {"OIDC": {"oidc_request": oidc_request}} if oidc_request is not None else {}


def test_normalize():
    assert i18n.normalize("fr-CA") == "fr"
    assert i18n.normalize("DE_at") == "de"
    assert i18n.normalize("es-419") == "es"
    assert i18n.normalize("pt-BR") is None
    assert i18n.normalize("") is None
    assert i18n.normalize(None) is None


def test_parse_accept_language_orders_by_q():
    assert i18n.parse_accept_language("de;q=0.5, fr-CH, en;q=0.8") == ["fr", "en", "de"]


def test_parse_accept_language_edge_cases():
    assert i18n.parse_accept_language("fr;q=0, en") == ["en"]
    assert i18n.parse_accept_language("*, es") == ["es"]
    assert i18n.parse_accept_language("de;q=abc, it;q=0.1") == ["it"]
    assert i18n.parse_accept_language("en-GB, en-US") == ["en"]
    assert i18n.parse_accept_language(None) == []


def test_lang_from_cookie():
    assert i18n.lang_from_cookie("a=1; sso_lang=de; b=2") == "de"
    assert i18n.lang_from_cookie("sso_lang=xx") is None
    assert i18n.lang_from_cookie(None) is None


def test_resolve_lang_malformed_cookie_header():
    ctx = _Ctx(cookie='sso_lang="; ;;=', accept_language="es")
    assert i18n.resolve_lang(ctx) == "es"


def test_resolve_lang_precedence_cookie_first():
    ctx = _Ctx(cookie="sso_lang=de", accept_language="fr",
               oidc_request="client_id=x&ui_locales=es+en&scope=openid")
    assert i18n.resolve_lang(ctx) == "de"


def test_resolve_lang_ui_locales_over_browser():
    ctx = _Ctx(accept_language="fr", oidc_request="client_id=x&ui_locales=pt-BR+es-419")
    assert i18n.resolve_lang(ctx) == "es"


def test_resolve_lang_browser():
    assert i18n.resolve_lang(_Ctx(accept_language="en-US,en;q=0.9")) == "en"


def test_resolve_lang_ignores_unsupported_cookie():
    assert i18n.resolve_lang(_Ctx(cookie="sso_lang=../../etc", accept_language="fr")) == "fr"


def test_resolve_lang_none_context():
    assert i18n.resolve_lang(None) == "it"


def test_resolve_lang_context_without_headers():
    class Bare:
        pass
    assert i18n.resolve_lang(Bare()) == "it"


def test_ui_locales_lang_absent():
    assert i18n.ui_locales_lang(_Ctx(oidc_request="client_id=x&scope=openid")) is None
    assert i18n.ui_locales_lang(_Ctx()) is None


def test_t_translates_and_falls_back(monkeypatch, tmp_path):
    (tmp_path / "it.json").write_text('{"a": "ciao {nome}", "b": "solo it"}', encoding="utf-8")
    (tmp_path / "en.json").write_text('{"a": "hi {nome}", "c": "only en"}', encoding="utf-8")
    (tmp_path / "de.json").write_text('{"a": "hallo {nome}"}', encoding="utf-8")
    monkeypatch.setattr(i18n, "I18N_DIR", str(tmp_path))
    i18n._load.cache_clear()
    assert i18n.t("de", "a", nome="Anna") == "hallo Anna"
    assert i18n.t("de", "c") == "only en"
    assert i18n.t("de", "b") == "solo it"
    assert i18n.t("de", "missing.key") == "missing.key"
    assert i18n.t("zz", "a", nome="X") == "hi X"


def test_load_rejects_unknown_lang(monkeypatch, tmp_path):
    monkeypatch.setattr(i18n, "I18N_DIR", str(tmp_path))
    assert i18n._load("../x") == {}


def test_template_vars():
    tv = i18n.template_vars("en")
    assert tv["lang"] == "en"
    assert tv["t"]("error.button.cancel") == "Cancel"
