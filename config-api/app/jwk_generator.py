import base64
import uuid

from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.backends import default_backend

from app.models import JwkKey


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _b64url_int(n: int) -> str:
    length = (n.bit_length() + 7) // 8
    return _b64url(n.to_bytes(length, byteorder="big"))


def generate_jwk(name: str, use: str) -> JwkKey:
    """Generate RSA 2048 keypair as JWK. Returns unsaved JwkKey instance."""
    private_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
        backend=default_backend(),
    )
    pub = private_key.public_key().public_numbers()
    priv = private_key.private_numbers()
    kid = str(uuid.uuid4())

    public_jwk = {
        "kty": "RSA",
        "alg": "RS256" if use in ("federation", "sig") else "RSA-OAEP-256",
        "use": use,
        "kid": kid,
        "n": _b64url_int(pub.n),
        "e": _b64url_int(pub.e),
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
