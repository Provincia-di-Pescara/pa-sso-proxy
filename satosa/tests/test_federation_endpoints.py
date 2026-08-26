import json
import pytest
from unittest.mock import MagicMock

from satosa.context import Context

from backends.cieoidc.endpoints.federation_list_endpoint import FederationListHandler
from backends.cieoidc.endpoints.federation_trust_mark_status_endpoint import (
    FederationTrustMarkStatusHandler,
)
from backends.cieoidc.endpoints.federation_fetch_endpoint import FederationFetchHandler
from backends.cieoidc.endpoints.federation_resolve_endpoint import FederationResolveHandler

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


def _make_ctx(sub="", fmt=""):
    ctx = Context()
    ctx.qs_params = {}
    if sub:
        ctx.qs_params["sub"] = sub
    if fmt:
        ctx.qs_params["format"] = fmt
    return ctx


def _common_args():
    return dict(
        internal_attributes={},
        base_url="http://iam-proxy-italia.example.org",
        name="auth",
        auth_callback_func=MagicMock(),
        converter=MagicMock(),
        trust=None,
    )


class TestFederationListHandler:
    def test_returns_empty_entities_list(self):
        handler = FederationListHandler(config={}, **_common_args())
        response = handler.endpoint(Context())
        assert response.status == "200"
        assert json.loads(response.message) == {"entities": []}


class TestFederationTrustMarkStatusHandler:
    def test_returns_inactive_by_default(self):
        handler = FederationTrustMarkStatusHandler(config={}, **_common_args())
        response = handler.endpoint(Context())
        assert response.status == "200"
        assert json.loads(response.message) == {"active": False}


class TestFederationFetchHandler:
    def _handler(self, client_id="client123"):
        config = {
            "jwks_core": _JWKS_CORE,
            "jwks_federation": _JWKS_FEDERATION,
            "entity_type": "openid_relying_party",
            "metadata": {"openid_relying_party": {"client_id": client_id}},
        }
        return FederationFetchHandler(config=config, **_common_args())

    def test_missing_sub_returns_400(self):
        handler = self._handler()
        response = handler.endpoint(_make_ctx())
        assert response.status == "400"
        assert json.loads(response.message)["error"] == "invalid_request"

    def test_unknown_sub_returns_404(self):
        handler = self._handler()
        response = handler.endpoint(_make_ctx(sub="https://not-me.example.org"))
        assert response.status == "404"

    def test_matching_sub_returns_signed_jws(self):
        handler = self._handler(client_id="https://me.example.org")
        response = handler.endpoint(_make_ctx(sub="https://me.example.org"))
        assert response.status == "200"
        assert response.message.count(".") == 2

    def test_sub_matches_ignoring_trailing_slash(self):
        handler = self._handler(client_id="https://me.example.org")
        response = handler.endpoint(_make_ctx(sub="https://me.example.org/"))
        assert response.status == "200"


class TestFederationResolveHandler:
    def _handler(self, client_id="client123"):
        config = {
            "jwks_core": _JWKS_CORE,
            "jwks_federation": _JWKS_FEDERATION,
            "entity_type": "openid_relying_party",
            "metadata": {"openid_relying_party": {"client_id": client_id}},
        }
        return FederationResolveHandler(config=config, **_common_args())

    def test_no_sub_resolves_self(self):
        handler = self._handler()
        response = handler.endpoint(_make_ctx())
        assert response.status == "200"

    def test_unknown_sub_returns_404(self):
        handler = self._handler()
        response = handler.endpoint(_make_ctx(sub="https://not-me.example.org"))
        assert response.status == "404"

    def test_json_format_includes_trust_chain_key(self):
        handler = self._handler(client_id="https://me.example.org")
        response = handler.endpoint(_make_ctx(sub="https://me.example.org", fmt="json"))
        assert response.status == "200"
        payload = json.loads(response.message)
        assert payload["trust_chain"] == []
