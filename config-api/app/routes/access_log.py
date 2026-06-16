import csv
import hashlib as _hashlib
import hmac as _hmac
import io
import os
import re
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from sqlalchemy import and_, select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.jinja_templates import templates
from app.models import AccessLog, OIDCClient

router = APIRouter()

_PAGE_SIZE = 25


def _auth_check(request: Request):
    return request.session.get("user")


def _build_filters(provider_type, result, from_date, to_date, idp_entity_id=None):
    filters = []
    if provider_type:
        filters.append(AccessLog.provider_type == provider_type)
    if result:
        filters.append(AccessLog.result == result)
    if idp_entity_id:
        filters.append(AccessLog.idp_entity_id == idp_entity_id)
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
    idp_entity_id: Optional[str] = Query(None),
):
    if not _auth_check(request):
        return RedirectResponse("/admin/login", status_code=302)

    filters = _build_filters(provider_type, result, from_date, to_date, idp_entity_id)
    offset = (page - 1) * _PAGE_SIZE
    q = select(AccessLog)
    if filters:
        q = q.where(and_(*filters))
    q = q.order_by(AccessLog.timestamp.desc()).offset(offset).limit(_PAGE_SIZE + 1)
    rows = list((await db.execute(q)).scalars().all())
    has_next = len(rows) > _PAGE_SIZE
    rows = rows[:_PAGE_SIZE]

    clients_res = await db.execute(select(OIDCClient.client_id, OIDCClient.name))
    client_name_map = {row.client_id: row.name for row in clients_res.all()}

    # Distinct IdP list for filter dropdown
    idp_rows = (await db.execute(
        select(AccessLog.idp_entity_id).where(AccessLog.idp_entity_id.isnot(None)).distinct()
    )).scalars().all()

    return templates.TemplateResponse(request, "access_log/index.html.j2", {
        "logs": rows,
        "page": page,
        "has_next": has_next,
        "provider_type": provider_type or "",
        "result_filter": result or "",
        "from_date": from_date or "",
        "to_date": to_date or "",
        "idp_entity_id": idp_entity_id or "",
        "idp_list": sorted(idp_rows),
        "client_name_map": client_name_map,
    })


@router.get("/access-log/export")
async def access_log_export(
    request: Request,
    db: AsyncSession = Depends(get_db),
    provider_type: Optional[str] = Query(None),
    result: Optional[str] = Query(None),
    from_date: Optional[str] = Query(None),
    to_date: Optional[str] = Query(None),
    idp_entity_id: Optional[str] = Query(None),
):
    if not _auth_check(request):
        return RedirectResponse("/admin/login", status_code=302)

    filters = _build_filters(provider_type, result, from_date, to_date, idp_entity_id)
    q = select(AccessLog)
    if filters:
        q = q.where(and_(*filters))
    q = q.order_by(AccessLog.timestamp.desc()).limit(10000)
    rows = list((await db.execute(q)).scalars().all())

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["timestamp", "provider_type", "idp_entity_id", "client_id", "user_type", "fiscal_number_hash", "result", "error_code"])
    for r in rows:
        writer.writerow([
            r.timestamp.isoformat() if r.timestamp else "",
            r.provider_type,
            r.idp_entity_id or "",
            r.client_id or "",
            r.user_type or "",
            r.fiscal_number_hash or "",
            r.result,
            r.error_code or "",
        ])
    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=access_log.csv"},
    )


def _compute_cf_hash(fiscal_no: str) -> str:
    cf_key = (os.environ.get("CF_HASH_KEY") or "default-dev-cf-hash-key").encode()
    if not fiscal_no:
        return ""
    normalized = str(fiscal_no).strip().upper()
    if normalized.startswith("TINIT-"):
        normalized = normalized[6:]
    return _hmac.new(cf_key, normalized.encode("utf-8"), _hashlib.sha256).hexdigest()


@router.get("/access-log/advanced", response_class=HTMLResponse)
async def access_log_advanced(
    request: Request,
    db: AsyncSession = Depends(get_db),
    page: int = Query(1, ge=1),
    search_cf: Optional[str] = Query(None),
    provider_type: Optional[str] = Query(None),
    from_date: Optional[str] = Query(None),
    to_date: Optional[str] = Query(None),
):
    if not _auth_check(request):
        return RedirectResponse("/admin/login", status_code=302)

    # We only show successful accesses
    filters = _build_filters(provider_type, "success", from_date, to_date)

    computed_hash = None
    total_cf_accesses = None

    if search_cf:
        search_cf_clean = search_cf.strip()
        # Check if it looks like a SHA256 HMAC (64 characters, hexadecimal)
        if len(search_cf_clean) == 64 and re.match(r"^[0-9a-fA-F]{64}$", search_cf_clean):
            computed_hash = search_cf_clean.lower()
        else:
            computed_hash = _compute_cf_hash(search_cf_clean)

        if computed_hash:
            filters.append(AccessLog.fiscal_number_hash == computed_hash)

            # Count overall successful accesses for this CF hash
            count_q = select(func.count(AccessLog.id)).where(
                and_(
                    AccessLog.fiscal_number_hash == computed_hash,
                    AccessLog.result == "success"
                )
            )
            total_cf_accesses = (await db.execute(count_q)).scalar_one()

    offset = (page - 1) * _PAGE_SIZE
    q = select(AccessLog)
    if filters:
        q = q.where(and_(*filters))
    q = q.order_by(AccessLog.timestamp.desc()).offset(offset).limit(_PAGE_SIZE + 1)
    rows = list((await db.execute(q)).scalars().all())
    has_next = len(rows) > _PAGE_SIZE
    rows = rows[:_PAGE_SIZE]

    clients_res = await db.execute(select(OIDCClient.client_id, OIDCClient.name))
    client_name_map = {row.client_id: row.name for row in clients_res.all()}

    return templates.TemplateResponse(request, "access_log/advanced.html.j2", {
        "logs": rows,
        "page": page,
        "has_next": has_next,
        "search_cf": search_cf or "",
        "computed_hash": computed_hash or "",
        "total_cf_accesses": total_cf_accesses,
        "provider_type": provider_type or "",
        "from_date": from_date or "",
        "to_date": to_date or "",
        "client_name_map": client_name_map,
    })
