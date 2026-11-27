"""Generatore: config SATOSA del backend IT-Wallet (OpenID4VP) solo se attivo e completo."""
import json
import logging

import pytest
import pytest_asyncio
import yaml
from sqlalchemy import select

from app.models import EnteSettings, ItWalletConfig, JwkKey, OIDCClient

TA = "http://trust-anchor.example.org:5002"
EXPECTED_CLAIM_SET = ["given_name", "family_name", "birthdate", "place_of_birth", "tax_id_code"]
EXPECTED_PATHS = {"/pre-request", "/request-uri", "/response-uri", "/status", "/redirect-uri"}


@pytest_asyncio.fixture
async def base_db(db_session):
    db_session.add_all([
        EnteSettings(
            id=1, proxy_hostname="proxy.ente.it", org_name="Ente", org_display_name="Ente Test",
            org_url="https://ente.it", ipa_code="P_T", contact_email="e@ente.it",
            contact_phone="+39001", org_city="Roma",
        ),
        OIDCClient(client_id="app-prod", client_secret_hash="h", client_secret_plain="s1",
                   name="Prod", redirect_uris=["https://a/cb"], allowed_scopes=["openid"]),
        OIDCClient(client_id="app-collaudo", client_secret_hash="h", client_secret_plain="s2",
                   name="Collaudo", redirect_uris=["https://b/cb"], allowed_scopes=["openid"],
                   allow_test_idps=True),
        OIDCClient(client_id="app-off", client_secret_hash="h", client_secret_plain="s3",
                   name="Off", enabled=False, redirect_uris=["https://c/cb"],
                   allowed_scopes=["openid"], allow_test_idps=True),
    ])
    await db_session.commit()
    return db_session


async def _add_wallet(db, *, enabled=True, environment="produzione", keys=True, trust_mark=None):
    from app.jwk_generator import generate_ec_jwk
    ids = {}
    if keys:
        for use in ("federation", "sig", "enc"):
            k = generate_ec_jwk(f"itwallet-{use}-test", use)
            db.add(k)
            await db.flush()
            ids[use] = k.id
    cfg = ItWalletConfig(
        id=1, enabled=enabled, environment=environment,
        trust_anchor_url=TA, authority_hint_url=TA,
        jwk_federation_id=ids.get("federation"), jwk_sig_id=ids.get("sig"),
        jwk_enc_id=ids.get("enc"),
        organization_name="Ente Test", client_name="Ente Test IT-Wallet",
        homepage_uri="https://ente.it", policy_uri="https://ente.it/privacy",
        tos_uri="https://ente.it/tos", logo_uri="https://ente.it/logo.svg",
        contact_email="pec@ente.it", trust_mark=trust_mark,
    )
    db.add(cfg)
    await db.commit()
    return cfg


async def _generate(db, tmp_path, monkeypatch):
    monkeypatch.setenv("SATOSA_CONF_DIR", str(tmp_path))
    monkeypatch.setenv("REDIS_URL", "redis://redis:6379/0")
    from app.satosa_config_generator import generate_satosa_config
    await generate_satosa_config(db)
    proxy = yaml.safe_load((tmp_path / "proxy.yaml").read_text())
    router = yaml.safe_load((tmp_path / "default_router.yaml").read_text())
    eid = json.loads((tmp_path / "locales" / "eid-it.json").read_text())
    return proxy, router, eid


def _backend(tmp_path):
    return yaml.safe_load((tmp_path / "itwallet_backend.yaml").read_text())


async def test_disabled_writes_nothing(base_db, tmp_path, monkeypatch):
    await _add_wallet(base_db, enabled=False)
    proxy, router, eid = await _generate(base_db, tmp_path, monkeypatch)
    assert not (tmp_path / "itwallet_backend.yaml").exists()
    assert proxy["BACKEND_MODULES"] == ["/satosa-conf/spid_backend.yaml"]
    assert router["config"]["entity_backends"] == {}
    assert "itwallet" not in eid["digital_id"]


async def test_no_config_row_writes_nothing(base_db, tmp_path, monkeypatch):
    proxy, router, eid = await _generate(base_db, tmp_path, monkeypatch)
    assert not (tmp_path / "itwallet_backend.yaml").exists()
    assert router["config"]["entity_backends"] == {}
    assert "itwallet" not in eid["digital_id"]


