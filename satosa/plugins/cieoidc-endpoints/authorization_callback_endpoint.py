import logging
import json
import inspect
import os
import time
import urllib.parse
from jinja2 import Environment, FileSystemLoader, select_autoescape
from typing import Callable
from satosa.attribute_mapping import AttributeMapper
from satosa.context import Context
from satosa.exception import SATOSAAuthenticationError, SATOSABadRequestError
from satosa.internal import InternalData, AuthenticationInformation
from satosa.response import Response
from pydantic import ValidationError
from ..utils.helpers.configuration_utils import ConfigurationPlugin
from ..utils.clients.oauth2 import OAuth2AuthorizationCodeGrant
from ..utils.clients.oidc import OidcUserInfo
from ..storage.db_engine import OidcDbEngine
from ..models.oidc_auth import OidcAuthentication
from ..models.user import OidcUser
from ..utils.exceptions import StorageUnreachable
from ..utils.helpers.misc import get_jwks, get_jwk_from_jwt, process_user_attributes
from ..utils.handlers.base_endpoint import BaseEndpoint
from ..utils.helpers.jwtse import verify_jws, unpad_jwt_payload, verify_at_hash
from pyeudiw.trust.dynamic import CombinedTrustEvaluator  # todo remove pyeudiw dependency

logger = logging.getLogger(__name__)


