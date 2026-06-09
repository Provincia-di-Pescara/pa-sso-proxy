import base64
import json
import os
from typing import Optional

import yaml
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import CieConfig, EnteSettings, JwkKey, OIDCClient, SpidIdP

SATOSA_CONF_DIR = os.environ.get("SATOSA_CONF_DIR", "/satosa-conf")
REDIS_URL = os.environ.get("REDIS_URL", "redis://redis:6379/0")


def _base_url(hostname: str) -> str:
    """Return the public base URL for SATOSA. PROXY_BASE_URL overrides hostname."""
    return os.environ.get("PROXY_BASE_URL", "").rstrip("/") or f"https://{hostname}"


def _cie_oidc_client_id(hostname: str) -> str:
    return f"{_base_url(hostname)}/CieOidcRp"


def _decode_jwt_payload(token: str) -> dict:
    parts = token.split(".")
    if len(parts) < 2:
        return {}
    padded = parts[1] + "==" * (-len(parts[1]) % 4)
    try:
        return json.loads(base64.urlsafe_b64decode(padded))
    except Exception:
        return {}


def _trust_mark_id_from_jwt(trust_mark_jwt: str) -> str:
    """Extract 'id' claim from trust mark JWT payload."""
    return _decode_jwt_payload(trust_mark_jwt).get("id", "")


_SPID_BACKEND_CLASS = "backends.spidsaml2.SpidSAMLBackend"
_CIE_SAML_BACKEND_CLASS = "backends.ciesaml2.CieSAMLBackend"
_OIDC_FRONTEND_CLASS = "satosa.frontends.openid_connect.OpenIDConnectFrontend"


def _proxy_yaml(hostname: str, include_cie_oidc: bool) -> dict:
    backend_modules = [
        "/satosa-conf/spid_backend.yaml",
        "/satosa-conf/cie_saml_backend.yaml",
    ]
    if include_cie_oidc:
        backend_modules.append("/satosa-conf/cie_oidc_backend.yaml")
    return {
        "BASE": _base_url(hostname),
        "INTERNAL_ATTRIBUTES": "/satosa_proxy/internal_attributes.yaml",
        "COOKIE_STATE_NAME": "satosa_state",
        "STATE_ENCRYPTION_KEY": os.environ.get("SATOSA_STATE_ENCRYPTION_KEY", "changeme-generate-random-state-key-32chars"),
        "USER_ID_HASH_SALT": os.environ.get("SATOSA_HASH_SALT", "changeme"),
        "CONSENT": {"enable": False},
        "BACKEND_MODULES": backend_modules,
        "FRONTEND_MODULES": ["/satosa-conf/oidc_frontend.yaml"],
        "CUSTOM_PLUGIN_MODULE_PATHS": ["/satosa-conf"],
        "MICRO_SERVICES": [
            "/satosa-conf/disco_to_target_issuer.yaml",
            "/satosa-conf/default_router.yaml",
        ],
    }


def _oidc_frontend_yaml(hostname: str) -> dict:
    return {
        "name": "OIDC",
        "module": _OIDC_FRONTEND_CLASS,
        "issuer": _base_url(hostname),
        "config": {
            "signing_key_path": "/satosa-conf/oidc_signing_key.pem",
            "client_db_path": "/satosa-conf/oidc_clients.json",
            "provider": {
                "response_types_supported": ["code"],
                "scopes_supported": ["openid", "profile", "email"],
                "subject_types_supported": ["pairwise", "public"],
                "id_token_lifetime": 3600,
            },
        },
    }


