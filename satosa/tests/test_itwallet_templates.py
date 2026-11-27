"""Template IT-Wallet (QR + errore) resi con il contesto che passa pyeudiw 2.9.0.

Contesto QR (PreRequestHandler._cross_device_http_response): qrcode_color,
qrcode_text (URL haip-vp://), qrcode_base64 (SVG del QR in base64), qrcode_size,
qrcode_logo_path, qrcode_expiration_time, state, status_endpoint (URL assoluto);
globale Jinja ``static`` (static_storage_url con slash finale).
Contesto errore (GetResponseHandler): error, error_description.
Jinja: Environment(FileSystemLoader(template_folder), autoescape=select_autoescape(["html"])).
"""
import json
import re
from pathlib import Path

import pytest

jinja2 = pytest.importorskip("jinja2")

_HERE = Path(__file__).resolve()
_CANDIDATES = [
    _HERE.parents[1] / "public" / "templates",  # sorgenti repo (host)
    Path("/satosa_proxy/templates_ours"),  # container: mount dei nostri file
    Path("/satosa_proxy/templates"),  # container: immagine buildata
]
TEMPLATES = next((p for p in _CANDIDATES if (p / "spid_login_error.html").is_file()), None)
STATIC_DIR = _HERE.parents[1] / "public" / "static"

pytestmark = pytest.mark.skipif(TEMPLATES is None, reason="template IT-Wallet non disponibili")

LINK = "haip-vp://?client_id=openid_federation%3Ahttps%3A%2F%2Fsso.example.it&request_uri=https%3A%2F%2Fsso.example.it%2Frequest&state=abc"
CTX = {
    "qrcode_color": "#000000",
    "qrcode_text": LINK,
    "qrcode_base64": "PHN2Zy8+",
    "qrcode_size": 250,
    "qrcode_logo_path": "itwallet/it-wallet-mark.svg",
    "qrcode_expiration_time": 120,
    "state": "abc",
    "status_endpoint": "https://sso.example.it/OpenID4VP/status?id=abc",
}


def _env():
    env = jinja2.Environment(
        loader=jinja2.FileSystemLoader(str(TEMPLATES)),
        autoescape=jinja2.select_autoescape(["html"]),
    )
    env.globals["static"] = "https://sso.example.it/static/"
    return env


def test_qr_template_renders_with_pyeudiw_context():
    html = _env().get_template("qr_code.html").render(CTX)
    # bottone same-device: href = link haip-vp
    assert re.search(r'<a[^>]+id="itw-open-app"[^>]+href="haip-vp://', html)
    assert 'id="itw-qr"' in html
    assert "data:image/svg+xml;base64,PHN2Zy8+" in html
    cfg = json.loads(re.search(r'<script type="application/json" id="itw-config">(.*?)</script>', html, re.S).group(1))
    assert cfg["status_endpoint"] == CTX["status_endpoint"]
    assert cfg["expiration"] == 120
    assert cfg["static"] == "https://sso.example.it/static/"
    assert "itwallet-qr.js" in html


def test_qr_template_escapes_context():
    html = _env().get_template("qr_code.html").render({**CTX, "qrcode_text": 'haip-vp://?a="><script>x()</script>'})
    assert "<script>x()" not in html


def test_qr_template_no_inline_script_and_no_external_urls():
    html = _env().get_template("qr_code.html").render(CTX)
    for m in re.finditer(r"<script\b([^>]*)>", html, re.IGNORECASE):
        attrs = m.group(1)
        assert "src=" in attrs or "application/json" in attrs, f"script inline: {attrs}"
    assert not re.search(r"\son\w+=", html, re.IGNORECASE), "handler inline"
    urls = re.findall(r'(?:src|href)="(https?://[^"]+)"', html)
    own = [u for u in urls if u.startswith("https://sso.example.it/static/")]
    assert urls == own, f"URL esterni: {set(urls) - set(own)}"


def test_error_template_renders():
    html = _env().get_template("itwallet_error.html").render({"error": "access_denied", "error_description": "user said no"})
    assert 'data-i18n="itwallet.error.title"' in html
    assert "access_denied" in html and "user said no" in html
    assert not re.search(r"\son\w+=", html)
    assert not [u for u in re.findall(r'(?:src|href)="(https?://[^"]+)"', html) if "sso.example.it" not in u]


def test_error_template_without_context_and_escaping():
    env = _env()
    assert env.get_template("itwallet_error.html").render({})
    html = env.get_template("itwallet_error.html").render({"error": "<img src=x>", "error_description": None})
    assert "<img src=x>" not in html


def test_templates_i18n_keys_in_catalog():
    if not (STATIC_DIR / "i18n" / "it.json").is_file():
        pytest.skip("catalogo non disponibile")
    cat = json.loads((STATIC_DIR / "i18n" / "it.json").read_text(encoding="utf-8"))
    used = set()
    for name in ("qr_code.html", "itwallet_error.html"):
        src = (TEMPLATES / name).read_text(encoding="utf-8")
        used |= set(re.findall(r'data-i18n(?:-html)?="([^"]+)"', src))
        used |= {k for _a, k in re.findall(r'data-i18n-attr="([\w-]+):([^"]+)"', src)}
    js = (STATIC_DIR / "sso" / "itwallet-qr.js").read_text(encoding="utf-8")
    used |= set(re.findall(r"""['"](itwallet\.[\w.]+)['"]""", js))
    assert used, "nessuna chiave trovata"
    assert not used - set(cat), sorted(used - set(cat))


def test_mark_asset_and_license_present():
    if not STATIC_DIR.is_dir():
        pytest.skip("sorgenti repo non disponibili")
    assert (STATIC_DIR / "itwallet" / "it-wallet-mark.svg").is_file()
    assert "Apache" in (STATIC_DIR / "itwallet" / "LICENSE").read_text(encoding="utf-8")

