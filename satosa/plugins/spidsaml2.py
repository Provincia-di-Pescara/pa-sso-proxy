import inspect
import json
import logging
import re

import saml2
import satosa.util as util
from jinja2 import Environment, FileSystemLoader, select_autoescape
from saml2.authn_context import requested_authn_context
from saml2.metadata import entity_descriptor, sign_entity_descriptor
from saml2.response import StatusAuthnFailed
from saml2.saml import NAMEID_FORMAT_TRANSIENT
from saml2.sigver import SignatureError, security_context
from saml2.validate import valid_instance
from satosa.backends.saml2 import SAMLBackend
from satosa.context import Context
from satosa.exception import SATOSAAuthenticationError
from satosa.response import Response
from satosa.saml_util import make_saml_response
from six import text_type

from .spidsaml2_validator import Saml2ResponseValidator

logger = logging.getLogger(__name__)


def _post_access_log(provider_type, client_id, result, error_code=None):
    try:
        import json as _json
        import os as _os
        import urllib.request as _urlreq
        _url = _os.environ.get("CONFIG_API_INTERNAL_URL", "http://config-api:8000") + "/internal/access-log"
        _payload = _json.dumps({
            "provider_type": provider_type,
            "client_id": client_id,
            "result": result,
            "error_code": error_code,
        }).encode("utf-8")
        _req = _urlreq.Request(_url, data=_payload, headers={"Content-Type": "application/json"}, method="POST")
        _urlreq.urlopen(_req, timeout=0.5)
    except Exception:
        pass


#
# Messaggi di Errore SPID
#
# Ref: https://docs.italia.it/italia/spid/spid-regole-tecniche/it/stabile/messaggi-errore.html
#
SPID_ANOMALIES = {
    19: {
        "message": "Autenticazione fallita per ripetuta sottomissione di credenziali errate",
        "troubleshoot": "Inserire credenziali corrette",
    },
    20: {
        "message": (
            "Utente privo di credenziali compatibili con "
            "il livello di autenticazione richiesto"
        ),
        "troubleshoot": "Acquisire credenziali di livello idoneo all'accesso al servizio",
    },
    21: {
        "message": "Timeout durante l'autenticazione utente",
        "troubleshoot": (
            "Si ricorda che l'operazione di autenticazione deve "
            "essere completata entro un determinato periodo di tempo"
        ),
    },
    22: {
        "message": "L'utente nega il consenso all'invio di dati al fornitore del servizio",
        "troubleshoot": "È necessario dare il consenso per poter accedere al servizio",
    },
    23: {"message": "Utente con identità sospesa/revocata o con credenziali bloccate"},
    25: {"message": "Processo di autenticazione annullato dall'utente"},
    30: {
        "message": "L'identità digitale utilizzata non è un'identità digitale del tipo atteso",
        "troubleshoot": (
            "È necessario eseguire l'autenticazione con le credenziali "
            "del corretto tipo di identità digitale richiesto"
        ),
    },
}

_TROUBLESHOOT_MSG = (
    "È stato riscontrato un problema di validazione "
    "della risposta proveniente dal "
    "Provider di Identità. "
    " Contattare il supporto tecnico per eventuali chiarimenti"
)


