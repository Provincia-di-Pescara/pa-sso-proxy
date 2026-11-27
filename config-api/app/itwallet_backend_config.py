"""Config SATOSA del backend IT-Wallet (OpenID4VP, pyeudiw) costruita da zero.

Struttura ricavata dall'esempio upstream `pyeudiw_backend.yaml` (iam-proxy-italia
v3.9.0, provato end-to-end con un wallet nello spike), con queste differenze volute:

- trust solo `federation` (niente `x509`, niente `direct_trust_*`);
- chiavi solo dal DB (EC P-256): niente chiavi RSA/EC di esempio, `sym_key` e
  `subject_id_random_value` derivati da SATOSA_HASH_SALT;
- storage su redis DB 3 con le classi nostre (`backends.itwallet.itwallet_storage`),
  niente MongoDB;
- DCQL con un solo `claim_set` (CF obbligatorio);
- nessun endpoint `jar_issuer`: in pyeudiw 2.9.0 `JarIssuerMetadataHandler`
  restituisce `metadata_jwks` così com'è, cioè con le parti private delle chiavi;
  col solo trust `federation` il wallet non lo usa;
- `ui.error_template`/`ui.error_url`: non letti da pyeudiw 2.9.0.
"""
import base64
import copy
import json
import os

from app.itwallet import derived_secret

BACKEND_NAME = "OpenID4VP"
BACKEND_MODULE = "backends.itwallet.ItWalletBackend"
BACKEND_FILENAME = "itwallet_backend.yaml"
LOGIN_URL = "/Saml2/disco?entityID=wallet"
DISCO_ENTITY_ID = "wallet"

# Client sempre ammessi in collaudo/personalizzato. Valore di
# app.routes.test_client.TEST_CLIENT_ID (non importato: ciclo di import col
# generatore); un test verifica che coincidano.
VERIFICA_CLIENT_ID = "__spid_verifica__"
ADMIN_TEST_CLIENT_ID = "__admin_test__"

ENVIRONMENTS = ("collaudo", "produzione", "personalizzato")
TEST_ONLY_ENVIRONMENTS = ("collaudo", "personalizzato")
KEY_ROLES = ("federation", "sig", "enc")

CLAIM_SET = ["given_name", "family_name", "birthdate", "place_of_birth", "tax_id_code"]
CREDENTIAL_VCT = "urn:it-wallet:eid:1"

_ENC_ALG_SUPPORTED = ["ECDH-ES"]
_ENC_ENC_SUPPORTED = ["A128GCM", "A256GCM"]
_SIG_ALG_SUPPORTED = ["RS256", "RS384", "RS512", "ES256", "ES384", "ES512"]
_PRIVATE_EC_MEMBERS = ("d",)


def _dcql_query() -> str:
    query = {
        "credentials": [
            {
                "id": "it-wallet-id",
                "format": "dc+sd-jwt",
                "meta": {"vct_values": [CREDENTIAL_VCT]},
                "claims": [{"id": c, "path": [c]} for c in CLAIM_SET],
                "claim_sets": [list(CLAIM_SET)],
            }
        ]
    }
    return json.dumps(query, separators=(",", ":"))


def _missing_keys(keys: dict | None) -> list[str]:
    keys = keys or {}
    return [
        role for role in KEY_ROLES
        if not isinstance(keys.get(role), dict)
        or keys[role].get("kty") != "EC"
        or not keys[role].get("d")
    ]


def itwallet_ready(cfg, keys: dict | None) -> tuple[bool, str | None]:
    """(True, None) se il wallet può essere configurato, altrimenti (False, motivo).

    `keys` = {"federation"|"sig"|"enc": JWK privata}. Il motivo è in italiano
    (mostrato anche nel pannello admin).
    """
    if cfg is None:
        return False, "configurazione IT-Wallet assente"
    if cfg.environment not in ENVIRONMENTS:
        return False, "ambiente non scelto (collaudo, produzione o personalizzato)"
    if not (cfg.trust_anchor_url or "").strip():
        return False, "trust anchor non impostato"
    missing = _missing_keys(keys)
    if missing:
        return False, "chiavi mancanti: " + ", ".join(missing)
    if not os.environ.get("SATOSA_HASH_SALT"):
        return False, "SATOSA_HASH_SALT non impostata: impossibile derivare i segreti"
    return True, None


def _public(jwk: dict) -> dict:
    return {k: v for k, v in jwk.items() if k not in _PRIVATE_EC_MEMBERS}


def _trust_mark_id(token: str) -> str:
    parts = token.split(".")
    if len(parts) < 2:
        return ""
    padded = parts[1] + "=" * (-len(parts[1]) % 4)
    try:
        return json.loads(base64.urlsafe_b64decode(padded)).get("id", "") or ""
    except Exception:
        return ""


