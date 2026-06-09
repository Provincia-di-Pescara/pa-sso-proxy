#!/bin/sh
set -e
. /.venv/bin/activate
PYTHON_VER=$(python -c 'import sys; print(f"python{sys.version_info.major}.{sys.version_info.minor}")')
mkdir -p /satosa-conf
touch /satosa-conf/.reload

if [ ! -f /satosa-conf/spid-idps-default.json ]; then
    cp /satosa_proxy/static/js/spid-idps-default.json /satosa-conf/spid-idps-default.json
fi

mkdir -p /satosa-conf/locales

exec uwsgi \
    --chdir /satosa_proxy \
    --wsgi-file "/.venv/lib/${PYTHON_VER}/site-packages/satosa/wsgi.py" \
    --callable app \
    --http-socket 0.0.0.0:8080 \
    --workers 2 \
    --harakiri 60 \
    --buffer-size 32768 \
    --touch-reload /satosa-conf/.reload \
    --static-map /static/js/spid-idps-default.json=/satosa-conf/spid-idps-default.json \
    --static-map /static/locales/eid-it.json=/satosa-conf/locales/eid-it.json \
    --static-map /static/locales/eid-en.json=/satosa-conf/locales/eid-en.json \
    --static-map /static=/satosa_proxy/static
