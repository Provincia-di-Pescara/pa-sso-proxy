"""Backend IT-Wallet (backends.itwallet.ItWalletBackend): guard persona giuridica e
collaudo, appiattimento di place_of_birth.

Solo nel container satosa (pyeudiw + albero /satosa_proxy). Il backend reale
richiede config pyeudiw completa (trust federation, storage, chiavi): per i guard
basta un'istanza senza __init__ con ``config`` impostata; la delega al padre è
verificata patchando ``OpenID4VPBackend.start_auth``.
"""

from unittest.mock import MagicMock, patch

import pytest
from markupsafe import escape
from satosa.backends.base import BackendModule
from satosa.context import Context
from satosa.internal import InternalData

from backends import i18n
from backends.itwallet import ItWalletBackend, flatten_place_of_birth
from pyeudiw.satosa.backends.openid4vp.openid4vp import OpenID4VPBackend

PARENT_START_AUTH = "pyeudiw.satosa.backends.openid4vp.openid4vp.OpenID4VPBackend.start_auth"


@pytest.fixture(autouse=True)
def _error_template(tmp_path, monkeypatch):
    (tmp_path / "spid_login_error.html").write_text(
        "{{ lang }}|{{ message }}|{{ troubleshoot }}", encoding="utf-8"
    )
    monkeypatch.setenv("SATOSA_TEMPLATE_FOLDER", str(tmp_path))


def _backend(access=None):
    backend = object.__new__(ItWalletBackend)
    backend.config = {} if access is None else {"itwallet_access": access}
    return backend


def _context(client_id="app-x", scope="openid+profile"):
    ctx = Context()
    ctx.state = {"OIDC": {"oidc_request": f"client_id={client_id}&scope={scope}&state=y"}}
    ctx.http_headers = {"HTTP_ACCEPT_LANGUAGE": "it"}
    ctx.cookie = ""
    return ctx


def _assert_error_page(resp, key):
    assert resp.status.startswith("403")
    lang, message, troubleshoot = resp.message.decode("utf-8").split("|")
    assert lang == "it"
    assert message == str(escape(i18n.t("it", key)))
    assert troubleshoot == str(escape(i18n.t("it", f"{key}.troubleshoot")))


# --- Guard --------------------------------------------------------------------

def test_legal_entity_rejected():
    backend = _backend()
    with patch(PARENT_START_AUTH) as parent:
        resp = backend.start_auth(_context(scope="openid+legal_entity"), MagicMock())
    _assert_error_page(resp, "error.legal_entity_spid_only")
    parent.assert_not_called()


def test_legal_entity_checked_before_test_only():
    """Anche un client ammesso al collaudo non passa con legal_entity."""
    backend = _backend({"test_only": True, "allowed_client_ids": ["app-x"]})
    with patch(PARENT_START_AUTH) as parent:
        resp = backend.start_auth(
            _context(client_id="app-x", scope="openid+legal_entity"), MagicMock()
        )
    _assert_error_page(resp, "error.legal_entity_spid_only")
    parent.assert_not_called()


def test_test_only_blocks_production_client():
    backend = _backend({"test_only": True, "allowed_client_ids": ["app-collaudo"]})
    with patch(PARENT_START_AUTH) as parent:
        resp = backend.start_auth(_context(client_id="app-x"), MagicMock())
    _assert_error_page(resp, "error.test_idp_verifica_only")
    parent.assert_not_called()


def test_test_only_blocks_missing_client_id():
    backend = _backend({"test_only": True, "allowed_client_ids": []})
    ctx = _context()
    ctx.state = {}
    with patch(PARENT_START_AUTH) as parent:
        resp = backend.start_auth(ctx, MagicMock())
    _assert_error_page(resp, "error.test_idp_verifica_only")
    parent.assert_not_called()


@pytest.mark.parametrize("client_id", ["__spid_verifica__", "app-collaudo"])
def test_test_only_allows_verifica_and_listed(client_id):
    backend = _backend({"test_only": True, "allowed_client_ids": ["app-collaudo"]})
    ctx = _context(client_id=client_id)
    internal_request = MagicMock()
    with patch(PARENT_START_AUTH, return_value="WALLET_PAGE") as parent:
        resp = backend.start_auth(ctx, internal_request)
    assert resp == "WALLET_PAGE"
    parent.assert_called_once_with(ctx, internal_request)


