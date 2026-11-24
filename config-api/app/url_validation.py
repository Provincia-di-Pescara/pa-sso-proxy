"""Validazione degli URL configurati dall'admin che finiscono come href/src
in pagine pubbliche (discovery SATOSA, pagina d'errore, /verifica) e admin."""
from urllib.parse import urlsplit

_URL_MAX_LEN = 2048
_URL_FORBIDDEN = frozenset('\\<>"\'')


def valid_public_url(value: str) -> bool:
    if value == "":
        return True
    if len(value) > _URL_MAX_LEN or any(c.isspace() or c in _URL_FORBIDDEN for c in value):
        return False
    if value.startswith("/"):
        return not value.startswith("//")
    try:
        parts = urlsplit(value)
    except ValueError:
        return False
    return parts.scheme in ("https", "http") and bool(parts.hostname) and not parts.username
