import pytest
from unittest.mock import MagicMock, patch

from satosa.context import Context
from satosa.exception import SATOSAAuthenticationError, SATOSABadRequestError

from backends.cieoidc.endpoints.authorization_callback_endpoint import (
    AuthorizationCallBackHandler,
)
from backends.cieoidc.utils.exceptions import StorageUnreachable


@pytest.fixture(autouse=True)
def mock_db_engine():
    with patch(
        "backends.cieoidc.endpoints.authorization_callback_endpoint.OidcDbEngine"
    ) as mock_engine:
        instance = mock_engine.return_value
        instance.connect.return_value = None
        instance.is_connected.return_value = True
        instance.get_sessions.return_value = [
            MagicMock(
                model_dump=lambda mode: {
                    "state": "dummy_state",
                    "provider_id": "http://cie-provider.example.org:8002/oidc/op",
                    "client_id": "client123",
                    "data": '{"redirect_uri":"http://iam-proxy-italia.example.org/cb"}',
                    "provider_configuration": {
                        "openid_provider": {
                            "token_endpoint": "http://cie-provider.example.org/op/token"
                        }
                    },
                }
            )
        ]
        instance.update_session.return_value = True
        yield instance


@pytest.fixture
def base_config():
    return {
        "client_assertion_type": "urn:ietf:params:oauth:client-assertion-type:jwt-bearer",
        "grant_type": "authorization_code",
        "jwks_core": {},
        "httpc_params": {"connection": {"ssl": False}, "session": {"timeout": 5}},
        "claims": {},
        "metadata": {"openid_relying_party": {"client_id": "client123"}},
        "db_config": {},
    }


@pytest.fixture
def handler(base_config):
    return AuthorizationCallBackHandler(
        config=base_config,
        internal_attributes={},
        base_url="http://localhost",
        name="test_handler",
        auth_callback_func=MagicMock(),
        converter=MagicMock(),
        trust_evaluator=MagicMock(),
    )


def test_init_raises_storage_unreachable_when_never_connects(base_config):
    with patch(
        "backends.cieoidc.endpoints.authorization_callback_endpoint.OidcDbEngine"
    ) as mock_engine, patch("time.sleep"):
        mock_engine.return_value.is_connected.return_value = False
        with pytest.raises(StorageUnreachable):
            AuthorizationCallBackHandler(
                config=base_config,
                internal_attributes={},
                base_url="http://localhost",
                name="test",
                auth_callback_func=MagicMock(),
                converter=MagicMock(),
                trust_evaluator=MagicMock(),
            )


def test_init_retries_before_giving_up(base_config):
    with patch(
        "backends.cieoidc.endpoints.authorization_callback_endpoint.OidcDbEngine"
    ) as mock_engine, patch("time.sleep") as mock_sleep:
        # non connesso ai primi 2 tentativi, connesso al 3
        mock_engine.return_value.is_connected.side_effect = [False, False, True]
        AuthorizationCallBackHandler(
            config=base_config,
            internal_attributes={},
            base_url="http://localhost",
            name="test",
            auth_callback_func=MagicMock(),
            converter=MagicMock(),
            trust_evaluator=MagicMock(),
        )
        assert mock_sleep.call_count == 2


def test_endpoint_error_param_returns_handled_response_not_raw_exception(handler):
    # context.qs_params["error"] deve essere gestito da _handle_idp_error
    # (redirect/pagina errore), mai propagare come eccezione non gestita.
    context = Context()
    context.state = MagicMock()
    context.qs_params = {"error": "invalid_request"}
    response = handler.endpoint(context)
    assert response.status == "200 OK"


def test_endpoint_raises_when_state_missing(handler):
    context = Context()
    context.state = MagicMock()
    context.qs_params = {"state": None}
    with pytest.raises(Exception):
        handler.endpoint(context)


def test_endpoint_raises_when_iss_mismatch(handler):
    context = Context()
    context.state = MagicMock()
    context.qs_params = {"state": "dummy_state", "code": "code123", "iss": "http://other-provider"}
    with pytest.raises(SATOSABadRequestError):
        handler.endpoint(context)


def test_endpoint_raises_when_authorization_not_found(handler):
    context = Context()
    context.state = MagicMock()
    context.qs_params = {
        "state": "nonexistent_state",
        "code": "code123",
        "iss": "http://cie-provider.example.org:8002/oidc/op",
    }
    with patch.object(handler, "_AuthorizationCallBackHandler__get_authorization", return_value=None):
        with pytest.raises(SATOSAAuthenticationError):
            handler.endpoint(context)


