"""Storage redis per pyeudiw (backend IT-Wallet OpenID4VP) al posto di MongoDB.

Caricato da ``pyeudiw.storage.db_engine.DBEngine`` tramite la config::

    storage:
      redis:
        cache:   {module: backends.itwallet.itwallet_storage, class: RedisCache,
                  init_params: {url: ..., conf: {...}, connection_params: {...}}}
        storage: {module: backends.itwallet.itwallet_storage, class: RedisStorage,
                  init_params: {url: ..., conf: {...}, connection_params: {...}}}

``conf``: ``data_ttl`` (secondi, default e tetto 3600: le sessioni VP durano
minuti, il valore di esempio upstream di 6 mesi non ha senso qui) e
``key_prefix`` (default ``itw:``).

Censimento pyeudiw 2.9.0 (immagine iam-proxy-italia v3.9.0)
----------------------------------------------------------
Metodi chiamati dal backend VP (``pyeudiw/satosa/backends/openid4vp/endpoints``),
tutti tramite ``DBEngine``:

- ``init_session`` (pre_request), ``get_pending_openid4vci_by_session_id`` +
  ``set_session_fields`` (pre_request, solo se c'è una sessione VCI pendente);
- ``get_by_state``, ``get_latest_by_session_id``, ``update_request_object``,
  ``mark_request_object_issued`` (request);
- ``get_by_state``, ``get_by_nonce_state`` (via ``update_response_object``),
  ``set_finalized``, ``get_by_response_encryption_kid``,
  ``abandon_openid4vci_*`` (via ``DBEngine.abandon_linked_openid4vci``) (response);
- ``get_by_state_and_session_id``, ``consume_response_code`` (get_response);
- ``get_latest_by_session_id`` (status); ``is_connected``.

Trust (``pyeudiw/trust/dynamic.py``): ``get_trust_source``/``add_trust_source``
(il chiamante fa ``del trust_source["_id"]``: ``_id`` va restituito).
``AnchorsLoader`` (anchor) non è chiamato da nessuno in 2.9.0; attestation e
anchor sono implementati per completezza dell'interfaccia trust.
Cache: solo ``DBEngine.is_par_jti_replay`` (frontend OpenID4VCI) usa
``try_retrieve``; ``DBEngine.try_retrieve`` ha la condizione invertita e non
tocca mai le cache.

``search_session_by_field``: il backend VP non lo chiama. Lo usa solo il
frontend OpenID4VCI (campi ``request_uri_part``, ``access_token_jti``,
``auth_code``, scritti con ``upsert_session_by_document_id``), non supportato
qui. Campi indicizzati: ``document_id``, ``state``, ``session_id``,
``response_encryption_kid``; altri campi -> ``NotImplementedError``.

Eccezioni allineate a ``MongoStorage``: documento di sessione assente ->
``ValueError`` (gli endpoint VP lo mappano su 401), trust assente -> ``None``
(``DBEngine.get`` lo trasforma in ``EntryNotFound``).

Divergenze note da ``MongoStorage``:

- ``get_by_nonce_state(nonce, state=None)`` solleva ``ValueError``; Mongo ricade
  sulla ricerca per solo ``nonce``. Nessun chiamante di pyeudiw 2.9.0 passa
  ``state=None`` (``update_response_object`` riceve sempre lo ``state``).
- ``add_trust_attestation_metadata`` su entità assente solleva ``ChainNotExist``
  (che ``DBEngine`` intercetta); Mongo solleva ``ValueError``.

Chiavi (con prefisso ``itw:``): ``sess:<document_id>`` (JSON),
``idx:state:<state>``, ``idx:sid:<session_id>`` (sorted set per data),
``idx:ns:<nonce>:<state>``, ``idx:kid:<kid>``, ``rc:<document_id>`` (codici di
risposta consumati), tutte con la scadenza della sessione;
``trust:<attestation|anchor|source>:<entity_id>`` (TTL = ``exp`` se presente,
altrimenti 86400); ``cache:<object_name>``.
"""

from __future__ import annotations

import datetime as dt
import json
import time
from typing import Any, Callable

import redis

from pyeudiw.storage.base_cache import BaseCache, RetrieveStatus
from pyeudiw.storage.base_storage import (
    BaseStorage,
    TrustType,
    trust_anchor_field_map,
    trust_attestation_field_map,
    trust_type_map,
)
from pyeudiw.storage.exceptions import ChainNotExist

