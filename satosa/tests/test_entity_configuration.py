import json
import pytest
from unittest.mock import MagicMock

from backends.cieoidc.endpoints.entity_configuration import EntityConfigHandler

# JWK RSA privata di test (non usata in produzione) — riutilizzata dalla
# suite upstream iam-proxy-italia per far passare validate_private_jwks.
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

_JWKS_FEDERATION = [{
    "d": "Npw19klvaNLdUWZRwe4MjPIgD8AH5BjfU5_dM05Gb6lBRWQKSWNlqP8bET-oZbWSw3zMaOAy2-k2GnYVXBYKu9WnjFFFPlbH-sVPfdKQLYzEABmxR_aaeSHrnDfKozTtFsYEgtI_WoGEaxPoE0P-Ds11Tp9h9ovZM48sDGnEdyjopnLPEZBR6VinP_yF1kfDg0kcIPmM1ZchIqJrnQpoKWeVTXtFFGrVqOAYmm4xBfP4U8TEimbeJJuYkJ9gLNnRDg_FC-ZPUiBIXigWZsEeJyevymP-NH4lq3osLgFOq0sqPxS3zkDwx9tWfT5UyqrCCortiQd2dxKzxZlEEvlQAQ",  # noqa: E501
    "e": "AQAB",
    "kid": "wL_LmP8UjLVN-sAeoZ7KGEMJfBkFtbNLd24eDD9RGCs",
    "kty": "RSA",
    "n": "6SDksa64IjBk7HNQC7x5C9nMARGaanfaUm3wC2WulwG_8a5aIy4CEwXN2LENkCyypODqWZcTAwCzWsiihVN9kDcEs7UNu-X1WokK252D7_DRY-FXI8AB3P0CxTngs0k-OjcmbxqVW2U8G56rJFp4G_CYA4vzBoAP_5skFBt-4a5lYJlBfJ2gJlE0vh4_46oyNuUT9kmKauR7npVSHjBUSxYyDELzoaPmvR7SkX4sJe0MK39HES6s4no9G7BraLp75eOwEQmHgEhESWscSOf_CmC5ALnzWJ3FcFhxgsuMkdjoU7bH09y8pdKs64kR2znxs-yIWrPFW8hJKnySc2fk8w",  # noqa: E501
    "p": "-1JcdcT2FdwavmPqtfOEKFUGBM9hhvwgX7KyCwl8tmresJQz8pNDkILMeKJf8ZCDVU7v4_i4C_P8oe41f2_SDsv9AIYh09zu_tQsMMdH_lqNx0YP8Yv25N5KOxnSOBO837SieFZ2xkbolXXIV7WIHrdFiyAOMOSWlETEO6JNu_M",  # noqa: E501
    "q": "7XfVt4ArSMLmRvvSl11yDF25t1aR3ylUmwZgLAJTNo76j-zo8Q2Ty7GfCIQmLOhOZTkwqnrbmwEBMEBsomWZFh_j90CLMyn1ccYUjiTI4CHJOTLMA8rYVWeArYkqek1jC4TQ9e1PkRrPcEvq2Tak8GFsBhnhOCzejJrMDgqkcwE",  # noqa: E501
}]


@pytest.fixture
def minimal_config():
    return {
        "entity_type": "openid_relying_party",
        "jwks_core": _JWKS_CORE,
        "jwks_federation": _JWKS_FEDERATION,
        "metadata": {
            "openid_relying_party": {
                "client_id": "client123",
                "redirect_uris": ["https://sp.example.org/cb"],
            },
        },
        "authority_hints": ["https://preproduzione.cie.interno.gov.it"],
        "default_sig_alg": "RS256",
        "entity_configuration_exp": 3600,
    }


def _make_handler(config):
    return EntityConfigHandler(
        config=config,
        internal_attributes={},
        base_url="http://iam-proxy-italia.example.org",
        name="auth",
        auth_callback_func=MagicMock(),
        converter=MagicMock(),
        trust=None,
    )


def test_client_id_from_metadata(minimal_config):
    handler = _make_handler(minimal_config)
    assert handler._client_id == "client123"


def test_client_id_falls_back_to_base_url_name(minimal_config):
    minimal_config["metadata"]["openid_relying_party"].pop("client_id")
    handler = _make_handler(minimal_config)
    assert handler._client_id == "http://iam-proxy-italia.example.org/auth"


def test_authority_hints_is_trust_anchor_not_op(minimal_config):
    # CLAUDE.md: authority_hints DEVE essere il Trust Anchor, mai l'OP.
    handler = _make_handler(minimal_config)
    assert handler._auth_hints == ["https://preproduzione.cie.interno.gov.it"]
    assert "idp/oidc/op" not in handler._auth_hints[0]


