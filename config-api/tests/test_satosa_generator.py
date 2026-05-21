import pytest
import pytest_asyncio
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


@pytest_asyncio.fixture
async def settings_for_gen(db_session):
    from app.models import EnteSettings
    s = EnteSettings(
        id=1, proxy_hostname="proxy.ente.it", org_name="Ente", org_display_name="Ente",
        org_url="https://ente.it", ipa_code="P_TEST", contact_email="e@e.it",
        contact_phone="0", org_city="Roma",
    )
    db_session.add(s)
    await db_session.commit()
    return db_session


async def test_generate_and_write_also_writes_satosa_config(settings_for_gen, tmp_path, monkeypatch):
    monkeypatch.setenv("SATOSA_CONF_DIR", str(tmp_path))
    from app.satosa_generator import generate_and_write
    await generate_and_write(settings_for_gen)
    assert (tmp_path / "oidcop_clients.yaml").exists()
    assert (tmp_path / "proxy.yaml").exists()
    assert (tmp_path / "oidc_frontend.yaml").exists()
