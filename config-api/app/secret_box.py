"""Cifratura a riposo dei secret dei client OIDC (colonna client_secret_plain).

SATOSA confronta il client_secret in chiaro, quindi config-api deve poterlo
rileggere: niente hash, ma cifratura. Così un dump del DB (backup di
postgres, volume copiato, lettura SQL) non espone i secret degli applicativi.
Il file YAML generato per SATOSA in /satosa-conf resta in chiaro per forza
(volume accessibile solo a uid 10001).

Chiave: HKDF-SHA256 da SATOSA_HASH_SALT, che non si cambia mai su
un'istanza esistente (cambierebbe anche gli hash dei CF nei log e il secret di
__spid_verifica__). Valori senza prefisso = righe precedenti in chiaro:
lette così come sono e cifrate all'avvio da encrypt_legacy_rows().
"""
from __future__ import annotations

import base64
import os

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from sqlalchemy import String, inspect, text
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlalchemy.types import TypeDecorator

PREFIX = "enc:v1:"
_INFO = b"pa-sso-proxy/oidc-client-secret/v1"


class SecretBoxError(RuntimeError):
    pass


def _fernet() -> Fernet:
    salt = os.environ.get("SATOSA_HASH_SALT", "")
    if not salt:
        raise SecretBoxError("SATOSA_HASH_SALT non impostata: impossibile cifrare i secret dei client")
    key = HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=_INFO).derive(salt.encode())
    return Fernet(base64.urlsafe_b64encode(key))


def encrypt(value: str) -> str:
    return PREFIX + _fernet().encrypt(value.encode()).decode()


def decrypt(value: str) -> str:
    if not value.startswith(PREFIX):
        return value  # riga precedente alla cifratura
    try:
        return _fernet().decrypt(value[len(PREFIX):].encode()).decode()
    except InvalidToken as exc:
        raise SecretBoxError(
            "Secret client OIDC non decifrabile: SATOSA_HASH_SALT è cambiata?"
        ) from exc


class EncryptedString(TypeDecorator):
    """Colonna stringa cifrata in modo trasparente (stesso tipo SQL di prima)."""

    impl = String
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None or value.startswith(PREFIX):
            return value
        return encrypt(value)

    def process_result_value(self, value, dialect):
        return None if value is None else decrypt(value)


async def encrypt_legacy_rows(engine: AsyncEngine) -> int:
    """Cifra i client_secret_plain ancora in chiaro (idempotente)."""
    async with engine.begin() as conn:
        has_table = await conn.run_sync(lambda c: inspect(c).has_table("oidc_clients"))
        if not has_table:
            return 0
        rows = (await conn.execute(text(
            "SELECT id, client_secret_plain FROM oidc_clients WHERE client_secret_plain IS NOT NULL"
        ))).all()
        count = 0
        for row_id, value in rows:
            if value.startswith(PREFIX):
                continue
            await conn.execute(
                text("UPDATE oidc_clients SET client_secret_plain = :v WHERE id = :id"),
                {"v": encrypt(value), "id": row_id},
            )
            count += 1
        return count
