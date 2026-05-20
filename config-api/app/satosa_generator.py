import os
import yaml
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import OIDCClient

SATOSA_CONF_DIR = os.environ.get("SATOSA_CONF_DIR", "/satosa-conf")


async def generate_and_write(db: AsyncSession) -> None:
    result = await db.execute(select(OIDCClient).where(OIDCClient.enabled == True))
    clients_rows = result.scalars().all()

    clients_dict = {}
    for c in clients_rows:
        clients_dict[c.client_id] = {
            "client_secret": f"{{bcrypt}}{c.client_secret_hash}",
            "redirect_uris": list(c.redirect_uris),
            "allowed_scopes": list(c.allowed_scopes),
        }

    config = {"OIDCOP": {"clients": clients_dict}}

    conf_dir = os.environ.get("SATOSA_CONF_DIR", SATOSA_CONF_DIR)
    os.makedirs(conf_dir, exist_ok=True)
    path = os.path.join(conf_dir, "oidcop_clients.yaml")
    with open(path, "w") as f:
        yaml.dump(config, f, default_flow_style=False, allow_unicode=True)