async def test_disable_removes_backend_file_and_router(base_db, tmp_path, monkeypatch):
    cfg = await _add_wallet(base_db, enabled=True)
    await _generate(base_db, tmp_path, monkeypatch)
    assert (tmp_path / "itwallet_backend.yaml").exists()

    cfg.enabled = False
    await base_db.commit()
    proxy, router, eid = await _generate(base_db, tmp_path, monkeypatch)
    assert not (tmp_path / "itwallet_backend.yaml").exists()
    assert "/satosa-conf/itwallet_backend.yaml" not in proxy["BACKEND_MODULES"]
    assert router["config"]["entity_backends"] == {}
    assert "itwallet" not in eid["digital_id"]


async def test_enabled_backend_yaml(base_db, tmp_path, monkeypatch):
    from app.itwallet import derived_secret
    cfg = await _add_wallet(base_db, trust_mark="eyJhbGciOiJFUzI1NiJ9.eyJpZCI6Imh0dHBzOi8vdG0uZXhhbXBsZS9pZCJ9.sig")
    await _generate(base_db, tmp_path, monkeypatch)
    doc = _backend(tmp_path)
    assert doc["module"] == "backends.itwallet.ItWalletBackend"
    assert doc["name"] == "OpenID4VP"
    c = doc["config"]

    paths = {e["path"] for e in c["endpoints"].values()}
    assert paths == EXPECTED_PATHS
    # jar-issuer di pyeudiw 2.9.0 pubblica metadata_jwks così com'è (chiavi private)
    assert "jar_issuer" not in c["endpoints"]

    assert c["authorization"]["scopes"] == ["urn:it-wallet:eid:1"]
    assert c["authorization"]["response_mode"] == "direct_post.jwt"
    assert c["authorization"]["url_scheme"] == "haip-vp"

    dcql = json.loads(c["duckle"]["dcql_query"])
    assert len(dcql["credentials"]) == 1
    cred = dcql["credentials"][0]
    assert cred["id"] == "it-wallet-id"
    assert cred["format"] == "dc+sd-jwt"
    assert cred["meta"] == {"vct_values": ["urn:it-wallet:eid:1"]}
    assert cred["claim_sets"] == [EXPECTED_CLAIM_SET]
    assert {cl["id"] for cl in cred["claims"]} == set(EXPECTED_CLAIM_SET)
    duckle = next(f for f in c["credential_presentation_handlers"]["formats"]
                  if f["class"] == "DuckleHandler")
    assert json.loads(duckle["config"]["dcql_query"]) == dcql
    assert json.loads(duckle["config"]["duckle"]["dcql_query"]) == dcql

    assert set(c["trust"]) == {"federation"}
    fed = c["trust"]["federation"]
    assert fed["module"] == "pyeudiw.trust.handler.federation"
    fc = fed["config"]
    assert fc["client_id"] == "openid_federation:https://proxy.ente.it/OpenID4VP"
    assert fc["authority_hints"] == [TA]
    assert fc["trust_anchors"] == {TA: []}
    assert fc["trust_marks"] == [{"id": "https://tm.example/id", "trust_mark": cfg.trust_mark}]
    assert fc["httpc_params"]["connection"]["ssl"] is True
    assert fc["federation_entity_metadata"]["organization_name"] == "Ente Test"
    assert fc["federation_entity_metadata"]["contacts"] == ["pec@ente.it"]
    assert fc["metadata"]["client_id"] == "https://proxy.ente.it/OpenID4VP"
    assert fc["metadata"]["response_uris"] == ["https://proxy.ente.it/OpenID4VP/response-uri"]
    assert fc["metadata"]["logo_uri"] == "https://ente.it/logo.svg"

    assert c["network"]["httpc_params"]["connection"]["ssl"] is True
    assert c["response_code"]["sym_key"] == derived_secret("itwallet-response-code", 64)
    assert c["user_attributes"]["subject_id_random_value"] == derived_secret("itwallet-subject", 64)
    assert c["ui"] == {
        "static_storage_url": "https://proxy.ente.it/static",
        "template_folder": "/satosa_proxy/templates",
        "qrcode_template": "qr_code.html",
        "authorization_error_template": "itwallet_error.html",
    }

    redis = c["storage"]["redis"]
    assert set(redis) == {"cache", "storage"}
    assert redis["storage"]["module"] == "backends.itwallet.itwallet_storage"
    assert redis["storage"]["class"] == "RedisStorage"
    assert redis["cache"]["class"] == "RedisCache"
    for part in redis.values():
        assert part["init_params"]["url"] == "redis://redis:6379/3"
    assert "mongo_db" not in c["storage"]

    # Chiavi: solo quelle del DB; federazione senza `use` (cryptojwt rifiuta use=federation)
    keys = {}
    for k in (await base_db.execute(select(JwkKey))).scalars():
        keys[k.use] = k.private_jwk
    assert c["metadata_jwks"][0] == keys["sig"]
    assert c["metadata_jwks"][1] == keys["enc"]
    assert len(c["metadata_jwks"]) == 2
    assert fc["federation_jwks"] == [{k: v for k, v in keys["federation"].items() if k != "use"}]
    # metadata pubblicati: nessuna parte privata
    for jwk in c["metadata"]["jwks"] + fc["metadata"]["jwks"]:
        assert "d" not in jwk
    text = (tmp_path / "itwallet_backend.yaml").read_text()
    allowed_private = {keys[u]["d"] for u in ("federation", "sig", "enc")}
    for line in text.splitlines():
        stripped = line.strip().lstrip("- ")
        if stripped.startswith("d: "):
            assert stripped[3:].strip("'\"") in allowed_private
    # niente valori di esempio upstream
    assert "1234567890abcdef" not in text
    assert "CHANGEME" not in text
    assert "developers.italia.it" not in text
    assert "x509" not in text
    assert "direct_trust" not in text