MAX_TTL = 3600
TRUST_DEFAULT_TTL = 86400
DEFAULT_PREFIX = "itw:"
_WATCH_RETRIES = 3
_DT_TAG = "__datetime__"

# campo -> indice stringa (valore -> document_id) aggiornato a ogni scrittura
_STRING_INDEXES = {
    "state": lambda d: d.get("state"),
    "kid": lambda d: d.get("response_encryption_kid"),
    "ns": lambda d: (
        f"{d['nonce']}:{d['state']}" if d.get("nonce") and d.get("state") else None
    ),
}


def _json_default(obj: Any) -> Any:
    if isinstance(obj, dt.datetime):
        return {_DT_TAG: obj.isoformat()}
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")


def _json_hook(obj: dict) -> Any:
    if len(obj) == 1 and _DT_TAG in obj:
        return dt.datetime.fromisoformat(obj[_DT_TAG])
    return obj


def _dumps(data: Any) -> str:
    return json.dumps(data, default=_json_default)


def _loads(raw: str | None) -> Any:
    return None if raw is None else json.loads(raw, object_hook=_json_hook)


def _ttl_from_conf(conf: dict | None) -> int:
    ttl = (conf or {}).get("data_ttl") or MAX_TTL
    return max(1, min(int(ttl), MAX_TTL))


def _client(url: str, connection_params: dict | None) -> redis.Redis:
    params = dict(connection_params or {})
    params.setdefault("socket_connect_timeout", 5)
    params.setdefault("socket_timeout", 5)
    params["decode_responses"] = True
    return redis.Redis.from_url(url, **params)


