import os
from pathlib import Path


def reload_satosa() -> bool:
    conf_dir = os.environ.get("SATOSA_CONF_DIR", "/satosa-conf")
    try:
        Path(conf_dir, ".reload").touch()
        return True
    except Exception:
        return False
