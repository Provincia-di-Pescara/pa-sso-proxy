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


async def test_proxy_yaml_uses_backend_modules_format(full_db, tmp_path, monkeypatch):
    monkeypatch.setenv("SATOSA_CONF_DIR", str(tmp_path))
    from app.satosa_config_generator import generate_satosa_config
    await generate_satosa_config(full_db)
    proxy = yaml.safe_load((tmp_path / "proxy.yaml").read_text())
    assert "PLUGIN" not in proxy
    assert "BACKEND_MODULES" in proxy
    assert "FRONTEND_MODULES" in proxy
    assert "/satosa-conf/spid_backend.yaml" in proxy["BACKEND_MODULES"]
    assert "/satosa-conf/cie_saml_backend.yaml" in proxy["BACKEND_MODULES"]
    assert "/satosa-conf/oidc_frontend.yaml" in proxy["FRONTEND_MODULES"]


async def test_cie_oidc_not_in_backend_modules_when_disabled(full_db, tmp_path, monkeypatch):
    monkeypatch.setenv("SATOSA_CONF_DIR", str(tmp_path))
    from app.satosa_config_generator import generate_satosa_config
    await generate_satosa_config(full_db)
    proxy = yaml.safe_load((tmp_path / "proxy.yaml").read_text())
    assert "/satosa-conf/cie_oidc_backend.yaml" not in proxy["BACKEND_MODULES"]
    assert not (tmp_path / "cie_oidc_backend.yaml").exists()


async def test_cie_oidc_backend_yaml_generated_when_enabled(db_session, tmp_path, monkeypatch):
    monkeypatch.setenv("SATOSA_CONF_DIR", str(tmp_path))
    from app.models import EnteSettings, CieConfig, JwkKey, SpidIdP

    s = EnteSettings(
        id=1, proxy_hostname="proxy.ente.it", org_name="Ente", org_display_name="Ente Test",
        org_url="https://ente.it", ipa_code="P_T", contact_email="e@ente.it",
        contact_phone="+39001", org_city="Roma",
    )
    idp = SpidIdP(alias="spid-aruba", display_name="Aruba", metadata_url="https://aruba/meta", enabled=True)
    fed_key = JwkKey(name="cie-fed", use="federation",
                     private_jwk={"kty": "EC", "crv": "P-256", "kid": "fed1"},
                     public_jwk={"kty": "EC"})
    sig_key = JwkKey(name="cie-sig", use="sig",
                     private_jwk={"kty": "EC", "crv": "P-256", "kid": "sig1"},
                     public_jwk={"kty": "EC"})
    enc_key = JwkKey(name="cie-enc", use="enc",
                     private_jwk={"kty": "EC", "crv": "P-256", "kid": "enc1"},
                     public_jwk={"kty": "EC"})
    db_session.add_all([s, idp, fed_key, sig_key, enc_key])
    await db_session.commit()
    await db_session.refresh(fed_key)
    await db_session.refresh(sig_key)
    await db_session.refresh(enc_key)

    cie = CieConfig(
        id=1,
        saml_metadata_url="https://idserver.servizicie.interno.gov.it/idp/shibboleth?Metadata",
        client_id="https://proxy.ente.it/CieOidcRp",
        oidc_federation_enabled=True,
        oidc_provider_url="https://preprod.oidc.interno.gov.it",
        trust_anchor_url="https://registry.cie.gov.it",
        authority_hint_url="https://registry.cie.gov.it",
        trust_mark_id="https://registry.cie.gov.it/tm/rp",
        trust_mark="eyJhbGciOiJFUzI1NiJ9.stub.sig",
        oidc_contact_email="admin@ente.it",
        jwk_federation_id=fed_key.id,
        jwk_core_sig_id=sig_key.id,
        jwk_core_enc_id=enc_key.id,
    )
    db_session.add(cie)
    await db_session.commit()

    from app.satosa_config_generator import generate_satosa_config
    await generate_satosa_config(db_session)

    proxy = yaml.safe_load((tmp_path / "proxy.yaml").read_text())
    assert "/satosa-conf/cie_oidc_backend.yaml" in proxy["BACKEND_MODULES"]

    cie_yaml = yaml.safe_load((tmp_path / "cie_oidc_backend.yaml").read_text())
    assert cie_yaml["module"] == "backends.cieoidc.CieOidcBackend"
    assert cie_yaml["config"]["providers"] == ["https://preprod.oidc.interno.gov.it"]
    assert cie_yaml["config"]["jwks"]["federation"] == [{"kty": "EC", "crv": "P-256", "kid": "fed1"}]
    assert "entity_config_endpoint" in cie_yaml["config"]["endpoints"]
    assert "authorization_endpoint" in cie_yaml["config"]["endpoints"]
    assert "authorization_callback_endpoint" in cie_yaml["config"]["endpoints"]


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