class RedisStorage(BaseStorage):
    """Sessioni OpenID4VP e materiale di trust di pyeudiw su redis."""

    def __init__(self, conf: dict, url: str, connection_params: dict | None = None) -> None:
        super().__init__()
        self.storage_conf = conf or {}
        self.url = url
        self.connection_params = connection_params
        self.prefix = self.storage_conf.get("key_prefix") or DEFAULT_PREFIX
        self.ttl = _ttl_from_conf(self.storage_conf)
        self.client = _client(url, connection_params)

    # -- connessione -------------------------------------------------------

    @property
    def is_connected(self) -> bool:
        try:
            return bool(self.client.ping())
        except Exception:
            return False

    def _connect(self) -> None:
        """Il client redis apre la connessione al primo comando."""

    def close(self) -> None:
        self.client.close()

    def set_session_retention_ttl(self, ttl: int) -> None:
        self.ttl = _ttl_from_conf({"data_ttl": ttl})

    def has_session_retention_ttl(self) -> bool:
        return True

    # -- chiavi ------------------------------------------------------------

    def _k(self, *parts: str) -> str:
        return self.prefix + ":".join(parts)

    def _sess_key(self, document_id: str) -> str:
        return self._k("sess", document_id)

    def _index_keys(self, doc: dict) -> set[str]:
        keys = set()
        for name, extract in _STRING_INDEXES.items():
            value = extract(doc)
            if value:
                keys.add(self._k("idx", name, value))
        return keys

    # -- lettura sessioni --------------------------------------------------

    def _load(self, document_id: str | None) -> dict | None:
        if not document_id:
            return None
        return _loads(self.client.get(self._sess_key(document_id)))

    def _by_index(self, name: str, value: str) -> dict | None:
        return self._load(self.client.get(self._k("idx", name, value)))

    def get_by_id(self, document_id: str) -> dict:
        document = self._load(document_id)
        if document is None:
            raise ValueError(f"Document with id {document_id} not found")
        return document

    def get_by_state(self, state: str) -> dict:
        return self.get_by_state_and_session_id(state)

    def get_by_state_and_session_id(self, state: str, session_id: str = "") -> dict:
        document = self._by_index("state", state)
        if document is None or (session_id and document.get("session_id") != session_id):
            raise ValueError(f"Document with state {state} not found.")
        return document

    def get_by_nonce_state(self, nonce: str, state: str | None) -> dict:
        document = self._by_index("ns", f"{nonce}:{state}") if state else None
        if document is None:
            raise ValueError(f"Document with nonce {nonce} and state {state} not found")
        return document

    def get_latest_by_session_id(self, session_id: str) -> dict:
        for document_id in self.client.zrevrange(self._k("idx", "sid", session_id), 0, -1):
            document = self._load(document_id)
            if document is not None:
                return document
        raise ValueError(f"Document with session id {session_id} not found.")

    def get_by_session_id(self, session_id: str) -> dict:
        return self.get_latest_by_session_id(session_id)

    def get_by_response_encryption_kid(self, kid: str) -> dict | None:
        return self._by_index("kid", kid)

    def search_session_by_field(self, field: str, value: str) -> dict:
        if field == "document_id":
            return self.get_by_id(value)
        if field == "state":
            return self.get_by_state(value)
        if field == "session_id":
            return self.get_latest_by_session_id(value)
        if field == "response_encryption_kid":
            document = self.get_by_response_encryption_kid(value)
            if document is None:
                raise ValueError(f"Document with {field} {value} not found.")
            return document
        raise NotImplementedError(
            f"search_session_by_field: campo non indicizzato nello storage redis: {field}"
        )

    # -- scrittura sessioni ------------------------------------------------

    def init_session(
        self, document_id: str, session_id: str, state: str, remote_flow_typ: str
    ) -> str:
        now = dt.datetime.now(tz=dt.timezone.utc)
        entity = {
            "_id": document_id,
            "document_id": document_id,
            "creation_date": now,
            "state": state,
            "session_id": session_id,
            "remote_flow_typ": remote_flow_typ,
            "finalized": False,
            "internal_response": None,
        }
        sid_key = self._k("idx", "sid", session_id)
        pipe = self.client.pipeline(transaction=True)
        pipe.set(self._sess_key(document_id), _dumps(entity), ex=self.ttl)
        for key in self._index_keys(entity):
            pipe.set(key, document_id, ex=self.ttl)
        pipe.zadd(sid_key, {document_id: now.timestamp()})
        pipe.expire(sid_key, self.ttl)
        pipe.execute()
        return document_id

    def _update(self, document_id: str, mutate: Callable[[dict], dict | None]) -> dict:
        """Read-modify-write atomico (WATCH/MULTI) del documento e dei suoi indici.

        ``mutate`` riceve il documento e restituisce i campi da impostare, oppure
        solleva per annullare. Documento assente -> ValueError.
        """
        key = self._sess_key(document_id)
        for _ in range(_WATCH_RETRIES):
            with self.client.pipeline(transaction=True) as pipe:
                try:
                    pipe.watch(key)
                    document = _loads(pipe.get(key))
                    if document is None:
                        raise ValueError(f"Document with id {document_id} not found")
                    pttl = pipe.pttl(key)
                    ttl_ms = pttl if pttl > 0 else self.ttl * 1000
                    old_indexes = self._index_keys(document)
                    document.update(mutate(document) or {})
                    new_indexes = self._index_keys(document)
                    stale = [
                        k for k in old_indexes - new_indexes if pipe.get(k) == document_id
                    ]

                    pipe.multi()
                    pipe.set(key, _dumps(document), keepttl=True)
                    for index_key in stale:
                        pipe.delete(index_key)
                    for index_key in new_indexes - old_indexes:
                        pipe.set(index_key, document_id, px=ttl_ms)
                    pipe.execute()
                    return document
                except redis.WatchError:
                    continue
        raise redis.WatchError(f"Concurrent updates on document {document_id}")

    def update_request_object(
        self,
        document_id: str,
        request_object: dict,
        response_encryption_jwk: dict | None = None,
    ) -> dict:
        fields = {
            "request_object": request_object,
            "nonce": request_object["nonce"],
            "state": request_object["state"],
        }
        if response_encryption_jwk:
            fields["response_encryption_jwk"] = response_encryption_jwk
            fields["response_encryption_kid"] = response_encryption_jwk.get("kid")
        return self._update(document_id, lambda _doc: fields)

    def mark_request_object_issued(self, document_id: str, request_object_jwt: str) -> dict:
        def _mutate(document: dict) -> dict:
            if document.get("request_object_issued") is True:
                raise ValueError(f"Request object for document {document_id} is already issued.")
            return {"request_object_issued": True, "request_object_jwt": request_object_jwt}

        return self._update(document_id, _mutate)

    def consume_response_code(self, document_id: str, response_code: str) -> bool:
        pttl = self.client.pttl(self._sess_key(document_id))
        if pttl == -2:
            return False
        rc_key = self._k("rc", document_id)
        pipe = self.client.pipeline(transaction=True)
        pipe.sadd(rc_key, response_code)
        pipe.pexpire(rc_key, pttl if pttl > 0 else self.ttl * 1000)
        added, _ = pipe.execute()
        return added == 1

    def set_finalized(self, document_id: str) -> dict:
        return self._update(document_id, lambda _doc: {"finalized": True})

    def update_response_object(
        self, nonce: str, state: str, internal_response: dict, isError: bool = False
    ) -> dict:
        document = self.get_by_nonce_state(nonce, state)
        label = "error_response" if isError else "internal_response"
        return self._update(document["document_id"], lambda _doc: {label: internal_response})

    def set_session_fields(self, document_id: str, fields: dict) -> bool:
        if not fields:
            return False
        try:
            self._update(document_id, lambda _doc: fields)
        except ValueError:
            return False
        return True

    # OpenID4VCI (frontend) non usato: nessuna sessione VCI in questo storage.
    def get_pending_openid4vci_by_session_id(self, session_id: str) -> dict | None:
        return None

    def abandon_openid4vci_sessions(
        self, session_id: str, except_document_id: str | None = None
    ) -> int:
        return 0

    def abandon_openid4vci_by_document_id(self, document_id: str) -> bool:
        return False

    # -- trust ---------------------------------------------------------------

    def _trust_key(self, kind: str, entity_id: str) -> str:
        return self._k("trust", kind, entity_id)

    def _get_trust(self, kind: str, entity_id: str) -> dict | None:
        return _loads(self.client.get(self._trust_key(kind, entity_id)))

    def _put_trust(self, kind: str, entity: dict, exp: Any = None) -> str:
        entity_id = entity["entity_id"]
        entity["_id"] = entity_id
        ttl = TRUST_DEFAULT_TTL
        if isinstance(exp, dt.datetime):
            # naive = ora locale, come datetime.fromtimestamp() usato da pyeudiw
            ttl = int(exp.timestamp() - time.time())
        elif isinstance(exp, (int, float)) and not isinstance(exp, bool):
            ttl = int(exp - time.time())
        self.client.set(self._trust_key(kind, entity_id), _dumps(entity), ex=max(1, ttl))
        return entity_id

    def get_trust_attestation(self, entity_id: str) -> dict | None:
        return self._get_trust("attestation", entity_id)

    def get_trust_anchor(self, entity_id: str) -> dict | None:
        return self._get_trust("anchor", entity_id)

    def get_trust_source(self, entity_id: str) -> dict | None:
        return self._get_trust("source", entity_id)

    def has_trust_attestation(self, entity_id: str) -> bool:
        return self.get_trust_attestation(entity_id) is not None

    def has_trust_anchor(self, entity_id: str) -> bool:
        return self.get_trust_anchor(entity_id) is not None

    def has_trust_source(self, entity_id: str) -> bool:
        return self.get_trust_source(entity_id) is not None

    @staticmethod
    def _set_attestation(entity, attestation, exp, trust_type: TrustType, jwks) -> dict:
        trust_name = trust_type_map[trust_type]
        trust_field = trust_attestation_field_map.get(trust_type)
        trust_entity = entity.get(trust_name, {})
        if trust_field and attestation:
            trust_entity[trust_field] = attestation
        if exp:
            trust_entity["exp"] = exp
        if jwks:
            trust_entity["jwks"] = jwks
        entity[trust_name] = trust_entity
        return entity

    def add_trust_attestation(
        self, entity_id: str, attestation: list[str], exp, trust_type: TrustType, jwks
    ) -> str:
        entity = {
            "entity_id": entity_id,
            "federation": {},
            "x509": {},
            "direct_trust_sd_jwt_vc": {},
            "metadata": {},
        }
        self._set_attestation(entity, attestation, exp, trust_type, jwks)
        return self._put_trust("attestation", entity, exp)

    def update_trust_attestation(
        self, entity_id: str, attestation: list[str], exp, trust_type: TrustType, jwks
    ) -> str:
        entity = self.get_trust_attestation(entity_id) or {"entity_id": entity_id}
        self._set_attestation(entity, attestation, exp, trust_type, jwks)
        return self._put_trust("attestation", entity, exp)

    def add_trust_attestation_metadata(
        self, entity_id: str, metadata_type: str, metadata: dict
    ) -> str:
        entity = self.get_trust_attestation(entity_id)
        if entity is None:
            raise ChainNotExist(f"Chain with entity id {entity_id} not exist")
        entity.setdefault("metadata", {})[metadata_type] = metadata
        ttl = self.client.ttl(self._trust_key("attestation", entity_id))
        return self._put_trust("attestation", entity, time.time() + ttl if ttl > 0 else None)

    def add_empty_trust_anchor(self, entity_id: str) -> str:
        return self._put_trust("anchor", {"entity_id": entity_id, "federation": {}, "x509": {}})

    def _set_anchor(self, entity, entity_configuration, exp, trust_type) -> str:
        trust_name = trust_type_map[trust_type]
        trust_field = trust_anchor_field_map.get(trust_type)
        trust_entity = entity.get(trust_name, {})
        if trust_field and entity_configuration:
            trust_entity[trust_field] = entity_configuration
        trust_entity["exp"] = exp
        entity[trust_name] = trust_entity
        return self._put_trust("anchor", entity, exp)

    def add_trust_anchor(self, entity_id: str, entity_configuration, exp, trust_type: TrustType):
        entity = {"entity_id": entity_id, "federation": {}, "x509": {}}
        return self._set_anchor(entity, entity_configuration, exp, trust_type)

    def update_trust_anchor(self, entity_id: str, entity_configuration, exp, trust_type: TrustType):
        entity = self.get_trust_anchor(entity_id)
        if entity is None:
            raise ChainNotExist(f"Chain with entity id {entity_id} not exist")
        return self._set_anchor(entity, entity_configuration, exp, trust_type)

    def add_trust_source(self, trust_source: dict) -> str:
        entity = self.get_trust_source(trust_source["entity_id"]) or {}
        entity.update(trust_source)
        expirations = [
            v["expiration_date"]
            for v in entity.values()
            if isinstance(v, dict) and isinstance(v.get("expiration_date"), (int, float))
        ]
        return self._put_trust("source", entity, min(expirations) if expirations else None)