def _trust_anchor_keys(jwks) -> list:
    if isinstance(jwks, dict):
        return list(jwks.get("keys") or [])
    if isinstance(jwks, list):
        return list(jwks)
    return []


def build_itwallet_backend(
    cfg,
    keys: dict[str, dict],
    hostname: str,
    redis_url: str,
    allowed_client_ids: list[str],
) -> dict:
    """Documento YAML del backend SATOSA `OpenID4VP` (da scrivere in /satosa-conf).

    `keys`: JWK private dal DB per "federation", "sig", "enc". `redis_url`: URL
    redis già sul DB del wallet (3). `allowed_client_ids`: client con
    `allow_test_idps` (in collaudo/personalizzato sono i soli ammessi, più
    `/verifica` e il test client admin).
    """
    base = f"https://{hostname}"
    backend_url = f"{base}/{BACKEND_NAME}"
    entity_id = backend_url
    trust_anchor = cfg.trust_anchor_url.strip()
    authority_hint = (cfg.authority_hint_url or "").strip() or trust_anchor
    org_name = cfg.organization_name or cfg.client_name or hostname
    client_name = cfg.client_name or org_name
    contacts = [cfg.contact_email] if cfg.contact_email else []

    sig = dict(keys["sig"])
    enc = dict(keys["enc"])
    # cryptojwt rifiuta use=federation in firma: senza `use` (RFC 7517: qualsiasi uso)
    federation = {k: v for k, v in keys["federation"].items() if k != "use"}

    httpc_params = {"connection": {"ssl": True}, "session": {"timeout": 6}}
    dcql = _dcql_query()

    def metadata() -> dict:
        # Copia indipendente per ogni uso: FederationHandler modifica `jwks` sul posto.
        return {
            "application_type": "web",
            "authorization_encrypted_response_alg": list(_ENC_ALG_SUPPORTED),
            "authorization_encrypted_response_enc": list(_ENC_ENC_SUPPORTED),
            "authorization_signed_response_alg": list(_SIG_ALG_SUPPORTED),
            "client_id": entity_id,
            "client_name": client_name,
            **({"logo_uri": cfg.logo_uri} if cfg.logo_uri else {}),
            "contacts": list(contacts),
            "id_token_encrypted_response_alg": list(_ENC_ALG_SUPPORTED),
            "id_token_encrypted_response_enc": list(_ENC_ENC_SUPPORTED),
            "id_token_signed_response_alg": list(_SIG_ALG_SUPPORTED),
            # solo parte pubblica: questi metadata finiscono nella entity configuration
            "jwks": [_public(sig), _public(enc)],
            "redirect_uris": [f"{backend_url}/redirect-uri"],
            "request_uris": [f"{backend_url}/request-uri"],
            "response_uris": [f"{backend_url}/response-uri"],
            "encrypted_response_enc_values_supported": list(_ENC_ENC_SUPPORTED),
            "vp_formats": {
                "dc+sd-jwt": {
                    "sd-jwt_alg_values": ["ES256", "ES384"],
                    "kb-jwt_alg_values": ["ES256", "ES384"],
                },
            },
            "vp_formats_supported": {
                "dc+sd-jwt": {
                    "sd-jwt_alg_values": ["ES256", "ES384"],
                    "kb-jwt_alg_values": ["ES256", "ES384"],
                },
                "mso_mdoc": {
                    "issuerauth_alg_values": [-7, -35],
                    "deviceauth_alg_values": [-7, -35],
                },
            },
            "token_endpoint_auth_methods_supported": ["attest_jwt_client_auth"],
            "client_attestation_signing_alg_values_supported": ["ES256", "ES384", "ES512"],
            "client_attestation_pop_signing_alg_values_supported": ["ES256", "ES384", "ES512"],
        }

    federation_entity = {
        "organization_name": org_name,
        **({"homepage_uri": cfg.homepage_uri} if cfg.homepage_uri else {}),
        **({"policy_uri": cfg.policy_uri} if cfg.policy_uri else {}),
        **({"tos_uri": cfg.tos_uri} if cfg.tos_uri else {}),
        **({"logo_uri": cfg.logo_uri} if cfg.logo_uri else {}),
        **({"contacts": list(contacts)} if contacts else {}),
    }

    trust_marks = []
    if cfg.trust_mark:
        tm_id = cfg.trust_mark_id or _trust_mark_id(cfg.trust_mark)
        trust_marks.append({"id": tm_id, "trust_mark": cfg.trust_mark})

    def storage_entry(cls: str) -> dict:
        return {
            "module": "backends.itwallet.itwallet_storage",
            "class": cls,
            "init_params": {
                "url": redis_url,
                "conf": {"data_ttl": 3600, "key_prefix": "itw:"},
                "connection_params": {},
            },
        }

    endpoints = {
        "pre_request": ("pre_request_endpoint", "PreRequestHandler", "/pre-request"),
        "response": ("response_endpoint", "ResponseHandler", "/response-uri"),
        "request": ("request_endpoint", "RequestHandler", "/request-uri"),
        "status": ("status_endpoint", "StatusHandler", "/status"),
        "get_response": ("get_response_endpoint", "GetResponseHandler", "/redirect-uri"),
    }

    config = {
        "itwallet_access": {
            "test_only": cfg.environment in TEST_ONLY_ENVIRONMENTS,
            "allowed_client_ids": sorted(
                set(allowed_client_ids) | {VERIFICA_CLIENT_ID, ADMIN_TEST_CLIENT_ID}
            ),
        },
        "ui": {
            "static_storage_url": f"{base}/static",
            "template_folder": "/satosa_proxy/templates",
            "qrcode_template": "qr_code.html",
            "authorization_error_template": "itwallet_error.html",
        },
        "endpoints": {
            name: {
                "module": f"pyeudiw.satosa.backends.openid4vp.endpoints.{module}",
                "class": cls,
                "path": path,
            }
            for name, (module, cls, path) in endpoints.items()
        },
        "qrcode": {
            "size": 250,
            "color": "#000000",
            "expiration_time": 120,
            "logo_path": "itwallet/it-wallet-mark.svg",
        },
        "response_code": {"sym_key": derived_secret("itwallet-response-code", 64)},
        "jwt": {
            "default_sig_alg": "ES256",
            "default_enc_alg": "ECDH-ES",
            "default_enc_enc": "A256GCM",
            "response_encryption_kty": "EC",
            "response_encryption_crv": "P-256",
            "response_encryption_use": "enc",
            "default_exp": 6,
            "enc_alg_supported": list(_ENC_ALG_SUPPORTED),
            "enc_enc_supported": list(_ENC_ENC_SUPPORTED),
            "sig_alg_supported": list(_SIG_ALG_SUPPORTED),
        },
        "authorization": {
            "url_scheme": "haip-vp",
            "scopes": [CREDENTIAL_VCT],
            "expiration_time": 2,
            "aud": "https://self-issued.me/v2",
            "response_mode": "direct_post.jwt",
        },
        "duckle": {"dcql_query": dcql},
        "user_attributes": {
            "unique_identifiers": ["tax_id_code", "unique_id", "personal_administrative_number"],
            "subject_id_random_value": derived_secret("itwallet-subject", 64),
        },
        "network": {"httpc_params": copy.deepcopy(httpc_params)},
        # [0] firma le request object (RequestHandler.default_metadata_private_jwk)
        "metadata_jwks": [sig, enc],
        "metadata": metadata(),
        "credential_presentation_handlers": {
            "max_submission_size": 4096,
            "formats": [
                {
                    "module": "pyeudiw.satosa.backends.openid4vp.vp_sd_jwt_vc",
                    "class": "VpVcSdJwtParserVerifier",
                    "format": "dc+sd-jwt",
                },
                {
                    "module": "pyeudiw.satosa.backends.openid4vp.vp_mdoc_cbor",
                    "class": "VpMDocCbor",
                    "format": "mso_mdoc",
                },
                {
                    "module": "pyeudiw.duckle_ql.handler",
                    "class": "DuckleHandler",
                    "format": "jwt_vc_json",
                    "config": {"dcql_query": dcql, "duckle": {"dcql_query": dcql}},
                },
            ],
        },
        "trust": {
            "federation": {
                "module": "pyeudiw.trust.handler.federation",
                "class": "FederationHandler",
                "config": {
                    "client_id": f"openid_federation:{entity_id}",
                    "httpc_params": copy.deepcopy(httpc_params),
                    "cache_ttl": 0,
                    "entity_configuration_exp": 600,
                    "metadata_type": "openid_credential_verifier",
                    "metadata": metadata(),
                    "authority_hints": [authority_hint],
                    # dict TA -> chiavi: FederationHandler fa `ta in trust_anchors` e
                    # `trust_anchors[ta]`; lista vuota = JWKS letto dalla entity
                    # configuration del TA.
                    "trust_anchors": {trust_anchor: _trust_anchor_keys(cfg.trust_anchor_jwks)},
                    "default_sig_alg": "ES256",
                    "trust_marks": trust_marks,
                    "federation_entity_metadata": federation_entity,
                    "federation_jwks": [federation],
                },
            },
        },
        "storage": {
            "redis": {
                "cache": storage_entry("RedisCache"),
                "storage": storage_entry("RedisStorage"),
            },
        },
    }
    return {"module": BACKEND_MODULE, "name": BACKEND_NAME, "config": config}
