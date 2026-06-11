import base64
import hashlib
import json

from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives.asymmetric import rsa

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


def portal_jwk(private_jwk: dict) -> dict:
    """Formato portale CIE: solo kty/kid/e/n/d/p/q/dp/dq/qi — senza alg/use."""
    return {
        "kty": private_jwk["kty"],
        "kid": private_jwk["kid"],
        "e": private_jwk["e"],
        "n": private_jwk["n"],
        "d": private_jwk["d"],
        "p": private_jwk["p"],
        "q": private_jwk["q"],
        "dp": private_jwk["dp"],
        "dq": private_jwk["dq"],
        "qi": private_jwk["qi"],
    }
