import logging

from app import log_filters
from app.log_filters import HealthcheckAccessFilter


def _record(method, path, status):
    return logging.LogRecord(
        "uvicorn.access", logging.INFO, __file__, 1,
        '%s - "%s %s HTTP/%s" %d', ("127.0.0.1:5000", method, path, "1.1", status), None,
    )


def test_health_ok_hidden():
    assert not HealthcheckAccessFilter().filter(_record("GET", "/health", 200))


def test_health_error_kept():
    assert HealthcheckAccessFilter().filter(_record("GET", "/health", 503))


def test_other_paths_kept():
    f = HealthcheckAccessFilter()
    assert f.filter(_record("GET", "/admin", 200))
    assert f.filter(_record("GET", "/health?x=1", 200))
    assert f.filter(_record("POST", "/health", 200))


def test_unexpected_args_kept():
    rec = logging.LogRecord("uvicorn.access", logging.INFO, __file__, 1, "msg", None, None)
    assert HealthcheckAccessFilter().filter(rec)


def test_install_idempotent():
    log_filters.install()
    log_filters.install()
    access = logging.getLogger("uvicorn.access")
    assert sum(isinstance(f, HealthcheckAccessFilter) for f in access.filters) == 1
