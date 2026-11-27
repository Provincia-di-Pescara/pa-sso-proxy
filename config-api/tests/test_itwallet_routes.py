import base64
import json
import time

import pytest
import pytest_asyncio
from cryptography import x509
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.database import get_db
from app.jwk_generator import generate_ec_jwk
from app.models import CieConfig, EnteSettings, ItWalletConfig, JwkKey

HOST = "sso.example.org"


@pytest.fixture
def app_env(monkeypatch, tmp_path):
    monkeypatch.setenv("ADMIN_USER", "admin")
    monkeypatch.setenv("ADMIN_PASSWORD", "secret")
    monkeypatch.setenv("SESSION_SECRET", "test-secret-32-chars-minimum-pad")
    monkeypatch.setenv("SATOSA_CONF_DIR", str(tmp_path))


@pytest.fixture
def regen_calls(monkeypatch):
    calls = []

    async def fake_generate(db):
        calls.append("generate")

    import app.routes.itwallet as mod
    monkeypatch.setattr(mod, "generate_and_write", fake_generate)
    monkeypatch.setattr(mod, "reload_satosa", lambda: calls.append("reload") or True)
    return calls


@pytest_asyncio.fixture
async def ente(db_session):
    s = EnteSettings(id=1, org_name="Comune di Prova", org_display_name="Comune di Prova",
                     ipa_code="c_x000", org_city="Pescara", proxy_hostname=HOST,
                     contact_email="pec@comune.example.it", org_url="https://www.comune.example.it")
    db_session.add(s)
    await db_session.commit()
    return s


@pytest_asyncio.fixture
async def client(db_session, app_env, regen_calls, ente):
    from app.main import app

    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        await c.post("/admin/login", data={"username": "admin", "password": "secret"})
        yield c
    app.dependency_overrides.clear()


async def _config(db_session) -> ItWalletConfig | None:
    db_session.expire_all()
    return (await db_session.execute(select(ItWalletConfig).where(ItWalletConfig.id == 1))).scalar_one_or_none()


async def _add_keys(db_session, cfg: ItWalletConfig) -> dict[str, JwkKey]:
    keys = {
        "federation": generate_ec_jwk("itwallet-federation-t", "federation"),
        "sig": generate_ec_jwk("itwallet-sig-t", "sig"),
        "enc": generate_ec_jwk("itwallet-enc-t", "enc"),
    }
    db_session.add_all(keys.values())
    await db_session.flush()
    cfg.jwk_federation_id = keys["federation"].id
    cfg.jwk_sig_id = keys["sig"].id
    cfg.jwk_enc_id = keys["enc"].id
    await db_session.commit()
    return keys


async def _ready_config(db_session, **kw) -> ItWalletConfig:
    values = dict(id=1, enabled=False, environment="collaudo",
                  trust_anchor_url="https://ta.example.org")
    values.update(kw)
    cfg = ItWalletConfig(**values)
    db_session.add(cfg)
    await db_session.commit()
    await _add_keys(db_session, cfg)
    return cfg


def _jwt(payload: dict) -> str:
    def enc(d):
        return base64.urlsafe_b64encode(json.dumps(d).encode()).rstrip(b"=").decode()
    return f"{enc({'alg': 'ES256', 'typ': 'trust-mark+jwt'})}.{enc(payload)}.c2ln"


# --- pagina -------------------------------------------------------------------

async def test_page_replaces_placeholder(client):
    r = await client.get("/admin/itwallet")
    assert r.status_code == 200
    assert "Prossimamente" not in r.text
    for tab in ("Stato", "Configurazione", "Chiavi", "Onboarding", "Trust mark"):
        assert tab in r.text
    # voce di menu attiva, senza "soon"
    assert 'href="/admin/itwallet" class="a-nav-item active"' in r.text
    assert "a-nav-soon" not in r.text


async def test_page_shows_onboarding_ids(client, db_session):
    await _ready_config(db_session)
    r = await client.get("/admin/itwallet")
    assert f"https://{HOST}/OpenID4VP" in r.text
    assert f"openid_federation:https://{HOST}/OpenID4VP" in r.text
    assert f"https://{HOST}/OpenID4VP/.well-known/openid-federation" in r.text
    assert "jar-issuer" not in r.text


async def test_page_prefills_organization_from_ente(client):
    r = await client.get("/admin/itwallet")
    assert 'value="Comune di Prova"' in r.text
    assert 'value="pec@comune.example.it"' in r.text


async def test_page_shows_ready_reason(client, db_session):
    db_session.add(ItWalletConfig(id=1, enabled=False))
    await db_session.commit()
    r = await client.get("/admin/itwallet")
    assert "ambiente non scelto" in r.text


# --- toggle -------------------------------------------------------------------

