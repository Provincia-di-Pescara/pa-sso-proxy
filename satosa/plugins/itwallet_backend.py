"""Backend IT-Wallet (OpenID4VP verifier): sottoclasse del backend pyeudiw.

COPY -> ``/satosa_proxy/backends/itwallet/__init__.py``: classe
``backends.itwallet.ItWalletBackend`` (nome backend ``OpenID4VP``, scritto dal
generatore config-api).

Aggiunge al backend upstream:

- guard persona giuridica: con scope ``legal_entity`` pagina d'errore del proxy
  ``LEGAL_ENTITY_SPID_ONLY_ERROR`` (il PID del wallet è solo persona fisica, come
  CIE ed eIDAS); controllato per primo;
- guard collaudo: ``config["itwallet_access"] = {"test_only": bool,
  "allowed_client_ids": [...]}``. Con ``test_only`` (ambiente collaudo/lab, il
  wallet accetta credenziali di prova) passano solo ``__spid_verifica__`` e i
  client in lista (il generatore ci mette ``__admin_test__`` e i client con
  ``allow_test_idps``), gli altri -> ``TEST_IDP_VERIFICA_ONLY_ERROR``. Chiave
  assente = produzione, tutti ammessi. Vale anche per l'URL di login aperto a
  mano (``start_auth`` è l'unico ingresso dal router);
- ``place_of_birth``: la credenziale PID lo porta come oggetto
  (``{"locality": "Roma", ...}``), il mapper SATOSA lo copia così com'è
  (``[{"locality": "Roma"}]`` sul claim OIDC). Lo appiattiamo alla ``locality``
  nel callback verso SATOSA (vedi ``_auth_callback_to_satosa``).
"""

import logging

from pyeudiw.satosa.backends.openid4vp.openid4vp import OpenID4VPBackend

from ..proxy_errors import render_proxy_error
from ..spidsaml2 import (
    LEGAL_ENTITY_SPID_ONLY_ERROR,
    TEST_IDP_VERIFICA_ONLY_ERROR,
    VERIFICA_CLIENT_ID,
    _legal_entity_requested,
    _requesting_client_id,
)

logger = logging.getLogger(__name__)

# Nome interno (internal_attributes.yaml) del luogo di nascita.
PLACE_OF_BIRTH_ATTRIBUTE = "placeOfBirth"


def _locality(value):
    if isinstance(value, dict):
        return value.get("locality") or None
    return value


def flatten_place_of_birth(attributes: dict) -> dict:
    """Sostituisce in ``attributes`` (interni, in place) ``placeOfBirth`` oggetto o
    lista di oggetti con la lista delle ``locality`` (stringhe, come SPID).

    Valori già stringa restano come sono; senza nessuna ``locality`` l'attributo
    è rimosso (meglio assente che un oggetto nel claim). Altri attributi intatti.
    """
    value = attributes.get(PLACE_OF_BIRTH_ATTRIBUTE)
    if value is None or isinstance(value, str):
        return attributes
    items = value if isinstance(value, list) else [value]
    flattened = [loc for loc in (_locality(item) for item in items) if loc]
    if flattened:
        attributes[PLACE_OF_BIRTH_ATTRIBUTE] = flattened
    else:
        del attributes[PLACE_OF_BIRTH_ATTRIBUTE]
    return attributes


class ItWalletBackend(OpenID4VPBackend):

    def __init__(self, auth_req_callback_func, internal_attributes, config, base_url, name):
        # pyeudiw passa self.auth_callback_func agli endpoint in register_endpoints;
        # l'unico che lo chiama è get-response (fine del flusso, stesso o altro
        # dispositivo), con l'InternalData riletto dallo storage. Avvolgerlo qui
        # copre tutti i percorsi senza ridefinire endpoint upstream.
        self._satosa_auth_callback = auth_req_callback_func
        super().__init__(self._auth_callback_to_satosa, internal_attributes, config, base_url, name)

    def _auth_callback_to_satosa(self, context, internal_response):
        flatten_place_of_birth(internal_response.attributes)
        return self._satosa_auth_callback(context, internal_response)

    def _client_allowed(self, context) -> bool:
        access = self.config.get("itwallet_access") or {}
        if not access.get("test_only"):
            return True
        client_id = _requesting_client_id(context)
        if not client_id:
            return False
        return client_id == VERIFICA_CLIENT_ID or client_id in (access.get("allowed_client_ids") or [])

    def start_auth(self, context, internal_request):
        if _legal_entity_requested(context):
            logger.warning("IT-Wallet richiesto con scope legal_entity: rifiutato (solo SPID)")
            return render_proxy_error(context, LEGAL_ENTITY_SPID_ONLY_ERROR)
        if not self._client_allowed(context):
            logger.warning(
                "IT-Wallet di collaudo richiesto dal client %r non autorizzato: rifiutato",
                _requesting_client_id(context),
            )
            return render_proxy_error(context, TEST_IDP_VERIFICA_ONLY_ERROR)
        return super().start_auth(context, internal_request)