async def test_trust_anchor_jwks_pinned(base_db, tmp_path, monkeypatch):
    cfg = await _add_wallet(base_db)
    pinned = {"kty": "EC", "crv": "P-256", "x": "a", "y": "b", "kid": "ta"}
    cfg.trust_anchor_jwks = {"keys": [pinned]}
    await base_db.commit()
    await _generate(base_db, tmp_path, monkeypatch)
    fc = _backend(tmp_path)["config"]["trust"]["federation"]["config"]
    assert fc["trust_anchors"] == {TA: [pinned]}


async def test_enabled_adds_module_router_and_disco(base_db, tmp_path, monkeypatch):
    await _add_wallet(base_db, environment="produzione")
    proxy, router, eid = await _generate(base_db, tmp_path, monkeypatch)
    assert "/satosa-conf/itwallet_backend.yaml" in proxy["BACKEND_MODULES"]
    assert router["config"]["entity_backends"] == {"wallet": "OpenID4VP"}
    assert eid["digital_id"]["itwallet"]["login_url"] == "/Saml2/disco?entityID=wallet"
    for lang in ("en", "fr", "de", "es"):
        other = json.loads((tmp_path / "locales" / f"eid-{lang}.json").read_text())
        assert other["digital_id"]["itwallet"] == eid["digital_id"]["itwallet"]


async def test_router_module_routes_entity_backends(tmp_path, monkeypatch, base_db):
    """Il router generato instrada entityID=wallet sul backend OpenID4VP."""
    import sys
    import types

    await _generate(base_db, tmp_path, monkeypatch)
    src = (tmp_path / "default_backend_router.py").read_text()

    class Context:
        KEY_TARGET_ENTITYID = "target_entity_id"

        def __init__(self, entity_id):
            self.target_backend = None
            self._entity_id = entity_id

        def get_decoration(self, key):
            return self._entity_id

    class RequestMicroService:
        def __init__(self, *a, **kw):
            pass

        def process(self, context, data):
            return context.target_backend

    stubs = {
        "satosa": types.ModuleType("satosa"),
        "satosa.context": types.ModuleType("satosa.context"),
        "satosa.micro_services": types.ModuleType("satosa.micro_services"),
        "satosa.micro_services.base": types.ModuleType("satosa.micro_services.base"),
    }
    stubs["satosa.context"].Context = Context
    stubs["satosa.micro_services.base"].RequestMicroService = RequestMicroService
    for name, mod in stubs.items():
        monkeypatch.setitem(sys.modules, name, mod)
    ns: dict = {}
    exec(compile(src, "default_backend_router.py", "exec"), ns)
    router = ns["DefaultBackendRouter"]({
        "default_backend": "spidSaml2",
        "cie_oidc_provider_urls": ["https://cie.example"],
        "entity_backends": {"wallet": "OpenID4VP"},
    })
    assert router.process(Context("wallet"), None) == "OpenID4VP"
    assert router.process(Context("https://cie.example"), None) == "CieOidcRp"
    assert router.process(Context("https://idp.example"), None) == "spidSaml2"
    no_wallet = ns["DefaultBackendRouter"]({"default_backend": "spidSaml2"})
    assert no_wallet.process(Context("wallet"), None) == "spidSaml2"