async def test_cie_oidc_not_generated_when_flag_false(db_session, tmp_path, monkeypatch):
    monkeypatch.setenv("SATOSA_CONF_DIR", str(tmp_path))
    from app.models import EnteSettings, CieConfig, JwkKey, SpidIdP

    s = EnteSettings(
        id=1, proxy_hostname="proxy.ente.it", org_name="Ente", org_display_name="Ente Test",
        org_url="https://ente.it", ipa_code="P_T", contact_email="e@ente.it",
        contact_phone="+39001", org_city="Roma",
    )
    idp = SpidIdP(alias="spid-aruba", display_name="Aruba", metadata_url="https://aruba/meta", enabled=True)
    fed_key = JwkKey(name="cie-fed2", use="federation",
                     private_jwk={"kty": "EC", "crv": "P-256", "kid": "fed2"},
                     public_jwk={"kty": "EC"})
    sig_key = JwkKey(name="cie-sig2", use="sig",
                     private_jwk={"kty": "EC", "crv": "P-256", "kid": "sig2"},
                     public_jwk={"kty": "EC"})
    enc_key = JwkKey(name="cie-enc2", use="enc",
                     private_jwk={"kty": "EC", "crv": "P-256", "kid": "enc2"},
                     public_jwk={"kty": "EC"})
    db_session.add_all([s, idp, fed_key, sig_key, enc_key])
    await db_session.commit()
    await db_session.refresh(fed_key)
    await db_session.refresh(sig_key)
    await db_session.refresh(enc_key)

    cie = CieConfig(
        id=1,
        saml_metadata_url="https://idserver.servizicie.interno.gov.it/idp/shibboleth?Metadata",
        client_id="https://proxy.ente.it/CieOidcRp",
        oidc_federation_enabled=False,  # explicitly disabled
        oidc_provider_url="https://preprod.oidc.interno.gov.it",
        trust_anchor_url="https://registry.cie.gov.it",
        authority_hint_url="https://registry.cie.gov.it",
        trust_mark_id="https://registry.cie.gov.it/tm/rp",
        trust_mark="eyJhbGciOiJFUzI1NiJ9.stub.sig",
        jwk_federation_id=fed_key.id,
        jwk_core_sig_id=sig_key.id,
        jwk_core_enc_id=enc_key.id,
    )
    db_session.add(cie)
    await db_session.commit()

    from app.satosa_config_generator import generate_satosa_config
    await generate_satosa_config(db_session)

    proxy = yaml.safe_load((tmp_path / "proxy.yaml").read_text())
    assert "/satosa-conf/cie_oidc_backend.yaml" not in proxy["BACKEND_MODULES"]
    assert not (tmp_path / "cie_oidc_backend.yaml").exists()


async def test_cie_oidc_callback_claims_mapping(db_session, tmp_path, monkeypatch):
    monkeypatch.setenv("SATOSA_CONF_DIR", str(tmp_path))
    from app.models import EnteSettings, CieConfig, JwkKey, SpidIdP

    s = EnteSettings(
        id=1, proxy_hostname="proxy.ente.it", org_name="Ente", org_display_name="Ente Test",
        org_url="https://ente.it", ipa_code="P_T", contact_email="e@ente.it",
        contact_phone="+39001", org_city="Roma",
    )
    idp = SpidIdP(alias="spid-aruba", display_name="Aruba", metadata_url="https://aruba/meta", enabled=True)
    fed_key = JwkKey(name="cie-fed3", use="federation",
                     private_jwk={"kty": "EC", "crv": "P-256", "kid": "fed3"},
                     public_jwk={"kty": "EC"})
    sig_key = JwkKey(name="cie-sig3", use="sig",
                     private_jwk={"kty": "EC", "crv": "P-256", "kid": "sig3"},
                     public_jwk={"kty": "EC"})
    enc_key = JwkKey(name="cie-enc3", use="enc",
                     private_jwk={"kty": "EC", "crv": "P-256", "kid": "enc3"},
                     public_jwk={"kty": "EC"})
    db_session.add_all([s, idp, fed_key, sig_key, enc_key])
    await db_session.commit()
    await db_session.refresh(fed_key)
    await db_session.refresh(sig_key)
    await db_session.refresh(enc_key)

    cie = CieConfig(
        id=1,
        saml_metadata_url="https://idserver.servizicie.interno.gov.it/idp/shibboleth?Metadata",
        client_id="https://proxy.ente.it/CieOidcRp",
        oidc_federation_enabled=True,
        oidc_provider_url="https://preprod.oidc.interno.gov.it",
        trust_anchor_url="https://registry.cie.gov.it",
        authority_hint_url="https://registry.cie.gov.it",
        trust_mark_id="https://registry.cie.gov.it/tm/rp",
        trust_mark="eyJhbGciOiJFUzI1NiJ9.stub.sig",
        jwk_federation_id=fed_key.id,
        jwk_core_sig_id=sig_key.id,
        jwk_core_enc_id=enc_key.id,
    )
    db_session.add(cie)
    await db_session.commit()

    from app.satosa_config_generator import generate_satosa_config
    await generate_satosa_config(db_session)

    cie_yaml = yaml.safe_load((tmp_path / "cie_oidc_backend.yaml").read_text())
    callback_claims = cie_yaml["config"]["endpoints"]["authorization_callback_endpoint"]["config"]["claims"]
    assert callback_claims["first_name"] == ["given_name", "first_name"]
    assert callback_claims["last_name"] == ["family_name", "last_name"]
    assert callback_claims["email"] == ["email", "email"]


