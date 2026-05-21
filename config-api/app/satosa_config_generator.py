import os

import yaml
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import CieConfig, EnteSettings, JwkKey, SpidIdP

SATOSA_CONF_DIR = os.environ.get("SATOSA_CONF_DIR", "/satosa-conf")

# SATOSA Python class paths — adapt for ghcr.io/italia/iam-proxy-italia if needed
_OIDC_FRONTEND_CLASS = "satosa.frontends.openid_connect.OpenIDConnectFrontend"
_SAML_BACKEND_CLASS = "satosa.backends.saml2.SAMLMirrorBackend"


def _proxy_yaml(hostname: str) -> dict:
    return {
        "BASE": f"https://{hostname}",
        "COOKIE_STATE_NAME": "satosa_state",
        "USER_ID_HASH_SALT": os.environ.get("SATOSA_HASH_SALT", "changeme"),
        "CONSENT": {"enable": False},
        "PLUGIN": [
            {
                "class": _OIDC_FRONTEND_CLASS,
                "name": "oidc_frontend",
                "config": {"op_config_file": "/satosa-conf/oidc_frontend.yaml"},
                "endpoints": [],
            },
            {
                "class": _SAML_BACKEND_CLASS,
                "name": "spid_backend",
                "config": {"sp_config": "/satosa-conf/spid_backend.yaml"},
                "endpoints": [
                    {
                        "path": "spid/sso/redirect",
                        "binding": "urn:oasis:names:tc:SAML:2.0:bindings:HTTP-Redirect",
                    },
                    {
                        "path": "spid/sso/post",
                        "binding": "urn:oasis:names:tc:SAML:2.0:bindings:HTTP-POST",
                    },
                ],
            },
            {
                "class": _SAML_BACKEND_CLASS,
                "name": "cie_saml_backend",
                "config": {"sp_config": "/satosa-conf/cie_saml_backend.yaml"},
                "endpoints": [
                    {
                        "path": "cie/saml/sso/redirect",
                        "binding": "urn:oasis:names:tc:SAML:2.0:bindings:HTTP-Redirect",
                    },
                    {
                        "path": "cie/saml/sso/post",
                        "binding": "urn:oasis:names:tc:SAML:2.0:bindings:HTTP-POST",
                    },
                ],
            },
        ],
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
                        [
                            f"https://{hostname}/spid/sso/redirect",
                            "urn:oasis:names:tc:SAML:2.0:bindings:HTTP-Redirect",
                        ],
                        [
                            f"https://{hostname}/spid/sso/post",
                            "urn:oasis:names:tc:SAML:2.0:bindings:HTTP-POST",
                        ],
                    ]
                },
                "want_response_signed": True,
                "authn_requests_signed": True,
                "allow_unsolicited": False,
            }
        },
        "key_file": key_path,
        "cert_file": cert_path,
        "metadata": {
            "remote": [{"url": idp.metadata_url} for idp in enabled_idps]
        },
    }


def _cie_saml_backend_yaml(hostname: str, cie_metadata_url: str, cert_path: str, key_path: str) -> dict:
    return {
        "entityid": f"https://{hostname}/cie/saml/metadata",
        "service": {
            "sp": {
                "endpoints": {
                    "single_sign_on_service": [
                        [
                            f"https://{hostname}/cie/saml/sso/redirect",
                            "urn:oasis:names:tc:SAML:2.0:bindings:HTTP-Redirect",
                        ],
                        [
                            f"https://{hostname}/cie/saml/sso/post",
                            "urn:oasis:names:tc:SAML:2.0:bindings:HTTP-POST",
                        ],
                    ]
                },
                "want_response_signed": True,
                "authn_requests_signed": True,
                "allow_unsolicited": False,
            }
        },
        "key_file": key_path,
        "cert_file": cert_path,
        "metadata": {
            "remote": [{"url": cie_metadata_url}]
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

    conf_dir = os.environ.get("SATOSA_CONF_DIR", SATOSA_CONF_DIR)
    os.makedirs(conf_dir, exist_ok=True)

    cert_path = "/satosa-conf/spid_sp_cert.pem"
    key_path = "/satosa-conf/spid_sp_key.pem"
    hostname = settings.proxy_hostname

    _write(conf_dir, "proxy.yaml", _proxy_yaml(hostname))
    _write(conf_dir, "oidc_frontend.yaml", _oidc_frontend_yaml(hostname, has_jwks))
    _write(conf_dir, "spid_backend.yaml", _spid_backend_yaml(hostname, enabled_idps, cert_path, key_path))
    _write(conf_dir, "cie_saml_backend.yaml", _cie_saml_backend_yaml(hostname, cie_metadata_url, cert_path, key_path))
