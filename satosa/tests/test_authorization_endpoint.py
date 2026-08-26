import pytest
from unittest.mock import MagicMock, patch

from backends.cieoidc.endpoints.authorization_endpoint import AuthorizationHandler

_JWKS_CORE = [{
    "kty": "RSA",
    "use": "sig",
    "n": "uXfJA-wTlTCA4FdsoE0qZfmKIgedmarrtWgQbElKbWg9RDR7Z8JVBaRLFqwyfyG1JJFm64G51cBJwLIFwWoF7nxsH9VYLm5ocjAnsR4RhlfVE0y_60wjf8skJgBRpiXQPlwH9jDGaqVE_PEBTObDO5w3XourD1F360-v5cLDLRHdFJIitdEVtqATqY5DglRDaKiBhis7a5_1bk839PDLaQhju4XJk4tvDy5-LVkMy5sP2zU6-1tJdA-VmaBZLXy9n0967FGIWmMzpafrBMOuHFcUOH56o-clDah_CITH1dq2D64K0MYhEpACO2p8AH4K8Q6YuJ1dnkVDDwZp2C84sQ",  # noqa: E501
    "p": "5PA7lJEDd3vrw5hlolFzvjvRriOu1SMHXx9Y52AgpOeQ6MnE1pO8qwn33lwYTSPGYinaq4jS3FKF_U5vOZltJAGBMa4ByEvAROJVCh958rKVRWKIqVXLOi8Gk11kHbVKw6oDXAd8Qt_y_ff8k_K6jW2EbWm1K6kfTvTMzoHkqrU",  # noqa: E501
    "q": "z2QeMH4WtrdiWUET7JgZNX0TbcaVBgd2Gpo8JHnfnGOUsvO_euKGgqpCcxiWVXSlqffQyTgVzl4iMROP8bEaQwvueHurtziMDSy9Suumyktu3PbGgjqu_izRim8Xlg7sz8Hs2quJPII_fQ8BCoaWpg30osFZqCBarQM7CWhxR40",  # noqa: E501
    "d": "n_ePK5DdOxqArf75tDGaViYrXDqRVk8zyl2dfKiiR0dXQJK7tbzJtHoGQeH4E-sw3_-Bc7OKY7DcbBWgHTijMRWj9LkAu9uCvqqGMaAroWH0aBcUmZAsNjcyUIyJ3_JRcNfUDiX3nVg67qe4ZWnMDogowaVZv3aXJiCvKE8aJK4BV_nF3Nt5R6zUYpjZQ8T1GDZCV3vza3qglDrXe8zoc-p8cLs3rJn7tMVSJVznCIqOfeM1VIg0I3n2bubYOx88sckHuDnfXTiTDlyq5IwDyBHmiIe3fpu-c4e1tiBmbOf2IqDCaX8SdpnU2gTj9YlZtRNqmh3NB_rksBKWLz3uIQ",  # noqa: E501
    "e": "AQAB",
    "kid": "YhuIJU6o15EUCyqA0LHEqJd-xVPJgoyW5wZ1o4padWs",
}]


@pytest.fixture
def minimal_config():
    return {
        "entity_type": "openid_relying_party",
        "jwks_core": _JWKS_CORE,
        "prompt": "login",
        "metadata": {
            "openid_relying_party": {
                "client_id": "client123",
                "redirect_uris": ["https://localhost/callback"],
                "scope": "openid",
                "claim": {"userinfo": {"email": None}},
                "response_types": ["code"],
                "code_challenge": {"length": 32, "method": "S256"},
            }
        },
        "endpoints": {
            "authorization_endpoint": {
                "config": {
                    "metadata": {
                        "openid_relying_party": {
                            "client_id": "client123",
                            "redirect_uris": ["https://localhost/callback"],
                        }
                    }
                }
            }
        },
        "trust_chain": {
            "config": {"httpc_params": {}, "trust_anchor": ["http://trust-anchor.example.org:5002"]}
        },
    }


@pytest.fixture
def context():
    ctx = MagicMock()
    ctx.internal_data = {"target_entity_id": "http://trust-anchor.example.org:5002"}
    ctx.get_decoration.return_value = "http://trust-anchor.example.org:5002"
    return ctx


@pytest.fixture
def trust_chain():
    tc = MagicMock()
    tc.subject = "http://trust-anchor.example.org:5002"
    tc.subject_configuration.payload = {
        "metadata": {
            "openid_provider": {
                "authorization_endpoint": "http://trust-anchor.example.org:5002/auth",
                "issuer": "http://trust-anchor.example.org:5002",
            }
        }
    }
    return tc


@pytest.fixture
def handler(minimal_config, trust_chain):
    with patch("backends.cieoidc.storage.db_engine.OidcDbEngine") as db_mock:
        db = db_mock.return_value
        db.connect.return_value = None
        db.add_session.return_value = 1

        return AuthorizationHandler(
            config=minimal_config,
            internal_attributes={},
            base_url="https://iam-proxy-italia.example.org",
            name="authz",
            auth_callback_func=MagicMock(),
            converter=MagicMock(),
            trust_chains={"http://trust-anchor.example.org:5002": trust_chain},
        )