class SpidSAMLBackend(SAMLBackend):
    """
    A saml2 backend module (acting as a SPID SP).
    """

    _authn_context = "https://www.spid.gov.it/SpidL1"

    def __init__(self, *args, **kwargs):

        logger.debug(
            f"Initializing: {self.__class__.__name__}. Params[args: {args}, kwargs: {kwargs}]"
        )

        super().__init__(*args, **kwargs)

        # error pages handler
        self.template_loader = Environment(
            loader=FileSystemLoader(searchpath=self.config["template_folder"]),
            autoescape=select_autoescape(["html"]),
        )
        _static_url = (
            self.config["static_storage_url"]
            if self.config["static_storage_url"][-1] == "/"
            else self.config["static_storage_url"] + "/"
        )
        self.template_loader.globals.update(
            {
                "static": _static_url,
            }
        )
        self.error_page = self.template_loader.get_template(
            self.config["error_template"]
        )

        logger.debug("inizializing metadata xmldoc")
        self.saml_base = saml2.md.SamlBase()
        self.xmldoc = self.__create_metadata(self.sp.config)

    def _metadata_contact_person(self, metadata, conf):
        logger.debug(
            f"Entering method: {inspect.getframeinfo(inspect.currentframe()).function}. "
            f"Params[ metadata: {metadata}, conf: {conf}]"
        )
        ##############
        # avviso 29 v3
        #
        # https://www.agid.gov.it/sites/default/files/repository_files/spid-avviso-n29v3-specifiche_sp_pubblici_e_privati_0.pdf
        # Avviso 29v3
        SPID_PREFIXES = dict(
            spid="https://spid.gov.it/saml-extensions",
            fpa="https://spid.gov.it/invoicing-extensions",
        )

        self.saml_base.register_prefix(SPID_PREFIXES)
        metadata.contact_person = []
        contact_map = conf.contact_person
        metadata.contact_person = []
        for contact in contact_map:
            spid_contact = saml2.md.ContactPerson()
            spid_contact.contact_type = contact["contact_type"]
            contact_kwargs = {
                key: contact[key]
                for key in ["email_address", "telephone_number", "company"]
                if key in contact
            }
            spid_extensions = saml2.ExtensionElement(
                "Extensions", namespace="urn:oasis:names:tc:SAML:2.0:metadata"
            )

            if contact["contact_type"] == "other":
                spid_contact.loadd(contact_kwargs)
                contact_kwargs["contact_type"] = contact["contact_type"]

                # Enforce specific order of SPID ContactPerson extensions
                ordered_keys = ["given_name", "FiscalCode", "IPACode", "Public"]
                ext_keys = []
                for k in contact.keys():
                    if k in contact_kwargs:
                        continue
                    if k == "Aggregated":
                        spid_contact.extension_attributes = {
                            "spid:entityType": "spid:aggregated"
                        }
                        continue
                    ext_keys.append(k)

                # Sort extension keys so they match ordered_keys, keeping other keys at the end
                def sort_key(x):
                    try:
                        return ordered_keys.index(x)
                    except ValueError:
                        return len(ordered_keys)

                ext_keys.sort(key=sort_key)

                for k in ext_keys:
                    v = contact[k]
                    # Skip empty optional elements (except for Public/Private flags which must be empty)
                    if k not in ["Public", "Private"] and not v:
                        continue
                    ext = saml2.ExtensionElement(
                        k, namespace=SPID_PREFIXES["spid"], text=v
                    )
                    # Avviso SPID n. 19 v.4 per enti AGGREGATORI il tag ContactPerson
                    # deve avere l’attributo spid:entityType valorizzato come spid:aggregator
                    if k == "PublicServicesFullAggregator":
                        spid_contact.extension_attributes = {
                            "spid:entityType": "spid:aggregator"
                        }
                    spid_extensions.children.append(ext)

                spid_contact.extensions = spid_extensions

            elif contact["contact_type"] == "billing":
                contact_kwargs["company"] = contact["company"]
                spid_contact.loadd(contact_kwargs)

                elements = {}
                for k, v in contact.items():
                    if k in contact_kwargs:
                        continue
                    ext = saml2.ExtensionElement(
                        k, namespace=SPID_PREFIXES["fpa"], text=v
                    )
                    elements[k] = ext

                # DatiAnagrafici
                IdFiscaleIVA = saml2.ExtensionElement(
                    "IdFiscaleIVA",
                    namespace=SPID_PREFIXES["fpa"],
                )
                Anagrafica = saml2.ExtensionElement(
                    "Anagrafica",
                    namespace=SPID_PREFIXES["fpa"],
                )
                Anagrafica.children.append(elements["Denominazione"])

                IdFiscaleIVA.children.append(elements["IdPaese"])
                IdFiscaleIVA.children.append(elements["IdCodice"])
                DatiAnagrafici = saml2.ExtensionElement(
                    "DatiAnagrafici",
                    namespace=SPID_PREFIXES["fpa"],
                )
                if elements.get("CodiceFiscale"):
                    DatiAnagrafici.children.append(elements["CodiceFiscale"])
                DatiAnagrafici.children.append(IdFiscaleIVA)
                DatiAnagrafici.children.append(Anagrafica)
                CessionarioCommittente = saml2.ExtensionElement(
                    "CessionarioCommittente",
                    namespace=SPID_PREFIXES["fpa"],
                )
                CessionarioCommittente.children.append(DatiAnagrafici)

                # Sede
                Sede = saml2.ExtensionElement(
                    "Sede",
                    namespace=SPID_PREFIXES["fpa"],
                )
                Sede.children.append(elements["Indirizzo"])
                Sede.children.append(elements["NumeroCivico"])
                Sede.children.append(elements["CAP"])
                Sede.children.append(elements["Comune"])
                Sede.children.append(elements["Provincia"])
                Sede.children.append(elements["Nazione"])
                CessionarioCommittente.children.append(Sede)

                spid_extensions.children.append(CessionarioCommittente)

            spid_contact.extensions = spid_extensions
            metadata.contact_person.append(spid_contact)
        #
        # fine avviso 29v3
        ###################

    def _metadata_endpoint(self, context):
        logger.debug(
            f"Entering method: {inspect.getframeinfo(inspect.currentframe()).function}. Params[ context: {context}]."
        )
        """
        Endpoint for retrieving the backend metadata
        :type context: satosa.context.Context
        :rtype: satosa.response.Response

        :param context: The current context
        :return: response with metadata
        """
        logger.debug("Sending metadata response")
        return Response(
            text_type(self.xmldoc).encode("utf-8"), content="text/xml; charset=utf8"
        )

    def get_kwargs_sign_dig_algs(self):
        logger.debug(
            f"Entering method: {inspect.getframeinfo(inspect.currentframe()).function}. Params[ self]"
        )
        kwargs = {}
        # backend support for selectable sign/digest algs
        alg_dict = dict(signing_algorithm="sign_alg",
                        digest_algorithm="digest_alg")
        for alg in alg_dict:
            selected_alg = self.config["sp_config"]["service"]["sp"].get(alg)
            if not selected_alg:
                continue
            kwargs[alg_dict[alg]] = selected_alg
        return kwargs

    def check_blacklist(self, context, entity_id):
        logger.debug(
            f"Entering method: {inspect.getframeinfo(inspect.currentframe()).function}. "
            f"Params[ context: {context}, entity_id: {entity_id}]"
        )
        # If IDP blacklisting is enabled and the selected IDP is blacklisted,
        # stop here
        if self.idp_blacklist_file:
            with open(self.idp_blacklist_file) as blacklist_file:
                blacklist_array = json.load(blacklist_file)["blacklist"]
                if entity_id in blacklist_array:
                    logger.debug(
                        "IdP with EntityID {} is blacklisted".format(entity_id)
                    )
                    raise SATOSAAuthenticationError(
                        context.state, "Selected IdP is blacklisted for this backend"
                    )

    def authn_request(self, context, entity_id):
        logger.debug(
            f"Entering method: {inspect.getframeinfo(inspect.currentframe()).function}. "
            f"Params[ context: {context}, entity_id: {entity_id}]"
        )
        """
        Do an authorization request on idp with given entity id.
        This is the start of the authorization.

        :type context: satosa.context.Context
        :type entity_id: str
        :rtype: satosa.response.Response

        :param context: The current context
        :param entity_id: Target IDP entity id
        :return: response to the user agent
        """
        self.check_blacklist(context, entity_id)
        kwargs = {}
        # fetch additional kwargs
        kwargs.update(self.get_kwargs_sign_dig_algs())

        authn_context = self.construct_requested_authn_context(entity_id)
        req_authn_context = authn_context or requested_authn_context(
            class_ref=self._authn_context
        )
        req_authn_context.comparison = self.config.get(
            "spid_acr_comparison", "minimum")

        # force_auth = true only if SpidL >= 2
        if "SpidL1" in authn_context.authn_context_class_ref[0].text:
            force_authn = "false"
        else:
            force_authn = "true"

        try:
            binding = saml2.BINDING_HTTP_POST
            destination = context.internal_data.get(
                "target_entity_id", entity_id)
            # SPID CUSTOMIZATION
            # client = saml2.client.Saml2Client(conf)
            client = self.sp

            logger.debug(f"binding: {binding}, destination: {destination}")

            # acs_endp, response_binding = self.sp.config.getattr("endpoints", "sp")["assertion_consumer_service"][0]
            # req_id, req = self.sp.create_authn_request(
            # destination, binding=response_binding, **kwargs)

            logger.debug(f"Redirecting user to the IdP via {binding} binding.")
            # use the html provided by pysaml2 if no template was specified or it didn't exist

            # SPID want the fqdn of the IDP as entityID, not the SSO endpoint
            # 'http://idpspid.testunical.it:8088'
            # dovrebbe essere destination ma nel caso di spid-testenv2 è entityid...
            # binding, destination = self.sp.pick_binding("single_sign_on_service", None, "idpsso", entity_id=entity_id)
            location = client.sso_location(destination, binding)
            # location = client.sso_location(entity_id, binding)

            # not used anymore thanks to avviso 11
            # location_fixed = destination  # entity_id
            # ...hope to see the SSO endpoint soon in spid-testenv2
            # returns 'http://idpspid.testunical.it:8088/sso'
            # fixed: https://github.com/italia/spid-testenv2/commit/6041b986ec87ab8515dd0d43fed3619ab4eebbe9

            # verificare qui
            # acs_endp, response_binding = self.sp.config.getattr("endpoints", "sp")["assertion_consumer_service"][0]

            authn_req = saml2.samlp.AuthnRequest()
            authn_req.force_authn = force_authn
            authn_req.destination = location
            # spid-testenv2 preleva l'attribute consumer service dalla authnRequest
            # (anche se questo sta già nei metadati...)
            # Imposta il consuming_service_index in base al default di ficep per le richieste ficep,
            # oppure a '0' per le richieste spid

            # Check if index is passed dynamically in the OIDC request
            custom_index = None
            for v in context.state.values():
                if isinstance(v, dict) and "oidc_request" in v:
                    oidc_request = v["oidc_request"]
                    if oidc_request:
                        try:
                            import urllib.parse
                            params = urllib.parse.parse_qs(oidc_request)
                            for key in ["attribute_consuming_service_index", "acs_index"]:
                                if key in params and params[key]:
                                    custom_index = params[key][0]
                                    break
                        except Exception as e:
                            logger.warning(f"Failed to parse oidc_request query params: {e}")
                    break

            acs_index = self.config["sp_config"].get("acs_index")

            if custom_index is not None:
                value = custom_index
            elif acs_index is not None:
                value = acs_index
            elif entity_id == self.config["sp_config"].get("ficep_entity_id"):
                value = self.config["sp_config"]["ficep_default_acs_index"]
            else:
                value = self.config["sp_config"].get("spid_default_acs_index", "0")

            authn_req.attribute_consuming_service_index = str(value)

            issuer = saml2.saml.Issuer()
            issuer.name_qualifier = client.config.entityid
            issuer.text = client.config.entityid
            issuer.format = "urn:oasis:names:tc:SAML:2.0:nameid-format:entity"
            authn_req.issuer = issuer

            # message id
            authn_req.id = saml2.s_utils.sid()
            authn_req.version = saml2.VERSION  # "2.0"
            authn_req.issue_instant = saml2.time_util.instant()

            name_id_policy = saml2.samlp.NameIDPolicy()
            # del(name_id_policy.allow_create)
            name_id_policy.format = NAMEID_FORMAT_TRANSIENT
            authn_req.name_id_policy = name_id_policy

            # TODO: use a parameter instead
            authn_req.requested_authn_context = req_authn_context
            authn_req.protocol_binding = binding

            assertion_consumer_service_url = client.config._sp_endpoints[
                "assertion_consumer_service"
            ][0][0]
            authn_req.assertion_consumer_service_url = (
                assertion_consumer_service_url  # 'http://sp-fqdn/saml2/acs/'
            )

            authn_req_signed = client.sign(
                authn_req,
                sign_prepare=False,
                sign_alg=kwargs["sign_alg"],
                digest_alg=kwargs["digest_alg"],
            )
            authn_req.id

            _req_str = authn_req_signed
            logger.debug(f"AuthRequest to {destination}: {_req_str}")

            relay_state = util.rndstr()
            ht_args = client.apply_binding(
                binding,
                _req_str,
                location,
                sign=True,
                sigalg=kwargs["sign_alg"],
                relay_state=relay_state,
            )

            if self.sp.config.getattr("allow_unsolicited", "sp") is False:
                if authn_req.id in self.outstanding_queries:
                    errmsg = "Request with duplicate id {}".format(
                        authn_req.id)
                    logger.debug(errmsg)
                    raise SATOSAAuthenticationError(context.state, errmsg)
                self.outstanding_queries[authn_req.id] = authn_req_signed

            context.state[self.name] = {"relay_state": relay_state}
            # these will give the way to check compliances between the req and resp
            context.state["req_args"] = {"id": authn_req.id}

            logger.info(f"SAMLRequest: {ht_args}")
            return make_saml_response(binding, ht_args)

        except Exception as exc:
            logger.debug("Failed to construct the AuthnRequest for state")
            raise SATOSAAuthenticationError(
                context.state, "Failed to construct the AuthnRequest"
            ) from exc

    def handle_error(
        self,
        message: str,
        troubleshoot: str = "",
        err="",
        template_path="templates",
        error_template="spid_login_error.html",
        context=None,
        error_type="generic",
    ):
        logger.debug(
            f"Entering method: {inspect.getframeinfo(inspect.currentframe()).function}. "
            f"Params[ message: {message}, troubleshoot: {troubleshoot}]"
        )
        logger.error(f"SPID authentication error: {message} {err}")

        # ── 1. Tenta redirect OIDC-conforme verso il client originante ────────────
        # Il context.state SATOSA (cookie) contiene la richiesta OIDC originale
        # con redirect_uri e state del client — stesso pattern del backend CIE.
        if context is not None:
            client_redirect_uri = None
            client_state = None
            _log_client_id = None
            try:
                import urllib.parse as _up
                for v in context.state.values():
                    if isinstance(v, dict) and "oidc_request" in v:
                        oidc_request = v.get("oidc_request") or ""
                        if oidc_request:
                            params = _up.parse_qs(oidc_request)
                            redirect_uri_list = params.get("redirect_uri")
                            state_list = params.get("state")
                            client_id_list = params.get("client_id")
                            if redirect_uri_list:
                                client_redirect_uri = redirect_uri_list[0]
                                client_state = state_list[0] if state_list else None
                            if client_id_list:
                                _log_client_id = client_id_list[0]
                        break
            except Exception as exc:
                logger.warning(f"Could not extract redirect_uri from context.state: {exc}")

            _post_access_log("spid", _log_client_id, "failure", str(err)[:64] if err else None)

            if client_redirect_uri:
                import json as _json
                error_params = {
                    "error": "access_denied",
                    "error_description": str(message),
                }
                if client_state:
                    error_params["state"] = client_state
                import urllib.parse as _up2
                cancel_url = client_redirect_uri + "?" + _up2.urlencode(error_params)
                logger.info(
                    f"Redirecting back to client after SPID error: {cancel_url[:80]}..."
                )
                _js_url = _json.dumps(cancel_url)
                html = (
                    f"<!DOCTYPE html><html><head><meta charset='utf-8'>"
                    f"<script>window.location.replace({_js_url});</script>"
                    f"</head><body></body></html>"
                ).encode("utf-8")
                return Response(message=html, status="200 OK", content="text/html; charset=utf-8")

        # ── 2. Fallback: pagina di errore branded ─────────────────────────────────
        import os as _os
        cancel_url = _os.environ.get("SATOSA_CANCEL_REDIRECT_URL") or "/"
        result = self.error_page.render(
            {
                "message": message,
                "troubleshoot": troubleshoot,
                "error_type": error_type,
                "cancel_url": cancel_url,
            }
        )
        return Response(result, content="text/html; charset=utf8", status="403")

    def handle_spid_anomaly(self, err_number, err, context=None):
        logger.debug(
            f"Entering method: {inspect.getframeinfo(inspect.currentframe()).function}. "
            f"Params[ err_number: {err_number}, err: {err}]"
        )
        return self.handle_error(**{**SPID_ANOMALIES[int(err_number)], "context": context})


    def authn_response(self, context, binding):
        logger.debug(
            f"Entering method: {inspect.getframeinfo(inspect.currentframe()).function}. "
            f"Params[ context: {context}, binding: {binding}]"
        )
        """
        Endpoint for the idp response
        :type context: satosa.context,Context
        :type binding: str
        :rtype: satosa.response.Response

        :param context: The current context
        :param binding: The saml binding type
        :return: response
        """
        if not context.request["SAMLResponse"]:
            logger.debug("Missing Response for state")
            raise SATOSAAuthenticationError(context.state, "Missing Response")

        try:
            authn_response = self.sp.parse_authn_request_response(
                context.request["SAMLResponse"],
                binding,
                outstanding=self.outstanding_queries,
            )
        except StatusAuthnFailed as err:
            erdict = re.search(r"ErrorCode nr(?P<err_code>\d+)", str(err))
            if erdict:
                return self.handle_spid_anomaly(erdict.groupdict()["err_code"], err, context=context)
            else:
                return self.handle_error(
                    **{
                        "err": err,
                        "message": "Autenticazione fallita",
                        "troubleshoot": (
                            "Anomalia riscontrata durante la fase di Autenticazione. "
                            f"{_TROUBLESHOOT_MSG}"
                        ),
                        "context": context,
                    }
                )
        except SignatureError as err:
            return self.handle_error(
                **{
                    "err": err,
                    "message": "Autenticazione fallita",
                    "troubleshoot": (
                        "La firma digitale della risposta ottenuta "
                        f"non risulta essere corretta. {_TROUBLESHOOT_MSG}"
                    ),
                    "context": context,
                }
            )
        except Exception as err:
            return self.handle_error(
                **{
                    "err": err,
                    "message": "Anomalia riscontrata nel processo di Autenticazione",
                    "troubleshoot": _TROUBLESHOOT_MSG,
                    "context": context,
                }
            )

        if self.sp.config.getattr("allow_unsolicited", "sp") is False:
            req_id = authn_response.in_response_to
            if req_id not in self.outstanding_queries:
                errmsg = ("No request with id: {}".format(req_id),)
                logger.debug(errmsg)
                return self.handle_error(
                    **{"message": errmsg, "troubleshoot": _TROUBLESHOOT_MSG, "context": context}
                )
            del self.outstanding_queries[req_id]

        # Context validation
        if not context.state.get(self.name):
            _msg = (
                f"context.state[self.name] KeyError: where self.name is {self.name}"
            )
            logger.error(_msg)
            return self.handle_error(
                **{"message": _msg, "troubleshoot": _TROUBLESHOOT_MSG, "context": context}
            )
        # check if the relay_state matches the cookie state
        if context.state[self.name]["relay_state"] != context.request["RelayState"]:
            _msg = "State did not match relay state for state"
            return self.handle_error(
                **{"message": _msg, "troubleshoot": _TROUBLESHOOT_MSG, "context": context}
            )

        # Spid and SAML2 additional tests
        _sp_config = self.config["sp_config"]
        accepted_time_diff = _sp_config["accepted_time_diff"]
        recipient = _sp_config["service"]["sp"]["endpoints"][
            "assertion_consumer_service"
        ][0][0]

        # ACR
        issuer = authn_response.response.issuer.text.strip()
        acr_map: dict = {}

        try:
            acr_map = self.config["acr_mapping"]
        except Exception:
            logger.warning(
                "acr_mapping not defined in the spid backend"
            )
            return self.handle_error(
                **{
                    "message": "acr_mapping not defined in the spid backend troubleshoot",
                    "troubleshoot": (
                        "Please contact the administrators of the platform and tell them to "
                        "configure properly the acr_mapping in the SPID/CIE backend"
                    ),
                    "context": context,
                }
            )
        acr_default = acr_map.get("", "https://www.spid.gov.it/SpidL2")
        authn_context_classref = acr_map.get(issuer, acr_default)

        # this will get the entity name in state
        if len(context.state.keys()) < 2:
            _msg = "Inconsistent context.state"
            return self.handle_error(
                **{"message": _msg, "troubleshoot": _TROUBLESHOOT_MSG, "context": context}
            )

        list(context.state.keys())[1]
        # deprecated
        # if not context.state.get('Saml2IDP'):
        # _msg = "context.state['Saml2IDP'] KeyError"
        # logger.error(_msg)
        # raise SATOSAStateError(context.state, "State without Saml2IDP")
        in_response_to = context.state["req_args"]["id"]

        # some debug
        if authn_response.ava:
            logging.debug(
                f"Attributes to {authn_response.return_addrs} "
                f"in_response_to {authn_response.in_response_to}: "
                f'{",".join(authn_response.ava.keys())}'
            )

        validator = Saml2ResponseValidator(
            authn_response=authn_response.xmlstr,
            recipient=recipient,
            in_response_to=in_response_to,
            accepted_time_diff=accepted_time_diff,
            authn_context_class_ref=authn_context_classref,
            return_addrs=authn_response.return_addrs,
            allowed_acrs=self.config["spid_allowed_acrs"],
        )
        try:
            validator.run()
        except Exception as e:
            logger.error(e)
            return self.handle_error(e, context=context)

        context.decorate(Context.KEY_BACKEND_METADATA_STORE, self.sp.metadata)
        if self.config.get(SAMLBackend.KEY_MEMORIZE_IDP):
            issuer = authn_response.response.issuer.text.strip()
            context.state[Context.KEY_MEMORIZED_IDP] = issuer
        context.state.pop(self.name, None)
        context.state.pop(Context.KEY_FORCE_AUTHN, None)

        logger.info(f"SAMLResponse{authn_response.xmlstr}")
        return self.auth_callback_func(
            context, self._translate_response(authn_response, context.state)
        )

    def _translate_response(self, response, state):
        internal_data = super()._translate_response(response, state)
        if internal_data and internal_data.attributes:
            # Extract fiscal number from spidcode if not already set (typical for eIDAS)
            if "spidcode" in internal_data.attributes and internal_data.attributes["spidcode"]:
                spid_val = internal_data.attributes["spidcode"][0]
                
                # Check if it matches eIDAS PersonIdentifier format: XX/YY/ZZ...
                import re as _re
                if _re.match(r"^[A-Z]{2}/[A-Z]{2}/", spid_val.upper()):
                    # It's an eIDAS login
                    if "TINIT-" in spid_val.upper():
                        # Italian citizen under eIDAS: extract and format as TINIT-<fiscal_code>
                        parts = spid_val.upper().split("TINIT-")
                        if len(parts) > 1:
                            fiscal_code = parts[1].strip()
                            full_fiscal = f"TINIT-{fiscal_code}"
                        else:
                            full_fiscal = spid_val
                    else:
                        # Foreign EU citizen: use the full eIDAS PersonIdentifier
                        full_fiscal = spid_val
                    
                    if "fiscalnumber" not in internal_data.attributes or not internal_data.attributes["fiscalnumber"]:
                        internal_data.attributes["fiscalnumber"] = [full_fiscal]
                    if "schacpersonaluniqueid" not in internal_data.attributes or not internal_data.attributes["schacpersonaluniqueid"]:
                        internal_data.attributes["schacpersonaluniqueid"] = [full_fiscal]
        return internal_data

    def __create_metadata(self, conf):
        """
        method __create_metadata private
        Create metadata for SpidSaml2

        :param self: Instance for SpidSaml2
        :param conf: Configuration for SpidSaml2
        :return: xmldoc
        """
        logger.debug(
            f"Entering method: {inspect.getframeinfo(inspect.currentframe()).function}. Params [conf: {conf}]"
        )
        metadata = entity_descriptor(conf)

        # creare gli attribute_consuming_service
        custom_acs = self.config["sp_config"].get("custom_attribute_consuming_services")
        if custom_acs:
            metadata.spsso_descriptor.attribute_consuming_service = []
            for idx, item in enumerate(custom_acs):
                acs = saml2.md.AttributeConsumingService()
                acs.index = str(idx)
                acs.service_name.append(saml2.md.ServiceName(lang="it", text=item.get("service_name")))
                acs.requested_attribute = [
                    saml2.md.RequestedAttribute(is_required='true', name_format=None, name=attr)
                    for attr in item.get("attributes", [])
                ]
                metadata.spsso_descriptor.attribute_consuming_service.append(acs)
        else:
            metadata.spsso_descriptor.attribute_consuming_service[0].index = '0'
            metadata.spsso_descriptor.attribute_consuming_service[0].service_name[0].lang = "it"
            metadata.spsso_descriptor.attribute_consuming_service[
                0].service_name[0].text = metadata.entity_id
            for reqattr in metadata.spsso_descriptor.attribute_consuming_service[0].requested_attribute:
                reqattr.name_format = None
                reqattr.friendly_name = None

        metadata.spsso_descriptor.assertion_consumer_service[0].index = '0'
        metadata.spsso_descriptor.assertion_consumer_service[0].is_default = 'true'

        if self.config["sp_config"]["ficep_enable"] is True:
            # ACS index 99 — eIDAS Natural Person Minimum Attribute Set.
            # Names MUST use the SPID vocabulary so the SPID validator accepts them.
            # The FICEP SP-proxy maps SPID attribute names to eIDAS internally.
            cie_99 = saml2.md.AttributeConsumingService()
            cie_99.index = '99'
            cie_99.service_name.append(saml2.md.ServiceName(lang="it", text="eIDAS Natural Person Minimum Attribute Set"))
            cie_99.requested_attribute = [
                saml2.md.RequestedAttribute(is_required='true', name_format=None, name='spidCode'),
                saml2.md.RequestedAttribute(is_required='true', name_format=None, name='name'),
                saml2.md.RequestedAttribute(is_required='true', name_format=None, name='familyName'),
                saml2.md.RequestedAttribute(is_required='true', name_format=None, name='dateOfBirth'),
            ]
            metadata.spsso_descriptor.attribute_consuming_service.append(cie_99)

            # ACS index 100 — eIDAS Natural Person Full Attribute Set.
            cie_100 = saml2.md.AttributeConsumingService()
            cie_100.index = '100'
            cie_100.service_name.append(saml2.md.ServiceName(lang="it", text="eIDAS Natural Person Full Attribute Set"))
            cie_100.requested_attribute = [
                saml2.md.RequestedAttribute(is_required='true', name_format=None, name='spidCode'),
                saml2.md.RequestedAttribute(is_required='true', name_format=None, name='name'),
                saml2.md.RequestedAttribute(is_required='true', name_format=None, name='familyName'),
                saml2.md.RequestedAttribute(is_required='true', name_format=None, name='dateOfBirth'),
                saml2.md.RequestedAttribute(is_required='true', name_format=None, name='placeOfBirth'),
                saml2.md.RequestedAttribute(is_required='true', name_format=None, name='gender'),
                saml2.md.RequestedAttribute(is_required='true', name_format=None, name='address'),
            ]
            metadata.spsso_descriptor.attribute_consuming_service.append(cie_100)



        # load ContactPerson Extensions
        self._metadata_contact_person(metadata, conf)

        # metadata signature
        secc = security_context(conf)
        #
        sign_dig_algs = self.get_kwargs_sign_dig_algs()
        eid, xmldoc = sign_entity_descriptor(
            metadata, None, secc, **sign_dig_algs)

        valid_instance(eid)

        return xmldoc
