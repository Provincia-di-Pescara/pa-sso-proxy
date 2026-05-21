import pytest
import pytest_asyncio
import yaml

from app.models import CieConfig, EnteSettings, JwkKey, SpidIdP


@pytest_asyncio.fixture
async def full_db(db_session):
    s = EnteSettings(
        id=1,
        proxy_hostname="proxy.ente.it",
        org_name="Ente Test",
        org_display_name="Ente Test SPA",
        org_url="https://ente.it",
        ipa_code="P_TEST",
        contact_email="e@ente.it",
        contact_phone="+39001",
        org_city="Roma",
    )
    idp = SpidIdP(
        alias="spid-aruba",
        display_name="Aruba PEC",
        metadata_url="https://loginspid.aruba.it/metadata",
        enabled=True,
    )
    jwk = JwkKey(
        name="cie-sig-abc",
        use="sig",
        private_jwk={"kty": "EC"},
        public_jwk={"kty": "EC"},
    )
    db_session.add_all([s, idp, jwk])
    await db_session.commit()
    return db_session


async def test_proxy_yaml_base(full_db, tmp_path, monkeypatch):
    monkeypatch.setenv("SATOSA_CONF_DIR", str(tmp_path))
    from app.satosa_config_generator import generate_satosa_config
    await generate_satosa_config(full_db)
    proxy = yaml.safe_load((tmp_path / "proxy.yaml").read_text())
    assert proxy["BASE"] == "https://proxy.ente.it"


async def test_proxy_yaml_has_three_plugins(full_db, tmp_path, monkeypatch):
    monkeypatch.setenv("SATOSA_CONF_DIR", str(tmp_path))
    from app.satosa_config_generator import generate_satosa_config
    await generate_satosa_config(full_db)
    proxy = yaml.safe_load((tmp_path / "proxy.yaml").read_text())
    plugin_names = [p["name"] for p in proxy["PLUGIN"]]
    assert "oidc_frontend" in plugin_names
    assert "spid_backend" in plugin_names
    assert "cie_saml_backend" in plugin_names


async def test_oidc_frontend_yaml_issuer(full_db, tmp_path, monkeypatch):
    monkeypatch.setenv("SATOSA_CONF_DIR", str(tmp_path))
    from app.satosa_config_generator import generate_satosa_config
    await generate_satosa_config(full_db)
    frontend = yaml.safe_load((tmp_path / "oidc_frontend.yaml").read_text())
    assert frontend["issuer"] == "https://proxy.ente.it"


async def test_spid_backend_yaml_has_idp_metadata(full_db, tmp_path, monkeypatch):
    monkeypatch.setenv("SATOSA_CONF_DIR", str(tmp_path))
    from app.satosa_config_generator import generate_satosa_config
    await generate_satosa_config(full_db)
    spid = yaml.safe_load((tmp_path / "spid_backend.yaml").read_text())
    urls = [r["url"] for r in spid["metadata"]["remote"]]
    assert "https://loginspid.aruba.it/metadata" in urls


async def test_no_generation_without_settings(db_session, tmp_path, monkeypatch):
    monkeypatch.setenv("SATOSA_CONF_DIR", str(tmp_path))
    from app.satosa_config_generator import generate_satosa_config
    await generate_satosa_config(db_session)
    assert not (tmp_path / "proxy.yaml").exists()


async def test_no_generation_without_hostname(db_session, tmp_path, monkeypatch):
    monkeypatch.setenv("SATOSA_CONF_DIR", str(tmp_path))
    s = EnteSettings(
        id=1, proxy_hostname="", org_name="", org_display_name="",
        org_url="", ipa_code="", contact_email="", contact_phone="", org_city=""
    )
    db_session.add(s)
    await db_session.commit()
    from app.satosa_config_generator import generate_satosa_config
    await generate_satosa_config(db_session)
    assert not (tmp_path / "proxy.yaml").exists()
