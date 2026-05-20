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
]


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