async def test_collaudo_writes_test_only_client_list(base_db, tmp_path, monkeypatch):
    await _add_wallet(base_db, environment="collaudo")
    _, _, eid = await _generate(base_db, tmp_path, monkeypatch)
    access = _backend(tmp_path)["config"]["itwallet_access"]
    assert access == {
        "test_only": True,
        "allowed_client_ids": ["__admin_test__", "__spid_verifica__", "app-collaudo"],
    }
    assert eid["digital_id"]["itwallet"]["test_only"] is True


async def test_personalizzato_is_test_only(base_db, tmp_path, monkeypatch):
    await _add_wallet(base_db, environment="personalizzato")
    _, _, eid = await _generate(base_db, tmp_path, monkeypatch)
    assert _backend(tmp_path)["config"]["itwallet_access"]["test_only"] is True
    assert eid["digital_id"]["itwallet"]["test_only"] is True


async def test_produzione_not_test_only(base_db, tmp_path, monkeypatch):
    await _add_wallet(base_db, environment="produzione")
    _, _, eid = await _generate(base_db, tmp_path, monkeypatch)
    assert _backend(tmp_path)["config"]["itwallet_access"]["test_only"] is False
    assert eid["digital_id"]["itwallet"]["test_only"] is False


def test_admin_test_client_id_matches_route():
    from app.itwallet_backend_config import ADMIN_TEST_CLIENT_ID
    from app.routes.test_client import TEST_CLIENT_ID
    assert ADMIN_TEST_CLIENT_ID == TEST_CLIENT_ID


async def test_pyeudiw_logger_not_debug(base_db, tmp_path, monkeypatch):
    monkeypatch.delenv("SATOSA_LOG_LEVEL", raising=False)
    proxy, _, _ = await _generate(base_db, tmp_path, monkeypatch)
    assert proxy["LOGGING"]["loggers"]["pyeudiw"]["level"] == "INFO"
    monkeypatch.setenv("SATOSA_LOG_LEVEL", "warning")
    proxy, _, _ = await _generate(base_db, tmp_path, monkeypatch)
    assert proxy["LOGGING"]["loggers"]["pyeudiw"]["level"] == "WARNING"


async def test_incomplete_config_not_written(base_db, tmp_path, monkeypatch, caplog):
    await _add_wallet(base_db, enabled=True, keys=False)
    with caplog.at_level(logging.WARNING, logger="app.satosa_config_generator"):
        proxy, router, eid = await _generate(base_db, tmp_path, monkeypatch)
    assert not (tmp_path / "itwallet_backend.yaml").exists()
    assert "/satosa-conf/itwallet_backend.yaml" not in proxy["BACKEND_MODULES"]
    assert router["config"]["entity_backends"] == {}
    assert "itwallet" not in eid["digital_id"]
    assert any("IT-Wallet" in r.getMessage() and "chiavi" in r.getMessage() for r in caplog.records)


# --- itwallet_ready (usato anche dal pannello) -------------------------------

def _cfg(**kw):
    base = dict(id=1, enabled=True, environment="collaudo", trust_anchor_url=TA, authority_hint_url=TA)
    base.update(kw)
    return ItWalletConfig(**base)


def _keys():
    from app.jwk_generator import generate_ec_jwk
    return {u: generate_ec_jwk(f"k-{u}", u).private_jwk for u in ("federation", "sig", "enc")}


def test_itwallet_ready_ok():
    from app.itwallet_backend_config import itwallet_ready
    assert itwallet_ready(_cfg(), _keys()) == (True, None)


@pytest.mark.parametrize("env", ["collaudo", "personalizzato"])
def test_itwallet_ready_without_trust_anchor_in_test_envs(env):
    from app.itwallet_backend_config import itwallet_ready
    assert itwallet_ready(_cfg(environment=env, trust_anchor_url=None, authority_hint_url=None),
                          _keys()) == (True, None)


