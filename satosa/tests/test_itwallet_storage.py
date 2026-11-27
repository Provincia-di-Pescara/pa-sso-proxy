"""Test di backends.itwallet.itwallet_storage (storage redis per pyeudiw OpenID4VP).

Solo nel container satosa: servono pyeudiw (venv dell'immagine) e il file
montato/copiato in /satosa_proxy/backends/itwallet/itwallet_storage.py.
"""

import datetime as dt
import time

import fakeredis
import pytest
import redis

from pyeudiw.storage.base_cache import BaseCache, RetrieveStatus
from pyeudiw.storage.base_storage import BaseStorage, TrustType
from pyeudiw.storage.db_engine import DBEngine
from pyeudiw.storage.exceptions import ChainNotExist

from backends.itwallet.itwallet_storage import RedisCache, RedisStorage

MODULE = "backends.itwallet.itwallet_storage"
URL = "redis://redis:6379/3"


@pytest.fixture
def server(monkeypatch):
    """Un solo FakeServer condiviso: ogni from_url apre un client verso lo stesso redis."""
    srv = fakeredis.FakeServer()

    def _from_url(url, **kwargs):
        return fakeredis.FakeRedis(
            server=srv, decode_responses=kwargs.get("decode_responses", False)
        )

    monkeypatch.setattr(redis.Redis, "from_url", staticmethod(_from_url))
    return srv


@pytest.fixture
def raw(server):
    return fakeredis.FakeRedis(server=server, decode_responses=True)


@pytest.fixture
def storage(server):
    return RedisStorage(conf={"data_ttl": 600}, url=URL)


def _request_object(state="st-1", nonce="n-1", **extra):
    ro = {"state": state, "nonce": nonce, "exp": int(time.time()) + 300}
    ro.update(extra)
    return ro


def test_classes_implement_pyeudiw_interfaces(server):
    assert isinstance(RedisStorage(conf={}, url=URL), BaseStorage)
    assert isinstance(RedisCache(conf={}, url=URL), BaseCache)


def test_init_session_and_get_by_state(storage):
    doc_id = storage.init_session("doc-1", "sid-1", "st-1", "same_device")

    assert doc_id == "doc-1"
    doc = storage.get_by_state("st-1")
    assert doc["document_id"] == "doc-1"
    assert doc["session_id"] == "sid-1"
    assert doc["remote_flow_typ"] == "same_device"
    assert doc["finalized"] is False
    assert isinstance(doc["creation_date"], dt.datetime)
    # stessa forma dei documenti Mongo: il chiamante può leggere/cancellare _id
    assert doc["_id"] == "doc-1"


def test_get_by_state_and_session_id_checks_session(storage):
    storage.init_session("doc-1", "sid-1", "st-1", "same_device")

    assert storage.get_by_state_and_session_id("st-1", "sid-1")["document_id"] == "doc-1"
    with pytest.raises(ValueError):
        storage.get_by_state_and_session_id("st-1", "other-sid")
    with pytest.raises(ValueError):
        storage.get_by_state("missing")


def test_get_latest_by_session_id_returns_newest(storage):
    storage.init_session("doc-old", "sid-1", "st-old", "same_device")
    time.sleep(0.01)
    storage.init_session("doc-new", "sid-1", "st-new", "cross_device")
    storage.init_session("doc-other", "sid-2", "st-x", "same_device")

    assert storage.get_latest_by_session_id("sid-1")["document_id"] == "doc-new"
    assert storage.get_by_session_id("sid-1")["document_id"] == "doc-new"
    with pytest.raises(ValueError):
        storage.get_latest_by_session_id("nobody")


