"""Tab IT-Wallet nella discovery: parsing statico di disco.html.

Host: file del repo; container: /satosa_proxy/static/disco.html. Skip se assente.
"""
import re
from pathlib import Path

import pytest

_CANDIDATES = [
    Path(__file__).resolve().parents[1] / "public" / "static" / "disco.html",
    Path("/satosa_proxy/static/disco.html"),
]
_DISCO = next((p for p in _CANDIDATES if p.is_file()), None)

pytestmark = pytest.mark.skipif(_DISCO is None, reason="disco.html non disponibile")


@pytest.fixture(scope="module")
def html():
    return _DISCO.read_text(encoding="utf-8")


def test_itwallet_tab_present_hidden_by_default(html):
    btn = re.search(r'<button[^>]*id="tab-itwallet"[^>]*>', html, re.S)
    assert btn, "bottone tab-itwallet assente"
    assert 'aria-controls="panel-itwallet"' in btn.group(0)
    assert 'role="tab"' in btn.group(0)
    assert 'style="display:none"' in btn.group(0)
    panel = re.search(r'<div[^>]*id="panel-itwallet"[^>]*>', html, re.S)
    assert panel, "pannello panel-itwallet assente"
    assert "hidden" in panel.group(0).split("panel-itwallet", 1)[1]
    assert 'role="tabpanel"' in panel.group(0)
    # marchio bianco su riquadro navy (tab) e sul pulsante blu: quello blu sparirebbe
    assert "/static/itwallet/it-wallet-mark-white.svg" in html
    white = Path(__file__).resolve().parents[1] / "public" / "static" / "itwallet" / "it-wallet-mark-white.svg"
    if white.is_file():
        assert 'fill="#FFFFFF"' in white.read_text(encoding="utf-8")
    for key in ("tab", "description", "button"):
        assert f"disco.itwallet.{key}" in html


def test_itwallet_tab_logic(html):
    m = re.search(r"var itw = [^\n]*itwallet;\n(.*?)\n\s*\n", html, re.S)
    assert m, "blocco JS IT-Wallet assente"
    block = m.group(0)
    assert "itw.login_url" in block
    assert "!LEGAL_ENTITY" in block
    assert "(!itw.test_only || VERIFICA)" in block
    assert "tab-itwallet" in block
    assert "itwallet-login-btn" in block
