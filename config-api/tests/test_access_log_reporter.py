"""Test del modulo access_log_reporter.py generato per SATOSA.

Il modulo importa satosa (non disponibile in config-api): lo si stubba in
sys.modules e si carica il sorgente generato da _ACCESS_LOG_REPORTER_PY.
"""
import importlib.util
import sys
import types

import pytest

from app.satosa_config_generator import _ACCESS_LOG_REPORTER_PY


@pytest.fixture
def reporter(tmp_path, monkeypatch):
    base = types.ModuleType("satosa.micro_services.base")
    base.ResponseMicroService = type("ResponseMicroService", (), {"__init__": lambda self, *a, **k: None})
    for name in ("satosa", "satosa.micro_services"):
        monkeypatch.setitem(sys.modules, name, types.ModuleType(name))
    monkeypatch.setitem(sys.modules, "satosa.micro_services.base", base)
    path = tmp_path / "access_log_reporter.py"
    path.write_text(_ACCESS_LOG_REPORTER_PY, encoding="utf-8")
    spec = importlib.util.spec_from_file_location("access_log_reporter_under_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_spid_tipo4_with_company_attributes_is_pg(reporter):
    # Attributi reali da login SPID Tipo 4 (Purpose=PG): fiscalNumber = CF persona fisica.
    attrs = {
        "fiscalNumber": ["TINIT-MNTMRA03M71C615V"],
        "companyName": ["Scuola magistrale Montessori"],
        "ivaCode": ["12345678987"],
        "registeredOffice": ["Via Listz 21 00144 Roma"],
    }
    fiscal_no = reporter._first_value(attrs, ["fiscal_number", "fiscalNumber"])
    assert fiscal_no == "TINIT-MNTMRA03M71C615V"
    assert reporter._detect_user_type(attrs, fiscal_no) == "PG"


def test_iva_code_alone_is_pg(reporter):
    assert reporter._detect_user_type({"ivaCode": "VATIT-12345678987"}, "TINIT-RSSMRA80A01H501U") == "PG"


def test_citizen_is_pf(reporter):
    attrs = {"fiscalNumber": ["TINIT-RSSMRA80A01H501U"]}
    assert reporter._detect_user_type(attrs, "TINIT-RSSMRA80A01H501U") == "PF"


def test_empty_company_attributes_ignored(reporter):
    attrs = {"companyName": [""], "ivaCode": []}
    assert reporter._detect_user_type(attrs, "TINIT-RSSMRA80A01H501U") == "PF"


def test_legacy_11_digit_fiscal_number_is_pg(reporter):
    assert reporter._detect_user_type({}, "TINIT-12345678901") == "PG"


def test_no_fiscal_number_no_company_is_none(reporter):
    assert reporter._detect_user_type({}, None) is None
