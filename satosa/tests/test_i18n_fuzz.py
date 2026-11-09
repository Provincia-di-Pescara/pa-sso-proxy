"""Fuzz (Hypothesis) della risoluzione lingua: cookie, Accept-Language e
ui_locales arrivano dal browser/client senza controlli. Qualunque input deve
dare una lingua supportata e mai un'eccezione (romperebbe login e pagina d'errore).
Gira sull'host e nel container, come test_i18n.py."""
import importlib.util
import urllib.parse
from pathlib import Path

from hypothesis import given, settings
from hypothesis import strategies as st

try:
    from backends import i18n  # container satosa
except ImportError:  # host: carica il file dal repo
    _spec = importlib.util.spec_from_file_location(
        "i18n", Path(__file__).resolve().parents[1] / "plugins" / "i18n.py"
    )
    i18n = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(i18n)

FUZZ = settings(max_examples=300, deadline=None)

# Testo qualsiasi + testo costruito con i separatori che i parser usano davvero.
_tokens = st.sampled_from(
    ["it", "EN", "fr-CA", "de_DE", "es", "xx", "*", ";", ",", "q=", "q=0", "q=1.5",
     "q=nan", "q=-1", "=", '"', "sso_lang", "\\", " ", "\t", "\x00", "é"]
)
header_text = st.one_of(st.text(), st.lists(_tokens, max_size=20).map("".join))


class _Ctx:
    def __init__(self, cookie, accept_language, state):
        self.http_headers = {"HTTP_ACCEPT_LANGUAGE": accept_language}
        self.cookie = cookie
        self.state = state


@FUZZ
@given(st.one_of(st.none(), header_text))
def test_normalize_solo_lingue_supportate(tag):
    assert i18n.normalize(tag) in (None, *i18n.SUPPORTED)


@FUZZ
@given(st.one_of(st.none(), header_text))
def test_accept_language_mai_eccezioni(header):
    langs = i18n.parse_accept_language(header)
    assert set(langs) <= set(i18n.SUPPORTED)
    assert len(langs) == len(set(langs))


@FUZZ
@given(st.one_of(st.none(), header_text, header_text.map(lambda v: f"sso_lang={v}")))
def test_cookie_mai_eccezioni(cookie):
    assert i18n.lang_from_cookie(cookie) in (None, *i18n.SUPPORTED)


@FUZZ
@given(
    cookie=st.one_of(st.none(), header_text),
    accept_language=st.one_of(st.none(), header_text),
    # Scritto solo da authn_request (stringa) nello stato SATOSA cifrato: non arriva dal client.
    state_lang=st.one_of(st.none(), st.text()),
    ui_locales=st.one_of(st.none(), header_text),
    raw_request=st.one_of(st.none(), st.text()),
)
def test_resolve_lang_sempre_supportata(cookie, accept_language, state_lang, ui_locales, raw_request):
    oidc_request = raw_request
    if ui_locales is not None:
        oidc_request = urllib.parse.urlencode({"ui_locales": ui_locales})
    state = {i18n.STATE_KEY: state_lang, "frontend": {"oidc_request": oidc_request}}
    ctx = _Ctx(cookie, accept_language, state)
    assert i18n.resolve_lang(ctx) in i18n.SUPPORTED