def test_build_without_trust_anchor_publishes_empty_hints():
    from app.itwallet_backend_config import build_itwallet_backend
    cfg = _cfg(trust_anchor_url=None, authority_hint_url=None)
    out = build_itwallet_backend(cfg, _keys(), "sso.example.org", "redis://redis:6379/3", [])
    fed = out["config"]["trust"]["federation"]["config"]
    assert fed["authority_hints"] == []
    assert fed["trust_anchors"] == {}


@pytest.mark.parametrize("cfg_kw, drop, fragment", [
    ({}, "sig", "chiavi"),
    ({"trust_anchor_url": "", "environment": "produzione"}, None, "trust anchor"),
    ({"environment": None}, None, "ambiente"),
    ({"environment": "boh"}, None, "ambiente"),
])
def test_itwallet_ready_reasons(cfg_kw, drop, fragment):
    from app.itwallet_backend_config import itwallet_ready
    keys = _keys()
    if drop:
        keys.pop(drop)
    ok, reason = itwallet_ready(_cfg(**cfg_kw), keys)
    assert ok is False
    assert fragment in reason


def test_itwallet_ready_none_config():
    from app.itwallet_backend_config import itwallet_ready
    ok, reason = itwallet_ready(None, {})
    assert ok is False and reason


def test_itwallet_ready_without_salt(monkeypatch):
    from app.itwallet_backend_config import itwallet_ready
    monkeypatch.delenv("SATOSA_HASH_SALT")
    ok, reason = itwallet_ready(_cfg(), _keys())
    assert ok is False and "SATOSA_HASH_SALT" in reason


# --- prefisso redis legato ad ambiente/trust anchor --------------------------

def test_storage_key_prefix_depends_on_environment_and_trust_anchor():
    from app.itwallet_backend_config import storage_key_prefix
    base = storage_key_prefix("collaudo", TA)
    assert base.startswith("itw:") and base.endswith(":") and len(base) == len("itw:") + 9
    assert storage_key_prefix("collaudo", TA) == base
    assert storage_key_prefix("collaudo", TA + "  ") == base
    assert storage_key_prefix("produzione", TA) != base
    assert storage_key_prefix("collaudo", "https://other-ta.example") != base


def test_backend_storage_and_cache_use_same_prefix():
    from app.itwallet_backend_config import build_itwallet_backend, storage_key_prefix
    doc = build_itwallet_backend(_cfg(), _keys(), "sso.example.it", "redis://redis:6379/3", [])
    redis_conf = doc["config"]["storage"]["redis"]
    prefixes = {redis_conf[k]["init_params"]["conf"]["key_prefix"] for k in ("cache", "storage")}
    assert prefixes == {storage_key_prefix("collaudo", TA)}
    other = build_itwallet_backend(
        _cfg(environment="produzione"), _keys(), "sso.example.it", "redis://redis:6379/3", []
    )
    assert other["config"]["storage"]["redis"]["storage"]["init_params"]["conf"]["key_prefix"]         not in prefixes


@pytest.mark.parametrize("environment", ["collaudo", "personalizzato", "produzione"])
async def test_verifica_client_injected_without_spid_test_idp(base_db, tmp_path, monkeypatch, environment):
    """Nessun IdP SPID di test abilitato: /verifica resta il percorso di collaudo del
    wallet, quindi __spid_verifica__ è in oidc_clients.json e tra i client ammessi."""
    from sqlalchemy import func
    from app.models import SpidIdP
    n_test = (await base_db.execute(
        select(func.count()).select_from(SpidIdP).where(
            SpidIdP.alias.in_(["spid-demo", "spid-validator"]), SpidIdP.enabled == True)
    )).scalar_one()
    assert n_test == 0
    await _add_wallet(base_db, environment=environment)
    await _generate(base_db, tmp_path, monkeypatch)
    clients = json.loads((tmp_path / "oidc_clients.json").read_text())
    assert "__spid_verifica__" in clients
    access = _backend(tmp_path)["config"]["itwallet_access"]
    assert "__spid_verifica__" in access["allowed_client_ids"]
    assert access["test_only"] is (environment != "produzione")
