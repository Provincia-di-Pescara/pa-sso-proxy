FROM ghcr.io/italia/iam-proxy-italia:latest

USER root

# Base image contains only /.venv/ — no project files. Clone them.
# Alpine-based image — use apk
RUN apk add --no-cache git

ARG IAM_PROXY_REF=v3.3
RUN git clone --depth 1 --branch "${IAM_PROXY_REF}" \
        https://github.com/italia/iam-proxy-italia.git /tmp/upstream \
    && cp -r /tmp/upstream/iam-proxy-italia-project/. /satosa_proxy/ \
    && rm -rf /tmp/upstream

# Install redis client inside the venv
RUN . /.venv/bin/activate && pip install redis --quiet

# Override CIE OIDC backend, endpoints and models
COPY plugins/cieoidc-backend/cieoidc.py /satosa_proxy/backends/cieoidc/cieoidc.py
COPY plugins/cieoidc-endpoints/ /satosa_proxy/backends/cieoidc/endpoints/
COPY plugins/cieoidc-models/    /satosa_proxy/backends/cieoidc/models/
COPY plugins/redis_storage.py   /satosa_proxy/backends/cieoidc/storage/impl/redis_storage.py
COPY plugins/spidsaml2.py       /satosa_proxy/backends/spidsaml2.py
COPY plugins/ciesaml2.py        /satosa_proxy/backends/ciesaml2.py

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 8080
ENTRYPOINT ["/entrypoint.sh"]