class RedisCache(BaseCache):
    """Cache pyeudiw su redis (oggetti ``{object_name, data, creation_date}``)."""

    def __init__(self, conf: dict, url: str, connection_params: dict | None = None) -> None:
        super().__init__()
        self.storage_conf = conf or {}
        self.url = url
        self.connection_params = connection_params
        self.prefix = self.storage_conf.get("key_prefix") or DEFAULT_PREFIX
        self.ttl = _ttl_from_conf(self.storage_conf)
        self.client = _client(url, connection_params)

    def _key(self, object_name: str) -> str:
        return f"{self.prefix}cache:{object_name}"

    def _connect(self) -> None:
        """Il client redis apre la connessione al primo comando."""

    def close(self) -> None:
        self.client.close()

    @staticmethod
    def _object(object_name: str, data: Any) -> dict:
        return {
            "object_name": object_name,
            "data": data,
            "creation_date": dt.datetime.now().isoformat(),
        }

    def try_retrieve(
        self, object_name: str, on_not_found: Callable[[], str]
    ) -> tuple[dict, RetrieveStatus]:
        key = self._key(object_name)
        cached = _loads(self.client.get(key))
        if cached is not None:
            return cached, RetrieveStatus.RETRIEVED
        cache_object = self._object(object_name, on_not_found())
        if self.client.set(key, _dumps(cache_object), ex=self.ttl, nx=True):
            return cache_object, RetrieveStatus.ADDED
        # un altro worker l'ha scritto nel frattempo: vale il suo
        return _loads(self.client.get(key)), RetrieveStatus.RETRIEVED

    def overwrite(self, object_name: str, value_gen_fn: Callable[[], str]) -> dict:
        cache_object = self._object(object_name, value_gen_fn())
        self.client.set(self._key(object_name), _dumps(cache_object), ex=self.ttl)
        return cache_object

    def set(self, data: dict) -> dict:
        self.client.set(self._key(data["object_name"]), _dumps(data), ex=self.ttl)
        return data
