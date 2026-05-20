import json
import os

from app.models import JwkKey

SATOSA_CONF_DIR = os.environ.get("SATOSA_CONF_DIR", "/satosa-conf")


def write_jwks_files(keys: list[JwkKey]) -> None:
    """Write public and private JWKS JSON to SATOSA volume."""
    conf_dir = os.environ.get("SATOSA_CONF_DIR", SATOSA_CONF_DIR)
    os.makedirs(conf_dir, exist_ok=True)
    public_jwks = {"keys": [k.public_jwk for k in keys]}
    private_jwks = {"keys": [k.private_jwk for k in keys]}
    with open(os.path.join(conf_dir, "cie_jwks_public.json"), "w") as f:
        json.dump(public_jwks, f)
    with open(os.path.join(conf_dir, "cie_jwks_private.json"), "w") as f:
        json.dump(private_jwks, f)
