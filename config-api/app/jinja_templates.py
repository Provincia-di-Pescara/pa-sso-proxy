from fastapi.templating import Jinja2Templates
from starlette.requests import Request
from sqlalchemy import select

from app.version import get_display_version


def _settings_context(request: Request) -> dict:
    s = getattr(request.state, "s", None)
    return {"s": s}


templates = Jinja2Templates(
    directory="app/templates",
    context_processors=[_settings_context],
)
templates.env.globals["app_version"] = get_display_version()
