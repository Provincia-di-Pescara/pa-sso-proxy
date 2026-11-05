import redis
from typing import Any


def _load_model():
    try:
        from backends.cieoidc.models.oidc_auth import OidcAuthentication
        return OidcAuthentication
    except ImportError:
        from pydantic import BaseModel
        from typing import Optional

        class _Stub(BaseModel):
            id: str
            client_id: str = ""
            state: str = ""
            endpoint: str = ""
            data: Optional[dict] = None
            provider_id: str = ""
            provider_configuration: Optional[dict] = None
            user: Optional[dict] = None
            access_token: Optional[str] = None
            code: Optional[str] = None
            id_token: Optional[str] = None
            refresh_token: Optional[str] = None
            scope: Optional[str] = None
            token_type: Optional[str] = None
            expires_in: Optional[int] = None
            revoked: bool = False
            completed: bool = False

        return _Stub


class RedisStorage:
    """Duck-typed OidcStorage implementation using Redis for CIE OIDC session state."""

    def __init__(self, url: str, ttl: int = 7200):
        self._url = url
        self._ttl = ttl
        self._client = None
        self._model = None

    def connect(self) -> None:
        self._client = redis.from_url(self._url, decode_responses=False)
        self._model = _load_model()

    def close(self) -> None:
        if self._client:
            try:
                self._client.close()
            except Exception:
                pass
        self._client = None

    def is_connected(self) -> bool:
        try:
            return self._client is not None and bool(self._client.ping())
        except Exception:
            return False

    def add_session(self, entity: Any) -> int:
        data = entity.model_dump_json()
        self._client.set(f"cie:sess:{entity.id}", data, ex=self._ttl)
        self._client.set(f"cie:state:{entity.state}", entity.id, ex=self._ttl)
        return 1

    def update_session(self, entity: Any) -> int:
        key = f"cie:sess:{entity.id}"
        ttl = self._client.ttl(key)
        ex = ttl if ttl > 0 else self._ttl
        self._client.set(key, entity.model_dump_json(), ex=ex)
        return 1

    def consume_session(self, state: str) -> Any:
        """Marca come usata la sessione legata a ``state`` e la restituisce.

        Atomico tra worker e richieste concorrenti: il marker ``cie:used:<state>``
        è scritto con SET NX, solo il primo chiamante lo ottiene. Un replay (o la
        seconda di due richieste parallele) riceve None.
        """
        if not state:
            return None
        sid = self._client.get(f"cie:state:{state}")
        if not sid:
            return None
        key = f"cie:sess:{sid.decode()}"
        ttl = self._client.ttl(key)
        if not self._client.set(f"cie:used:{state}", b"1", nx=True, ex=ttl if ttl > 0 else self._ttl):
            return None
        doc = self._client.get(key)
        if not doc:
            return None
        model = self._model or _load_model()
        entity = model.model_validate_json(doc)
        if getattr(entity, "completed", False) or entity.code or entity.access_token or entity.user:
            return None
        entity.completed = True
        self.update_session(entity)
        return entity

    def get_sessions(self, state: str) -> list:
        sid = self._client.get(f"cie:state:{state}")
        if not sid:
            return []
        doc = self._client.get(f"cie:sess:{sid.decode()}")
        if not doc:
            return []
        model = self._model or _load_model()
        return [model.model_validate_json(doc)]
