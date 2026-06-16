import csv
import io
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.jinja_templates import templates
from app.models import AccessLog

router = APIRouter()

_PAGE_SIZE = 25


def _auth_check(request: Request):
    return request.session.get("user")


def _build_filters(provider_type, result, from_date, to_date):
    filters = []
    if provider_type:
        filters.append(AccessLog.provider_type == provider_type)
    if result:
        filters.append(AccessLog.result == result)
    if from_date:
        try:
            filters.append(
                AccessLog.timestamp >= datetime.fromisoformat(from_date).replace(tzinfo=timezone.utc)
            )
        except ValueError:
            pass
    if to_date:
        try:
            filters.append(
                AccessLog.timestamp <= datetime.fromisoformat(to_date + "T23:59:59").replace(tzinfo=timezone.utc)
            )
        except ValueError:
            pass
    return filters


@router.get("/access-log", response_class=HTMLResponse)
async def access_log_list(
    request: Request,
    db: AsyncSession = Depends(get_db),
    page: int = Query(1, ge=1),
    provider_type: Optional[str] = Query(None),
    result: Optional[str] = Query(None),
    from_date: Optional[str] = Query(None),
    to_date: Optional[str] = Query(None),
):
    if not _auth_check(request):
        return RedirectResponse("/admin/login", status_code=302)

    filters = _build_filters(provider_type, result, from_date, to_date)
    offset = (page - 1) * _PAGE_SIZE
    q = select(AccessLog)
    if filters:
        q = q.where(and_(*filters))
    q = q.order_by(AccessLog.timestamp.desc()).offset(offset).limit(_PAGE_SIZE + 1)
    rows = list((await db.execute(q)).scalars().all())
    has_next = len(rows) > _PAGE_SIZE
    rows = rows[:_PAGE_SIZE]

    return templates.TemplateResponse(request, "access_log/index.html.j2", {
        "logs": rows,
        "page": page,
        "has_next": has_next,
        "provider_type": provider_type or "",
        "result_filter": result or "",
        "from_date": from_date or "",
        "to_date": to_date or "",
    })


@router.get("/access-log/export")
async def access_log_export(
    request: Request,
    db: AsyncSession = Depends(get_db),
    provider_type: Optional[str] = Query(None),
    result: Optional[str] = Query(None),
    from_date: Optional[str] = Query(None),
    to_date: Optional[str] = Query(None),
):
    if not _auth_check(request):
        return RedirectResponse("/admin/login", status_code=302)

    filters = _build_filters(provider_type, result, from_date, to_date)
    q = select(AccessLog)
    if filters:
        q = q.where(and_(*filters))
    q = q.order_by(AccessLog.timestamp.desc()).limit(10000)
    rows = list((await db.execute(q)).scalars().all())

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["timestamp", "provider_type", "client_id", "result", "error_code"])
    for r in rows:
        writer.writerow([
            r.timestamp.isoformat() if r.timestamp else "",
            r.provider_type,
            r.client_id or "",
            r.result,
            r.error_code or "",
        ])
    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=access_log.csv"},
    )