def test_endpoint_raises_when_client_id_mismatch(handler):
    context = Context()
    context.state = MagicMock()
    context.qs_params = {
        "state": "dummy_state", "code": "code", "iss": "http://cie-provider.example.org:8002/oidc/op"
    }
    authorization = {
        "state": "dummy_state",
        "provider_id": "http://cie-provider.example.org:8002/oidc/op",
        "client_id": "WRONG_CLIENT",
        "data": '{"redirect_uri":"http://cb"}',
        "provider_configuration": {"openid_provider": {"token_endpoint": "x"}},
    }
    with patch.object(
        handler, "_AuthorizationCallBackHandler__get_authorization", return_value=authorization
    ):
        with pytest.raises(SATOSABadRequestError):
            handler.endpoint(context)


def test_endpoint_wraps_access_token_request_exception(handler):
    # Fix recente (636b7a3): un timeout sul token endpoint CIE non deve
    # propagare come eccezione generica non gestita, ma diventare un errore
    # SATOSA dedicato con pagina di errore SPID/CIE.
    context = Context()
    context.state = MagicMock()
    context.qs_params = {
        "state": "dummy_state", "code": "code", "iss": "http://cie-provider.example.org:8002/oidc/op"
    }
    with patch(
        "backends.cieoidc.utils.clients.oauth2.OAuth2AuthorizationCodeGrant.access_token_request",
        side_effect=TimeoutError("connect timeout"),
    ):
        with pytest.raises(SATOSAAuthenticationError, match="token request failed"):
            handler.endpoint(context)


def test_endpoint_raises_when_token_response_empty(handler):
    context = Context()
    context.state = MagicMock()
    context.qs_params = {
        "state": "dummy_state", "code": "code", "iss": "http://cie-provider.example.org:8002/oidc/op"
    }
    with patch(
        "backends.cieoidc.utils.clients.oauth2.OAuth2AuthorizationCodeGrant.access_token_request",
        return_value=None,
    ):
        with pytest.raises(SATOSAAuthenticationError):
            handler.endpoint(context)


def test_endpoint_raises_when_jwk_missing(handler):
    context = Context()
    context.state = MagicMock()
    context.qs_params = {
        "state": "dummy_state", "code": "code", "iss": "http://cie-provider.example.org:8002/oidc/op"
    }
    with patch(
        "backends.cieoidc.utils.clients.oauth2.OAuth2AuthorizationCodeGrant.access_token_request",
        return_value={"access_token": "a", "id_token": "b", "token_type": "Bearer", "expires_in": 1},
    ), patch(
        "backends.cieoidc.endpoints.authorization_callback_endpoint.get_jwks", return_value={"keys": []}
    ), patch(
        "backends.cieoidc.endpoints.authorization_callback_endpoint.get_jwk_from_jwt", return_value=None
    ):
        with pytest.raises(SATOSAAuthenticationError):
            handler.endpoint(context)


def test_endpoint_raises_on_verify_jws_failure(handler):
    context = Context()
    context.state = MagicMock()
    context.qs_params = {
        "state": "dummy_state", "code": "code", "iss": "http://cie-provider.example.org:8002/oidc/op"
    }
    with patch(
        "backends.cieoidc.utils.clients.oauth2.OAuth2AuthorizationCodeGrant.access_token_request",
        return_value={"access_token": "a", "id_token": "b", "token_type": "Bearer", "expires_in": 1},
    ), patch(
        "backends.cieoidc.endpoints.authorization_callback_endpoint.get_jwks", return_value={"keys": []}
    ), patch(
        "backends.cieoidc.endpoints.authorization_callback_endpoint.get_jwk_from_jwt",
        return_value={"kid": "k"},
    ), patch(
        "backends.cieoidc.endpoints.authorization_callback_endpoint.verify_jws",
        side_effect=Exception("boom"),
    ):
        with pytest.raises(SATOSAAuthenticationError):
            handler.endpoint(context)


