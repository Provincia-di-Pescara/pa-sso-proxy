import json
from datetime import datetime, timezone
from urllib.parse import quote

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import SpidIdP

SPID_IDPS = [
    {"alias": "spid-aruba",      "display_name": "Aruba PEC",         "metadata_url": "https://loginspid.aruba.it/metadata"},
    {"alias": "spid-infocert",   "display_name": "InfoCert ID",        "metadata_url": "https://identity.infocert.it/metadata/metadata.xml"},
    {"alias": "spid-intesa",     "display_name": "Intesa Sanpaolo",    "metadata_url": "https://spid.intesaid.com/saml2/idp/metadata"},
    {"alias": "spid-lepida",     "display_name": "Lepida ID",          "metadata_url": "https://id.lepida.it/idp/shibboleth"},
    {"alias": "spid-namirial",   "display_name": "Namirial ID",        "metadata_url": "https://idp.namirialtsp.com/idp/metadata"},
    {"alias": "spid-poste",      "display_name": "Poste ID",           "metadata_url": "https://posteid.poste.it/jod-fs/metadata/idp"},
    {"alias": "spid-register",   "display_name": "Register.it",        "metadata_url": "https://spid.register.it/login/metadata"},
    {"alias": "spid-sielte",     "display_name": "Sielte",             "metadata_url": "https://identity.sielte.it/idp/shibboleth"},
    {"alias": "spid-tim",        "display_name": "TIM Personal ID",    "metadata_url": "https://login.id.tim.it/affwebservices/public/saml2sso"},
    {"alias": "spid-teamsystem", "display_name": "TeamSystem ID",      "metadata_url": "https://spid.teamsystem.com/idp/saml2/metadata"},
    {"alias": "spid-trust",      "display_name": "Trust Technologies", "metadata_url": "https://idp.trusttechnologies.it/saml2/idp/metadata"},
    {"alias": "spid-demo",       "display_name": "Demo Provider",      "metadata_url": "https://demo.spid.gov.it/metadata.xml"},
    {"alias": "spid-validator",  "display_name": "AgID Validator",     "metadata_url": "https://validator.spid.gov.it/metadata.xml"},
]

SPID_REGISTRY_API_LIST_URL = "https://registry.spid.gov.it/entities-idp?output=json&page=1&numMetadata=50"


def _normalize_alias(entity_id: str) -> str:
    raw = entity_id.lower().strip()
    for prefix in ("https://", "http://"):
        if raw.startswith(prefix):
            raw = raw[len(prefix):]
    raw = raw.replace("/", "-").replace(".", "-").replace("_", "-")
    raw = "".join(ch for ch in raw if ch.isalnum() or ch == "-")
    raw = "-".join(filter(None, raw.split("-")))
    if not raw:
        raw = "spid-registry"
    return f"spid-{raw}"[:64]


def _extract_registry_items(payload) -> list[dict]:
    if isinstance(payload, list):
        return [p for p in payload if isinstance(p, dict)]
    if isinstance(payload, dict):
        items = payload.get("Entita") or payload.get("entita") or payload.get("entities") or payload.get("items") or []
        return [p for p in items if isinstance(p, dict)]
    return []


async def sync_spid_idps_from_registry(db: AsyncSession) -> int:
    """Sync local spid_idps cache from AgID registry. Returns number of inserted rows."""
    async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as client:
        response = await client.get(SPID_REGISTRY_API_LIST_URL, headers={"Accept": "application/json"})
        response.raise_for_status()
    items = _extract_registry_items(response.json())

    result = await db.execute(select(SpidIdP))
    existing = list(result.scalars().all())
    by_entity_id = {x.registry_entity_id: x for x in existing if x.registry_entity_id}
    by_alias = {x.alias: x for x in existing}

    inserted = 0
    sync_now = datetime.now(timezone.utc)

    for item in items:
        entity_id = item.get("entity_id") or item.get("entityId") or item.get("sp_entityid")
        if not entity_id:
            continue

        alias = _normalize_alias(entity_id)
        row = by_entity_id.get(entity_id) or by_alias.get(alias)
        if row is None:
            row = SpidIdP(
                alias=alias,
                display_name=item.get("organization_name") or entity_id,
                metadata_url=f"https://registry.spid.gov.it/entities-idp/{quote(entity_id, safe='')}",
                enabled=True,  # provider produzione abilitati di default
            )
            db.add(row)
            inserted += 1

        row.registry_entity_id = entity_id
        row.registry_logo_uri = item.get("logo_uri")
        row.registry_organization_name = item.get("organization_name")
        row.registry_lastupdate_date = item.get("lastupdate_date")
        row.registry_disabled = (item.get("_disabled") == "Y") if item.get("_disabled") is not None else None
        row.registry_payload_json = json.dumps(item)
        row.registry_synced_at = sync_now
        if not row.display_name or row.display_name == row.alias:
            row.display_name = item.get("organization_name") or entity_id

    await db.commit()
    return inserted


async def seed_spid_idps(db: AsyncSession) -> None:
    result = await db.execute(select(SpidIdP.alias))
    existing = {row[0] for row in result.all()}
    for data in SPID_IDPS:
        if data["alias"] not in existing:
            db.add(SpidIdP(
                alias=data["alias"],
                display_name=data["display_name"],
                metadata_url=data["metadata_url"],
                enabled=False,
            ))
    await db.commit()
