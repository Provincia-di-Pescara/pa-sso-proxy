"""Profilo metadata SPID validato: impronta del metadata, stato attuale vs validato,
creazione e ripristino del profilo.

Spec: docs/superpowers/specs/2026-11-10-spid-metadata-validated-profile-design.md
"""
import hashlib
import json
import logging
import os
from dataclasses import dataclass, field

from defusedxml import ElementTree as DefusedET
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import EnteSettings, SpidCert, SpidIdP, SpidMetadataProfile, SpidMetadataVersion

logger = logging.getLogger(__name__)

_DS_SIGNATURE = "{http://www.w3.org/2000/09/xmldsig#}Signature"
# Attributi che cambiano a ogni generazione senza cambiare il significato.
_VOLATILE_ATTRS = frozenset({"ID", "validUntil", "cacheDuration"})

# Parametri di EnteSettings che finiscono nel metadata SP (o, per
# eidas_environment, decidono il nodo FICEP validato), in ordine di visualizzazione.
PROFILE_SETTINGS_FIELDS = {
    "eidas_enabled": "eIDAS",
    "eidas_environment": "Ambiente eIDAS",
    "legal_entity_enabled": "Persona giuridica",
    "org_name": "Nome ente",
    "org_display_name": "Nome visualizzato",
    "org_url": "URL ente",
    "ipa_code": "Codice IPA",
    "vat_number": "Codice fiscale / P.IVA",
    "contact_email": "Email contatto",
    "contact_phone": "Telefono contatto",
}


def metadata_fingerprint(xml_text: str) -> str:
    """Impronta del contenuto del metadata, indipendente da serializzazione.

    Ignora firma (ds:Signature), ID/validUntil/cacheDuration, prefissi dei
    namespace (tag in notazione Clark) e whitespace tra elementi. Dipende da
    tutto il resto: entityID, certificati, ACS e attributi, Organization,
    ContactPerson. Serve perché pysaml2 7.5.5 serializza lo stesso contenuto con
    prefissi diversi (ns0: invece di md:) e la firma usa un ID casuale.
    """
    try:
        root = DefusedET.fromstring(xml_text.encode("utf-8"))
    except Exception:
        return hashlib.sha256(xml_text.encode("utf-8")).hexdigest()

    out: list = []

    def walk(el) -> None:
        if el.tag == _DS_SIGNATURE:
            return
        attrs = sorted((k, v) for k, v in el.attrib.items() if k not in _VOLATILE_ATTRS)
        out.append([el.tag, attrs, " ".join((el.text or "").split())])
        for child in el:
            walk(child)
        out.append(None)

    walk(root)
    return hashlib.sha256(json.dumps(out, separators=(",", ":")).encode("utf-8")).hexdigest()


def cert_fingerprint(certificate_pem: str | None) -> str | None:
    if not certificate_pem:
        return None
    return hashlib.sha256("".join(certificate_pem.split()).encode("ascii", "ignore")).hexdigest()


def spid_entity_id(hostname: str) -> str:
    """entityID del metadata SP, come lo calcola satosa_config_generator."""
    from app.satosa_config_generator import _base_url

    return f"{_base_url(hostname)}/spidSaml2/metadata"


def _display(field_name: str, value) -> str:
    if isinstance(value, bool):
        return "on" if value else "off"
    if field_name == "eidas_environment":
        return {"prod": "produzione", "qa": "collaudo (QA)"}.get(value, value or "—")
    return value if value not in (None, "") else "—"


@dataclass
class Difference:
    label: str
    current: str
    validated: str


@dataclass
class ProfileStatus:
    profile: SpidMetadataProfile | None
    differences: list[Difference] = field(default_factory=list)
    # None = non determinabile (nessun metadata generato o profilo senza impronta)
    document_matches: bool | None = None
    latest_version: SpidMetadataVersion | None = None
    cert_restorable: bool = True
    entity_id_differs: bool = False

    @property
    def matches(self) -> bool:
        return self.profile is not None and not self.differences and self.document_matches is not False


async def _settings(db: AsyncSession) -> EnteSettings | None:
    return (await db.execute(select(EnteSettings).where(EnteSettings.id == 1))).scalar_one_or_none()


