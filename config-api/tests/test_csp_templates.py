"""CSP senza 'unsafe-inline' sugli script e font self-hosted.

La CSP di /admin e /verifica (nginx) è `script-src 'self'`: un handler inline
(onclick/onsubmit) o un <script> inline in un template smetterebbe di
funzionare in produzione senza errori visibili nei test HTTP. Questi test lo
bloccano alla fonte. Font: nessuna richiesta a server esterni (IP del
visitatore a terzi, GDPR).
"""
import re
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from app.database import get_db
from app.models import OIDCClient

APP_DIR = Path(__file__).resolve().parent.parent / "app"
REPO_DIR = APP_DIR.parent.parent
TEMPLATES = sorted((APP_DIR / "templates").rglob("*.j2"))
ADMIN_JS = APP_DIR / "static" / "js" / "admin.js"

INLINE_HANDLER = re.compile(r"""<[^>]*\son[a-z]+\s*=""", re.I | re.S)
SCRIPT_TAG = re.compile(r"<script\b([^>]*)>", re.I)
JS_URL = re.compile(r"""(href|src|action)\s*=\s*["']\s*javascript:""", re.I)
EXTERNAL_FONTS = re.compile(r"fonts\.googleapis\.com|fonts\.gstatic\.com|fonts\.bunny\.net", re.I)


def test_templates_found():
    assert len(TEMPLATES) > 20


@pytest.mark.parametrize("tpl", TEMPLATES, ids=lambda p: str(p.relative_to(APP_DIR)))
def test_no_inline_javascript(tpl):
    text = tpl.read_text(encoding="utf-8")
    assert not INLINE_HANDLER.search(text), "handler inline: usare data-* + static/js/admin.js"
    assert not JS_URL.search(text), "URL javascript:"
    for attrs in SCRIPT_TAG.findall(text):
        # ammessi: script da file e blocchi dati JSON (non eseguibili)
        assert re.search(r"\bsrc\s*=", attrs) or 'type="application/json"' in attrs, (
            f"<script{attrs}> inline: spostarlo in static/js"
        )


def test_submit_handlers_exist():
    used = set()
    for tpl in TEMPLATES:
        used |= set(re.findall(r'data-submit="([^"]+)"', tpl.read_text(encoding="utf-8")))
    js = ADMIN_JS.read_text(encoding="utf-8")
    block = js[js.index("var SUBMIT_HANDLERS"):]
    for name in used:
        assert re.search(rf'(^|\s|"){re.escape(name)}"?\s*:\s*function', block, re.M), name
    assert used >= {"eidas", "legal-entity", "restore-profile"}


@pytest.mark.parametrize("path", [
    *TEMPLATES,
    APP_DIR / "static" / "css" / "admin.css",
    REPO_DIR / "satosa" / "public" / "static" / "sso" / "sso.css",
    REPO_DIR / "satosa" / "public" / "static" / "disco.html",
], ids=lambda p: p.name)
def test_no_external_fonts(path):
    if not path.exists():
        pytest.skip(f"{path} non presente (test eseguito fuori dal repo)")
    assert not EXTERNAL_FONTS.search(path.read_text(encoding="utf-8"))


@pytest.mark.parametrize("fonts_dir", [
    APP_DIR / "static" / "fonts",
    REPO_DIR / "satosa" / "public" / "static" / "sso" / "fonts",
], ids=["config-api", "satosa"])
def test_font_files_referenced_exist(fonts_dir):
    if not fonts_dir.exists():
        pytest.skip("cartella font non presente")
    css = (fonts_dir / "fonts.css").read_text(encoding="utf-8")
    refs = re.findall(r"url\(\./([^)]+)\)", css)
    assert refs
    for ref in refs:
        assert (fonts_dir / ref).is_file(), ref
    assert list(fonts_dir.glob("LICENSE-*.txt"))


# --- HTTP ----------------------------------------------------------------------

@pytest.fixture
def app_admin(db_session, monkeypatch):
    import sys
    monkeypatch.setenv("SESSION_SECRET", "test-secret-32-chars-minimum-pad")
    from app.main import app
    monkeypatch.setattr(sys.modules["app.main"], "ADMIN_USER", "admin")
    monkeypatch.setattr(sys.modules["app.main"], "ADMIN_PASSWORD", "secret")

    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    yield app
    app.dependency_overrides.clear()


def _client(app):
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def test_public_static_assets(app_admin):
    async with _client(app_admin) as c:
        r = await c.get("/admin/static/js/admin.js")
        assert r.status_code == 200
        assert "javascript" in r.headers["content-type"]
        for base in ("/admin/static/fonts", "/verifica/static/fonts"):
            r = await c.get(f"{base}/fonts.css")
            assert r.status_code == 200, base
            first = re.search(r"url\(\./([^)]+)\)", r.text).group(1)
            assert (await c.get(f"{base}/{first}")).status_code == 200


def test_autoescape_enabled_for_j2_templates():
    """Starlette usa select_autoescape() (solo .html/.htm/.xml): i nostri
    .html.j2 restavano senza escape. Deve valere per ogni template."""
    from app.jinja_templates import templates
    out = templates.env.from_string("{{ v }}").render(v="<b>")
    assert out == "&lt;b&gt;"
    tpl = templates.env.get_template("clients/form.html.j2")
    assert tpl.environment.autoescape is True


async def test_client_name_is_escaped(app_admin, db_session):
    """Nome client = dato non fidato: escapato in HTML e mai in una stringa JS
    (prima `onsubmit="return confirm('Eliminare {{ c.name }}?')"`)."""
    db_session.add(OIDCClient(
        client_id="client-x", client_secret_hash="h", client_secret_plain="s",
        name="x');alert(1);//\"<img src=x>", redirect_uris=["https://app.example/cb?a=<i>"],
        allowed_scopes=["openid"],
    ))
    await db_session.commit()
    async with _client(app_admin) as c:
        await c.post("/admin/login", data={"username": "admin", "password": "secret"})
        r = await c.get("/admin/clients")
    assert r.status_code == 200
    assert "<img src=x>" not in r.text
    assert "<i>" not in r.text
    assert 'data-confirm="Eliminare x&#39;);alert(1);//&#34;&lt;img src=x&gt;?"' in r.text