def _spid_backend_yaml(hostname: str, enabled_idps: list, cert_path: str, key_path: str, settings: "EnteSettings") -> dict:
    local_metadata = ["/satosa_proxy/metadata/idp/spid-entities-idps.xml"]
    remote_metadata = [{"url": idp.metadata_url} for idp in enabled_idps]
    metadata_config = {"local": local_metadata}
    if remote_metadata:
        metadata_config["remote"] = remote_metadata

    sp_config = {
        "key_file": key_path,
        "cert_file": cert_path,
        "encryption_keypairs": [{"key_file": key_path, "cert_file": cert_path}],
        "attribute_map_dir": "/satosa_proxy/attributes-map",
        "organization": {
            "display_name": [[settings.org_display_name, "it"]],
            "name": [[settings.org_name, "it"]],
            "url": [[settings.org_url, "it"]],
        },
        "contact_person": [
            {
                "contact_type": "other",
                "given_name": settings.org_display_name,
                "email_address": settings.contact_email,
                "telephone_number": settings.contact_phone,
                "FiscalCode": settings.ipa_code,
                "IPACode": settings.ipa_code,
                "Public": "",
            }
        ],
        "metadata": metadata_config,
        "ficep_enable": False,
        "entityid": "<base_url>/<name>/metadata",
        "accepted_time_diff": 10,
        "service": {
            "sp": {
                "authn_requests_signed": True,
                "want_response_signed": True,
                "want_assertions_signed": True,
                "signing_algorithm": "http://www.w3.org/2001/04/xmldsig-more#rsa-sha256",
                "digest_algorithm": "http://www.w3.org/2001/04/xmlenc#sha256",
                "only_use_keys_in_metadata": True,
                "name_id_format_allow_create": False,
                "name_id_format": "urn:oasis:names:tc:SAML:2.0:nameid-format:transient",
                "requested_attribute_name_format": "urn:oasis:names:tc:SAML:2.0:attrname-format:basic",
                "allow_unknown_attributes": True,
                "allow_unsolicited": True,
                "required_attributes": ["spidCode", "name", "familyName", "fiscalNumber", "email"],
                "endpoints": {
                    "assertion_consumer_service": [
                        ["<base_url>/<name>/acs/post", "urn:oasis:names:tc:SAML:2.0:bindings:HTTP-POST"],
                    ],
                    "single_logout_service": [
                        ["<base_url>/<name>/ls/post/", "urn:oasis:names:tc:SAML:2.0:bindings:HTTP-POST"],
                    ],
                    "discovery_response": [
                        ["<base_url>/<name>/disco", "urn:oasis:names:tc:SAML:profiles:SSO:idp-discovery-protocol"],
                    ],
                },
            }
        },
    }
    return {
        "name": "spidSaml2",
        "module": _SPID_BACKEND_CLASS,
        "metadata": metadata_config,
        "config": {
            "template_folder": "/satosa_proxy/templates",
            "static_storage_url": f"{_base_url(hostname)}/static",
            "error_template": "spid_login_error.html",
            "entityid_endpoint": True,
            "spid_allowed_acrs": [
                "https://www.spid.gov.it/SpidL1",
                "https://www.spid.gov.it/SpidL2",
                "https://www.spid.gov.it/SpidL3",
            ],
            "spid_acr_comparison": "minimum",
            "acr_mapping": {"": "https://www.spid.gov.it/SpidL2"},
            "sp_config": sp_config,
            "disco_srv": f"{_base_url(hostname)}/static/disco.html",
        },
    }


