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

# Override CIE OIDC endpoints and models with GovPay versions
COPY plugins/cieoidc-endpoints/ /satosa_proxy/backends/cieoidc/endpoints/
COPY plugins/cieoidc-models/    /satosa_proxy/backends/cieoidc/models/
COPY plugins/redis_storage.py   /satosa_proxy/backends/cieoidc/storage/impl/redis_storage.py

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 8080
ENTRYPOINT ["/entrypoint.sh"]