class AuthorizationCallBackHandler(BaseEndpoint):

    def __init__(
        self,
        config: dict,
        internal_attributes: dict[str, dict[str, str | list[str]]],
        base_url: str,
        name: str,
        auth_callback_func: Callable[[Context, InternalData], Response],
        converter: AttributeMapper,
        trust_evaluator: CombinedTrustEvaluator
    ) -> None:

        super().__init__(config, internal_attributes, base_url, name, auth_callback_func, converter)

        self.httpc_params = config.get("httpc_params", {})
        self.claims = config.get("claims", {})
        self.client_assertion_type = config.get("client_assertion_type")
        self.grant_type = config.get("grant_type")
        self.jws_core = config.get("jwks_core")
        self._db_engine = OidcDbEngine(config.get("db_config", {}))
        self._db_engine.connect()
        if not self._db_engine.is_connected():
            raise StorageUnreachable
        self.configuration_plugins = self.generate_configuration_plugin(self.config)

        # Jinja2 template loader per le pagine di errore
        _template_folder = config.get(
            "template_folder",
            os.environ.get("SATOSA_TEMPLATE_FOLDER", "/satosa_proxy/templates")
        )
        _static_url = config.get(
            "static_storage_url",
            os.environ.get("SATOSA_STATIC_URL", "/static/")
        )
        if _static_url and _static_url[-1] != "/":
            _static_url += "/"
        _jinja_env = Environment(
            loader=FileSystemLoader(searchpath=_template_folder),
            autoescape=select_autoescape(["html"]),
        )
        _jinja_env.globals.update({"static": _static_url})
        self.error_page = _jinja_env.get_template(
            config.get("error_template", "spid_login_error.html")
        )

    def endpoint(self, context, *args):
        """
        Handle the authentication response from the OP.
        Args:
            context (satosa.context.Context): Satosa Context.
            *args (Any): extra arguments.
        Returns:
            Response (satosa.response.Response): Satosa Response object.
        """
        logger.debug(
            f"Entering method: {inspect.getframeinfo(inspect.currentframe()).function}. "
            f"Params [qs_params {context.qs_params}]"
        )
        if context.qs_params.get("error"):
            return self._handle_idp_error(context)

        state: str = context.qs_params.get("state")
        authorization = self.__get_authorization(state)

        if not authorization:
            logger.debug("Authorization empty")
            raise SATOSAAuthenticationError(context.state, "Authorization empty")

        # todo validate authorization ->raise exc

        code: str = context.qs_params.get("code")
        iss: str = context.qs_params.get("iss")

        if not self.__check_provider(authorization.get("provider_id"), iss):
            logger.debug("Provider ID and iss don't match")
            raise SATOSABadRequestError("Provider ID and iss don't match")

        authorization["code"] = code

        # authorization_token =  self.__create_token(authorization, code)
        if authorization["client_id"] != self.config["metadata"]["openid_relying_party"]["client_id"]:
            logger.debug("invalid request - Relying party not found")
            raise SATOSABadRequestError("Invalid relaying party")

        authorization_data = json.loads(authorization.get("data"))
        oAuth2_authorization = OAuth2AuthorizationCodeGrant(
            grant_type=self.grant_type,
            client_assertion_type=self.client_assertion_type,
            jws_core=self.jws_core,
            httpc_params=self.httpc_params,
        )

        token_response = oAuth2_authorization.access_token_request(
            redirect_uri=authorization_data["redirect_uri"],
            state=authorization.get("state"),
            code=code,
            client_id=authorization.get("client_id"),
            token_endpoint_url=authorization["provider_configuration"]["openid_provider"].get(
                "token_endpoint"
            ),
            code_verifier=authorization_data.get("code_verifier"),
        )

        if not token_response:
            logger.debug("Token response is empty")
            raise SATOSAAuthenticationError(context.state, "Token response is empty")

        jwks = get_jwks(authorization["provider_configuration"].get("openid_provider"), self.httpc_params)
        access_token = token_response["access_token"]
        id_token = token_response["id_token"]

        op_ac_jwk = get_jwk_from_jwt(access_token, jwks)
        op_id_jwk = get_jwk_from_jwt(id_token, jwks)

        if not op_ac_jwk or not op_id_jwk:
            logger.debug("AC JWK or ID JWK is empty")
            raise SATOSAAuthenticationError(context.state, "AC JWK or ID JWK is empty")

        try:
            verify_jws(access_token, op_ac_jwk, self.configuration_plugins.get_signing_alg_values_supported)
            verify_jws(id_token, op_id_jwk, self.configuration_plugins.get_signing_alg_values_supported)
        except Exception as exception:
            logger.error(f"Exception from verify_jws, detail: {exception}")
            raise SATOSAAuthenticationError(context.state, "tokens jws verification failed")

        decoded_id_token = unpad_jwt_payload(id_token)
        # logger.debug(f"Token decoded:  {decoded_id_token}")

        try:
            verify_at_hash(decoded_id_token, access_token)
        except Exception as exception:
            logger.error(f"Exception from verify_at_hash, detail: {exception}")
            raise SATOSAAuthenticationError(context.state, "tokens verification failed")

        # decoded_access_token = unpad_jwt_payload(access_token)
        # logger.debug(f"unpad_jwt_payload: {decoded_access_token}")
        self.__update_authentication_token(authorization, access_token, id_token, token_response)

        # retrieve user data
        oidc_user = OidcUserInfo(authorization["provider_configuration"].get("openid_provider"), self.jws_core,
                                 self.httpc_params)
        user_info = oidc_user.get_userinfo(
            authorization.get("state"),
            authorization.get("access_token"),
            verify=self.httpc_params["connection"].get("ssl"),
            timeout=self.httpc_params["session"].get("timeout"),
            configuration_utils=self.configuration_plugins,
        )

        if not user_info:
            logger.error(
                "User_info request failed for state: "
                f"{authorization.get('state')} to {authorization.get('provider_id')}"
            )
            raise SATOSAAuthenticationError(
                context.state,
                f"User_info request failed for state: {authorization.get('state')} "
                f"to {authorization.get('provider_id')}",
            )

        user_attrs = process_user_attributes(user_info, self.claims, authorization)
        if not user_attrs:
            logger.error(
                "No user attributes have been processed: "
                f"user_info: {user_info} claims: {self.claims} authorization: {authorization}"
            )
            raise SATOSAAuthenticationError(context.state, "No user attributes have been processed")

        user = self.__add_user(user_attrs)

        if not user:
            logger.error("User is empty")
            raise SATOSAAuthenticationError(context.state, "User is empty")

        if token_response.get('refresh_token', None):
            authorization["refresh_token"] = token_response["refresh_token"]

        authorization["user"] = user

        self.__update_authorization(authorization)

        internal_data = self._translate_response(user.model_dump(mode="json"), iss, user.sub)
        return self._auth_callback(context, internal_data)

    def _handle_idp_error(self, context) -> Response:
        """
        Gestisce gli errori restituiti dal CIE IdP al callback OIDC.

        Tenta di estrarre la redirect_uri e lo state del client OIDC originante
        dal context.state SATOSA (cookie di sessione). Se disponibili, esegue
        un redirect OIDC-conforme verso il client con i parametri di errore.
        In fallback, mostra una pagina di errore styled con i tasti Riprova e Annulla.
        """
        error = context.qs_params.get("error", "")
        description = context.qs_params.get("error_description", "Autenticazione non riuscita")
        logger.warning(f"CIE IdP returned error: {error} — {description}")

        # ── 1. Recupera redirect_uri e state del client OIDC originante ──────────
        # Il context.state SATOSA (da cookie) contiene la richiesta OIDC originale
        # con redirect_uri e state del client, esattamente come avviene nel flusso
        # di successo. Lo stesso pattern è usato in spidsaml2.py per oidc_request.
        client_redirect_uri = None
        client_state = None
        try:
            for v in context.state.values():
                if isinstance(v, dict) and "oidc_request" in v:
                    oidc_request = v.get("oidc_request") or ""
                    if oidc_request:
                        params = urllib.parse.parse_qs(oidc_request)
                        redirect_uri_list = params.get("redirect_uri")
                        state_list = params.get("state")
                        if redirect_uri_list:
                            client_redirect_uri = redirect_uri_list[0]
                            client_state = state_list[0] if state_list else None
                            break
        except Exception as exc:
            logger.warning(f"Could not extract redirect_uri from context.state: {exc}")

        # ── 2. Redirect OIDC-conforme verso il client originante ─────────────────
        if client_redirect_uri:
            oidc_error = "access_denied"
            error_params = {
                "error": oidc_error,
                "error_description": description,
            }
            if client_state:
                error_params["state"] = client_state
            cancel_url = client_redirect_uri + "?" + urllib.parse.urlencode(error_params)
            logger.info(
                f"Redirecting back to client after CIE error: "
                f"{error} → {cancel_url[:80]}..."
            )
            _js_url = json.dumps(cancel_url)
            html = (
                f"<!DOCTYPE html><html><head><meta charset='utf-8'>"
                f"<script>window.location.replace({_js_url});</script>"
                f"</head><body></body></html>"
            ).encode("utf-8")
            return Response(message=html, status="200 OK", content="text/html; charset=utf-8")

        # ── 3. Fallback: pagina di errore branded con tasti Riprova e Annulla ────
        logger.warning(
            "Could not determine client redirect_uri from context.state — "
            "showing branded error page"
        )
        if error in ("login_required", "access_denied"):
            error_type = "cancelled"
            message = "Hai annullato l'operazione di accesso con CIE."
        elif error in ("request_timeout", "interaction_required"):
            error_type = "timeout"
            message = "Il tempo a disposizione per autenticarsi è scaduto. Riprova."
        else:
            error_type = "generic"
            message = description

        cancel_url = os.environ.get("SATOSA_CANCEL_REDIRECT_URL") or "/"
        result = self.error_page.render({
            "message": message,
            "troubleshoot": f"{error}: {description}" if error_type == "generic" else "",
            "error_type": error_type,
            "cancel_url": cancel_url,
        })
        return Response(result.encode("utf-8"), content="text/html; charset=utf8", status="200 OK")


    def __get_authorization(self, state: str) -> dict:
        """
        method __get_authorization:
        This method get the state from DB.

        :type self: object
        :type state: str

        :param self: object
        :param state: str

        """
        logger.debug(
            f"Entering method: {inspect.getframeinfo(inspect.currentframe()).function}. Params [state {state}]")
        try:
            output = self._db_engine.get_sessions(state)
            if output:
                return output[0].model_dump(mode="json")
        except ValidationError as e:
            logger.debug(e)
        return {}

    def __add_user(self, user_attrs: dict) -> OidcUser | None:

        logger.debug(
            f"Entering method: {inspect.getframeinfo(inspect.currentframe()).function}. "
            f"Params [user_attrs {user_attrs}]"
        )

        # SATOSA pipeline SPID/SAML may require edupersontargetedid.
        # For CIE OIDC, use sub as stable identifier fallback.
        if "edupersontargetedid" not in user_attrs:
            sub_value = user_attrs.get("sub")
            if sub_value:
                user_attrs["edupersontargetedid"] = sub_value

        try:
            user_token = OidcUser(**user_attrs)
            user_token.attributes = user_attrs
            return user_token
        except ValidationError as e:
            logger.debug(e)
            return None

    def __update_authentication_token(
        self, authorization: dict, access_token: dict, id_token: dict, token_response: dict
    ):
        """
        method __update_authentication_token:
        This method update the authentication token. Add this properties:
            - access_token
            - id_token
            - scope
            - token_type
            - expiration
        """
        logger.debug(
            f"Entering method: {inspect.getframeinfo(inspect.currentframe()).function}. "
            f"Params [authorization {authorization}, access_token: {access_token}, "
            f"id_token: {id_token}, token_response: {token_response}]"
        )
        authorization["access_token"] = access_token
        authorization["id_token"] = id_token
        authorization["scope"] = token_response.get("scope")
        authorization["token_type"] = token_response["token_type"]
        authorization["expires_in"] = token_response["expires_in"]
        self.__update_authorization(authorization)

    def __update_authorization(self, authorization_input: dict):
        """
        method __update_authorization:
        This method update the authorization dict.

        :type self: object
        :type authorization_input: dict

        :param self: object
        :param authorization_input: dict

        """
        logger.debug(
            f"Entering method: {inspect.getframeinfo(inspect.currentframe()).function}. "
            f"Params [authorization_input {authorization_input}]"
        )

        try:
            auth_token = OidcAuthentication(**authorization_input)
            if not self._db_engine.update_session(auth_token):
                logger.error("Unable to insert the AuthenticationToken object")
        except ValidationError as e:
            logger.debug(e)

        logger.debug(
            f"Registration success for input: {authorization_input}"
        )

    def __check_provider(self, provider_is: str, iss: str) -> bool:
        """
        method __check_issuer:
        This method check if provider is equal to iss.


        :type self: object
        :type provider_is: dict
        :type iss: dict

        :param self: object
        :param provider_is: dict
        :param iss: dict

        """
        logger.debug(
            f"Entering method: {inspect.getframeinfo(inspect.currentframe()).function}. "
            f"Params [provider_is {provider_is}, iss: {iss}]"
        )

        if provider_is.endswith("/") and not iss.endswith("/"):
            iss += "/"
        elif not provider_is.endswith("/") and iss.endswith("/"):
            iss = iss[:-1]

        return provider_is == iss

    def _translate_response(self, attributes: dict, issuer: str, sub: str) -> InternalData:
        """Translates oidc response to SATOSA internal response.

        :param attributes: Dictionary with attribute name as key.
        :param issuer: The oidc op that gave the response.
        :returns: A SATOSA internal response
        """
        auth_info = AuthenticationInformation("https://www.spid.gov.it/SpidL2", str(round(time.time())), issuer)
        internal_resp = InternalData(auth_info=auth_info)
        internal_resp.attributes = self._converter.to_internal("cie_oidc", attributes)

        def _set_if_missing(key: str, value: str) -> None:
            if value and key not in internal_resp.attributes:
                internal_resp.attributes[key] = [value]

        # Defensive fallback: some SATOSA/SPID flows expect this key explicitly.
        # Ensure it is always available even if converter mapping omits it.
        if "edupersontargetedid" not in internal_resp.attributes:
            targeted_id = (
                attributes.get("edupersontargetedid")
                or attributes.get("sub")
                or sub
            )
            if targeted_id:
                internal_resp.attributes["edupersontargetedid"] = [targeted_id]

        first_name = str(attributes.get("first_name") or attributes.get("given_name") or "")
        last_name = str(attributes.get("last_name") or attributes.get("family_name") or "")
        fiscal_number = str(
            attributes.get("fiscal_number")
            or attributes.get("https://attributes.eid.gov.it/fiscal_number")
            or ""
        )

        # Frontoffice SAML callback checks multiple aliases; provide them defensively.
        _set_if_missing("first_name", first_name)
        _set_if_missing("given_name", first_name)
        _set_if_missing("givenName", first_name)
        _set_if_missing("name", first_name)
        _set_if_missing("urn:oid:2.5.4.42", first_name)

        _set_if_missing("last_name", last_name)
        _set_if_missing("family_name", last_name)
        _set_if_missing("familyName", last_name)
        _set_if_missing("sn", last_name)
        _set_if_missing("surname", last_name)
        _set_if_missing("urn:oid:2.5.4.4", last_name)

        _set_if_missing("fiscal_number", fiscal_number)
        _set_if_missing("fiscalNumber", fiscal_number)
        _set_if_missing("fiscalnumber", fiscal_number)
        _set_if_missing("FiscalNumber", fiscal_number)
        _set_if_missing("fiscalCode", fiscal_number)
        _set_if_missing("fiscal_code", fiscal_number)
        _set_if_missing("codiceFiscale", fiscal_number)
        _set_if_missing("https://attributes.eid.gov.it/fiscal_number", fiscal_number)
        _set_if_missing("https://attributes.spid.gov.it/fiscalNumber", fiscal_number)
        _set_if_missing("urn:oid:2.5.4.97", fiscal_number)
        _set_if_missing("urn:oid:1.3.6.1.4.1.4710.2.1.1", fiscal_number)

        internal_resp.subject_id = sub
        return internal_resp

    @staticmethod
    def generate_configuration_plugin(config) -> ConfigurationPlugin:
        """
        method generate_configuration_plugin:
        This method generate a ConfigurationPlugin Object for endpoint.

        """
        logger.debug(
            f"Entering method: {inspect.getframeinfo(inspect.currentframe()).function}. Params: [config: {config}]"
        )

        configuration_plugin = ConfigurationPlugin(
            config.get("default_enc_alg"),
            config.get("default_enc_enc"),
            config.get("supported_sign_alg"),
            config.get("supported_enc_alg"),
        )

        return configuration_plugin