def _cie_saml_backend_yaml(hostname: str, cie_metadata_url: str, cert_path: str, key_path: str, settings: "EnteSettings") -> dict:
    sp_config = {
        "key_file": key_path,
        "cert_file": cert_path,
        "encryption_keypairs": [{"key_file": key_path, "cert_file": cert_path}],
        "attribute_map_dir": "/satosa_proxy/attributes-map",
        "organization": {
            "display_name": [[settings.org_display_name, "it"]],
            "name": [[settings.org_name, "it"]],
            "url": [[settings.org_url, "it"]],
        },
        "contact_person": [
            {
                "contact_type": "administrative",
                "company": settings.org_name,
                "email_address": settings.contact_email,
                "telephone_number": settings.contact_phone,
                "cie_info": {
                    "Public": "",
                    "IPACode": settings.ipa_code,
                    "Municipality": settings.org_city,
                },
            }
        ],
        "metadata": {"local": ["/satosa_proxy/metadata/idp/cie-production.xml"]},
        "entityid": "<base_url>/<name>/metadata",
        "accepted_time_diff": 10,
        "service": {
            "sp": {
                "authn_requests_signed": True,
                "want_response_signed": True,
                "want_assertions_signed": True,
                "signing_algorithm": "http://www.w3.org/2001/04/xmldsig-more#rsa-sha256",
                "digest_algorithm": "http://www.w3.org/2001/04/xmlenc#sha256",
                "only_use_keys_in_metadata": True,
                "name_id_format_allow_create": False,
                "name_id_format": "urn:oasis:names:tc:SAML:2.0:nameid-format:transient",
                "requested_attribute_name_format": "urn:oasis:names:tc:SAML:2.0:attrname-format:basic",
                "allow_unknown_attributes": True,
                "allow_unsolicited": True,
                "required_attributes": ["name", "familyName", "dateOfBirth", "fiscalNumber"],
                "endpoints": {
                    "assertion_consumer_service": [
                        ["<base_url>/<name>/acs/post", "urn:oasis:names:tc:SAML:2.0:bindings:HTTP-POST"],
                    ],
                    "single_logout_service": [
                        ["<base_url>/<name>/ls/post/", "urn:oasis:names:tc:SAML:2.0:bindings:HTTP-POST"],
                    ],
                    "discovery_response": [
                        ["<base_url>/<name>/disco", "urn:oasis:names:tc:SAML:profiles:SSO:idp-discovery-protocol"],
                    ],
                },
            }
        },
    }
    return {
        "name": "cieSaml2",
        "module": _CIE_SAML_BACKEND_CLASS,
        "config": {
            "template_folder": "/satosa_proxy/templates",
            "static_storage_url": f"{_base_url(hostname)}/static",
            "error_template": "spid_login_error.html",
            "entityid_endpoint": True,
            "sp_config": sp_config,
            "disco_srv": f"{_base_url(hostname)}/static/disco.html",
        },
    }


