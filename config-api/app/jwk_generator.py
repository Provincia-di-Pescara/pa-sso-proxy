import base64
import uuid

from cryptography.hazmat.primitives.asymmetric import ec

from app.models import JwkKey


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _b64url_int(n: int, length: int = 32) -> str:
    return _b64url(n.to_bytes(length, byteorder="big"))


def generate_jwk(name: str, use: str) -> JwkKey:
    """Generate EC P-256 keypair as JWK. Returns unsaved JwkKey instance."""
    private_key = ec.generate_private_key(ec.SECP256R1())
    pub = private_key.public_key().public_numbers()
    priv = private_key.private_numbers()
    kid = str(uuid.uuid4())

    public_jwk = {
        "kty": "EC",
        "crv": "P-256",
        "x": _b64url_int(pub.x),
        "y": _b64url_int(pub.y),
        "use": use,
        "kid": kid,
    }
    private_jwk = {**public_jwk, "d": _b64url_int(priv.private_value)}

    return JwkKey(name=name, use=use, private_jwk=private_jwk, public_jwk=public_jwk)
