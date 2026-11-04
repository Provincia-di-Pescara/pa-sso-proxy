# Digest fisso (aggiornato da dependabot): ciò che è stato scansionato è ciò che gira.
FROM python:3.14-slim@sha256:930e1abba7c4e8f96ed93e8012c35d174d7732752731bbd5e8e757d7ec6f3966

WORKDIR /app

# Data del giorno passata dalla CI (build-arg): invalida la cache del layer di
# upgrade dei pacchetti di sistema almeno una volta al giorno. Senza, la cache
# GHA riusa il layer vecchio e le patch OS (es. libexpat) non arrivano finché
# non cambia l'immagine base.
ARG PKG_REFRESH=
RUN echo "pkg refresh: ${PKG_REFRESH}" && apt-get update -qq && apt-get upgrade -y -qq && apt-get install -y -qq --no-install-recommends curl && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
# Lock completo con hash (dirette + transitive): installa esattamente ciò che è
# stato verificato; --no-deps perché il lock è già chiuso, pip check lo conferma.
RUN pip install --no-cache-dir --require-hashes --no-deps -r requirements.txt \
    && pip check \
    # pip non serve a runtime (solo uvicorn nel CMD) — lo rimuoviamo insieme al suo
    # bundle vendorizzato interno (pip/_vendor/), che porta con se' copie di setuptools/
    # msgpack in versioni vulnerabili (CVE-2025-47273, GHSA-6v7p-g79w-8964) non ancora
    # aggiornate upstream in nessuna release pip disponibile (verificato: pip --upgrade
    # e' gia' l'ultima, 26.2.1). Eliminarlo fisicamente e' meglio di ignorare lo scan.
    && python -m pip uninstall -y pip setuptools

COPY . .

# Runtime non-root, stesso uid di satosa: entrambi scrivono su /satosa-conf.
# Un volume nominato vuoto prende proprietario e permessi della directory
# dell'immagine al primo mount (Docker e Podman).
RUN groupadd -r -g 10001 sso && useradd -r -u 10001 -g sso -M -d /app -s /usr/sbin/nologin sso     && mkdir -p /satosa-conf && chown 10001:10001 /satosa-conf
USER 10001:10001

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
