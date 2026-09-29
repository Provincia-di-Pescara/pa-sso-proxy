"""Completezza del catalogo i18n e copertura delle chiavi usate.

Gira sull'host (job `pytest` di satosa-tests.yml): nel container satosa è
montata solo /tests, quindi i sorgenti del repo non ci sono → skip.
"""
import json
import re
from pathlib import Path

import pytest

REPO_SATOSA = Path(__file__).resolve().parents[1]
I18N_DIR = REPO_SATOSA / "public" / "static" / "i18n"
LANGS = ("it", "en", "fr", "de", "es")

pytestmark = pytest.mark.skipif(not I18N_DIR.is_dir(), reason="sorgenti repo non disponibili")

_PLACEHOLDER = re.compile(r"\{(\w+)\}")


def _catalog(lang):
    return json.loads((I18N_DIR / f"{lang}.json").read_text(encoding="utf-8"))


def test_catalog_same_keys_in_all_languages():
    ref = set(_catalog("it"))
    for lang in LANGS[1:]:
        keys = set(_catalog(lang))
        assert keys == ref, f"{lang}: mancanti={sorted(ref - keys)} extra={sorted(keys - ref)}"


def test_catalog_no_empty_values():
    for lang in LANGS:
        empty = [k for k, v in _catalog(lang).items() if not isinstance(v, str) or not v.strip()]
        assert not empty, f"{lang}: valori vuoti {empty}"


def test_catalog_same_placeholders():
    ref = _catalog("it")
    for lang in LANGS[1:]:
        cat = _catalog(lang)
        for key, value in ref.items():
            assert set(_PLACEHOLDER.findall(cat[key])) == set(_PLACEHOLDER.findall(value)), f"{lang}:{key}"


def test_catalog_html_markup_only_in_html_keys():
    for lang in LANGS:
        for key, value in _catalog(lang).items():
            if not key.endswith("_html"):
                assert "<" not in value, f"{lang}:{key} contiene markup ma non è una chiave _html"


def test_disco_keys_exist():
    html = (REPO_SATOSA / "public" / "static" / "disco.html").read_text(encoding="utf-8")
    used = set(re.findall(r'data-i18n(?:-html)?="([^"]+)"', html))
    used |= {k for _attr, k in re.findall(r'data-i18n-attr="([\w-]+):([^"]+)"', html)}
    used |= set(re.findall(r"\bt\('([\w.]+)'", html))
    assert used, "nessuna chiave trovata in disco.html"
    missing = used - set(_catalog("it"))
    assert not missing, f"chiavi usate in disco.html ma assenti: {sorted(missing)}"


def test_server_keys_exist():
    sources = [
        REPO_SATOSA / "plugins" / "spidsaml2.py",
        REPO_SATOSA / "plugins" / "cieoidc-backend" / "cieoidc.py",
        REPO_SATOSA / "plugins" / "cieoidc-endpoints" / "authorization_callback_endpoint.py",
        REPO_SATOSA / "public" / "templates" / "spid_login_error.html",
    ]
    used = set()
    for src in sources:
        used |= set(re.findall(r"""["']((?:error|common|footer)\.[\w.]+)["']""", src.read_text(encoding="utf-8")))
    assert used, "nessuna chiave trovata nei plugin"
    missing = used - set(_catalog("it"))
    assert not missing, f"chiavi usate lato server ma assenti: {sorted(missing)}"