def test_get_by_nonce_state_and_response_kid(storage):
    storage.init_session("doc-1", "sid-1", "st-1", "same_device")
    storage.update_request_object(
        "doc-1", _request_object(), {"kty": "EC", "kid": "kid-1", "d": "secret"}
    )

    assert storage.get_by_nonce_state(nonce="n-1", state="st-1")["document_id"] == "doc-1"
    doc = storage.get_by_response_encryption_kid("kid-1")
    assert doc["document_id"] == "doc-1"
    assert doc["response_encryption_jwk"]["d"] == "secret"
    assert storage.get_by_response_encryption_kid("unknown") is None
    with pytest.raises(ValueError):
        storage.get_by_nonce_state(nonce="n-1", state="other")


def test_update_request_and_response_object_roundtrip(storage):
    storage.init_session("doc-1", "sid-1", "st-1", "same_device")
    ro = _request_object(wallet_metadata={"alg_values_supported": ["ES256"]})
    storage.update_request_object("doc-1", ro)

    doc = storage.get_by_state("st-1")
    assert doc["request_object"] == ro
    assert doc["nonce"] == "n-1"
    assert "response_encryption_jwk" not in doc

    storage.update_response_object("n-1", "st-1", {"attributes": {"given_name": ["Mario"]}})
    storage.set_finalized("doc-1")
    doc = storage.get_by_state("st-1")
    assert doc["internal_response"] == {"attributes": {"given_name": ["Mario"]}}
    assert doc["finalized"] is True

    storage.update_response_object("n-1", "st-1", {"error": "access_denied"}, True)
    assert storage.get_by_state("st-1")["error_response"] == {"error": "access_denied"}


def test_update_request_object_moves_state_index(storage):
    storage.init_session("doc-1", "sid-1", "st-1", "same_device")
    storage.update_request_object("doc-1", _request_object(state="st-2"))

    assert storage.get_by_state("st-2")["document_id"] == "doc-1"
    with pytest.raises(ValueError):
        storage.get_by_state("st-1")


def test_update_request_object_missing_document_raises(storage):
    with pytest.raises(ValueError):
        storage.update_request_object("missing", _request_object())


def test_mark_request_object_issued_only_once(storage):
    storage.init_session("doc-1", "sid-1", "st-1", "same_device")
    storage.mark_request_object_issued("doc-1", "jwt-1")

    doc = storage.get_by_state("st-1")
    assert doc["request_object_issued"] is True
    assert doc["request_object_jwt"] == "jwt-1"
    with pytest.raises(ValueError):
        storage.mark_request_object_issued("doc-1", "jwt-2")
    assert storage.get_by_state("st-1")["request_object_jwt"] == "jwt-1"


def test_consume_response_code_once_across_clients(server):
    worker_a = RedisStorage(conf={"data_ttl": 600}, url=URL)
    worker_b = RedisStorage(conf={"data_ttl": 600}, url=URL)
    worker_a.init_session("doc-1", "sid-1", "st-1", "same_device")

    assert worker_a.consume_response_code("doc-1", "code-1") is True
    assert worker_b.consume_response_code("doc-1", "code-1") is False
    assert worker_b.consume_response_code("doc-1", "code-2") is True
    # documento inesistente: come Mongo (modified_count 0) -> False
    assert worker_a.consume_response_code("missing", "code-1") is False


def test_set_finalized_missing_document_raises(storage):
    with pytest.raises(ValueError):
        storage.set_finalized("missing")


def test_session_ttl_capped_at_3600(server, raw):
    st = RedisStorage(conf={"data_ttl": 15768000}, url=URL)
    st.init_session("doc-1", "sid-1", "st-1", "same_device")
    st.update_request_object("doc-1", _request_object(), {"kid": "kid-1"})
    st.consume_response_code("doc-1", "code-1")

    keys = raw.keys("itw:*")
    assert {
        "itw:sess:doc-1",
        "itw:idx:state:st-1",
        "itw:idx:sid:sid-1",
        "itw:idx:ns:n-1:st-1",
        "itw:idx:kid:kid-1",
        "itw:rc:doc-1",
    } <= set(keys)
    for key in keys:
        assert 0 < raw.ttl(key) <= 3600, key