def _cie_oidc_backend_yaml(
    hostname: str,
    cie_config: "CieConfig",
    settings: "EnteSettings",
    jwk_federation: dict,
    jwk_core_sig: dict,
    jwk_core_enc: dict,
    redis_url: str,
) -> dict:
    contact_email = cie_config.oidc_contact_email or settings.contact_email
    org_name = settings.org_display_name
    client_id = _cie_oidc_client_id(hostname)
    trust_mark_id = _trust_mark_id_from_jwt(cie_config.trust_mark or "") if cie_config.trust_mark else ""
    trust_marks = [{"id": trust_mark_id, "trust_mark": cie_config.trust_mark}] if trust_mark_id else []

    db_config = {
        "redis": {
            "module": "backends.cieoidc.storage.impl.redis_storage",
            "class": "RedisStorage",
            "init_params": {"url": redis_url, "ttl": 7200},
        }
    }
    httpc_params = {"connection": {"ssl": True}, "session": {"timeout": 6}}
    metadata = {
        "federation_entity": {
            "federation_resolve_endpoint": f"{_base_url(hostname)}/CieOidcRp/resolve",
            "organization_name": org_name,
            "homepage_uri": cie_config.homepage_uri,
            "policy_uri": cie_config.policy_uri,
            "logo_uri": cie_config.logo_uri,
            "contacts": [contact_email],
        },
        "openid_relying_party": {
            "application_type": "web",
            "client_id": client_id,
            "client_name": org_name,
            "organization_name": org_name,
            "client_registration_types": ["automatic"],
            "signed_jwks_uri": f"{_base_url(hostname)}/CieOidcRp/openid_relying_party/jwks.jose",
            "jwks": None,
            "contacts": [contact_email],
            "grant_types": ["refresh_token", "authorization_code"],
            "redirect_uris": [f"{_base_url(hostname)}/CieOidcRp/oidc/callback"],
            "response_types": ["code"],
            "subject_type": "pairwise",
            "id_token_signed_response_alg": "RS256",
            "userinfo_signed_response_alg": "RS256",
            "userinfo_encrypted_response_alg": "RSA-OAEP-256",
            "userinfo_encrypted_response_enc": "A256GCM",
            "token_endpoint_auth_method": "private_key_jwt",
            "scope": "openid email",
            "code_challenge": {"length": 64, "method": "S256"},
            "claim": {
                "id_token": {
                    "sub": {"essential": True},
                    "family_name": {"essential": True},
                    "given_name": {"essential": True},
                },
                "userinfo": {
                    "sub": None,
                    "given_name": None,
                    "family_name": None,
                    "email": {"essential": True},
                    "https://attributes.eid.gov.it/fiscal_number": None,
                },
            },
        },
    }

    endpoint_base = {
        "metadata": metadata,
        "jwks_federation": [jwk_federation],
        "jwks_core": [jwk_core_sig, jwk_core_enc],
        "entity_type": "openid_relying_party",
        "entity_configuration_exp": 525600,
        "default_sig_alg": "RS256",
        "authority_hints": [cie_config.authority_hint_url],
    }
    return {
        "module": "backends.cieoidc.CieOidcBackend",
        "name": "CieOidcRp",
        "config": {
            "network": {"httpc_params": httpc_params},
            "storage": db_config,
            "providers": [cie_config.oidc_provider_url],
            "security_operations": {
                "hash": {"default": {"func": "SHA-256"}},
                "sign": {
                    "default": {"alg": "RS256"},
                    "supported": {"alg": ["RS256", "RS384", "RS512", "ES256", "ES384", "ES512"]},
                },
                "encrypt": {
                    "default": {"alg": "RSA-OAEP-256", "enc": "A256GCM"},
                    "supported": {
                        "alg": [
                            "RSA-OAEP", "RSA-OAEP-256", "ECDH-ES",
                            "ECDH-ES+A128KW", "ECDH-ES+A192KW", "ECDH-ES+A256KW",
                        ],
                        "enc": [
                            "A128CBC-HS256", "A192CBC-HS384", "A256CBC-HS512",
                            "A128GCM", "A192GCM", "A256GCM",
                        ],
                    },
                },
            },
            "jwks": {
                "federation": [jwk_federation],
                "core": [jwk_core_sig, jwk_core_enc],
            },
            "metadata": metadata,
            "trust_chain": {
                "config": {
                    "cache_ttl": 0,
                    "trust_anchor": [cie_config.trust_anchor_url],
                    "httpc_params": httpc_params,
                }
            },
            "endpoints": {
                "entity_config_endpoint": {
                    "module": "backends.cieoidc.endpoints.entity_configuration",
                    "class": "EntityConfigHandler",
                    "routes": [
                        "/.well-known/openid-federation",
                        "/openid_relying_party/jwks.json",
                        "/openid_relying_party/jwks.jose",
                    ],
                    "config": {**endpoint_base, "trust_marks": trust_marks},
                },
                "federation_resolve_endpoint": {
                    "module": "backends.cieoidc.endpoints.federation_resolve_endpoint",
                    "class": "FederationResolveHandler",
                    "routes": ["/resolve"],
                    "config": {**endpoint_base, "trust_marks": []},
                },
                "federation_fetch_endpoint": {
                    "module": "backends.cieoidc.endpoints.federation_fetch_endpoint",
                    "class": "FederationFetchHandler",
                    "routes": ["/fetch"],
                    "config": {**endpoint_base, "trust_marks": []},
                },
                "federation_trust_mark_status_endpoint": {
                    "module": "backends.cieoidc.endpoints.federation_trust_mark_status_endpoint",
                    "class": "FederationTrustMarkStatusHandler",
                    "routes": ["/trust_mark_status"],
                    "config": {},
                },
                "federation_list_endpoint": {
                    "module": "backends.cieoidc.endpoints.federation_list_endpoint",
                    "class": "FederationListHandler",
                    "routes": ["/list"],
                    "config": {},
                },
                "authorization_endpoint": {
                    "module": "backends.cieoidc.endpoints.authorization_endpoint",
                    "class": "AuthorizationHandler",
                    "routes": ["/oidc/authorization"],
                    "config": {
                        **endpoint_base,
                        "db_config": db_config,
                        "trust_marks": trust_marks,
                        "prompt": "consent",
                    },
                },
                "authorization_callback_endpoint": {
                    "module": "backends.cieoidc.endpoints.authorization_callback_endpoint",
                    "class": "AuthorizationCallBackHandler",
                    "routes": ["/oidc/callback"],
                    "config": {
                        **endpoint_base,
                        "db_config": db_config,
                        "httpc_params": httpc_params,
                        "trust_marks": trust_marks,
                        "default_sign_alg": "RS256",
                        "supported_sign_alg": ["RS256", "RS384", "RS512", "ES256", "ES384", "ES512"],
                        "default_enc_alg": "RSA-OAEP-256",
                        "default_enc_enc": "A256GCM",
                        "supported_enc_alg": [
                            "RSA-OAEP", "RSA-OAEP-256", "ECDH-ES",
                            "ECDH-ES+A128KW", "ECDH-ES+A192KW", "ECDH-ES+A256KW",
                        ],
                        "client_assertion_type": "urn:ietf:params:oauth:client-assertion-type:jwt-bearer",
                        "grant_type": "authorization_code",
                        "claims": {
                            "sub": ["sub"],
                            "username": [{
                                "func": "backends.cieoidc.utils.helpers.misc.issuer_prefixed_sub",
                                "kwargs": {"sep": "__"},
                            }],
                            "first_name": ["given_name", "first_name"],
                            "last_name": ["family_name", "last_name"],
                            "email": ["email", "email"],
                            "fiscal_number": [
                                "https://attributes.eid.gov.it/fiscal_number",
                                "fiscal_number",
                            ],
                        },
                    },
                },
                "extends_session_endpoint": {
                    "module": "backends.cieoidc.endpoints.extend_session_endpoint",
                    "class": "ExtendSessionHandler",
                    "routes": ["/extend_session"],
                    "config": {
                        **endpoint_base,
                        "httpc_params": httpc_params,
                        "trust_marks": trust_marks,
                        "client_assertion_type": "urn:ietf:params:oauth:client-assertion-type:jwt-bearer",
                        "grant_type": "refresh_token",
                    },
                },
            },
        },
    }