async def test_toggle_refused_when_incomplete(client, db_session, regen_calls):
    db_session.add(ItWalletConfig(id=1, enabled=False, environment="collaudo"))
    await db_session.commit()
    r = await client.post("/admin/itwallet/toggle",
                          data={"enabled": "yes", "confirmed": "yes", "password": "secret"},
                          follow_redirects=False)
    assert r.status_code == 302
    cfg = await _config(db_session)
    assert cfg.enabled is False
    assert regen_calls == []
    page = await client.get("/admin/itwallet")
    assert "trust anchor non impostato" in page.text


async def test_toggle_requires_step_up_and_confirm(client, db_session, regen_calls):
    await _ready_config(db_session)

    # senza conferma: niente
    await client.post("/admin/itwallet/toggle",
                      data={"enabled": "yes", "password": "secret"}, follow_redirects=False)
    assert (await _config(db_session)).enabled is False

    # senza password (step-up): niente
    await client.post("/admin/itwallet/toggle",
                      data={"enabled": "yes", "confirmed": "yes"}, follow_redirects=False)
    assert (await _config(db_session)).enabled is False
    page = await client.get("/admin/itwallet")
    assert "Password non valida" in page.text

    # password sbagliata: niente
    await client.post("/admin/itwallet/toggle",
                      data={"enabled": "yes", "confirmed": "yes", "password": "nope"},
                      follow_redirects=False)
    assert (await _config(db_session)).enabled is False
    assert regen_calls == []

    r = await client.post("/admin/itwallet/toggle",
                          data={"enabled": "yes", "confirmed": "yes", "password": "secret"},
                          follow_redirects=False)
    assert r.status_code == 302
    assert (await _config(db_session)).enabled is True
    assert regen_calls == ["generate", "reload"]

    # disattivare: anche questo sotto step-up
    await client.post("/admin/itwallet/toggle", data={}, follow_redirects=False)
    assert (await _config(db_session)).enabled is True
    await client.post("/admin/itwallet/toggle", data={"password": "secret"}, follow_redirects=False)
    assert (await _config(db_session)).enabled is False


async def test_toggle_production_without_trust_mark_warns(client, db_session):
    await _ready_config(db_session, environment="produzione")
    await client.post("/admin/itwallet/toggle",
                      data={"enabled": "yes", "confirmed": "yes", "password": "secret"},
                      follow_redirects=False)
    assert (await _config(db_session)).enabled is True
    page = await client.get("/admin/itwallet")
    assert "senza trust mark" in page.text


# --- chiavi -------------------------------------------------------------------

async def test_generate_keys_requires_step_up(client, db_session, regen_calls):
    await client.post("/admin/itwallet/keys/generate", data={}, follow_redirects=False)
    cfg = await _config(db_session)
    assert cfg is None or cfg.jwk_federation_id is None

    await client.post("/admin/itwallet/keys/generate", data={"password": "secret"},
                      follow_redirects=False)
    cfg = await _config(db_session)
    ids = (cfg.jwk_federation_id, cfg.jwk_sig_id, cfg.jwk_enc_id)
    assert all(ids)
    keys = (await db_session.execute(select(JwkKey))).scalars().all()
    by_id = {k.id: k for k in keys}
    assert [by_id[i].use for i in ids] == ["federation", "sig", "enc"]
    assert all(by_id[i].private_jwk["kty"] == "EC" for i in ids)
    assert regen_calls == ["generate", "reload"]


async def test_regenerate_requires_confirmation(client, db_session):
    cfg = await _ready_config(db_session)
    old = (cfg.jwk_federation_id, cfg.jwk_sig_id, cfg.jwk_enc_id)

    await client.post("/admin/itwallet/keys/generate", data={"password": "secret"},
                      follow_redirects=False)
    cfg = await _config(db_session)
    assert (cfg.jwk_federation_id, cfg.jwk_sig_id, cfg.jwk_enc_id) == old
    page = await client.get("/admin/itwallet")
    assert "non confermata" in page.text

    await client.post("/admin/itwallet/keys/generate",
                      data={"password": "secret", "confirm_regenerate": "yes"},
                      follow_redirects=False)
    cfg = await _config(db_session)
    new = (cfg.jwk_federation_id, cfg.jwk_sig_id, cfg.jwk_enc_id)
    assert all(new) and set(new).isdisjoint(old)
    remaining = {k.id for k in (await db_session.execute(select(JwkKey))).scalars().all()}
    assert remaining == set(new)


