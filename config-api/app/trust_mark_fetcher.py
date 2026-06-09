import base64
import json
import logging

import httpx

logger = logging.getLogger(__name__)

# Registry CIE centralizzato — stesso URL per prod e collaudo.
_REGISTRY_FETCH_URL = "https://oidc.registry.servizicie.interno.gov.it/fetch"


def _decode_jwt_payload(token: str) -> dict:
    parts = token.split(".")
    if len(parts) < 2:
        raise ValueError("not a JWS")
    padded = parts[1] + "==" * (-len(parts[1]) % 4)
    return json.loads(base64.urlsafe_b64decode(padded))


def _extract_trust_mark(payload: dict) -> tuple[str, str] | None:
    """Return (trust_mark_id, trust_mark_jwt) from entity statement payload, or None."""
    tms = payload.get("trust_marks", [])
    if not tms:
        return None
    tm = tms[0]
    if isinstance(tm, dict):
        tm_id = tm.get("id", "")
        tm_jwt = tm.get("trust_mark", "")
    else:
        # tm è una stringa JWS — id è nel suo payload
        inner = _decode_jwt_payload(tm)
        tm_id = inner.get("id", "")
        tm_jwt = tm
    if tm_id and tm_jwt:
        return tm_id, tm_jwt
    return None


async def fetch_trust_mark(client_id: str) -> tuple[str, str] | None:
    """
    Fetch trust mark from CIE central registry for the given client_id (sub).
    Returns (trust_mark_id, trust_mark_jwt) or None on failure.
    """
    url = f"{_REGISTRY_FETCH_URL}?iss={_REGISTRY_FETCH_URL.split('/fetch')[0]}&sub={client_id}"
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            payload = _decode_jwt_payload(resp.text.strip())
            result = _extract_trust_mark(payload)
            if result:
                logger.info("Trust mark ottenuto per %s (id: %s)", client_id, result[0])
            else:
                logger.warning("Registry CIE non contiene trust_marks per %s", client_id)
            return result
    except Exception:
        logger.warning("Fetch trust mark fallito per %s", client_id, exc_info=True)
        return None
