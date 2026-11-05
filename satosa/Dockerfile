# Digest fisso: aggiornato da dependabot con una PR (revisione manuale, vedi
# dependabot-automerge.yml). Deve corrispondere a IAM_PROXY_REF qui sotto:
# venv dell'immagine e codice clonato vengono dalla stessa release upstream.
FROM ghcr.io/italia/iam-proxy-italia:latest@sha256:aa3660abdad8ddb715fedc4abfda8a66133cec48e8c0c1886a5b83728edce572

USER root

# Versione applicativo (tag git / sha) iniettata a build-time, usata come
# Sentry "release" per raggruppare gli errori per versione deployata.
ARG APP_VERSION=unknown
ENV APP_VERSION=${APP_VERSION}

# Base image contains only /.venv/ — no project files. Clone them.
# Alpine-based image — use apk
# Data del giorno passata dalla CI (build-arg): invalida la cache del layer di
# upgrade dei pacchetti di sistema almeno una volta al giorno. Senza, la cache
# GHA riusa il layer vecchio e le patch OS (es. libexpat) non arrivano finché
# non cambia l'immagine base.
ARG PKG_REFRESH=
RUN echo "pkg refresh: ${PKG_REFRESH}" && apk update && apk upgrade --no-cache
RUN apk add --no-cache git

# Non visto da dependabot: upstream-check.yml apre una issue a ogni nuova release.
ARG IAM_PROXY_REF=v3.4.0
RUN git clone --depth 1 --branch "${IAM_PROXY_REF}" \
        https://github.com/italia/iam-proxy-italia.git /tmp/upstream \
    && cp -r /tmp/upstream/iam-proxy-italia-project/. /satosa_proxy/ \
    && rm -rf /tmp/upstream

# Install redis client and sentry-sdk inside the venv
# Versioni in requirements-runtime.txt (aggiornate da dependabot).
#
# Il venv upstream porta tool di sviluppo/packaging mai usati a runtime
# (poetry, pipx, flake8, pdbpp, …) con le loro dipendenze, più pacchetti
# orfani (pillow, satosa-oidcop/idpyoidc: il frontend OIDC qui è pyop, httpx:
# import solo opzionali in sentry-sdk/dnspython). Rimossi: meno superficie e
# meno CVE (pillow CRITICAL, dulwich/virtualenv/msgpack/soupsieve HIGH).
# Lista = pacchetti non raggiungibili dalle radici (satosa, pyeudiw, redis,
# sentry-sdk, uwsgi) né importati da /satosa_proxy o satosa/plugins.
# device-detector/regex restano: pyeudiw/tools/mobile.py li importa.
# pip rimosso per ultimo (dopo pip check): da 26.3 Trivy segnala il
# pkg_resources vendorizzato (setuptools 70.3.0, CVE-2025-47273, codice non
# vendorizzato) senza percorso, quindi non ignorabile per path. La CI dei test
# lo reinstalla nel container con `python -m ensurepip`.
# Lock con hash (requirements-runtime.txt, da .in): --no-deps perché il resto
# del venv viene dall'immagine upstream; pip check alla fine verifica che le
# versioni fissate e le rimozioni non rompano le dipendenze dei pacchetti tenuti.
COPY requirements-runtime.txt /tmp/requirements-runtime.txt
RUN . /.venv/bin/activate && pip install --require-hashes --no-deps -r /tmp/requirements-runtime.txt --quiet \
    && pip uninstall -y --quiet \
        pillow \
        poetry poetry-core pipx flake8 pdbpp \
        satosa-oidcop idpyoidc \
        httpx httpcore httpx2 httpcore2 truststore h11 anyio backports.zstd \
        argcomplete beautifulsoup4 soupsieve build cachecontrol cleo crashtest \
        distlib dulwich fancycompleter fastjsonschema filelock findpython \
        installer jaraco.classes jaraco.context jaraco.functools jeepney keyring \
        mccabe more-itertools msgpack pbs-installer pkginfo platformdirs \
        pycodestyle pyflakes pygments pyproject_hooks pyrepl python-discovery \
        rapidfuzz requests-toolbelt responses secretstorage setuptools \
        shellingham tomlkit trove-classifiers userpath virtualenv zstandard \
    && pip check \
    && python -m pip uninstall -y --quiet pip

# Sentry WSGI wrapper
COPY wsgi_sentry.py /satosa_proxy/wsgi_sentry.py

# Override CIE OIDC backend, endpoints and models

COPY plugins/cieoidc-backend/cieoidc.py /satosa_proxy/backends/cieoidc/cieoidc.py
COPY plugins/cieoidc-endpoints/ /satosa_proxy/backends/cieoidc/endpoints/
COPY plugins/cieoidc-models/    /satosa_proxy/backends/cieoidc/models/
COPY plugins/redis_storage.py   /satosa_proxy/backends/cieoidc/storage/impl/redis_storage.py
COPY plugins/spidsaml2.py       /satosa_proxy/backends/spidsaml2.py
COPY plugins/i18n.py            /satosa_proxy/backends/i18n.py
COPY internal_attributes.yaml  /satosa_proxy/internal_attributes.yaml

# Override public-facing SSO pages (design system .italia — card centrata)
COPY public/static/sso/         /satosa_proxy/static/sso/
COPY public/static/spid/        /satosa_proxy/static/spid/
COPY public/static/cie/         /satosa_proxy/static/cie/
COPY public/static/eidas/       /satosa_proxy/static/eidas/
COPY public/static/disco.html   /satosa_proxy/static/disco.html
COPY public/static/i18n/        /satosa_proxy/static/i18n/
COPY public/templates/           /satosa_proxy/templates/


COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh \
    && addgroup -S -g 10001 sso && adduser -S -D -H -u 10001 -G sso sso     && mkdir -p /satosa-conf && chown 10001:10001 /satosa-conf

# Runtime non-root. /satosa-conf (volume condiviso con config-api, stesso uid):
# un volume nominato vuoto prende proprietario e permessi della directory
# dell'immagine al primo mount (Docker e Podman).
USER 10001:10001

EXPOSE 8080
ENTRYPOINT ["/entrypoint.sh"]