async def _active_cert(db: AsyncSession) -> SpidCert | None:
    return (await db.execute(select(SpidCert).where(SpidCert.is_active == True).limit(1))).scalar_one_or_none()  # noqa: E712


async def latest_generated_version(db: AsyncSession) -> SpidMetadataVersion | None:
    return (
        await db.execute(
            select(SpidMetadataVersion)
            .where(SpidMetadataVersion.source == "generated")
            .order_by(SpidMetadataVersion.id.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


async def validated_profile(db: AsyncSession) -> SpidMetadataProfile | None:
    return (
        await db.execute(
            select(SpidMetadataProfile)
            .where(SpidMetadataProfile.status == "validated")
            .order_by(SpidMetadataProfile.id.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


async def profile_status(db: AsyncSession, profile: SpidMetadataProfile | None = None) -> ProfileStatus:
    """Configurazione attuale vs profilo (default: il validato)."""
    if profile is None:
        profile = await validated_profile(db)
    latest = await latest_generated_version(db)
    status = ProfileStatus(profile=profile, latest_version=latest)
    if profile is None:
        return status

    settings = await _settings(db)
    for name, label in PROFILE_SETTINGS_FIELDS.items():
        current = getattr(settings, name, None) if settings else None
        expected = getattr(profile, name)
        if isinstance(expected, bool):
            differs = bool(current) != expected
        else:
            differs = (current or "") != (expected or "")
        if name == "eidas_environment" and not profile.eidas_enabled and not getattr(settings, "eidas_enabled", False):
            differs = False  # eIDAS spento in entrambi: l'ambiente non conta
        if differs:
            status.differences.append(Difference(label, _display(name, current), _display(name, expected)))

    cert = await _active_cert(db)
    if profile.cert_fingerprint and cert_fingerprint(cert.certificate_pem if cert else None) != profile.cert_fingerprint:
        status.differences.append(
            Difference(
                "Certificato",
                f"#{cert.id}" if cert else "—",
                f"#{profile.cert_id}" if profile.cert_id else "non più presente",
            )
        )
    status.cert_restorable = profile.cert_fingerprint is None or profile.cert_id is not None

    if settings is not None and profile.entity_id:
        current_entity_id = spid_entity_id(settings.proxy_hostname)
        if current_entity_id != profile.entity_id:
            status.entity_id_differs = True
            status.differences.append(Difference("Entity ID", current_entity_id, profile.entity_id))

    if latest is not None and profile.content_hash:
        status.document_matches = latest.content_hash == profile.content_hash
    return status


async def create_validated_profile(db: AsyncSession, label: str = "") -> SpidMetadataProfile:
    """Fotografa la configurazione attuale come profilo validato; archivia il precedente."""
    settings = await _settings(db)
    cert = await _active_cert(db)
    latest = await latest_generated_version(db)
    for old in (
        await db.execute(select(SpidMetadataProfile).where(SpidMetadataProfile.status == "validated"))
    ).scalars():
        old.status = "archived"
    profile = SpidMetadataProfile(
        label=label.strip(),
        status="validated",
        cert_id=cert.id if cert else None,
        cert_fingerprint=cert_fingerprint(cert.certificate_pem if cert else None),
        entity_id=spid_entity_id(settings.proxy_hostname) if settings else "",
        metadata_version_id=latest.id if latest else None,
        content_hash=latest.content_hash if latest else None,
        **{name: getattr(settings, name) for name in PROFILE_SETTINGS_FIELDS if settings is not None},
    )
    db.add(profile)
    await db.commit()
    return profile


class CertConfirmationRequired(Exception):
    """Il ripristino riattiverebbe un certificato diverso: serve conferma esplicita."""


class CertMissing(Exception):
    """Il certificato del profilo non è più nel DB."""


async def restore_profile(db: AsyncSession, profile: SpidMetadataProfile, confirm_cert: bool) -> bool:
    """Riapplica i parametri del profilo. True se il certificato attivo è cambiato.

    Non rigenera la config né ricarica SATOSA: lo fa il chiamante.
    """
    settings = await _settings(db)
    if settings is None:
        raise ValueError("Impostazioni ente assenti")

    cert = await _active_cert(db)
    target_cert = None
    if profile.cert_fingerprint and cert_fingerprint(cert.certificate_pem if cert else None) != profile.cert_fingerprint:
        if profile.cert_id is None:
            raise CertMissing()
        target_cert = (await db.execute(select(SpidCert).where(SpidCert.id == profile.cert_id))).scalar_one_or_none()
        if target_cert is None:
            raise CertMissing()
        if not confirm_cert:
            raise CertConfirmationRequired()

    for name in PROFILE_SETTINGS_FIELDS:
        setattr(settings, name, getattr(profile, name))
    # Stessa sincronizzazione del toggle eIDAS (routes/eidas.py): IdP FICEP
    # dell'ambiente scelto abilitato, l'altro no.
    for alias, env in (("eidas-qa", "qa"), ("eidas-prod", "prod")):
        idp = (await db.execute(select(SpidIdP).where(SpidIdP.alias == alias))).scalar_one_or_none()
        if idp:
            idp.enabled = profile.eidas_enabled and profile.eidas_environment == env

    if target_cert is not None:
        for c in (await db.execute(select(SpidCert))).scalars():
            c.is_active = c.id == target_cert.id
    await db.commit()

    if target_cert is not None:
        import asyncio

        from app.spid_cert_writer import write_spid_cert

        await asyncio.to_thread(write_spid_cert, target_cert)
    return target_cert is not None


def override_path() -> str:
    conf_dir = os.environ.get("SATOSA_CONF_DIR", "/satosa-conf")
    return os.path.join(conf_dir, "spid_sp_metadata_override.xml")


async def normalize_metadata_history(db: AsyncSession) -> None:
    """Allinea lo storico allo schema "profilo = parametri". Idempotente, all'avvio.

    1. Impronte ricalcolate con metadata_fingerprint (prima: hash del testo, che
       cambiava con i prefissi XML di pysaml2).
    2. Riga storica is_validated senza profilo validato → profilo dai suoi toggle
       e cert, dati ente attuali (lo storico non li aveva).
    3. File di override: tenuto solo se esposta una riga caricata a mano. Per le
       righe generate bloccava il metadata pubblicato su una versione vecchia.
    """
    versions = list((await db.execute(select(SpidMetadataVersion).order_by(SpidMetadataVersion.id))).scalars())
    for v in versions:
        fp = metadata_fingerprint(v.xml_content)
        if v.content_hash != fp:
            v.content_hash = fp
    await db.commit()

    if await validated_profile(db) is None:
        legacy = next((v for v in reversed(versions) if v.is_validated), None)
        if legacy is not None:
            settings = await _settings(db)
            cert = None
            if legacy.cert_id is not None:
                cert = (await db.execute(select(SpidCert).where(SpidCert.id == legacy.cert_id))).scalar_one_or_none()
            values = {name: getattr(settings, name) for name in PROFILE_SETTINGS_FIELDS if settings is not None}
            for name in ("eidas_enabled", "eidas_environment", "legal_entity_enabled"):
                if getattr(legacy, name) is not None:
                    values[name] = getattr(legacy, name)
            db.add(
                SpidMetadataProfile(
                    label=f"Migrato dallo storico (validato, generato il {legacy.created_at:%Y-%m-%d %H:%M})"
                    if legacy.created_at
                    else "Migrato dallo storico",
                    status="validated",
                    cert_id=cert.id if cert else None,
                    cert_fingerprint=cert_fingerprint(cert.certificate_pem) if cert else None,
                    entity_id=spid_entity_id(settings.proxy_hostname) if settings else "",
                    metadata_version_id=legacy.id,
                    content_hash=legacy.content_hash,
                    **values,
                )
            )
            await db.commit()
            logger.info("Profilo metadata validato creato dalla riga storica %s", legacy.id)

    uploaded_exposed = any(v.source == "uploaded" and v.is_exposed for v in versions)
    path = override_path()
    if not uploaded_exposed:
        if os.path.exists(path):
            try:
                os.remove(path)
                logger.warning("Rimosso %s: le righe generate non si espongono più", path)
            except OSError:
                logger.warning("Impossibile rimuovere %s", path, exc_info=True)
        for v in versions:
            if v.is_exposed:
                v.is_exposed = False
        await db.commit()
