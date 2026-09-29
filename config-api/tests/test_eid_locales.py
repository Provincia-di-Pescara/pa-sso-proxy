from types import SimpleNamespace

from app.satosa_config_generator import _eid_locale_strings


def _settings(**kw):
    base = dict(logo_url="https://e/logo.png", favicon_url="", privacy_url="https://e/p",
                legal_notes_url="", accessibility_url="https://e/a", support_url="",
                org_display_name="Comune di Test")
    base.update(kw)
    return SimpleNamespace(**base)


def test_five_languages_identical_payload():
    out = _eid_locale_strings("/CieOidcRp/authorization", _settings(), [])
    assert set(out) == {"it", "en", "fr", "de", "es"}
    assert all(out[lang] == out["it"] for lang in out)


def test_payload_has_only_dynamic_data():
    data = _eid_locale_strings("/CieOidcRp/authorization", _settings(), [])["it"]
    assert data["header"] == {"region_name": "Comune di Test", "logo_url": "https://e/logo.png", "favicon_url": ""}
    assert data["digital_id"] == {"cie": {"login_url": "/CieOidcRp/authorization"}}
    assert data["footer"] == {"privacy_policy_url": "https://e/p", "legal_notice_url": "",
                              "accessibility_url": "https://e/a", "support_url": ""}
    assert "titles" not in data
    assert "version" in data


def test_eidas_login_url_only_when_idp_enabled():
    idp = SimpleNamespace(alias="eidas-qa")
    data = _eid_locale_strings(None, _settings(), [idp])["de"]
    assert data["digital_id"]["eidas"]["login_url"].startswith("/spidSaml2/disco?entityID=")
    assert data["digital_id"]["cie"] == {"login_url": ""}


def test_no_settings_defaults():
    data = _eid_locale_strings(None, None, None)["es"]
    assert data["header"]["region_name"] == ""
