"""Cifratura del bundle di backup (chiave privata SPID, JWK CIE, secret client).

Formato (JSON, così si riconosce a colpo d'occhio e resta versionabile):

    {"format": "pa-sso-proxy-backup", "enc": 1,
     "kdf": {"name": "scrypt", "n": 131072, "r": 8, "p": 1, "salt": <b64>},
     "nonce": <b64>, "ciphertext": <b64>}

Chiave AES-256-GCM derivata dalla passphrase con scrypt; header (format, enc,
kdf) come dati autenticati: un parametro alterato fa fallire la decifratura.
I backup in chiaro NON sono accettati (decisione: niente chiavi private in
file leggibili, anche a costo di invalidare i backup precedenti).
"""
from __future__ import annotations

import base64
import json
import os

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

FORMAT = "pa-sso-proxy-backup"
ENC_VERSION = 1
MIN_PASSPHRASE_LEN = 16

# ~128 MiB e qualche centinaio di ms per tentativo: rende costoso il brute force
# offline di un file rubato.
SCRYPT_N = 2 ** 17
SCRYPT_R = 8
SCRYPT_P = 1
# Limiti sui parametri letti da un file caricato (evita file costruiti per
# esaurire memoria/CPU di config-api).
_MAX_N = 2 ** 20
_MAX_R = 16
_MAX_P = 4


class BackupCryptoError(ValueError):
    """Messaggio adatto a essere mostrato all'amministratore."""


def _b64e(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def _b64d(value: object, field: str) -> bytes:
    if not isinstance(value, str):
        raise BackupCryptoError(f"Backup non valido: campo {field} mancante")
    try:
        return base64.b64decode(value, validate=True)
    except ValueError as exc:
        raise BackupCryptoError(f"Backup non valido: campo {field} non base64") from exc


def _derive(passphrase: str, salt: bytes, n: int, r: int, p: int) -> bytes:
    return Scrypt(salt=salt, length=32, n=n, r=r, p=p).derive(passphrase.encode("utf-8"))


def _aad(header: dict) -> bytes:
    return json.dumps(header, sort_keys=True, separators=(",", ":")).encode("utf-8")


def check_passphrase(passphrase: str, confirm: str | None = None) -> None:
    if len(passphrase) < MIN_PASSPHRASE_LEN:
        raise BackupCryptoError(f"La passphrase deve avere almeno {MIN_PASSPHRASE_LEN} caratteri")
    if confirm is not None and passphrase != confirm:
        raise BackupCryptoError("Le due passphrase non coincidono")


def encrypt_bundle(bundle: dict, passphrase: str) -> bytes:
    check_passphrase(passphrase)
    salt = os.urandom(16)
    nonce = os.urandom(12)
    header = {
        "format": FORMAT,
        "enc": ENC_VERSION,
        "kdf": {"name": "scrypt", "n": SCRYPT_N, "r": SCRYPT_R, "p": SCRYPT_P, "salt": _b64e(salt)},
    }
    key = _derive(passphrase, salt, SCRYPT_N, SCRYPT_R, SCRYPT_P)
    plaintext = json.dumps(bundle, ensure_ascii=False).encode("utf-8")
    ciphertext = AESGCM(key).encrypt(nonce, plaintext, _aad(header))
    envelope = dict(header, nonce=_b64e(nonce), ciphertext=_b64e(ciphertext))
    return json.dumps(envelope, indent=2).encode("utf-8")


def decrypt_bundle(raw: bytes, passphrase: str) -> dict:
    try:
        envelope = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BackupCryptoError("File non valido: non è un backup JSON") from exc
    if not isinstance(envelope, dict) or envelope.get("format") != FORMAT:
        if isinstance(envelope, dict) and "version" in envelope and "oidc_clients" in envelope:
            raise BackupCryptoError(
                "Backup in chiaro non più accettato: esporta un nuovo backup cifrato "
                "e distruggi le copie in chiaro (contengono chiavi private)"
            )
        raise BackupCryptoError("File non valido: non è un backup di PA SSO Proxy")
    if envelope.get("enc") != ENC_VERSION:
        raise BackupCryptoError(f"Versione di cifratura non supportata: {envelope.get('enc')!r}")
    kdf = envelope.get("kdf")
    if not isinstance(kdf, dict) or kdf.get("name") != "scrypt":
        raise BackupCryptoError("Backup non valido: KDF non supportata")
    n, r, p = kdf.get("n"), kdf.get("r"), kdf.get("p")
    if not all(isinstance(v, int) and not isinstance(v, bool) for v in (n, r, p)) \
            or not (2 <= n <= _MAX_N and n & (n - 1) == 0 and 1 <= r <= _MAX_R and 1 <= p <= _MAX_P):
        raise BackupCryptoError("Backup non valido: parametri KDF fuori dai limiti")
    salt = _b64d(kdf.get("salt"), "salt")
    nonce = _b64d(envelope.get("nonce"), "nonce")
    ciphertext = _b64d(envelope.get("ciphertext"), "ciphertext")
    if len(nonce) != 12:
        raise BackupCryptoError("Backup non valido: nonce")
    header = {"format": envelope["format"], "enc": envelope["enc"], "kdf": kdf}
    key = _derive(passphrase, salt, n, r, p)
    try:
        plaintext = AESGCM(key).decrypt(nonce, ciphertext, _aad(header))
    except InvalidTag as exc:
        raise BackupCryptoError("Passphrase errata o file alterato") from exc
    bundle = json.loads(plaintext.decode("utf-8"))
    if not isinstance(bundle, dict):
        raise BackupCryptoError("Backup non valido: contenuto inatteso")
    return bundle