def test_endpoint_raises_on_verify_at_hash_failure(handler):
    context = Context()
    context.state = MagicMock()
    context.qs_params = {
        "state": "dummy_state", "code": "code", "iss": "http://cie-provider.example.org:8002/oidc/op"
    }
    with patch(
        "backends.cieoidc.utils.clients.oauth2.OAuth2AuthorizationCodeGrant.access_token_request",
        return_value={"access_token": "a", "id_token": "b", "token_type": "Bearer", "expires_in": 1},
    ), patch(
        "backends.cieoidc.endpoints.authorization_callback_endpoint.get_jwks", return_value={"keys": []}
    ), patch(
        "backends.cieoidc.endpoints.authorization_callback_endpoint.get_jwk_from_jwt",
        return_value={"kid": "k"},
    ), patch(
        "backends.cieoidc.endpoints.authorization_callback_endpoint.verify_jws", return_value=True
    ), patch(
        "backends.cieoidc.endpoints.authorization_callback_endpoint.unpad_jwt_payload",
        return_value={"at_hash": "x"},
    ), patch(
        "backends.cieoidc.endpoints.authorization_callback_endpoint.verify_at_hash",
        side_effect=Exception("boom"),
    ):
        with pytest.raises(SATOSAAuthenticationError):
            handler.endpoint(context)


def test_endpoint_raises_when_userinfo_empty(handler):
    context = Context()
    context.state = MagicMock()
    context.qs_params = {
        "state": "dummy_state", "code": "code", "iss": "http://cie-provider.example.org:8002/oidc/op"
    }
    with patch(
        "backends.cieoidc.utils.clients.oauth2.OAuth2AuthorizationCodeGrant.access_token_request",
        return_value={"access_token": "a", "id_token": "b", "token_type": "Bearer", "expires_in": 1},
    ), patch(
        "backends.cieoidc.endpoints.authorization_callback_endpoint.get_jwks", return_value={"keys": []}
    ), patch(
        "backends.cieoidc.endpoints.authorization_callback_endpoint.get_jwk_from_jwt",
        return_value={"kid": "k"},
    ), patch(
        "backends.cieoidc.endpoints.authorization_callback_endpoint.verify_jws", return_value=True
    ), patch(
        "backends.cieoidc.endpoints.authorization_callback_endpoint.unpad_jwt_payload",
        return_value={"sub": "user123", "at_hash": "x"},
    ), patch(
        "backends.cieoidc.endpoints.authorization_callback_endpoint.verify_at_hash", return_value=True
    ), patch(
        "backends.cieoidc.utils.clients.oidc.OidcUserInfo.get_userinfo", return_value=None
    ):
        with pytest.raises(SATOSAAuthenticationError):
            handler.endpoint(context)


def test_endpoint_raises_when_no_user_attrs_processed(handler):
    context = Context()
    context.state = MagicMock()
    context.qs_params = {
        "state": "dummy_state", "code": "code", "iss": "http://cie-provider.example.org:8002/oidc/op"
    }
    with patch(
        "backends.cieoidc.utils.clients.oauth2.OAuth2AuthorizationCodeGrant.access_token_request",
        return_value={"access_token": "a", "id_token": "b", "token_type": "Bearer", "expires_in": 1},
    ), patch(
        "backends.cieoidc.endpoints.authorization_callback_endpoint.get_jwks", return_value={"keys": []}
    ), patch(
        "backends.cieoidc.endpoints.authorization_callback_endpoint.get_jwk_from_jwt",
        return_value={"kid": "k"},
    ), patch(
        "backends.cieoidc.endpoints.authorization_callback_endpoint.verify_jws", return_value=True
    ), patch(
        "backends.cieoidc.endpoints.authorization_callback_endpoint.unpad_jwt_payload",
        return_value={"sub": "user123", "at_hash": "x"},
    ), patch(
        "backends.cieoidc.endpoints.authorization_callback_endpoint.verify_at_hash", return_value=True
    ), patch(
        "backends.cieoidc.endpoints.authorization_callback_endpoint.process_user_attributes",
        return_value=None,
    ), patch(
        "backends.cieoidc.utils.clients.oidc.OidcUserInfo.get_userinfo",
        return_value={"email": "test@example.com"},
    ):
        with pytest.raises(SATOSAAuthenticationError):
            handler.endpoint(context)


