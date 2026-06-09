import base64
import json
import os
import random
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
_OIDC_FRONTEND_CLASS = "satosa.frontends.openid_connect.OpenIDConnectFrontend"
_OIDC_FRONTEND_EXT_CLASS = "oidc_frontend_ext.OIDCFrontendWithEndSession"

# Custom OIDC frontend extension deployed to satosa-conf:
# - adds end_session_endpoint to OIDC discovery document
# - handles RP-initiated logout (redirects to post_logout_redirect_uri)
# - uses extra_scopes to release fiscal_number when profile scope is requested
_OIDC_FRONTEND_EXT_PY = '''\
from satosa.frontends.openid_connect import OpenIDConnectFrontend
from satosa.response import SeeOther, Response


class OIDCFrontendWithEndSession(OpenIDConnectFrontend):
    def register_endpoints(self, backend_names):
        url_map = super().register_endpoints(backend_names)
        end_session_url = "{}/end_session".format(self.endpoint_baseurl)
        self.provider.configuration_information["end_session_endpoint"] = end_session_url
        url_map.append(("^{}/end_session$".format(self.name), self.end_session))
        return url_map

    def end_session(self, context):
        params = context.request or {}
        redirect_uri = params.get("post_logout_redirect_uri")
        if isinstance(redirect_uri, list):
            redirect_uri = redirect_uri[0] if redirect_uri else None
        if redirect_uri:
            return SeeOther(redirect_uri)
        return Response("Logout completato", status="200 OK")
'''


