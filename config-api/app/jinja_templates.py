from fastapi.templating import Jinja2Templates
from starlette.requests import Request
from sqlalchemy import select

from app.version import get_display_version


async def _settings_context(request: Request) -> dict:
    from app.models import EnteSettings
    from app.database import AsyncSessionLocal
    async with AsyncSessionLocal() as db:
        s = (await db.execute(
            select(EnteSettings).where(EnteSettings.id == 1)
        )).scalar_one_or_none()
    return {"s": s}


templates = Jinja2Templates(
    directory="app/templates",
    context_processors=[_settings_context],
)
templates.env.globals["app_version"] = get_display_version()
