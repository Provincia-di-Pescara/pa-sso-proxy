from fastapi.templating import Jinja2Templates
from app.version import get_display_version

templates = Jinja2Templates(directory="app/templates")
templates.env.globals["app_version"] = get_display_version()