def _proxy_yaml(hostname: str, include_cie_oidc: bool) -> dict:
    backend_modules = [
        "/satosa-conf/spid_backend.yaml",
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
    base = _base_url(hostname)
    # Use Redis DB 1 for OIDC authz_state — CIE backend occupies DB 0
    _redis_scheme, _redis_hostpath = REDIS_URL.split("://", 1)
    redis_db1 = f"{_redis_scheme}://{_redis_hostpath.split('/')[0]}/1"
    return {
        "name": "OIDC",
        "module": _OIDC_FRONTEND_EXT_CLASS,
        "issuer": base,
        "config": {
            "signing_key_path": "/satosa-conf/oidc_signing_key.pem",
            "client_db_path": "/satosa-conf/oidc_clients.json",
            "db_uri": redis_db1,
            "provider": {
                "response_types_supported": ["code"],
                "scopes_supported": ["openid", "profile", "email"],
                "subject_types_supported": ["pairwise", "public"],
                "id_token_lifetime": 3600,
                # extra_scopes replaces (not extends) the default oic scope→claims mapping,
                # so profile must include all standard OIDC profile claims + fiscal_number
                "extra_scopes": {
                    "profile": [
                        "name", "given_name", "family_name", "middle_name", "nickname",
                        "profile", "picture", "website", "gender", "birthdate",
                        "zoneinfo", "locale", "updated_at", "preferred_username",
                        "fiscal_number",
                    ],
                },
            },
        },
    }


def _spid_backend_yaml(hostname: str, enabled_idps: list, cert_path: str, key_path: str, settings: "EnteSettings") -> dict:
    local_metadata = ["/satosa_proxy/metadata/idp/spid-entities-idps.xml"]
    # Production IdPs are already in the local aggregate XML; their metadata_url
    # endpoints redirect (307) which pysaml2 does not follow → SourceNotFound crash.
    # Only demo/test IdPs need remote metadata (their URLs return 200 directly).
    _TEST_ALIASES = {"spid-demo", "spid-validator"}
    remote_metadata = [
        {"url": idp.metadata_url}
        for idp in enabled_idps
        if idp.metadata_url and idp.alias in _TEST_ALIASES
    ]
    metadata_config = {"local": local_metadata}
    if remote_metadata:
        metadata_config["remote"] = remote_metadata

    sp_config = {
        "key_file": key_path,
        "cert_file": cert_path,
        "encryption_keypairs": [{"key_file": key_path, "cert_file": cert_path}],
        "attribute_map_dir": "/satosa_proxy/attributes-map",
        "custom_attribute_consuming_services": [
            {
                "service_name": "min",
                "attributes": ["spidCode", "name", "familyName", "fiscalNumber", "email"],
            },
            {
                "service_name": "med",
                "attributes": ["spidCode", "name", "familyName", "fiscalNumber", "email", "gender", "dateOfBirth", "placeOfBirth", "countyOfBirth", "mobilePhone"],
            },
            {
                "service_name": "max",
                "attributes": [
                    "spidCode", "name", "familyName", "placeOfBirth", "countyOfBirth",
                    "dateOfBirth", "gender", "companyName", "registeredOffice",
                    "fiscalNumber", "ivaCode", "idCard", "mobilePhone", "email",
                    "domicileStreetAddress", "domicilePostalCode", "domicileMunicipality",
                    "domicileProvince", "domicileNation", "expirationDate", "digitalAddress"
                ],
            }
        ],
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
            "userinfo_encrypted_response_alg": "RSA-OAEP",
            "userinfo_encrypted_response_enc": "A256CBC-HS512",
            "token_endpoint_auth_method": "private_key_jwt",
            "scope": "openid profile email",
            "code_challenge": {"length": 64, "method": "S256"},
            "claim": {
                "id_token": {
                    "sub": {"essential": True},
                    "family_name": {"essential": True},
                    "given_name": {"essential": True},
                },
                "userinfo": {
                    "sub": None,
                    "given_name": {"essential": True},
                    "family_name": {"essential": True},
                    "email": {"essential": True},
                    "https://attributes.eid.gov.it/fiscal_number": {"essential": True},
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
                    "default": {"alg": "RSA-OAEP", "enc": "A256CBC-HS512"},
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
                        "default_enc_alg": "RSA-OAEP",
                        "default_enc_enc": "A256CBC-HS512",
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


def _eid_locale_strings(cie_oidc_login_url: str | None, settings: "EnteSettings | None" = None) -> dict:
    """Return eid locale dicts for 'it' and 'en' with correct CIE URLs substituted."""
    it_wallet_it = {
        "name": "IT-Wallet",
        "logo_text": "Entra con IT-Wallet",
        "logo": "it-wallet/wallet_icon.svg",
        "login_url": "it-wallet.html",
        "learn_more_descr": (
            "IT-Wallet è il sistema italiano di portafogli digitali che ti permette di autenticarti online "
            "e di accedere a servizi pubblici e privati in modo sicuro e veloce."
        ),
        "learn_more_link": "https://innovazione.gov.it/progetti/sistema-it-wallet/",
        "learn_more_label": "Scopri come ottenerlo",
    }
    it_wallet_en = {
        "name": "IT-Wallet",
        "logo_text": "Login with IT-Wallet",
        "logo": "it-wallet/wallet_icon.svg",
        "login_url": "it-wallet.html",
        "learn_more_descr": (
            "IT-Wallet is Italy's national digital wallet system. It lets you authenticate online and access "
            "public and private services securely and quickly."
        ),
        "learn_more_link": "https://innovazione.gov.it/progetti/sistema-it-wallet/",
        "learn_more_label": "Find out how to get it",
    }
    cie_it = {
        "name": "CIE",
        "logo_text": "Entra con CIE",
        "logo": "cie/cie_white.svg",
        "login_url": cie_oidc_login_url or "",
        "learn_more_descr": (
            "La CIE (Carta d'Identità Elettronica) è il documento d'identità elettronico italiano. "
            "Usala per accedere ai servizi online in modo sicuro tramite il protocollo OpenID Connect."
        ),
        "learn_more_link": "https://www.cartaidentita.interno.gov.it/",
        "learn_more_label": "Scopri come ottenerla",
    }
    cie_en = {
        "name": "CIE",
        "logo_text": "Login with CIE",
        "logo": "cie/cie_white.svg",
        "login_url": cie_oidc_login_url or "",
        "learn_more_descr": (
            "CIE (Carta d'Identità Elettronica) is the Italian electronic identity card. "
            "Use it to access online services securely via the OpenID Connect protocol."
        ),
        "learn_more_link": "https://www.cartaidentita.interno.gov.it/",
        "learn_more_label": "Find out how to get it",
    }
    spid_it = {
        "name": "SPID",
        "logo_text": "Entra con SPID",
        "logo": "https://raw.githubusercontent.com/italia/spid-idp-login-layout/master/img/spid-ico-circle-bb.svg",
        "login_url": "#spid-idp-button-xlarge-post",
        "learn_more_descr": (
            "SPID (Sistema Pubblico di Identità Digitale) è il sistema pubblico di identità digitale italiano. "
            "Scegli il tuo gestore di identità per accedere con le tue credenziali SPID."
        ),
        "learn_more_link": "https://www.spid.gov.it/",
        "learn_more_label": "Scopri come ottenerla",
    }
    spid_en = {
        "name": "SPID",
        "logo_text": "Login with SPID",
        "logo": "https://raw.githubusercontent.com/italia/spid-idp-login-layout/master/img/spid-ico-circle-bb.svg",
        "login_url": "#spid-idp-button-xlarge-post",
        "learn_more_descr": (
            "SPID (Sistema Pubblico di Identità Digitale) is the Italian public digital identity system. "
            "Choose your identity provider to log in with your SPID credentials."
        ),
        "learn_more_link": "https://www.spid.gov.it/",
        "learn_more_label": "Find out how to get it",
    }

    def _digital_id(cie, spid, it_wallet, cie_oidc_login, lang):
        d = {"it_wallet": it_wallet, "cie": cie, "spid": spid}
        if cie_oidc_login:
            cie_oidc_name = "CIE OpenID Connect"
            cie_oidc_descr_it = (
                "La CIE (Carta d'Identità Elettronica) può essere usata con il protocollo OIDC "
                "per autenticarti e accedere ai servizi online."
            )
            cie_oidc_descr_en = (
                "CIE (Carta d'Identità Elettronica) can be used with the OIDC protocol "
                "to authenticate and access online services."
            )
            d["cie_oidc"] = {
                "name": cie_oidc_name,
                "logo_text": "Entra con CIE" if lang == "it" else "Login with CIE",
                "logo": "cie/cie_white.svg",
                "login_url": cie_oidc_login,
                "learn_more_descr": cie_oidc_descr_it if lang == "it" else cie_oidc_descr_en,
            }
        return d

    common_titles_it = {
        "page_title": "Pagina di selezione del metodo di Autenticazione",
        "login_logo": "Il tuo logo",
        "login_digital_identity": "Accedi con un'identità digitale",
        "login_alternative_method": "Accedi con un metodo alternativo",
        "havent_digital_identy": "Non hai un'identità digitale?",
        "find_how_to_get_digital_id": "Scopri come ottenerla",
        "find_how_to_get_digital_id_url": "https://identitadigitale.gov.it/",
        "learn_more": "Scopri di più",
    }
    common_titles_en = {
        "page_title": "Authentication method selection page",
        "login_logo": "Your logo",
        "login_digital_identity": "Sign in with a digital identity",
        "login_alternative_method": "Sign in with an alternative method",
        "havent_digital_identy": "Don't have a digital identity?",
        "find_how_to_get_digital_id": "Find out how to get one",
        "find_how_to_get_digital_id_url": "https://identitadigitale.gov.it/",
        "learn_more": "Learn more",
    }
    _s = settings
    _logo_url = (_s.logo_url or "") if _s else ""
    _favicon_url = (_s.favicon_url or "") if _s else ""
    _privacy_url = (_s.privacy_url or "") if _s else ""
    _legal_notes_url = (_s.legal_notes_url or "") if _s else ""
    _accessibility_url = (_s.accessibility_url or "") if _s else ""
    _support_url = (_s.support_url or "") if _s else ""
    _org_name_it = (_s.org_display_name or "Nome dell'Organizzazione") if _s else "Nome dell'Organizzazione"
    _org_name_en = (_s.org_display_name or "Organisation Name") if _s else "Organisation Name"

    footer_it = {
        "legal_notice": "Note legali",
        "legal_notice_url": _legal_notes_url,
        "privacy_policy": "Privacy Policy",
        "privacy_policy_url": _privacy_url,
        "accessibility_statement": "Dichiarazione Accessibilità",
        "accessibility_url": _accessibility_url,
        "support": "Assistenza",
        "support_url": _support_url,
    }
    footer_en = {
        "legal_notice": "Legal notice",
        "legal_notice_url": _legal_notes_url,
        "privacy_policy": "Privacy Policy",
        "privacy_policy_url": _privacy_url,
        "accessibility_statement": "Accessibility statement",
        "accessibility_url": _accessibility_url,
        "support": "Support",
        "support_url": _support_url,
    }

    it_locale = {
        "header": {"region_name": _org_name_it, "logo_url": _logo_url, "favicon_url": _favicon_url},
        "titles": common_titles_it,
        "digital_id": _digital_id(cie_it, spid_it, it_wallet_it, cie_oidc_login_url, "it"),
        "footer": footer_it,
    }
    en_locale = {
        "header": {"region_name": _org_name_en, "logo_url": _logo_url, "favicon_url": _favicon_url},
        "titles": common_titles_en,
        "digital_id": _digital_id(cie_en, spid_en, it_wallet_en, cie_oidc_login_url, "en"),
        "footer": footer_en,
    }
    return {"it": it_locale, "en": en_locale}


_DEFAULT_BACKEND_ROUTER_PY = '''\
import logging
from satosa.context import Context
from satosa.micro_services.base import RequestMicroService

logger = logging.getLogger(__name__)


class DefaultBackendRouter(RequestMicroService):
    def __init__(self, config, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.default_backend = config.get("default_backend", "spidSaml2")
        self.cie_oidc_provider_urls = set(config.get("cie_oidc_provider_urls", []))

    def process(self, context, data):
        if not context.target_backend:
            entity_id = context.get_decoration(Context.KEY_TARGET_ENTITYID)
            if entity_id and self.cie_oidc_provider_urls and entity_id in self.cie_oidc_provider_urls:
                context.target_backend = "CieOidcRp"
                logger.info(f"DefaultBackendRouter: CIE OIDC entity {entity_id} → CieOidcRp")
            else:
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
    with open(os.path.join(conf_dir, filename), "w", encoding="utf-8") as f:
        yaml.dump(data, f, default_flow_style=False, allow_unicode=True)


def _write_json(conf_dir: str, filename: str, data: dict) -> None:
    with open(os.path.join(conf_dir, filename), "w", encoding="utf-8") as f:
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
                # Strip 'use' so cryptojwt accepts the key for signing
                # (cryptojwt rejects use=federation; RFC 7517 absent=any purpose)
                jwk_federation = {kk: v for kk, v in k.private_jwk.items() if kk != "use"}
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

    with open(os.path.join(conf_dir, "default_backend_router.py"), "w", encoding="utf-8") as f:
        f.write(_DEFAULT_BACKEND_ROUTER_PY)

    with open(os.path.join(conf_dir, "oidc_frontend_ext.py"), "w", encoding="utf-8") as f:
        f.write(_OIDC_FRONTEND_EXT_PY)

    cie_oidc_urls = (
        [cie_config.oidc_provider_url]
        if include_cie_oidc and cie_config and cie_config.oidc_provider_url
        else []
    )
    _write(conf_dir, "default_router.yaml", {
        "name": "DefaultRouter",
        "module": "default_backend_router.DefaultBackendRouter",
        "config": {
            "default_backend": "spidSaml2",
            "cie_oidc_provider_urls": cie_oidc_urls,
        },
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

    # Generate and write dynamic spid-idps-default.json based on active providers
    spid_idps_json = []

    for idp in enabled_idps:
        if idp.alias == "spid-demo":
            spid_idps_json.append({
                "organization_name": "Demo Provider",
                "entity_id": "https://demo.spid.gov.it",
                "logo_uri": "https://pagopa-prx.comune.montesilvano.pe.it/static/spid/spid-agid-logo-lb.png"
            })
        elif idp.alias == "spid-validator":
            spid_idps_json.append({
                "organization_name": "AgID Validator",
                "entity_id": "https://validator.spid.gov.it",
                "logo_uri": "https://pagopa-prx.comune.montesilvano.pe.it/static/spid/spid-agid-logo-lb.png"
            })
        elif idp.registry_entity_id:
            spid_idps_json.append({
                "organization_name": idp.registry_organization_name or idp.display_name,
                "entity_id": idp.registry_entity_id,
                "logo_uri": idp.registry_logo_uri or ""
            })

    if not spid_idps_json:
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
    spid_idps_json.sort(key=lambda x: x["organization_name"])


    _write_json(conf_dir, "spid-idps-default.json", spid_idps_json)

    # Generate locale overrides with correct CIE URLs (CIE is OIDC only)
    cie_oidc_login_url = (
        f"/Saml2/disco?entityID={cie_config.oidc_provider_url}"
        if include_cie_oidc and cie_config and cie_config.oidc_provider_url
        else None
    )
    os.makedirs(os.path.join(conf_dir, "locales"), exist_ok=True)
    for lang, strings in _eid_locale_strings(cie_oidc_login_url, settings).items():
        _write_json(conf_dir, f"locales/eid-{lang}.json", strings)

    _write(conf_dir, "proxy.yaml", _proxy_yaml(hostname, include_cie_oidc))
    _write(conf_dir, "oidc_frontend.yaml", _oidc_frontend_yaml(hostname))
    _write(conf_dir, "spid_backend.yaml", _spid_backend_yaml(hostname, enabled_idps, cert_path, key_path, settings))


    if include_cie_oidc:
        _write(
            conf_dir,
            "cie_oidc_backend.yaml",
            _cie_oidc_backend_yaml(
                hostname, cie_config, settings,
                jwk_federation, jwk_core_sig, jwk_core_enc, redis_url,
            ),
        )
