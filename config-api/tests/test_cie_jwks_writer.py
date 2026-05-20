import json
from app.models import JwkKey


def test_write_jwks_creates_files(tmp_path, monkeypatch):
    monkeypatch.setenv("SATOSA_CONF_DIR", str(tmp_path))

    keys = [
        JwkKey(
            name="k1", use="sig",
            public_jwk={"kty": "EC", "kid": "abc", "use": "sig"},
            private_jwk={"kty": "EC", "kid": "abc", "use": "sig", "d": "xxx"},
        ),
    ]

    from app.cie_jwks_writer import write_jwks_files
    write_jwks_files(keys)

    pub_path = tmp_path / "cie_jwks_public.json"
    priv_path = tmp_path / "cie_jwks_private.json"
    assert pub_path.exists()
    assert priv_path.exists()

    pub_data = json.loads(pub_path.read_text())
    priv_data = json.loads(priv_path.read_text())
    assert pub_data == {"keys": [{"kty": "EC", "kid": "abc", "use": "sig"}]}
    assert priv_data == {"keys": [{"kty": "EC", "kid": "abc", "use": "sig", "d": "xxx"}]}


def test_write_jwks_empty_keys(tmp_path, monkeypatch):
    monkeypatch.setenv("SATOSA_CONF_DIR", str(tmp_path))

    from app.cie_jwks_writer import write_jwks_files
    write_jwks_files([])

    pub_data = json.loads((tmp_path / "cie_jwks_public.json").read_text())
    assert pub_data == {"keys": []}