async def test_cie_regenerate_keeps_itwallet_keys(client, db_session, monkeypatch):
    import app.routes.cie as cie_mod

    async def noop(db):
        return None
    monkeypatch.setattr(cie_mod, "generate_and_write", noop)
    cfg = await _ready_config(db_session)
    fed_id = cfg.jwk_federation_id
    wallet_ids = {fed_id, cfg.jwk_sig_id, cfg.jwk_enc_id}

    page = await client.get("/admin/cie")
    assert "itwallet-federation-t" not in page.text

    await client.post("/admin/cie/generate-all", follow_redirects=False)
    db_session.expire_all()
    remaining = {k.id for k in (await db_session.execute(select(JwkKey))).scalars().all()}
    assert wallet_ids <= remaining
    cie = (await db_session.execute(select(CieConfig).where(CieConfig.id == 1))).scalar_one()
    assert not {cie.jwk_federation_id, cie.jwk_core_sig_id, cie.jwk_core_enc_id} & wallet_ids

    # cancellare da /admin/cie una chiave IT-Wallet: rifiutato
    await client.post(f"/admin/cie/delete-jwk/{fed_id}", follow_redirects=False)
    db_session.expire_all()
    remaining = {k.id for k in (await db_session.execute(select(JwkKey))).scalars().all()}
    assert wallet_ids <= remaining


# --- JWKS / CSR ---------------------------------------------------------------

async def test_jwks_endpoint_public_only(client, db_session):
    await _ready_config(db_session)
    r = await client.get("/admin/itwallet/jwks.json")
    assert r.status_code == 200
    body = r.json()
    assert len(body["keys"]) == 1
    key = body["keys"][0]
    assert set(key) <= {"kty", "crv", "x", "y", "kid", "use", "alg"}
    assert "d" not in key and '"d"' not in r.text
    assert key["use"] == "federation"


async def test_jwks_endpoint_empty_without_keys(client):
    r = await client.get("/admin/itwallet/jwks.json")
    assert r.status_code == 200
    assert r.json() == {"keys": []}


async def test_csr_download(client, db_session):
    cfg = await _ready_config(db_session)
    r = await client.get("/admin/itwallet/csr")
    assert r.status_code == 200
    assert "itwallet-federation.csr" in r.headers["content-disposition"]
    csr = x509.load_pem_x509_csr(r.content)
    assert csr.is_signature_valid
    assert "CN=sso.example.org" in csr.subject.rfc4514_string()


async def test_csr_refused_without_ipa_code(client, db_session, ente):
    await _ready_config(db_session)
    ente.ipa_code = ""
    await db_session.commit()
    r = await client.get("/admin/itwallet/csr", follow_redirects=False)
    assert r.status_code == 302
    page = await client.get("/admin/itwallet")
    assert "codice IPA" in page.text


async def test_csr_refused_without_keys(client):
    r = await client.get("/admin/itwallet/csr", follow_redirects=False)
    assert r.status_code == 302


# --- impostazioni -------------------------------------------------------------

SETTINGS_FORM = {
    "environment": "collaudo",
    "trust_anchor_url": "https://ta.example.org",
    "authority_hint_url": "",
    "trust_anchor_jwks": "",
    "organization_name": "Comune di Prova",
    "client_name": "Comune di Prova SSO",
    "homepage_uri": "https://www.comune.example.it",
    "policy_uri": "",
    "tos_uri": "",
    "logo_uri": "",
    "contact_email": "pec@comune.example.it",
}


async def test_settings_saved(client, db_session, regen_calls):
    r = await client.post("/admin/itwallet/settings", data=SETTINGS_FORM, follow_redirects=False)
    assert r.status_code == 302
    cfg = await _config(db_session)
    assert cfg.environment == "collaudo"
    assert cfg.trust_anchor_url == "https://ta.example.org"
    assert cfg.client_name == "Comune di Prova SSO"
    assert cfg.policy_uri is None
    assert regen_calls == ["generate", "reload"]


async def test_environment_change_warns_onboarding(client, db_session):
    await client.post("/admin/itwallet/settings", data=SETTINGS_FORM, follow_redirects=False)
    page = await client.get("/admin/itwallet")
    assert "onboarding da rifare" not in page.text

    await client.post("/admin/itwallet/settings",
                      data={**SETTINGS_FORM, "environment": "produzione"}, follow_redirects=False)
    assert (await _config(db_session)).environment == "produzione"
    page = await client.get("/admin/itwallet")
    assert "onboarding da rifare" in page.text


@pytest.mark.parametrize("field,value", [
    ("trust_anchor_url", "http://ta.example.org"),
    ("trust_anchor_url", "javascript:alert(1)"),
    ("homepage_uri", "ftp://x.example.org"),
    ("logo_uri", 'https://x.example.org/"><script>'),
    ("environment", "boh"),
    ("contact_email", "non-una-mail"),
    ("trust_anchor_jwks", "{non json"),
    ("trust_anchor_jwks", '{"keys": [{"kty": "EC", "d": "segreto"}]}'),
    ("trust_anchor_jwks", '"stringa"'),
])
async def test_settings_invalid_rejected(client, db_session, field, value, regen_calls):
    await client.post("/admin/itwallet/settings", data={**SETTINGS_FORM, field: value},
                      follow_redirects=False)
    cfg = await _config(db_session)
    assert cfg is None or cfg.trust_anchor_url is None
    assert regen_calls == []