def test_validate_configs_ok(handler):
    handler._validate_configs()


def test_validate_configs_raises_when_endpoints_missing(minimal_config):
    del minimal_config["endpoints"]
    with patch("backends.cieoidc.storage.db_engine.OidcDbEngine"):
        handler = AuthorizationHandler(
            config=minimal_config,
            internal_attributes={},
            base_url="x",
            name="x",
            auth_callback_func=MagicMock(),
            converter=MagicMock(),
            trust_chains={},
        )
    with pytest.raises(ValueError):
        handler._validate_configs()


def test_pkce_generation_raises_on_empty_length(handler):
    handler.config["metadata"]["openid_relying_party"]["code_challenge"]["length"] = None
    with pytest.raises(ValueError):
        handler._AuthorizationHandler__pkce_generation({})


def test_pkce_generation_raises_on_empty_method(handler):
    handler.config["metadata"]["openid_relying_party"]["code_challenge"]["method"] = None
    with pytest.raises(ValueError):
        handler._AuthorizationHandler__pkce_generation({})


def test_pkce_generation_populates_authz_data(handler):
    authz_data = {}
    handler._AuthorizationHandler__pkce_generation(authz_data)
    assert "code_challenge" in authz_data
    assert "code_challenge_method" in authz_data
    assert authz_data["code_challenge_method"] == "S256"


def test_authorization_data_uses_provider_issuer_as_aud(handler):
    authz_data = handler._AuthorizationHandler__authorization_data(
        "http://trust-anchor.example.org:5002/auth",
        "http://trust-anchor.example.org:5002",
    )
    # JAR (RFC 9101): aud deve essere l'issuer, non l'authorization endpoint.
    assert authz_data["aud"] == "http://trust-anchor.example.org:5002"
    assert authz_data["client_id"] == "client123"
    assert authz_data["claims"] == {"userinfo": {"email": None}}


def test_authorization_data_falls_back_to_endpoint_when_no_issuer(handler):
    authz_data = handler._AuthorizationHandler__authorization_data(
        "http://trust-anchor.example.org:5002/auth", None
    )
    assert authz_data["aud"] == "http://trust-anchor.example.org:5002/auth"


def test_authorization_data_forces_spid_l2_acr(handler):
    authz_data = handler._AuthorizationHandler__authorization_data(
        "http://trust-anchor.example.org:5002/auth",
        "http://trust-anchor.example.org:5002",
    )
    assert authz_data["acr_values"] == "https://www.spid.gov.it/SpidL2"


def test_generate_uri(handler):
    authz_data = {
        "client_id": "client123",
        "scope": "openid",
        "response_type": "code",
        "code_challenge": "abc",
        "code_challenge_method": "S256",
        "acr_values": "https://www.spid.gov.it/SpidL2",
        "request": "jwt",
    }
    uri = AuthorizationHandler.generate_uri(authz_data)
    assert "client_id=client123" in uri
    assert "request=jwt" in uri


def test_insert_calls_db_engine(handler):
    handler._db_engine.add_session = MagicMock(return_value=1)
    auth_obj = {
        "client_id": "client123",
        "state": "state",
        "endpoint": "x",
        "provider_id": "y",
        "data": "{}",
        "provider_configuration": {},
    }
    handler._AuthorizationHandler__insert(auth_obj)
    handler._db_engine.add_session.assert_called_once()


def test_insert_swallows_validation_error_on_bad_input(handler):
    handler._db_engine.add_session = MagicMock(return_value=1)
    # manca 'data' obbligatorio nel modello OidcAuthentication -> ValidationError gestita
    bad_obj = {"client_id": "client123", "state": "state"}
    handler._AuthorizationHandler__insert(bad_obj)
    handler._db_engine.add_session.assert_not_called()


@patch("backends.cieoidc.endpoints.authorization_endpoint.get_pkce")
@patch("backends.cieoidc.endpoints.authorization_endpoint.create_jws")
@patch("backends.cieoidc.endpoints.authorization_endpoint.get_key")
def test_endpoint_happy_path_returns_response(get_key_mock, create_jws_mock, get_pkce_mock, handler, context):
    get_pkce_mock.return_value = {"code_challenge": "abc", "code_challenge_method": "S256"}
    get_key_mock.return_value = {"kty": "RSA"}
    create_jws_mock.return_value = "signed.jwt"

    response = handler.endpoint(context)

    assert response is not None
    assert response.status == "200 OK"


def test_get_trust_chain_uses_cached_chain(handler, trust_chain):
    result = handler._AuthorizationHandler__get_trust_chain("http://trust-anchor.example.org:5002")
    assert result is trust_chain


@patch("backends.cieoidc.endpoints.authorization_endpoint.get_entity_configurations")
def test_get_trust_chain_raises_when_ondemand_fetch_fails(mock_get_ec, handler):
    mock_get_ec.side_effect = ConnectionError("registry unreachable")
    with pytest.raises(ValueError):
        handler._AuthorizationHandler__get_trust_chain("http://unknown-provider.example.org")
