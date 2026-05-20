import os
import docker

SATOSA_CONTAINER_NAME = os.environ.get("SATOSA_CONTAINER_NAME", "pa-sso-proxy-satosa-1")


def reload_satosa() -> bool:
    try:
        client = docker.from_env()
        container = client.containers.get(SATOSA_CONTAINER_NAME)
        container.restart(timeout=10)
        return True
    except Exception:
        return False
