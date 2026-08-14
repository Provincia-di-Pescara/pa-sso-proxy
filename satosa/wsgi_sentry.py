import logging
import os

logger = logging.getLogger(__name__)

sentry_dsn = os.environ.get("SENTRY_DSN")
if sentry_dsn:
    try:
        import sentry_sdk
        sentry_env = os.environ.get("SENTRY_ENVIRONMENT", "production")
        sample_rate_str = os.environ.get("SENTRY_TRACES_SAMPLE_RATE", "0.1")
        try:
            sample_rate = float(sample_rate_str)
        except ValueError:
            sample_rate = 0.1

        sentry_sdk.init(
            dsn=sentry_dsn,
            environment=sentry_env,
            traces_sample_rate=sample_rate,
        )
        logger.info("[SATOSA] Sentry inizializzato con successo (environment=%s)", sentry_env)
    except ImportError:
        logger.warning("[SATOSA] sentry-sdk non installato, tracciamento Sentry disabilitato.")

from satosa.wsgi import app