async def test_settings_http_allowed_for_custom_environment(client, db_session):
    await client.post("/admin/itwallet/settings", data={
        **SETTINGS_FORM, "environment": "personalizzato",
        "trust_anchor_url": "http://trust-anchor.example.org:5002",
    }, follow_redirects=False)
    assert (await _config(db_session)).trust_anchor_url == "http://trust-anchor.example.org:5002"


async def test_settings_trust_anchor_jwks_list_normalized(client, db_session):
    jwks = [{"kty": "EC", "crv": "P-256", "x": "a", "y": "b", "kid": "k1"}]
    await client.post("/admin/itwallet/settings",
                      data={**SETTINGS_FORM, "trust_anchor_jwks": json.dumps(jwks)},
                      follow_redirects=False)
    assert (await _config(db_session)).trust_anchor_jwks == {"keys": jwks}


# --- trust mark ---------------------------------------------------------------

async def test_trust_mark_decoded_shows_expiry(client, db_session, regen_calls):
    exp = int(time.time()) + 86400 * 30
    token = _jwt({"id": "https://ta.example.org/tm/verifier", "iss": "https://ta.example.org",
                  "sub": f"https://{HOST}/OpenID4VP", "exp": exp})
    await client.post("/admin/itwallet/trust-mark", data={"trust_mark": token}, follow_redirects=False)
    cfg = await _config(db_session)
    assert cfg.trust_mark == token
    assert cfg.trust_mark_id == "https://ta.example.org/tm/verifier"
    assert regen_calls == ["generate", "reload"]

    page = await client.get("/admin/itwallet")
    from datetime import datetime, timezone
    assert datetime.fromtimestamp(exp, timezone.utc).strftime("%Y-%m-%d") in page.text
    assert "https://ta.example.org/tm/verifier" in page.text
    assert "scaduto" not in page.text.lower().replace("non scaduto", "")


async def test_trust_mark_expired_flagged(client, db_session):
    token = _jwt({"trust_mark_id": "tm-id", "exp": int(time.time()) - 60})
    await client.post("/admin/itwallet/trust-mark", data={"trust_mark": token}, follow_redirects=False)
    assert (await _config(db_session)).trust_mark_id == "tm-id"
    page = await client.get("/admin/itwallet")
    assert "Scaduto" in page.text


@pytest.mark.parametrize("token", [
    "non-un-jwt",
    "a.b",
    "a.!!!.c",
    "eyJhbGciOiJFUzI1NiJ9.bm9uLWpzb24.c2ln",  # payload non JSON
    "x" * 20000,
])
async def test_trust_mark_invalid_rejected(client, db_session, token, regen_calls):
    await client.post("/admin/itwallet/trust-mark", data={"trust_mark": token}, follow_redirects=False)
    cfg = await _config(db_session)
    assert cfg is None or cfg.trust_mark is None
    assert regen_calls == []


async def test_trust_mark_removed_when_empty(client, db_session):
    token = _jwt({"id": "tm", "exp": int(time.time()) + 60})
    await client.post("/admin/itwallet/trust-mark", data={"trust_mark": token}, follow_redirects=False)
    await client.post("/admin/itwallet/trust-mark", data={"trust_mark": ""}, follow_redirects=False)
    cfg = await _config(db_session)
    assert cfg.trust_mark is None and cfg.trust_mark_id is None


# --- anteprima entity configuration -------------------------------------------

async def test_entity_configuration_preview(client, db_session, monkeypatch):
    await _ready_config(db_session, enabled=True)
    import app.routes.itwallet as mod
    ec_jwt = _jwt({"iss": f"openid_federation:https://{HOST}/OpenID4VP", "note": "<b>x</b>"})

    async def fake_fetch():
        return ec_jwt
    monkeypatch.setattr(mod, "_fetch_entity_configuration", fake_fetch)
    page = await client.get("/admin/itwallet")
    assert "&#34;iss&#34;" in page.text or "&quot;iss&quot;" in page.text
    assert "<b>x</b>" not in page.text


async def test_entity_configuration_preview_failure_is_friendly(client, db_session, monkeypatch):
    await _ready_config(db_session, enabled=True)
    import app.routes.itwallet as mod

    async def boom():
        raise RuntimeError("connessione rifiutata")
    monkeypatch.setattr(mod, "_fetch_entity_configuration", boom)
    page = await client.get("/admin/itwallet")
    assert page.status_code == 200
    assert "non disponibile" in page.text
