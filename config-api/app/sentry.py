import logging
import os

logger = logging.getLogger(__name__)


def init_sentry() -> None:
    """Inizializza Sentry SDK se SENTRY_DSN è definito nell'ambiente."""
    sentry_dsn = os.environ.get("SENTRY_DSN")
    if not sentry_dsn:
        logger.info("SENTRY_DSN non impostato, tracciamento Sentry disabilitato.")
        return

    try:
        import sentry_sdk
    except ImportError:
        logger.warning("sentry-sdk non installato nell'ambiente Python, tracciamento Sentry disabilitato.")
        return

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
    logger.info("Sentry inizializzato con successo (environment=%s)", sentry_env)
