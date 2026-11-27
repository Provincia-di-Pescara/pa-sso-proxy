"""Pagina d'errore del proxy per i backend senza un ``handle_error`` proprio
(CIE OIDC, IT-Wallet): stesso template ``spid_login_error.html`` e stesse chiavi
i18n della pagina d'errore SPID, nessun redirect al client.

COPY -> ``/satosa_proxy/backends/proxy_errors.py`` (import ``from ..proxy_errors``).
"""

import os

from jinja2 import Environment, FileSystemLoader, select_autoescape
from satosa.response import Response

from . import i18n


def render_proxy_error(context, error: dict, status: str = "403") -> Response:
    """Rende la pagina d'errore del proxy.

    ``error``: dict con ``message_key`` e ``troubleshoot_key`` (es.
    ``LEGAL_ENTITY_SPID_ONLY_ERROR`` di ``spidsaml2``); lingua da
    ``i18n.resolve_lang(context)``.
    """
    template_folder = os.environ.get("SATOSA_TEMPLATE_FOLDER", "/satosa_proxy/templates")
    static_url = os.environ.get("SATOSA_STATIC_URL", "/static/")
    if not static_url.endswith("/"):
        static_url += "/"
    env = Environment(
        loader=FileSystemLoader(searchpath=template_folder),
        autoescape=select_autoescape(["html"]),
    )
    env.globals.update({"static": static_url})
    lang = i18n.resolve_lang(context)
    result = env.get_template("spid_login_error.html").render({
        "message": i18n.t(lang, error["message_key"]),
        "troubleshoot": i18n.t(lang, error["troubleshoot_key"]),
        "error_type": "generic",
        "cancel_url": os.environ.get("SATOSA_CANCEL_REDIRECT_URL") or "/",
        **i18n.template_vars(lang),
    })
    return Response(result.encode("utf-8"), content="text/html; charset=utf8", status=status)
