import logging
import inspect

from satosa.backends.base import BackendModule
from satosa.backends.oauth import get_metadata_desc_for_oauth_backend

from .utils.endpoints_loader import EndpointsLoader

from pyeudiw.federation.trust_chain_builder import TrustChainBuilder
from pyeudiw.federation.statements import EntityStatement, get_entity_configurations


logger = logging.getLogger(__name__)


class CieOidcBackend(BackendModule):

    def __init__(self, callback, internal_attributes, module_config, base_url, name):
        logger.debug(f"Initializing: {self.__class__.__name__}.")
        super().__init__(callback, internal_attributes, base_url, name)
        self.config = module_config
        self.endpoints = {}
        self.trust_chain = self._generate_trust_chains()
        metadata = self.config.get("metadata", {}).get("openid_relying_party", {})
        self._client_id = metadata.get("client_id") or f"{base_url}/{name}"

    def start_auth(self, context, internal_request):
        logger.debug(
            f"Entering method: {inspect.getframeinfo(inspect.currentframe()).function}. "
            f"Params [metadata: {context}, conf: {internal_request}]"
        )
        authorization_endpoint = self.endpoints.get("authorization")
        if not authorization_endpoint:
            raise ValueError("No authorization endpoint configured in the CieOidc backend")
        return authorization_endpoint(context)

    def register_endpoints(self):
        el = EndpointsLoader(
            self.config,
            self.internal_attributes,
            self.base_url,
            self.name,
            self.auth_callback_func,
            self.converter,
            self.trust_chain,
        )
        url_map = []
        for path, inst in el.endpoint_instances.items():
            url_map.append((f"{self.name}/{path}", inst))
        for path, inst in url_map:
            key = path.split("/")[-1].replace("-", "_").replace("$", "")
            self.endpoints[key] = inst
        logger.debug(f"Loaded CIE OIDC endpoints: {url_map}")
        return url_map

    def get_metadata_desc(self):
        meta = get_metadata_desc_for_oauth_backend(self._client_id, self.config)
        return meta

    def _generate_trust_chains(self) -> dict:
        logger.debug(
            f"Entering method: {inspect.getframeinfo(inspect.currentframe()).function}."
        )
        try:
            httpc_params = self.config["trust_chain"]["config"]["httpc_params"]
            ta_url = self.config["trust_chain"]["config"]["trust_anchor"][0]
            jwt = get_entity_configurations(ta_url, httpc_params=httpc_params)[0]
            trust_anchor_ec = EntityStatement(jwt, httpc_params=httpc_params)
            trust_anchor_ec.validate_by_itself()
            providers = self.config["providers"]
            trust_chains = dict()
            for provider_url in providers:
                try:
                    trust_chains[provider_url] = CieOidcBackend.generate_trust_chain(
                        trust_anchor_ec, provider_url, httpc_params
                    )
                except Exception as exc:
                    logger.error(
                        f"Trust chain build failed for provider {provider_url}: {exc}"
                    )
            return trust_chains
        except Exception as exc:
            # Trust anchor unreachable at startup (e.g. DNS not yet available).
            # SATOSA starts anyway; entity config endpoint still works.
            logger.warning(
                f"Could not build trust chains at startup (will retry on first request): {exc}"
            )
            return {}

    @staticmethod
    def generate_trust_chain(
        trust_anchor_ec: EntityStatement, provider_endpoint: str, httpc_params
    ) -> TrustChainBuilder:
        logger.debug(
            f"Entering method: {inspect.getframeinfo(inspect.currentframe()).function}."
        )
        trust_chain = TrustChainBuilder(
            subject=provider_endpoint,
            trust_anchor=trust_anchor_ec.sub,
            trust_anchor_configuration=trust_anchor_ec,
            httpc_params=httpc_params,
        )
        trust_chain.start()
        trust_chain.apply_metadata_policy()
        return trust_chain