@pytest.mark.parametrize("access", [None, {"test_only": False, "allowed_client_ids": []}])
def test_production_allows_any_client(access):
    backend = _backend(access)
    ctx = _context(client_id="app-x")
    internal_request = MagicMock()
    with patch(PARENT_START_AUTH, return_value="WALLET_PAGE") as parent:
        resp = backend.start_auth(ctx, internal_request)
    assert resp == "WALLET_PAGE"
    parent.assert_called_once_with(ctx, internal_request)


# --- place_of_birth -------------------------------------------------------------

@pytest.mark.parametrize(
    "value, expected",
    [
        ({"locality": "Roma"}, ["Roma"]),
        ([{"locality": "Roma"}], ["Roma"]),
        ([{"locality": "Roma", "country": "IT"}], ["Roma"]),
        (["Roma"], ["Roma"]),
        ("Roma", "Roma"),
    ],
)
def test_flatten_place_of_birth_shapes(value, expected):
    attributes = {"placeOfBirth": value, "fiscalnumber": ["X"], "address": [{"locality": "Y"}]}
    flatten_place_of_birth(attributes)
    assert attributes["placeOfBirth"] == expected
    assert attributes["fiscalnumber"] == ["X"]
    assert attributes["address"] == [{"locality": "Y"}]


def test_flatten_place_of_birth_without_locality_drops_attribute():
    attributes = {"placeOfBirth": [{"country": "IT"}], "fiscalnumber": ["X"]}
    flatten_place_of_birth(attributes)
    assert "placeOfBirth" not in attributes
    assert attributes["fiscalnumber"] == ["X"]


def test_flatten_place_of_birth_absent_is_noop():
    attributes = {"fiscalnumber": ["X"]}
    flatten_place_of_birth(attributes)
    assert attributes == {"fiscalnumber": ["X"]}


def _base_init(self, auth_req_callback_func, internal_attributes, config, base_url, name):
    BackendModule.__init__(self, auth_req_callback_func, internal_attributes, base_url, name)
    self.config = config


def _completion_backend(config):
    satosa_callback = MagicMock(return_value="FRONTEND")
    with patch.object(OpenID4VPBackend, "__init__", _base_init):
        backend = ItWalletBackend(
            satosa_callback, {"attributes": {}}, config, "https://h", "OpenID4VP"
        )
    return backend, satosa_callback


def _internal():
    internal = InternalData()
    internal.attributes = {"placeOfBirth": [{"locality": "Roma"}], "fiscalnumber": ["X"]}
    return internal


def test_auth_callback_flattens_before_satosa():
    """Il callback dato a pyeudiw (endpoint get-response) appiattisce prima di SATOSA."""
    backend, satosa_callback = _completion_backend({})
    internal = _internal()
    ctx = _context(client_id="app-x")
    assert backend.auth_callback_func(ctx, internal) == "FRONTEND"
    satosa_callback.assert_called_once_with(ctx, internal)
    assert internal.attributes == {"placeOfBirth": ["Roma"], "fiscalnumber": ["X"]}


def test_auth_callback_rejects_client_changed_after_start():
    """Wallet avviato da /verifica, poi nello stesso browser il login di un
    applicativo di produzione sostituisce la richiesta OIDC nello stato: al
    completamento l'identità di prova non va consegnata."""
    backend, satosa_callback = _completion_backend(
        {"itwallet_access": {"test_only": True, "allowed_client_ids": []}}
    )
    ctx = _context(client_id="__spid_verifica__")
    with patch(PARENT_START_AUTH, return_value="WALLET_PAGE"):
        assert backend.start_auth(ctx, MagicMock()) == "WALLET_PAGE"
    ctx.state = {"OIDC": {"oidc_request": "client_id=app-x&scope=openid+profile&state=z"}}
    resp = backend.auth_callback_func(ctx, _internal())
    _assert_error_page(resp, "error.test_idp_verifica_only")
    satosa_callback.assert_not_called()


def test_auth_callback_rejects_legal_entity_requested_after_start():
    backend, satosa_callback = _completion_backend({})
    ctx = _context(client_id="app-x", scope="openid+legal_entity")
    resp = backend.auth_callback_func(ctx, _internal())
    _assert_error_page(resp, "error.legal_entity_spid_only")
    satosa_callback.assert_not_called()


def test_auth_callback_allows_listed_client_in_test_only():
    backend, satosa_callback = _completion_backend(
        {"itwallet_access": {"test_only": True, "allowed_client_ids": ["app-collaudo"]}}
    )
    ctx = _context(client_id="app-collaudo")
    assert backend.auth_callback_func(ctx, _internal()) == "FRONTEND"
    satosa_callback.assert_called_once()
