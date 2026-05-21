#!/bin/sh
set -e
. /.venv/bin/activate
PYTHON_VER=$(python -c 'import sys; print(f"python{sys.version_info.major}.{sys.version_info.minor}")')
mkdir -p /satosa-conf
touch /satosa-conf/.reload
exec uwsgi \
    --chdir /satosa_proxy \
    --wsgi-file "/.venv/lib/${PYTHON_VER}/site-packages/satosa/wsgi.py" \
    --callable app \
    --http-socket 0.0.0.0:8080 \
    --workers 2 \
    --timeout 60 \
    --buffer-size 32768 \
    --touch-reload /satosa-conf/.reload
