import base64
import json


def _make_jwt(payload: dict) -> str:
    header = base64.urlsafe_b64encode(b'{"alg":"ES256"}').rstrip(b"=").decode()
    pl = base64.urlsafe_b64encode(json.dumps(payload).encode()).rstrip(b"=").decode()
    return f"{header}.{pl}.fakesig"


def test_trust_mark_id_from_jwt_dict_tm():
    from app.satosa_config_generator import _trust_mark_id_from_jwt

    tm_id = "https://registry.servizicie.interno.gov.it/openid_relying_party/public"
    tm_jwt = _make_jwt({"id": tm_id, "iss": "issuer", "sub": "sub"})
    assert _trust_mark_id_from_jwt(tm_jwt) == tm_id


def test_trust_mark_id_from_jwt_empty():
    from app.satosa_config_generator import _trust_mark_id_from_jwt
    assert _trust_mark_id_from_jwt("") == ""
    assert _trust_mark_id_from_jwt("notajwt") == ""


def test_extract_trust_mark_dict():
    from app.trust_mark_fetcher import _extract_trust_mark, _decode_jwt_payload

    tm_id = "https://registry.example.it/tm/rp"
    tm_jwt = _make_jwt({"id": tm_id})
    entity_payload = {"trust_marks": [{"id": tm_id, "trust_mark": tm_jwt}]}
    result = _extract_trust_mark(entity_payload)
    assert result is not None
    assert result[0] == tm_id
    assert result[1] == tm_jwt


def test_extract_trust_mark_jws_string():
    from app.trust_mark_fetcher import _extract_trust_mark

    tm_id = "https://registry.example.it/tm/rp"
    # trust_mark è una stringa JWS — l'id si estrae dal suo payload
    inner_jwt = _make_jwt({"id": tm_id, "iss": "issuer"})
    entity_payload = {"trust_marks": [inner_jwt]}
    result = _extract_trust_mark(entity_payload)
    assert result is not None
    assert result[0] == tm_id


def test_extract_trust_mark_empty():
    from app.trust_mark_fetcher import _extract_trust_mark
    assert _extract_trust_mark({}) is None
    assert _extract_trust_mark({"trust_marks": []}) is None
