import pytest

from app import admin_2fa, cli


class _SessionCtx:
    def __init__(self, session):
        self._session = session

    async def __aenter__(self):
        return self._session

    async def __aexit__(self, *exc):
        return False


@pytest.fixture
def cli_db(db_session, monkeypatch):
    monkeypatch.setenv("SESSION_SECRET", "test-secret-32-chars-minimum-pad")
    monkeypatch.setattr(cli, "AsyncSessionLocal", lambda: _SessionCtx(db_session))
    return db_session


async def test_reset_2fa_deletes_row(cli_db, capsys):
    await admin_2fa.get_or_create_pending(cli_db)
    assert await cli._reset_2fa() == 0
    assert await admin_2fa.get_totp(cli_db) is None
    assert "2FA admin azzerato" in capsys.readouterr().out


async def test_reset_2fa_idempotent(cli_db, capsys):
    assert await cli._reset_2fa() == 0
    assert "Nessun 2FA admin configurato" in capsys.readouterr().out


def test_main_requires_command():
    with pytest.raises(SystemExit):
        cli.main([])
