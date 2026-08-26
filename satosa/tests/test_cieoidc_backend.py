import pytest
from unittest.mock import patch, MagicMock

from satosa.context import Context
from backends.cieoidc.cieoidc import CieOidcBackend


@pytest.fixture
def minimal_config():
    return {
        "metadata": {
            "openid_relying_party": {
                "client_id": "client123"
            }
        },
        "trust_chain": {
            "config": {
                "httpc_params": {},
                "trust_anchor": ["http://trust-anchor.example.org:5002"]
            }
        },
        "providers": [
            "http://cie-provider.example.org"
        ],
        "endpoints": {}
    }


@pytest.fixture
def internal_attributes():
    return {
        "attributes": {
            "username": {"oidc": ["preferred_username", "sub"]},
        },
        "template_attributes": {},
    }


@pytest.fixture
def backend(minimal_config, internal_attributes):
    with patch.object(CieOidcBackend, "_generate_trust_chains", return_value={}):
        return CieOidcBackend(
            callback=MagicMock(),
            internal_attributes=internal_attributes,
            module_config=minimal_config,
            base_url="http://localhost",
            name="test_endpoint",
        )


def test_initialization_sets_client_id(backend):
    assert backend._client_id == "client123"


def test_client_id_falls_back_to_base_url_name(internal_attributes):
    config = {
        "metadata": {"openid_relying_party": {}},
        "trust_chain": {"config": {"httpc_params": {}, "trust_anchor": ["http://ta"]}},
        "providers": [],
    }
    with patch.object(CieOidcBackend, "_generate_trust_chains", return_value={}):
        backend = CieOidcBackend(
            callback=MagicMock(),
            internal_attributes=internal_attributes,
            module_config=config,
            base_url="http://localhost",
            name="cie",
        )
    assert backend._client_id == "http://localhost/cie"


def test_initialization_calls_generate_trust_chains(minimal_config, internal_attributes):
    with patch.object(CieOidcBackend, "_generate_trust_chains", return_value={}) as mock_tc:
        CieOidcBackend(
            callback=MagicMock(),
            internal_attributes=internal_attributes,
            module_config=minimal_config,
            base_url="http://localhost",
            name="test_endpoint",
        )
        mock_tc.assert_called_once()


def test_start_auth_without_authorization_endpoint_raises(backend):
    with pytest.raises(ValueError):
        backend.start_auth(Context(), MagicMock())


def test_start_auth_calls_authorization_endpoint(backend):
    mock_auth = MagicMock(return_value="response")
    backend.endpoints["authorization"] = mock_auth

    res = backend.start_auth(Context(), MagicMock())

    mock_auth.assert_called_once()
    assert res == "response"


@patch("backends.cieoidc.cieoidc.get_metadata_desc_for_oauth_backend")
def test_get_metadata_desc(mock_meta, backend):
    mock_meta.return_value = "metadata-desc"

    res = backend.get_metadata_desc()

    mock_meta.assert_called_once_with(backend._client_id, backend.config)
    assert res == "metadata-desc"


@patch("backends.cieoidc.cieoidc.get_entity_configurations")
@patch("backends.cieoidc.cieoidc.EntityStatement")
@patch("backends.cieoidc.cieoidc.CieOidcBackend.generate_trust_chain")
def test_generate_trust_chains_success(
    mock_gen_tc, mock_entity_statement, mock_get_ec, minimal_config, internal_attributes
):
    mock_get_ec.return_value = ["jwt"]
    mock_ec = MagicMock()
    mock_ec.sub = "ta"
    mock_entity_statement.return_value = mock_ec
    mock_gen_tc.return_value = "trust-chain"

    backend = CieOidcBackend(
        callback=MagicMock(),
        internal_attributes=internal_attributes,
        module_config=minimal_config,
        base_url="http://localhost",
        name="cie",
    )

    trust_chains = backend.trust_chain
    mock_ec.validate_by_itself.assert_called_once()
    assert trust_chains["http://cie-provider.example.org"] == "trust-chain"


@patch("backends.cieoidc.cieoidc.get_entity_configurations")
def test_generate_trust_chains_returns_empty_on_unreachable_trust_anchor(
    mock_get_ec, minimal_config, internal_attributes
):
    # Trust anchor irraggiungibile a boot (es. DNS non ancora disponibile):
    # SATOSA deve avviarsi comunque, endpoint entity config resta funzionante.
    mock_get_ec.side_effect = ConnectionError("network unreachable")

    backend = CieOidcBackend(
        callback=MagicMock(),
        internal_attributes=internal_attributes,
        module_config=minimal_config,
        base_url="http://localhost",
        name="cie",
    )

    assert backend.trust_chain == {}


@patch("backends.cieoidc.cieoidc.get_entity_configurations")
@patch("backends.cieoidc.cieoidc.EntityStatement")
@patch("backends.cieoidc.cieoidc.CieOidcBackend.generate_trust_chain")
def test_generate_trust_chains_skips_failing_provider(
    mock_gen_tc, mock_entity_statement, mock_get_ec, internal_attributes
):
    config = {
        "metadata": {"openid_relying_party": {"client_id": "c"}},
        "trust_chain": {"config": {"httpc_params": {}, "trust_anchor": ["http://ta"]}},
        "providers": ["http://good-provider.example.org", "http://bad-provider.example.org"],
    }
    mock_get_ec.return_value = ["jwt"]
    mock_ec = MagicMock()
    mock_ec.sub = "ta"
    mock_entity_statement.return_value = mock_ec

    def _gen(trust_anchor_ec, provider_url, httpc_params):
        if "bad" in provider_url:
            raise RuntimeError("trust chain build failed")
        return "trust-chain-ok"

    mock_gen_tc.side_effect = _gen

    backend = CieOidcBackend(
        callback=MagicMock(),
        internal_attributes=internal_attributes,
        module_config=config,
        base_url="http://localhost",
        name="cie",
    )

    assert backend.trust_chain == {"http://good-provider.example.org": "trust-chain-ok"}


@patch("backends.cieoidc.cieoidc.TrustChainBuilder")
def test_generate_trust_chain_static(mock_tcb):
    mock_tc = MagicMock()
    mock_tcb.return_value = mock_tc
    trust_anchor_ec = MagicMock()
    trust_anchor_ec.sub = "ta"

    res = CieOidcBackend.generate_trust_chain(
        trust_anchor_ec,
        "https://cie-provider.example.org",
        httpc_params={},
    )
    mock_tc.start.assert_called_once()
    mock_tc.apply_metadata_policy.assert_called_once()
    assert res == mock_tc
