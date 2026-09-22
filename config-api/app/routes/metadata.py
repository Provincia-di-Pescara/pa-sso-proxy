from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from app.jinja_templates import templates
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import SpidCert, SpidMetadataVersion

router = APIRouter()


def _auth_check(request: Request) -> bool:
    return request.session.get("user") is not None


@router.get("/metadata", response_class=HTMLResponse)
async def metadata_history(request: Request, db: AsyncSession = Depends(get_db)):
    if not _auth_check(request):
        return RedirectResponse("/admin/login", status_code=302)
    result = await db.execute(select(SpidMetadataVersion).order_by(SpidMetadataVersion.created_at.desc()))
    versions = result.scalars().all()

    active_cert_result = await db.execute(select(SpidCert).where(SpidCert.is_active == True).limit(1))
    active_cert = active_cert_result.scalar_one_or_none()

    return templates.TemplateResponse(
        request,
        "metadata/history.html.j2",
        {
            "versions": versions,
            "active_cert_id": active_cert.id if active_cert else None,
            "error": request.query_params.get("error"),
            "warning": request.query_params.get("warning"),
        },
    )
