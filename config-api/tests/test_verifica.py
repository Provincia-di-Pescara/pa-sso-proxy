import json
from urllib.parse import parse_qs, urlsplit

import pytest
from httpx import ASGITransport, AsyncClient

from app.database import get_db
from app.models import EnteSettings, SpidIdP


@pytest.fixture
def verifica_app(db_session, monkeypatch):
    monkeypatch.setenv("SESSION_SECRET", "test-secret-32-chars-minimum-pad")
    monkeypatch.delenv("PROXY_BASE_URL", raising=False)
    from app.main import app

    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    yield app
    app.dependency_overrides.clear()


async def _setup(db_session, legal_entity_enabled: bool):
    db_session.add_all([
        EnteSettings(id=1, proxy_hostname="proxy.ente.it", legal_entity_enabled=legal_entity_enabled),
        SpidIdP(alias="spid-demo", display_name="Demo", metadata_url="https://demo.spid.gov.it/metadata.xml", enabled=True),
    ])
    await db_session.commit()


def _client(app):
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _authorize_params(app, **query) -> dict:
    async with _client(app) as c:
        r = await c.get("/verifica/start", params=query, follow_redirects=False)
    assert r.status_code == 302
    return {k: v[0] for k, v in parse_qs(urlsplit(r.headers["location"]).query).items()}


async def test_selector_hidden_without_legal_entity(verifica_app, db_session):
    await _setup(db_session, legal_entity_enabled=False)
    async with _client(verifica_app) as c:
        page = await c.get("/verifica")
    assert page.status_code == 200
    assert 'name="subject"' not in page.text


async def test_selector_shown_with_legal_entity(verifica_app, db_session):
    await _setup(db_session, legal_entity_enabled=True)
    async with _client(verifica_app) as c:
        page = await c.get("/verifica")
    assert 'name="subject" value="pf"' in page.text
    assert 'name="subject" value="pg"' in page.text
    assert "Persona giuridica" in page.text


async def test_start_default_is_persona_fisica(verifica_app, db_session):
    await _setup(db_session, legal_entity_enabled=True)
    params = await _authorize_params(verifica_app)
    assert params["scope"] == "openid profile email"
    assert "company_name" not in json.loads(params["claims"])["userinfo"]


async def test_start_persona_giuridica(verifica_app, db_session):
    await _setup(db_session, legal_entity_enabled=True)
    params = await _authorize_params(verifica_app, subject="pg")
    assert params["scope"] == "openid profile email legal_entity"
    userinfo = json.loads(params["claims"])["userinfo"]
    for claim in ("company_name", "registered_office", "iva_code", "fiscal_number"):
        assert claim in userinfo


async def test_start_persona_giuridica_ignored_when_disabled(verifica_app, db_session):
    await _setup(db_session, legal_entity_enabled=False)
    params = await _authorize_params(verifica_app, subject="pg")
    assert params["scope"] == "openid profile email"
    assert "company_name" not in json.loads(params["claims"])["userinfo"]


def test_result_shows_company_block():
    from app.jinja_templates import templates
    html = templates.env.get_template("verifica/result.html.j2").render(
        success=True, claims={}, settings=None,
        userinfo={"fiscal_number": "TINIT-RSSMRA80A01H501U", "company_name": "ACME S.r.l.",
                  "iva_code": "VATIT-12345678901", "registered_office": "Via Roma 1, Pescara"},
    )
    assert "Persona Giuridica" in html
    assert "ACME S.r.l." in html
    assert "VATIT-12345678901" in html
    assert "Via Roma 1, Pescara" in html


def test_result_without_company_has_no_block():
    from app.jinja_templates import templates
    html = templates.env.get_template("verifica/result.html.j2").render(
        success=True, claims={}, settings=None, userinfo={"fiscal_number": "TINIT-RSSMRA80A01H501U"},
    )
    assert "Persona Giuridica" not in html


def test_result_company_block_unwraps_list_values():
    # Valori reali da login SPID Tipo 4: gli attributi azienda arrivano come liste.
    from app.jinja_templates import templates
    html = templates.env.get_template("verifica/result.html.j2").render(
        success=True, claims={}, settings=None,
        userinfo={"fiscal_number": ["TINIT-MNTMRA03M71C615V"],
                  "company_name": ["Scuola magistrale Montessori"],
                  "iva_code": ["12345678987"],
                  "registered_office": ["Via Listz 21 00144 Roma"]},
    )
    block = html.split("Persona Giuridica", 1)[1].split("Attributi Utente Ricevuti", 1)[0]
    assert "Scuola magistrale Montessori" in block
    assert "12345678987" in block
    assert "Via Listz 21 00144 Roma" in block
    assert "[" not in block and "&#39;" not in block
