import base64
import hashlib
import json
from typing import Literal

from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives.asymmetric import ec, rsa

from app.models import JwkKey


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _b64url_int(n: int) -> str:
    length = (n.bit_length() + 7) // 8
    return _b64url(n.to_bytes(length, byteorder="big"))


def _rfc7638_kid(e_b64: str, n_b64: str) -> str:
    """Compute JWK Thumbprint per RFC 7638: SHA-256 of canonical {"e","kty","n"}."""
    canonical = json.dumps({"e": e_b64, "kty": "RSA", "n": n_b64}, separators=(",", ":"), sort_keys=True)
    digest = hashlib.sha256(canonical.encode()).digest()
    return _b64url(digest)


def generate_jwk(name: str, use: str) -> JwkKey:
    """Generate RSA 4096 keypair as JWK. KID = RFC 7638 thumbprint."""
    private_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=4096,
        backend=default_backend(),
    )
    pub = private_key.public_key().public_numbers()
    priv = private_key.private_numbers()

    e_b64 = _b64url_int(pub.e)
    n_b64 = _b64url_int(pub.n)
    kid = _rfc7638_kid(e_b64, n_b64)

    # Formato interno SATOSA: include alg e use per routing corretto
    public_jwk = {
        "kty": "RSA",
        "alg": "RS256" if use in ("federation", "sig") else "RSA-OAEP",
        "use": use,
        "kid": kid,
        "e": e_b64,
        "n": n_b64,
    }
    private_jwk = {
        **public_jwk,
        "d": _b64url_int(priv.d),
        "p": _b64url_int(priv.p),
        "q": _b64url_int(priv.q),
        "dp": _b64url_int(priv.dmp1),
        "dq": _b64url_int(priv.dmq1),
        "qi": _b64url_int(priv.iqmp),
    }

    return JwkKey(name=name, use=use, private_jwk=private_jwk, public_jwk=public_jwk)


def generate_ec_jwk(name: str, use: Literal["federation", "sig", "enc"]) -> JwkKey:
    """Genera una coppia EC P-256. KID = thumbprint RFC 7638 su {crv,kty,x,y}.

    alg: ES256 per federation/sig, ECDH-ES per enc. La parte pubblica contiene
    solo kty/crv/x/y/kid/use/alg.
    """
    private_key = ec.generate_private_key(ec.SECP256R1())
    numbers = private_key.private_numbers()
    pub = numbers.public_numbers

    x_b64 = _b64url(pub.x.to_bytes(32, "big"))
    y_b64 = _b64url(pub.y.to_bytes(32, "big"))
    canonical = json.dumps(
        {"crv": "P-256", "kty": "EC", "x": x_b64, "y": y_b64}, separators=(",", ":"), sort_keys=True
    )
    kid = _b64url(hashlib.sha256(canonical.encode()).digest())

    public_jwk = {
        "kty": "EC",
        "crv": "P-256",
        "x": x_b64,
        "y": y_b64,
        "kid": kid,
        "use": use,
        "alg": "ECDH-ES" if use == "enc" else "ES256",
    }
    private_jwk = {**public_jwk, "d": _b64url(numbers.private_value.to_bytes(32, "big"))}
    return JwkKey(name=name, use=use, private_jwk=private_jwk, public_jwk=public_jwk)


def portal_jwk(jwk: dict) -> dict:
    """Formato portale CIE: solo parte pubblica kty/kid/e/n — senza alg/use.

    Il portale accetta la sola chiave pubblica: la privata non deve uscire dal proxy.
    """
    return {
        "kty": jwk["kty"],
        "kid": jwk["kid"],
        "e": jwk["e"],
        "n": jwk["n"],
    }
