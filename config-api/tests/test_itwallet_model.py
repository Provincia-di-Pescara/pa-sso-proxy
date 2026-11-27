import hmac
import hashlib

import pytest

from app.models import Base, ItWalletConfig


def test_derived_secret_stable_and_label_separated():
    from app.itwallet import derived_secret
    a = derived_secret("itwallet-response-code", 64)
    assert len(a) == 64
    assert a == derived_secret("itwallet-response-code", 64)
    assert a != derived_secret("itwallet-subject", 64)
    assert derived_secret("itwallet-subject", 16) == derived_secret("itwallet-subject", 64)[:16]
    expected = hmac.new(b"test-hash-salt", b"itwallet-response-code", hashlib.sha256).hexdigest()
    assert a == expected


def test_derived_secret_rejects_bad_length_and_missing_salt(monkeypatch):
    from app.itwallet import derived_secret
    with pytest.raises(ValueError):
        derived_secret("x", 65)
    monkeypatch.delenv("SATOSA_HASH_SALT")
    with pytest.raises(RuntimeError):
        derived_secret("x", 8)


def test_itwallet_config_table_in_metadata():
    t = Base.metadata.tables["itwallet_config"]
    assert ItWalletConfig.__tablename__ == "itwallet_config"
    expected = {
        "id", "enabled", "environment", "trust_anchor_url", "authority_hint_url",
        "trust_anchor_jwks", "jwk_federation_id", "jwk_sig_id", "jwk_enc_id",
        "organization_name", "client_name", "homepage_uri", "policy_uri", "tos_uri",
        "logo_uri", "contact_email", "trust_mark", "trust_mark_id",
    }
    assert set(t.columns.keys()) == expected
    for col in ("jwk_federation_id", "jwk_sig_id", "jwk_enc_id"):
        fks = list(t.columns[col].foreign_keys)
        assert len(fks) == 1 and fks[0].target_fullname == "jwk_keys.id"
        assert t.columns[col].nullable
    assert t.columns["enabled"].default.arg is False
    assert not t.columns["enabled"].nullable