async def test_satosa_config_generator_spid_testing_providers(db_session, tmp_path, monkeypatch):
    import json
    from sqlalchemy import delete
    monkeypatch.setenv("SATOSA_CONF_DIR", str(tmp_path))
    from app.models import EnteSettings, SpidIdP
    from app.satosa_config_generator import generate_satosa_config

    s = EnteSettings(
        id=1, proxy_hostname="proxy.ente.it", org_name="Ente", org_display_name="Ente Test",
        org_url="https://ente.it", ipa_code="P_T", contact_email="e@ente.it",
        contact_phone="+39001", org_city="Roma",
    )
    
    # 1. Test default mode: neither is enabled (no demo, no validator)
    await db_session.execute(delete(SpidIdP))
    db_session.add(s)
    await db_session.commit()
    
    await generate_satosa_config(db_session)
    
    # Verify spid-idps-default.json fallback is written
    idps_default = json.loads((tmp_path / "spid-idps-default.json").read_text())
    assert len(idps_default) > 1
    assert any(x["organization_name"] == "Aruba PEC" for x in idps_default)
    
    # Verify spid_backend.yaml has only local metadata config
    spid_yaml = yaml.safe_load((tmp_path / "spid_backend.yaml").read_text())
    assert "local" in spid_yaml["metadata"]
    assert "/satosa_proxy/metadata/idp/spid-entities-idps.xml" in spid_yaml["metadata"]["local"]
    assert "remote" not in spid_yaml["metadata"]
    
    # 2. Test demo mode enabled
    demo = SpidIdP(
        alias="spid-demo",
        display_name="Demo Provider",
        metadata_url="https://demo.spid.gov.it/metadata.xml",
        enabled=True,
    )
    db_session.add(demo)
    await db_session.commit()
    
    await generate_satosa_config(db_session)
    
    # Verify spid-idps-default.json has only demo provider
    idps_demo = json.loads((tmp_path / "spid-idps-default.json").read_text())
    assert len(idps_demo) == 1
    assert idps_demo[0]["organization_name"] == "Demo Provider"
    assert idps_demo[0]["entity_id"] == "https://demo.spid.gov.it"
    
    # Verify spid_backend.yaml has both local catalog and remote demo metadata URL
    spid_yaml = yaml.safe_load((tmp_path / "spid_backend.yaml").read_text())
    assert "local" in spid_yaml["metadata"]
    assert "/satosa_proxy/metadata/idp/spid-entities-idps.xml" in spid_yaml["metadata"]["local"]
    assert "remote" in spid_yaml["metadata"]
    assert spid_yaml["metadata"]["remote"] == [{"url": "https://demo.spid.gov.it/metadata.xml"}]
    
    # 3. Test validator mode enabled
    demo.enabled = False
    validator = SpidIdP(
        alias="spid-validator",
        display_name="AgID Validator",
        metadata_url="https://validator.spid.gov.it/metadata.xml",
        enabled=True,
    )
    db_session.add(validator)
    await db_session.commit()
    
    await generate_satosa_config(db_session)
    
    # Verify spid-idps-default.json has only validator
    idps_val = json.loads((tmp_path / "spid-idps-default.json").read_text())
    assert len(idps_val) == 1
    assert idps_val[0]["organization_name"] == "AgID Validator"
    assert idps_val[0]["entity_id"] == "https://validator.spid.gov.it"
    
    # Verify spid_backend.yaml has both local catalog and remote validator metadata URL
    spid_yaml = yaml.safe_load((tmp_path / "spid_backend.yaml").read_text())
    assert "local" in spid_yaml["metadata"]
    assert "/satosa_proxy/metadata/idp/spid-entities-idps.xml" in spid_yaml["metadata"]["local"]
    assert "remote" in spid_yaml["metadata"]
    assert spid_yaml["metadata"]["remote"] == [{"url": "https://validator.spid.gov.it/metadata.xml"}]