def test_metadata_strips_internal_code_challenge_field(minimal_config):
    minimal_config["metadata"]["openid_relying_party"]["code_challenge"] = {
        "length": 32, "method": "S256"
    }
    handler = _make_handler(minimal_config)
    meta = handler._metadata
    assert "code_challenge" not in meta["openid_relying_party"]


def test_metadata_renames_claim_to_claims(minimal_config):
    minimal_config["metadata"]["openid_relying_party"]["claim"] = {
        "userinfo": {"email": None}
    }
    handler = _make_handler(minimal_config)
    meta = handler._metadata
    assert "claim" not in meta["openid_relying_party"]
    assert meta["openid_relying_party"]["claims"] == {"userinfo": {"email": None}}


def test_metadata_omits_claims_when_no_internal_claim_field(minimal_config):
    handler = _make_handler(minimal_config)
    meta = handler._metadata
    assert "claims" not in meta["openid_relying_party"]


def test_metadata_client_id_and_jwks_populated(minimal_config):
    handler = _make_handler(minimal_config)
    meta = handler._metadata
    assert meta["openid_relying_party"]["client_id"] == "client123"
    assert meta["openid_relying_party"]["jwks"]["keys"][0]["kid"] == _JWKS_CORE[0]["kid"]
    # Deve essere pubblicata solo la chiave pubblica, mai i parametri privati.
    assert "d" not in meta["openid_relying_party"]["jwks"]["keys"][0]
    assert "p" not in meta["openid_relying_party"]["jwks"]["keys"][0]


def test_metadata_rp_profile_excludes_federation_only_endpoints(minimal_config):
    minimal_config["metadata"]["federation_entity"] = {
        "federation_fetch_endpoint": "https://sp.example.org/fetch",
        "federation_trust_mark_status_endpoint": "https://sp.example.org/tm-status",
        "federation_list_endpoint": "https://sp.example.org/list",
        "contacts": ["protocollo@pec.comune.example.it"],
    }
    handler = _make_handler(minimal_config)
    fed_meta = handler._metadata["federation_entity"]
    assert "federation_fetch_endpoint" not in fed_meta
    assert "federation_trust_mark_status_endpoint" not in fed_meta
    assert "federation_list_endpoint" not in fed_meta
    assert fed_meta["contacts"] == ["protocollo@pec.comune.example.it"]


def test_metadata_rp_profile_strips_none_federation_fields(minimal_config):
    minimal_config["metadata"]["federation_entity"] = {
        "contacts": ["protocollo@pec.comune.example.it"],
        "homepage_uri": None,
    }
    handler = _make_handler(minimal_config)
    fed_meta = handler._metadata["federation_entity"]
    assert "homepage_uri" not in fed_meta


def test_contacts_must_be_pec_by_convention(minimal_config):
    # CLAUDE.md: contacts in federation_entity deve essere la PEC dell'ente,
    # non una email generica. Verifichiamo solo che il campo sopravviva
    # intatto nel metadata pubblicato (la policy PEC è responsabilità di
    # chi compila la config, non del codice).
    minimal_config["metadata"]["federation_entity"] = {
        "contacts": ["protocollo@pec.comune.example.it"],
    }
    handler = _make_handler(minimal_config)
    assert handler._metadata["federation_entity"]["contacts"] == [
        "protocollo@pec.comune.example.it"
    ]


def test_get_entity_configuration_returns_valid_json(minimal_config):
    handler = _make_handler(minimal_config)
    res = handler.get_entity_configuration(jws=False)
    data = json.loads(res)
    assert data["sub"] == "client123"
    assert data["metadata"]["openid_relying_party"]["client_id"] == "client123"


def test_get_entity_configuration_jws_is_signed_string(minimal_config):
    handler = _make_handler(minimal_config)
    res = handler.get_entity_configuration(jws=True)
    assert isinstance(res, str)
    assert res.count(".") == 2  # header.payload.signature


def test_get_openid_jwks_json_contains_only_public_keys(minimal_config):
    handler = _make_handler(minimal_config)
    result = json.loads(handler.get_openid_jwks(jws=False))
    assert len(result["keys"]) == 1
    assert result["keys"][0]["kid"] == _JWKS_CORE[0]["kid"]
    assert "d" not in result["keys"][0]


def test_endpoint_well_known_json(minimal_config):
    from satosa.context import Context

    handler = _make_handler(minimal_config)
    context = Context()
    context.target_backend = "auth"
    context.path = "auth/.well-known/openid-federation"
    context.qs_params = {"format": "json"}
    response = handler.endpoint(context)
    assert response.status == "200"


def test_endpoint_unknown_path_returns_404(minimal_config):
    from satosa.context import Context

    handler = _make_handler(minimal_config)
    context = Context()
    context.target_backend = "auth"
    context.path = "auth/unknown"
    context.qs_params = {}
    response = handler.endpoint(context)
    assert response.status == "404"