_DEFAULT_BACKEND_ROUTER_PY = '''\
import logging
from satosa.micro_services.base import RequestMicroService

logger = logging.getLogger(__name__)


class DefaultBackendRouter(RequestMicroService):
    def __init__(self, config, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.default_backend = config.get("default_backend", "spidSaml2")

    def process(self, context, data):
        if not context.target_backend:
            context.target_backend = self.default_backend
            logger.info(f"DefaultBackendRouter: set target_backend={self.default_backend}")
        return super().process(context, data)
'''


def _ensure_rsa_key(path: str) -> None:
    if os.path.exists(path):
        return
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption(),
    )
    with open(path, "wb") as f:
        f.write(pem)


def _write(conf_dir: str, filename: str, data: dict) -> None:
    with open(os.path.join(conf_dir, filename), "w") as f:
        yaml.dump(data, f, default_flow_style=False, allow_unicode=True)


def _write_json(conf_dir: str, filename: str, data: dict) -> None:
    with open(os.path.join(conf_dir, filename), "w") as f:
        json.dump(data, f, indent=2)


async def generate_satosa_config(db: AsyncSession) -> None:
    """Generate all SATOSA YAML config files from DB. No-op if proxy_hostname not set."""
    result = await db.execute(select(EnteSettings).where(EnteSettings.id == 1))
    settings = result.scalar_one_or_none()
    if not settings or not settings.proxy_hostname:
        return

    result = await db.execute(select(SpidIdP).where(SpidIdP.enabled == True))
    enabled_idps = list(result.scalars().all())

    result = await db.execute(select(CieConfig).where(CieConfig.id == 1))
    cie_config = result.scalar_one_or_none()
    cie_metadata_url = (
        cie_config.saml_metadata_url
        if cie_config
        else "https://idserver.servizicie.interno.gov.it/idp/shibboleth?Metadata"
    )

    result = await db.execute(select(JwkKey).limit(1))
    has_jwks = result.scalar_one_or_none() is not None

    jwk_federation = None
    jwk_core_sig = None
    jwk_core_enc = None
    if cie_config:
        if cie_config.jwk_federation_id:
            r = await db.execute(select(JwkKey).where(JwkKey.id == cie_config.jwk_federation_id))
            k = r.scalar_one_or_none()
            if k:
                jwk_federation = k.private_jwk
        if cie_config.jwk_core_sig_id:
            r = await db.execute(select(JwkKey).where(JwkKey.id == cie_config.jwk_core_sig_id))
            k = r.scalar_one_or_none()
            if k:
                jwk_core_sig = k.private_jwk
        if cie_config.jwk_core_enc_id:
            r = await db.execute(select(JwkKey).where(JwkKey.id == cie_config.jwk_core_enc_id))
            k = r.scalar_one_or_none()
            if k:
                jwk_core_enc = k.private_jwk

    include_cie_oidc = bool(
        cie_config is not None
        and cie_config.oidc_federation_enabled
        and cie_config.authority_hint_url
        and cie_config.trust_anchor_url
        and cie_config.oidc_provider_url
        and jwk_federation is not None
        and jwk_core_sig is not None
        and jwk_core_enc is not None
    )

    conf_dir = os.environ.get("SATOSA_CONF_DIR", SATOSA_CONF_DIR)
    os.makedirs(conf_dir, exist_ok=True)

    cert_path = "/satosa-conf/spid_sp_cert.pem"
    key_path = "/satosa-conf/spid_sp_key.pem"
    hostname = settings.proxy_hostname
    redis_url = os.environ.get("REDIS_URL", REDIS_URL)

    _ensure_rsa_key(os.path.join(conf_dir, "oidc_signing_key.pem"))

    with open(os.path.join(conf_dir, "default_backend_router.py"), "w") as f:
        f.write(_DEFAULT_BACKEND_ROUTER_PY)

    _write(conf_dir, "default_router.yaml", {
        "name": "DefaultRouter",
        "module": "default_backend_router.DefaultBackendRouter",
        "config": {"default_backend": "spidSaml2"},
    })

    _write(conf_dir, "disco_to_target_issuer.yaml", {
        "name": "DiscoToTargetIssuer",
        "module": "satosa.micro_services.disco.DiscoToTargetIssuer",
        "config": {"disco_endpoints": [".*/disco$"]},
    })

    result = await db.execute(select(OIDCClient).where(OIDCClient.enabled == True))
    clients = result.scalars().all()
    client_db = {
        c.client_id: {
            "client_secret": c.client_secret_plain or c.client_secret_hash,
            "redirect_uris": list(c.redirect_uris),
            "allowed_scopes": list(c.allowed_scopes),
            "response_types": ["code"],
        }
        for c in clients
    }
    _write_json(conf_dir, "oidc_clients.json", client_db)

    # Generate and write dynamic spid-idps-default.json based on active test provider
    spid_idps_json = []
    demo_enabled = any(x.alias == "spid-demo" for x in enabled_idps)
    validator_enabled = any(x.alias == "spid-validator" for x in enabled_idps)

    if demo_enabled:
        spid_idps_json = [{
            "organization_name": "Demo Provider",
            "entity_id": "https://demo.spid.gov.it",
            "logo_uri": "/static/spid/spid-agid-logo-lb.png"
        }]
    elif validator_enabled:
        spid_idps_json = [{
            "organization_name": "AgID Validator",
            "entity_id": "https://validator.spid.gov.it",
            "logo_uri": "/static/spid/spid-agid-logo-lb.png"
        }]
    else:
        # Load registry IDPs
        db_idps_res = await db.execute(
            select(SpidIdP)
            .where(SpidIdP.registry_entity_id != None)
            .order_by(SpidIdP.registry_organization_name)
        )
        db_idps = db_idps_res.scalars().all()
        if db_idps:
            for idp in db_idps:
                spid_idps_json.append({
                    "organization_name": idp.registry_organization_name or idp.display_name,
                    "entity_id": idp.registry_entity_id,
                    "logo_uri": idp.registry_logo_uri or ""
                })
        else:
            # Fallback list of production IdPs
            spid_idps_json = [
                { "organization_name": "Aruba PEC", "entity_id": "https://loginspid.aruba.it", "logo_uri": "/static/img/spid-idp-arubaid.svg" },
                { "organization_name": "InfoCert ID", "entity_id": "https://identity.infocert.it", "logo_uri": "/static/img/spid-idp-infocertid.svg" },
                { "organization_name": "Poste ID", "entity_id": "https://posteid.poste.it", "logo_uri": "/static/img/spid-idp-posteid.svg" },
                { "organization_name": "Sielte", "entity_id": "https://identity.sielte.it", "logo_uri": "/static/img/spid-idp-sielteid.svg" },
                { "organization_name": "TIM Personal ID", "entity_id": "https://login.id.tim.it/affwebservices/public/saml2sso", "logo_uri": "/static/img/spid-idp-timid.svg" },
                { "organization_name": "Lepida ID", "entity_id": "https://id.lepida.it/idp/shibboleth", "logo_uri": "/static/img/spid-idp-lepidaid.svg" },
                { "organization_name": "Register.it", "entity_id": "https://spid.register.it", "logo_uri": "/static/img/spid-idp-spiditalia.svg" },
                { "organization_name": "Namirial ID", "entity_id": "https://idp.namirialtsp.com/idp", "logo_uri": "/static/img/spid-idp-namirialid.svg" },
                { "organization_name": "TeamSystem ID", "entity_id": "https://spid.teamsystem.com/idp", "logo_uri": "/static/img/spid-idp-teamsystemid.svg" },
                { "organization_name": "Intesa Sanpaolo", "entity_id": "https://spid.intesaid.com/saml2/idp/metadata", "logo_uri": "/static/img/spid-idp-intesaid.svg" }
            ]

    _write_json(conf_dir, "spid-idps-default.json", spid_idps_json)

    _write(conf_dir, "proxy.yaml", _proxy_yaml(hostname, include_cie_oidc))
    _write(conf_dir, "oidc_frontend.yaml", _oidc_frontend_yaml(hostname))
    _write(conf_dir, "spid_backend.yaml", _spid_backend_yaml(hostname, enabled_idps, cert_path, key_path, settings))
    _write(conf_dir, "cie_saml_backend.yaml", _cie_saml_backend_yaml(hostname, cie_metadata_url, cert_path, key_path, settings))

    if include_cie_oidc:
        _write(
            conf_dir,
            "cie_oidc_backend.yaml",
            _cie_oidc_backend_yaml(
                hostname, cie_config, settings,
                jwk_federation, jwk_core_sig, jwk_core_enc, redis_url,
            ),
        )
