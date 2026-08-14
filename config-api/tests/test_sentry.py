import os
import sys
from unittest.mock import MagicMock, patch

# Inseriamo un mock per sentry_sdk se non installato nello stubs locale
mock_sentry_sdk = MagicMock()
sys.modules.setdefault("sentry_sdk", mock_sentry_sdk)

from app.sentry import init_sentry


def test_init_sentry_disabled():
    with patch.dict(os.environ, {}, clear=True):
        mock_sentry_sdk.reset_mock()
        init_sentry()
        mock_sentry_sdk.init.assert_not_called()


def test_init_sentry_enabled():
    env = {
        "SENTRY_DSN": "https://examplePublicKey@glitchtip.example.com/1",
        "SENTRY_ENVIRONMENT": "staging",
        "SENTRY_TRACES_SAMPLE_RATE": "0.5",
    }
    with patch.dict(os.environ, env, clear=True), \
         patch("app.version.get_display_version", return_value="v1.2.3"):
        mock_sentry_sdk.reset_mock()
        init_sentry()
        mock_sentry_sdk.init.assert_called_once_with(
            dsn="https://examplePublicKey@glitchtip.example.com/1",
            environment="staging",
            traces_sample_rate=0.5,
            release="config-api@v1.2.3",
        )


def test_init_sentry_fallback_sample_rate():
    env = {
        "SENTRY_DSN": "https://examplePublicKey@glitchtip.example.com/1",
        "SENTRY_TRACES_SAMPLE_RATE": "invalid_float",
    }
    with patch.dict(os.environ, env, clear=True), \
         patch("app.version.get_display_version", return_value="v1.2.3"):
        mock_sentry_sdk.reset_mock()
        init_sentry()
        mock_sentry_sdk.init.assert_called_once_with(
            dsn="https://examplePublicKey@glitchtip.example.com/1",
            environment="production",
            traces_sample_rate=0.1,
            release="config-api@v1.2.3",
        )
