"""Filtri per i log di accesso di uvicorn."""
import logging

# Healthcheck del container config-api (ogni 10 s) e di nginx (ogni 30 s):
# una riga di log a testa, nessuna informazione utile.
_QUIET_PATHS = frozenset({"/health"})


class HealthcheckAccessFilter(logging.Filter):
    """Scarta dal log `uvicorn.access` le GET /health andate a buon fine.

    Gli argomenti del record uvicorn sono (client, metodo, path, http, status):
    un /health con status diverso da 200 resta nel log (serve a capire
    perché il container è unhealthy).
    """

    def filter(self, record: logging.LogRecord) -> bool:
        args = record.args
        if not isinstance(args, tuple) or len(args) < 5:
            return True
        _, method, path, _, status = args[:5]
        return not (method == "GET" and path in _QUIET_PATHS and status == 200)


def install() -> None:
    """Idempotente: uvicorn configura i suoi logger prima di importare l'app."""
    access = logging.getLogger("uvicorn.access")
    if not any(isinstance(f, HealthcheckAccessFilter) for f in access.filters):
        access.addFilter(HealthcheckAccessFilter())
