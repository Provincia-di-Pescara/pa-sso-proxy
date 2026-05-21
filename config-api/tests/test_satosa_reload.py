import os
from unittest.mock import MagicMock, patch

import pytest

from app.satosa_reload import reload_satosa


def test_reload_satosa_success(tmp_path):
    with patch.dict(os.environ, {"SATOSA_CONF_DIR": str(tmp_path)}):
        result = reload_satosa()

    assert result is True
    assert (tmp_path / ".reload").exists()


def test_reload_satosa_returns_false_on_error():
    fake_path = MagicMock()
    fake_path.touch.side_effect = OSError("permission denied")

    with patch("app.satosa_reload.Path", return_value=fake_path), \
         patch.dict(os.environ, {"SATOSA_CONF_DIR": "/satosa-conf"}):
        result = reload_satosa()

    assert result is False
