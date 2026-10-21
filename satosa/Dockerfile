# Digest fisso: aggiornato da dependabot con una PR (revisione manuale, vedi
# dependabot-automerge.yml). Deve corrispondere a IAM_PROXY_REF qui sotto:
# venv dell'immagine e codice clonato vengono dalla stessa release upstream.
FROM ghcr.io/italia/iam-proxy-italia:latest@sha256:48ffe2a3654737f6ccbb13ff3458cb6291cab3ebe484f06ed811f7fad6929af7

USER root

# Versione applicativo (tag git / sha) iniettata a build-time, usata come
# Sentry "release" per raggruppare gli errori per versione deployata.
ARG APP_VERSION=unknown
ENV APP_VERSION=${APP_VERSION}

# Base image contains only /.venv/ — no project files. Clone them.
# Alpine-based image — use apk
RUN apk update && apk upgrade --no-cache
RUN apk add --no-cache git

# Non visto da dependabot: upstream-check.yml apre una issue a ogni nuova release.
ARG IAM_PROXY_REF=v3.3
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
# pip resta: la CI installa i requirement dei test dentro l'immagine.
COPY requirements-runtime.txt /tmp/requirements-runtime.txt
RUN . /.venv/bin/activate && pip install -r /tmp/requirements-runtime.txt --quiet \
    && pip uninstall -y --quiet \
        pillow \
        poetry poetry-core pipx flake8 pdbpp \
        satosa-oidcop idpyoidc \
        httpx httpcore h11 anyio \
        argcomplete beautifulsoup4 soupsieve build cachecontrol cleo crashtest \
        distlib dulwich fancycompleter fastjsonschema filelock findpython \
        installer jaraco.classes jaraco.context jaraco.functools jeepney keyring \
        mccabe more-itertools msgpack pbs-installer pkginfo platformdirs \
        pycodestyle pyflakes pygments pyproject_hooks pyrepl python-discovery \
        rapidfuzz requests-toolbelt responses secretstorage setuptools \
        shellingham tomlkit trove-classifiers userpath virtualenv zstandard

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
RUN chmod +x /entrypoint.sh

EXPOSE 8080
ENTRYPOINT ["/entrypoint.sh"]