def test_session_ttl_default_and_key_prefix(server, raw):
    st = RedisStorage(conf={"key_prefix": "lab:"}, url=URL)
    st.init_session("doc-1", "sid-1", "st-1", "same_device")

    assert raw.keys("itw:*") == []
    assert 0 < raw.ttl("lab:sess:doc-1") <= 3600
    assert st.get_by_state("st-1")["document_id"] == "doc-1"


def test_set_session_fields(storage):
    storage.init_session("doc-1", "sid-1", "st-1", "same_device")

    assert storage.set_session_fields("doc-1", {"vci_document_id": "vci-1"}) is True
    assert storage.get_by_state("st-1")["vci_document_id"] == "vci-1"
    assert storage.set_session_fields("missing", {"a": 1}) is False
    assert storage.set_session_fields("doc-1", {}) is False


def test_trust_attestation_and_anchor_roundtrip(storage, raw):
    exp = dt.datetime.now(tz=dt.timezone.utc) + dt.timedelta(seconds=500)

    assert storage.get_trust_attestation("https://issuer.example") is None
    assert storage.has_trust_attestation("https://issuer.example") is False
    storage.add_trust_attestation(
        "https://issuer.example", ["ec-1", "ec-2"], exp, TrustType.FEDERATION, [{"kid": "k"}]
    )
    att = storage.get_trust_attestation("https://issuer.example")
    assert att["federation"]["chain"] == ["ec-1", "ec-2"]
    assert att["federation"]["exp"] == exp
    assert att["federation"]["jwks"] == [{"kid": "k"}]
    assert storage.has_trust_attestation("https://issuer.example") is True
    assert 0 < raw.ttl("itw:trust:attestation:https://issuer.example") <= 500

    storage.update_trust_attestation(
        "https://issuer.example", ["x5c-1"], exp, TrustType.X509, []
    )
    att = storage.get_trust_attestation("https://issuer.example")
    assert att["x509"]["x5c"] == ["x5c-1"]
    assert att["federation"]["chain"] == ["ec-1", "ec-2"]

    storage.add_trust_attestation_metadata("https://issuer.example", "openid_credential_issuer", {"a": 1})
    assert storage.get_trust_attestation("https://issuer.example")["metadata"] == {
        "openid_credential_issuer": {"a": 1}
    }

    with pytest.raises(ChainNotExist):
        storage.update_trust_anchor("https://ta.example", "ec", exp, TrustType.FEDERATION)
    storage.add_empty_trust_anchor("https://ta.example")
    assert storage.has_trust_anchor("https://ta.example") is True
    assert 0 < raw.ttl("itw:trust:anchor:https://ta.example") <= 86400
    storage.update_trust_anchor("https://ta.example", "ec-ta", exp, TrustType.FEDERATION)
    anchor = storage.get_trust_anchor("https://ta.example")
    assert anchor["entity_id"] == "https://ta.example"
    assert anchor["federation"]["entity_configuration"] == "ec-ta"
    assert 0 < raw.ttl("itw:trust:anchor:https://ta.example") <= 500


def test_trust_source_roundtrip_keeps_mongo_shape(storage, raw):
    soon = int(time.time()) + 700
    source = {
        "entity_id": "https://issuer.example",
        "policies": {},
        "revoked": False,
        "metadata": {"jwks": {"keys": []}},
        "direct_trust_sd_jwt_vc": {"expiration_date": soon, "jwks": []},
    }
    storage.add_trust_source(source)

    got = storage.get_trust_source("https://issuer.example")
    # pyeudiw.trust.dynamic fa `del trust_source["_id"]` prima di TrustSourceData(**...)
    del got["_id"]
    assert got == source
    assert storage.has_trust_source("https://issuer.example") is True
    assert 0 < raw.ttl("itw:trust:source:https://issuer.example") <= 700
    assert storage.get_trust_source("https://other.example") is None


