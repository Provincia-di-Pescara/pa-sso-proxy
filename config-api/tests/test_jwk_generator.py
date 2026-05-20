from app.models import JwkKey


def test_generate_jwk_returns_jwk_key_instance():
    from app.jwk_generator import generate_jwk
    key = generate_jwk("test-key", "sig")
    assert isinstance(key, JwkKey)
    assert key.name == "test-key"
    assert key.use == "sig"


def test_generate_jwk_public_jwk_format():
    from app.jwk_generator import generate_jwk
    key = generate_jwk("test-sig", "sig")
    pub = key.public_jwk
    assert pub["kty"] == "EC"
    assert pub["crv"] == "P-256"
    assert "x" in pub
    assert "y" in pub
    assert "kid" in pub
    assert pub["use"] == "sig"
    assert "d" not in pub


def test_generate_jwk_private_jwk_has_d():
    from app.jwk_generator import generate_jwk
    key = generate_jwk("test-enc", "enc")
    assert "d" in key.private_jwk
    assert key.private_jwk["kty"] == "EC"
