import pytest
from sqlalchemy.ext.asyncio import AsyncSession
from app.models import OIDCClient, SpidIdP, EnteSettings, JwkKey, SpidCert, CieConfig


@pytest.mark.asyncio
async def test_oidc_client_create(db_session: AsyncSession):
    client = OIDCClient(
        client_id="test-app",
        client_secret_hash="hash",
        name="Test App",
        redirect_uris=["https://app.test/callback"],
        allowed_scopes=["openid", "profile"],
    )
    db_session.add(client)
    await db_session.commit()
    await db_session.refresh(client)
    assert client.id is not None
    assert client.enabled is True


@pytest.mark.asyncio
async def test_spid_idp_create(db_session: AsyncSession):
    idp = SpidIdP(
        alias="spid-aruba",
        display_name="Aruba ID",
        metadata_url="https://loginspid.aruba.it/metadata",
    )
    db_session.add(idp)
    await db_session.commit()
    await db_session.refresh(idp)
    assert idp.enabled is False
    assert idp.metadata_cache is None


@pytest.mark.asyncio
async def test_jwk_key_create(db_session: AsyncSession):
    key = JwkKey(
        name="jwk-federation",
        use="federation",
        private_jwk={"kty": "RSA", "d": "private"},
        public_jwk={"kty": "RSA", "e": "AQAB"},
    )
    db_session.add(key)
    await db_session.commit()
    await db_session.refresh(key)
    assert key.id is not None
    assert key.public_jwk["kty"] == "RSA"
