import os
from fastapi import Request
from fastapi.responses import RedirectResponse

ADMIN_USER = os.environ.get("ADMIN_USER", "admin")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "changeme")


def get_current_user(request: Request) -> str:
    user = request.session.get("user")
    if not user:
        return None
    return user
