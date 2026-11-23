"""Secret client OIDC cifrati a riposo e validazione delle redirect URI."""
import pytest
from sqlalchemy import select, text

from app import secret_box
from app.models import OIDCClient
from app.routes.clients import validate_redirect_uris


async def test_secret_encrypted_in_db_and_transparent(db_session):
    db_session.add(OIDCClient(client_id="c1", client_secret_hash="h", client_secret_plain="segreto-123",
                              name="C1", redirect_uris=["https://a.example/cb"], allowed_scopes=["openid"]))
    await db_session.commit()
    raw = (await db_session.execute(text("SELECT client_secret_plain FROM oidc_clients"))).scalar_one()
    assert raw.startswith(secret_box.PREFIX)
    assert "segreto-123" not in raw
    db_session.expire_all()
    c = (await db_session.execute(select(OIDCClient))).scalar_one()
    assert c.client_secret_plain == "segreto-123"


async def test_legacy_plaintext_rows_encrypted_at_startup(db_session):
    engine = db_session.bind
    await db_session.execute(text(
        "INSERT INTO oidc_clients (client_id, client_secret_hash, client_secret_plain, name, redirect_uris, "
        "allowed_scopes, enabled, allow_test_idps) VALUES ('old', 'h', 'vecchio-chiaro', 'Old', '[]', '[]', 1, 0)"
    ))
    await db_session.commit()
    assert await secret_box.encrypt_legacy_rows(engine) == 1
    assert await secret_box.encrypt_legacy_rows(engine) == 0  # idempotente
    raw = (await db_session.execute(text("SELECT client_secret_plain FROM oidc_clients"))).scalar_one()
    assert raw.startswith(secret_box.PREFIX)
    db_session.expire_all()
    assert (await db_session.execute(select(OIDCClient))).scalar_one().client_secret_plain == "vecchio-chiaro"


def test_wrong_salt_fails_loudly(monkeypatch):
    token = secret_box.encrypt("x")
    monkeypatch.setenv("SATOSA_HASH_SALT", "altro")
    with pytest.raises(secret_box.SecretBoxError, match="SATOSA_HASH_SALT"):
        secret_box.decrypt(token)


def test_missing_salt_fails(monkeypatch):
    monkeypatch.delenv("SATOSA_HASH_SALT")
    with pytest.raises(secret_box.SecretBoxError):
        secret_box.encrypt("x")


@pytest.mark.parametrize("uris", [
    ["https://app.ente.it/callback"],
    ["https://app.ente.it:8443/cb?x=1", "https://altra.ente.it/cb"],
    ["http://localhost:3000/cb"],
    ["http://127.0.0.1/cb"],
    ["http://[::1]:8080/cb"],
])
def test_redirect_uris_ok(uris):
    assert validate_redirect_uris(uris) is None


@pytest.mark.parametrize("uri", [
    "http://app.ente.it/cb",
    "javascript:alert(1)",
    "data:text/html,x",
    "app.ente.it/cb",
    "https:///cb",
    "https://*.ente.it/cb",
    "https://app.ente.it/cb#frag",
    "https://user:pw@app.ente.it/cb",
    "https://app.ente.it:99999/cb",
    "https://app.ente.it/c b",
    "http://localhost.evil.example/cb",
    "custom-scheme://cb",
])
def test_redirect_uris_rejected(uri):
    assert validate_redirect_uris([uri]) is not None


def test_redirect_uris_empty():
    assert validate_redirect_uris([]) is not None
