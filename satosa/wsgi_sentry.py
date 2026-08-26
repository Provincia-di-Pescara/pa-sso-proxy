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

        release = f"satosa@{os.environ.get('APP_VERSION', 'unknown')}"

        # Bot di scansione automatica colpiscono il dominio SSO pubblico con path
        # casuali (wp-login.php, .env, .git/config, ecc.) non mappati a nessun
        # frontend/backend SATOSA. Il core SATOSA logga questi tentativi a livello
        # ERROR ("URL-path is not bound to any endpoint ..."), generando una issue
        # Sentry separata per ogni hit — rumore puro, non azionabile, non un bug
        # dell'applicativo. Il logger esatto varia a seconda del punto di codice
        # upstream che solleva l'errore, quindi filtriamo per contenuto messaggio
        # in before_send piuttosto che per nome logger.
        _NOISE_MESSAGE_SNIPPETS = (
            "is not bound to any endpoint",
        )

        def _drop_bot_scan_noise(event, hint):
            def _matches(text):
                return text and any(s in text for s in _NOISE_MESSAGE_SNIPPETS)

            message = event.get("message") or ""
            if _matches(message):
                return None

            log_entry = event.get("logentry") or {}
            if _matches(log_entry.get("message") or log_entry.get("formatted") or ""):
                return None

            for exc in (event.get("exception") or {}).get("values", []):
                if _matches(exc.get("value") or ""):
                    return None

            return event

        sentry_sdk.init(
            dsn=sentry_dsn,
            environment=sentry_env,
            traces_sample_rate=sample_rate,
            release=release,
            before_send=_drop_bot_scan_noise,
        )

        # pysaml2 (saml2.sigver) logga a livello ERROR ogni tentativo di verifica
        # firma fallito con xmlsec1 anche quando un tentativo successivo con un
        # altro certificato dell'IdP (rotazione chiave) va a buon fine — il login
        # SPID completa comunque con successo. Questo genera issue Sentry rumorose
        # e non azionabili. Il fallimento reale (nessun cert valido) è già loggato
        # esplicitamente da spidsaml2.py (SignatureError) su un logger separato.
        from sentry_sdk.integrations.logging import ignore_logger
        ignore_logger("saml2.sigver")

        logger.info("[SATOSA] Sentry inizializzato con successo (environment=%s, release=%s)", sentry_env, release)
    except ImportError:
        logger.warning("[SATOSA] sentry-sdk non installato, tracciamento Sentry disabilitato.")

from satosa.wsgi import app
