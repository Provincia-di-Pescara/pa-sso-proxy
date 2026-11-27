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
    assert pub["kty"] == "RSA"
    assert "n" in pub
    assert "e" in pub
    assert "kid" in pub
    assert pub["use"] == "sig"
    assert pub["alg"] == "RS256"
    assert "d" not in pub


def test_generate_jwk_enc_alg():
    from app.jwk_generator import generate_jwk
    key = generate_jwk("test-enc", "enc")
    assert key.public_jwk["alg"] == "RSA-OAEP"
    assert key.public_jwk["kty"] == "RSA"


def test_generate_jwk_private_jwk_has_rsa_params():
    from app.jwk_generator import generate_jwk
    key = generate_jwk("test-enc", "enc")
    priv = key.private_jwk
    assert priv["kty"] == "RSA"
    for field in ("d", "p", "q", "dp", "dq", "qi"):
        assert field in priv, f"missing {field}"


def test_portal_jwk_public_only():
    from app.jwk_generator import generate_jwk, portal_jwk
    key = generate_jwk("test-fed", "federation")
    out = portal_jwk(key.public_jwk)
    assert set(out) == {"kty", "kid", "e", "n"}
    assert out["kid"] == key.private_jwk["kid"]
    assert out["n"] == key.private_jwk["n"]
    # Anche se riceve la privata, non deve mai esportarne i parametri
    assert set(portal_jwk(key.private_jwk)) == {"kty", "kid", "e", "n"}


def test_ec_jwk_public_has_no_private_fields():
    from app.jwk_generator import generate_ec_jwk
    for use, alg in (("federation", "ES256"), ("sig", "ES256"), ("enc", "ECDH-ES")):
        key = generate_ec_jwk(f"ec-{use}", use)
        assert isinstance(key, JwkKey)
        assert key.use == use
        assert set(key.public_jwk) == {"kty", "crv", "x", "y", "kid", "use", "alg"}
        assert key.public_jwk["kty"] == "EC"
        assert key.public_jwk["crv"] == "P-256"
        assert key.public_jwk["alg"] == alg
        assert key.public_jwk["use"] == use
        assert "d" not in key.public_jwk
        assert "d" in key.private_jwk
        assert {k: key.private_jwk[k] for k in key.public_jwk} == key.public_jwk


def test_ec_jwk_kid_is_rfc7638():
    import base64
    import hashlib
    from app.jwk_generator import generate_ec_jwk
    key = generate_ec_jwk("ec-kid", "sig")
    pub = key.public_jwk
    # Calcolo a mano: SHA-256 del JSON canonico con membri in ordine lessicografico.
    canonical = '{"crv":"P-256","kty":"EC","x":"%s","y":"%s"}' % (pub["x"], pub["y"])
    expected = base64.urlsafe_b64encode(hashlib.sha256(canonical.encode()).digest()).rstrip(b"=").decode()
    assert pub["kid"] == expected
    assert len(base64.urlsafe_b64decode(pub["x"] + "==")) == 32
    assert len(base64.urlsafe_b64decode(pub["y"] + "==")) == 32