def test_openid4vci_methods_are_noop(storage):
    storage.init_session("doc-1", "sid-1", "st-1", "same_device")

    assert storage.get_pending_openid4vci_by_session_id("sid-1") is None
    assert storage.abandon_openid4vci_sessions("sid-1") == 0
    assert storage.abandon_openid4vci_sessions("sid-1", except_document_id="doc-1") == 0
    assert storage.abandon_openid4vci_by_document_id("doc-1") is False


def test_search_session_by_field(storage):
    storage.init_session("doc-1", "sid-1", "st-1", "same_device")
    storage.update_request_object("doc-1", _request_object(), {"kid": "kid-1"})

    assert storage.search_session_by_field("state", "st-1")["document_id"] == "doc-1"
    assert storage.search_session_by_field("document_id", "doc-1")["document_id"] == "doc-1"
    assert storage.search_session_by_field("session_id", "sid-1")["document_id"] == "doc-1"
    assert (
        storage.search_session_by_field("response_encryption_kid", "kid-1")["document_id"]
        == "doc-1"
    )
    with pytest.raises(ValueError):
        storage.search_session_by_field("state", "missing")


def test_search_session_by_field_unindexed_raises(storage):
    storage.init_session("doc-1", "sid-1", "st-1", "same_device")

    with pytest.raises(NotImplementedError, match="auth_code"):
        storage.search_session_by_field("auth_code", "x")


def test_cache_try_retrieve_overwrite_set(server, raw):
    cache = RedisCache(conf={"data_ttl": 15768000}, url=URL)
    calls = []

    def gen():
        calls.append(1)
        return "value-1"

    obj, status = cache.try_retrieve("par_jti:c:j", gen)
    assert status is RetrieveStatus.ADDED
    assert obj["object_name"] == "par_jti:c:j"
    assert obj["data"] == "value-1"
    assert 0 < raw.ttl("itw:cache:par_jti:c:j") <= 3600

    obj, status = RedisCache(conf={}, url=URL).try_retrieve("par_jti:c:j", gen)
    assert status is RetrieveStatus.RETRIEVED
    assert obj["data"] == "value-1"
    assert len(calls) == 1

    obj = cache.overwrite("par_jti:c:j", lambda: "value-2")
    assert obj["data"] == "value-2"
    assert cache.try_retrieve("par_jti:c:j", gen)[0]["data"] == "value-2"

    cache.set({"object_name": "other", "data": "v", "creation_date": "now"})
    assert cache.try_retrieve("other", gen) == (
        {"object_name": "other", "data": "v", "creation_date": "now"},
        RetrieveStatus.RETRIEVED,
    )


def test_is_connected_false_when_redis_down():
    # niente fixture server: client redis vero verso una porta chiusa
    st = RedisStorage(
        conf={}, url="redis://127.0.0.1:1/0", connection_params={"socket_connect_timeout": 0.5}
    )
    assert st.is_connected is False


def test_is_connected_true(storage):
    assert storage.is_connected is True


def test_openid4vp_backend_with_redis_storage(server):
    init_params = {"url": URL, "conf": {"data_ttl": 600}, "connection_params": {}}
    engine = DBEngine(
        {
            "redis": {
                "cache": {"module": MODULE, "class": "RedisCache", "init_params": init_params},
                "storage": {"module": MODULE, "class": "RedisStorage", "init_params": init_params},
            }
        }
    )

    doc_id = engine.init_session(session_id="sid-1", state="st-1", remote_flow_typ="same_device")
    engine.update_request_object(doc_id, _request_object(), {"kid": "kid-1"})
    doc = engine.get_by_state("st-1")

    assert doc["document_id"] == doc_id
    assert doc["request_object"]["nonce"] == "n-1"
    assert engine.get_by_response_encryption_kid("kid-1")["document_id"] == doc_id
    assert engine.consume_response_code(doc_id, "code-1") is True
    assert engine.consume_response_code(doc_id, "code-1") is False
    assert engine.is_connected is True
    assert engine.is_par_jti_replay("client", "jti-1") is False
    assert engine.is_par_jti_replay("client", "jti-1") is True