def test_endpoint_happy_path_calls_auth_callback(handler):
    context = Context()
    context.state = MagicMock()
    context.qs_params = {
        "state": "dummy_state",
        "code": "dummy_code",
        "iss": "http://cie-provider.example.org:8002/oidc/op",
    }
    user_attrs = {
        "username": "u",
        "first_name": "Mario",
        "last_name": "Rossi",
        "sub": "user123",
        "fiscal_number": "RSSMRA80A01H501U",
    }
    with patch(
        "backends.cieoidc.utils.clients.oauth2.OAuth2AuthorizationCodeGrant.access_token_request",
        return_value={
            "access_token": "dummy_access_token",
            "id_token": "dummy_id_token",
            "expires_in": 3600,
            "token_type": "Bearer",
            "scope": "openid",
        },
    ), patch(
        "backends.cieoidc.endpoints.authorization_callback_endpoint.get_jwks", return_value={"keys": []}
    ), patch(
        "backends.cieoidc.endpoints.authorization_callback_endpoint.get_jwk_from_jwt",
        return_value={"kid": "key1"},
    ), patch(
        "backends.cieoidc.endpoints.authorization_callback_endpoint.verify_jws", return_value=True
    ), patch(
        "backends.cieoidc.endpoints.authorization_callback_endpoint.unpad_jwt_payload",
        return_value={"sub": "user123", "at_hash": "dummy"},
    ), patch(
        "backends.cieoidc.endpoints.authorization_callback_endpoint.verify_at_hash"
    ), patch(
        "backends.cieoidc.endpoints.authorization_callback_endpoint.process_user_attributes",
        return_value=user_attrs,
    ), patch(
        "backends.cieoidc.utils.clients.oidc.OidcUserInfo.get_userinfo",
        return_value={"email": "test@example.com"},
    ):
        response = handler.endpoint(context)
        assert response is not None
        handler._auth_callback.assert_called_once()


def test_check_provider_normalizes_trailing_slash(handler):
    assert handler._AuthorizationCallBackHandler__check_provider(
        "https://example.org/", "https://example.org"
    )
    assert handler._AuthorizationCallBackHandler__check_provider(
        "https://example.org", "https://example.org/"
    )


def test_check_provider_mismatch(handler):
    assert not handler._AuthorizationCallBackHandler__check_provider(
        "https://example.org", "https://other.org"
    )


def test_add_user_returns_none_on_invalid_data(handler):
    result = handler._AuthorizationCallBackHandler__add_user({"invalid": "data"})
    assert result is None


def test_add_user_fills_edupersontargetedid_from_sub(handler):
    user = handler._AuthorizationCallBackHandler__add_user({
        "username": "u",
        "first_name": "Mario",
        "last_name": "Rossi",
        "sub": "user123",
        "fiscal_number": "RSSMRA80A01H501U",
    })
    assert user is not None
    assert user.attributes["edupersontargetedid"] == "user123"


def test_translate_response_sets_subject_id(handler):
    attributes = {"sub": "user123"}
    internal = handler._translate_response(attributes, "issuer123", "sub123")
    assert internal.subject_id == "sub123"
    assert hasattr(internal, "attributes")


def test_translate_response_sets_fiscal_number_aliases(handler):
    handler._converter.to_internal.return_value = {}
    attributes = {"sub": "s", "fiscal_number": "RSSMRA80A01H501U"}
    internal = handler._translate_response(attributes, "issuer123", "s")
    assert internal.attributes["fiscalnumber"] == ["RSSMRA80A01H501U"]
    assert internal.attributes["fiscalCode"] == ["RSSMRA80A01H501U"]


def test_generate_configuration_plugin(handler):
    plugin = handler.generate_configuration_plugin(handler.config)
    assert plugin is not None


def test_update_authorization_swallows_db_failure(handler):
    handler._db_engine.update_session.return_value = False
    auth = {"state": "s", "provider_id": "i", "client_id": "c", "data": "{}", "provider_configuration": {}}
    handler._AuthorizationCallBackHandler__update_authorization(auth)


def test_handle_idp_error_redirects_to_client_when_context_has_oidc_request(handler):
    context = Context()
    context.qs_params = {"error": "access_denied", "error_description": "Denied"}
    context.state = {
        "oidcop": {
            "oidc_request": "redirect_uri=https://client.example.org/cb&state=cstate&client_id=c1"
        }
    }
    response = handler._handle_idp_error(context)
    assert response.status == "200 OK"
    assert b"client.example.org" in response.message


def test_handle_idp_error_falls_back_to_branded_page_without_oidc_request(handler):
    context = Context()
    context.qs_params = {"error": "login_required", "error_description": "cancelled"}
    context.state = {}
    response = handler._handle_idp_error(context)
    assert response.status == "200 OK"
