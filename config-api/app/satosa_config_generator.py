import os
from typing import Optional

import yaml
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import CieConfig, EnteSettings, JwkKey, SpidIdP

SATOSA_CONF_DIR = os.environ.get("SATOSA_CONF_DIR", "/satosa-conf")
REDIS_URL = os.environ.get("REDIS_URL", "redis://redis:6379/0")

_OIDC_FRONTEND_CLASS = "satosa.frontends.openid_connect.OpenIDConnectFrontend"
_SAML_BACKEND_CLASS = "satosa.backends.saml2.SAMLMirrorBackend"


def _proxy_yaml(hostname: str, include_cie_oidc: bool) -> dict:
    backend_modules = [
        "/satosa-conf/spid_backend.yaml",
        "/satosa-conf/cie_saml_backend.yaml",
    ]
    if include_cie_oidc:
        backend_modules.append("/satosa-conf/cie_oidc_backend.yaml")
    return {
        "BASE": f"https://{hostname}",
        "COOKIE_STATE_NAME": "satosa_state",
        "USER_ID_HASH_SALT": os.environ.get("SATOSA_HASH_SALT", "changeme"),
        "CONSENT": {"enable": False},
        "BACKEND_MODULES": backend_modules,
        "FRONTEND_MODULES": ["/satosa-conf/oidc_frontend.yaml"],
    }


def _oidc_frontend_yaml(hostname: str, has_jwks: bool) -> dict:
    config: dict = {
        "issuer": f"https://{hostname}",
        "client_db": {
            "class": "oidcop.client_authn.from_file.ClientAuthnFromFile",
            "kwargs": {"client_file": "/satosa-conf/oidcop_clients.yaml"},
        },
        "authentication": {
            "user": {
                "acr": "urn:oasis:names:tc:SAML:2.0:ac:classes:PasswordProtectedTransport",
                "class": "oidcop.user_authn.authn_context.UserAuthnContextCritical",
            }
        },
    }
    if has_jwks:
        config["keys"] = {
            "private_path": "/satosa-conf/cie_jwks_private.json",
            "public_path": "/satosa-conf/cie_jwks_public.json",
            "read_only": False,
        }
    return config


def _spid_backend_yaml(hostname: str, enabled_idps: list, cert_path: str, key_path: str) -> dict:
    return {
        "entityid": f"https://{hostname}/spid/metadata",
        "service": {
            "sp": {
                "endpoints": {
                    "single_sign_on_service": [
                        [f"https://{hostname}/spid/sso/redirect",
                         "urn:oasis:names:tc:SAML:2.0:bindings:HTTP-Redirect"],
                        [f"https://{hostname}/spid/sso/post",
                         "urn:oasis:names:tc:SAML:2.0:bindings:HTTP-POST"],
                    ]
                },
                "want_response_signed": True,
                "authn_requests_signed": True,
                "allow_unsolicited": False,
            }
        },
        "key_file": key_path,
        "cert_file": cert_path,
        "metadata": {"remote": [{"url": idp.metadata_url} for idp in enabled_idps]},
    }


def _cie_saml_backend_yaml(hostname: str, cie_metadata_url: str, cert_path: str, key_path: str) -> dict:
    return {
        "entityid": f"https://{hostname}/cie/saml/metadata",
        "service": {
            "sp": {
                "endpoints": {
                    "single_sign_on_service": [
                        [f"https://{hostname}/cie/saml/sso/redirect",
                         "urn:oasis:names:tc:SAML:2.0:bindings:HTTP-Redirect"],
                        [f"https://{hostname}/cie/saml/sso/post",
                         "urn:oasis:names:tc:SAML:2.0:bindings:HTTP-POST"],
                    ]
                },
                "want_response_signed": True,
                "authn_requests_signed": True,
                "allow_unsolicited": False,
            }
        },
        "key_file": key_path,
        "cert_file": cert_path,
        "metadata": {"remote": [{"url": cie_metadata_url}]},
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
            "federation_resolve_endpoint": f"https://{hostname}/CieOidcRp/resolve",
            "organization_name": org_name,
            "homepage_uri": cie_config.homepage_uri,
            "policy_uri": cie_config.policy_uri,
            "logo_uri": cie_config.logo_uri,
            "contacts": [contact_email],
        },
        "openid_relying_party": {
            "application_type": "web",
            "client_id": cie_config.client_id,
            "client_name": org_name,
            "organization_name": org_name,
            "client_registration_types": ["automatic"],
            "signed_jwks_uri": f"https://{hostname}/CieOidcRp/openid_relying_party/jwks.jose",
            "jwks": None,
            "contacts": [contact_email],
            "grant_types": ["refresh_token", "authorization_code"],
            "redirect_uris": [f"https://{hostname}/CieOidcRp/oidc/callback"],
            "response_types": ["code"],
            "subject_type": "pairwise",
            "id_token_signed_response_alg": "ES256",
            "userinfo_signed_response_alg": "ES256",
            "userinfo_encrypted_response_alg": "ECDH-ES+A128KW",
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
            "claims": {
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
        "default_sig_alg": "ES256",
        "authority_hints": [cie_config.authority_hint_url],
    }
    trust_marks = [{"id": cie_config.trust_mark_id, "trust_mark": cie_config.trust_mark}]

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
                    "default": {"alg": "ES256"},
                    "supported": {"alg": ["RS256", "RS384", "RS512", "ES256", "ES384", "ES512"]},
                },
                "encrypt": {
                    "default": {"alg": "ECDH-ES+A128KW", "enc": "A256GCM"},
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
                        "default_sign_alg": "ES256",
                        "supported_sign_alg": ["RS256", "RS384", "RS512", "ES256", "ES384", "ES512"],
                        "default_enc_alg": "ECDH-ES+A128KW",
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
                            "first_name": ["given_name", "given_name"],
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


def _write(conf_dir: str, filename: str, data: dict) -> None:
    with open(os.path.join(conf_dir, filename), "w") as f:
        yaml.dump(data, f, default_flow_style=False, allow_unicode=True)


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
        and cie_config.trust_mark
        and cie_config.trust_mark_id
        and cie_config.authority_hint_url
        and cie_config.trust_anchor_url
        and cie_config.client_id
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

    _write(conf_dir, "proxy.yaml", _proxy_yaml(hostname, include_cie_oidc))
    _write(conf_dir, "oidc_frontend.yaml", _oidc_frontend_yaml(hostname, has_jwks))
    _write(conf_dir, "spid_backend.yaml", _spid_backend_yaml(hostname, enabled_idps, cert_path, key_path))
    _write(conf_dir, "cie_saml_backend.yaml", _cie_saml_backend_yaml(hostname, cie_metadata_url, cert_path, key_path))

    if include_cie_oidc:
        _write(
            conf_dir,
            "cie_oidc_backend.yaml",
            _cie_oidc_backend_yaml(
                hostname, cie_config, settings,
                jwk_federation, jwk_core_sig, jwk_core_enc, redis_url,
            ),
        )
