import pytest
import yaml
from app.models import OIDCClient


async def test_generate_writes_yaml(db_session, tmp_path, monkeypatch):
    monkeypatch.setenv("SATOSA_CONF_DIR", str(tmp_path))

    c = OIDCClient(
        client_id="myapp",
        client_secret_hash="$2b$12$fakehash",
        name="My App",
        redirect_uris=["https://myapp.test/cb"],
        allowed_scopes=["openid", "profile"],
        enabled=True,
    )
    db_session.add(c)
    await db_session.commit()

    from app.satosa_generator import generate_and_write
    await generate_and_write(db_session)

    out = tmp_path / "oidcop_clients.yaml"
    assert out.exists()
    data = yaml.safe_load(out.read_text())
    assert "myapp" in data["OIDCOP"]["clients"]
    assert data["OIDCOP"]["clients"]["myapp"]["redirect_uris"] == ["https://myapp.test/cb"]
    assert data["OIDCOP"]["clients"]["myapp"]["client_secret"] == "{bcrypt}$2b$12$fakehash"


async def test_generate_excludes_disabled_clients(db_session, tmp_path, monkeypatch):
    monkeypatch.setenv("SATOSA_CONF_DIR", str(tmp_path))

    c = OIDCClient(
        client_id="disabled-app",
        client_secret_hash="hash",
        name="Disabled",
        redirect_uris=["https://x.test/cb"],
        allowed_scopes=["openid"],
        enabled=False,
    )
    db_session.add(c)
    await db_session.commit()

    from app.satosa_generator import generate_and_write
    await generate_and_write(db_session)

    out = tmp_path / "oidcop_clients.yaml"
    data = yaml.safe_load(out.read_text())
    assert "disabled-app" not in data["OIDCOP"]["clients"]


async def test_generate_empty_clients(db_session, tmp_path, monkeypatch):
    monkeypatch.setenv("SATOSA_CONF_DIR", str(tmp_path))

    from app.satosa_generator import generate_and_write
    await generate_and_write(db_session)

    out = tmp_path / "oidcop_clients.yaml"
    data = yaml.safe_load(out.read_text())
    assert data["OIDCOP"]["clients"] == {}
