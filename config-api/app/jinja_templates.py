from datetime import datetime, timezone
import zoneinfo
from fastapi.templating import Jinja2Templates
from starlette.requests import Request
from sqlalchemy import select

from app.admin_2fa import is_2fa_enabled, is_2fa_reset_requested
from app.version import get_display_version


def _settings_context(request: Request) -> dict:
    s = getattr(request.state, "s", None)
    return {
        "s": s,
        "admin_2fa_disabled": not is_2fa_enabled(),
        "admin_2fa_reset_active": is_2fa_reset_requested(),
    }


def to_italian_time(dt: datetime) -> datetime:
    if not dt:
        return dt
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(zoneinfo.ZoneInfo("Europe/Rome"))


templates = Jinja2Templates(
    directory="app/templates",
    context_processors=[_settings_context],
)
templates.env.globals["app_version"] = get_display_version()
templates.env.filters["to_italian_time"] = to_italian_time

