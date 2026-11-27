"""IT-Wallet: segreti derivati deterministicamente da SATOSA_HASH_SALT."""
import hashlib
import hmac
import os


def derived_secret(label: str, length: int) -> str:
    """HMAC-SHA256(SATOSA_HASH_SALT, label) in hex, troncato a `length` caratteri (max 64).

    Mai salvato né letto da esempi upstream: si ricalcola a ogni generazione di config.
    """
    if not 0 < length <= 64:
        raise ValueError("length deve essere tra 1 e 64")
    salt = os.environ.get("SATOSA_HASH_SALT", "")
    if not salt:
        raise RuntimeError("SATOSA_HASH_SALT non impostata: impossibile derivare i segreti IT-Wallet")
    return hmac.new(salt.encode(), label.encode(), hashlib.sha256).hexdigest()[:length]
