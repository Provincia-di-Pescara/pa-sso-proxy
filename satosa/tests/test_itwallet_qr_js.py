"""itwallet-qr.js eseguito con node (redirect solo same-origin, polling con backoff).

Nessuna dipendenza Python oltre pytest: gira nel job host della CI (i runner
ubuntu hanno node). Skip se node o il sorgente non sono disponibili (container).
"""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

JS = Path(__file__).resolve().parents[1] / "public" / "static" / "sso" / "itwallet-qr.js"
NODE = shutil.which("node")

pytestmark = pytest.mark.skipif(
    NODE is None or not JS.is_file(), reason="node o itwallet-qr.js non disponibili"
)

# DOM minimo: abbastanza per caricare lo script e far partire initQr().
_HARNESS = r"""
const fs = require('fs');
const src = fs.readFileSync(process.argv[1], 'utf8');
const scenario = JSON.parse(process.argv[2] || '{}');
const cfg = {page: 'qr', status_endpoint: 'https://sso.example.it/OpenID4VP/status?id=abc',
             expiration: scenario.expiration || 120, static: '/static/'};
const timers = [];
let now = 0;
const events = [];
const elements = {};
function el(id) {
  if (id === 'itw-config') return {textContent: JSON.stringify(cfg)};
  if (!elements[id]) elements[id] = {id, hidden: false, textContent: '', style: {},
    classList: {add() {}}, addEventListener() {}, setAttribute() {}, getAttribute() { return ''; }};
  return elements[id];
}
let ready = null;
global.document = {cookie: '', title: '', documentElement: {},
  addEventListener(ev, fn) { if (ev === 'DOMContentLoaded') ready = fn; },
  getElementById: el, querySelectorAll() { return []; }};
global.navigator = {languages: ['it']};
global.window = {location: {href: 'https://sso.example.it/OpenID4VP/pre-request?x=1',
  origin: 'https://sso.example.it', search: '?x=1',
  assign(u) { events.push(['redirect', u]); }}};
global.setTimeout = (fn, ms) => { const t = {fn, at: now + ms, ms, kind: 'timeout'}; timers.push(t); return t; };
global.clearTimeout = (t) => { const i = timers.indexOf(t); if (i >= 0) timers.splice(i, 1); };
global.setInterval = (fn, ms) => { const t = {fn, at: now + ms, ms, kind: 'interval'}; timers.push(t); return t; };
global.clearInterval = global.clearTimeout;
const statuses = (scenario.statuses || []).slice();
global.fetch = (url) => {
  if (url !== cfg.status_endpoint) return Promise.resolve({status: 200, json: () => Promise.resolve({})});
  const next = statuses.length ? statuses.shift() : 202;
  if (next === 'neterr') return Promise.reject(new Error('net'));
  events.push(['status', next]);
  return Promise.resolve({status: next, json: () => Promise.resolve({redirect_uri: scenario.redirect})});
};
eval(src);
const flush = () => new Promise((r) => setImmediate(r));
(async () => {
  if (scenario.unit) {
    const q = window.ItwQr;
    const loc = {href: 'https://sso.example.it/OpenID4VP/pre-request', origin: 'https://sso.example.it'};
    const f = q.safeRedirectUrl;
    console.log(JSON.stringify({
      redirect: [f('https://sso.example.it/get_response?response_code=x', loc), f('/get_response?x=1', loc),
        f('javascript:alert(1)', loc), f('https://evil.example/x', loc), f('data:text/html,x', loc),
        f('', loc), f(null, loc), f('//evil.example/x', loc)],
      classify: [200, 201, 202, 401, 403, 404, 429, 500, 502, 503].map(q.classifyStatus),
      delays: [0, 1, 2, 3, 4, 10].map(q.retryDelay)}));
    return;
  }
  ready();
  await flush();
  const pollDelays = [];
  for (let i = 0; i < 400 && timers.length; i++) {
    timers.sort((a, b) => a.at - b.at);
    const t = timers.shift();
    now = t.at;
    if (t.kind === 'interval') { t.at = now + t.ms; timers.push(t); }
    else pollDelays.push(t.ms);
    t.fn();
    await flush(); await flush(); await flush();
  }
  console.log(JSON.stringify({events, pollDelays, message: (elements['itw-message'] || {}).textContent || null}));
})();
"""


def _run(scenario: dict) -> dict:
    out = subprocess.run(
        [NODE, "-e", _HARNESS, str(JS), json.dumps(scenario)],
        capture_output=True, text=True, check=True, timeout=30,
    ).stdout
    return json.loads(out)


def test_status_redirect_origin_validation():
    """safeRedirectUrl accetta solo URL same-origin."""
    res = _run({"unit": True})
    assert res["redirect"] == [
        "https://sso.example.it/get_response?response_code=x",
        "https://sso.example.it/get_response?x=1",
        None, None, None, None, None, None,
    ]


def test_classify_and_backoff():
    res = _run({"unit": True})
    assert res["classify"] == [
        "redirect", "wait", "wait", "failed", "expired", "failed",
        "retry", "retry", "retry", "retry",
    ]
    assert res["delays"] == [2000, 4000, 8000, 10000, 10000, 10000]


def test_transient_errors_retry_with_backoff_then_redirect():
    res = _run({
        "statuses": [202, 429, 503, 500, "neterr", 202, 200],
        "redirect": "https://sso.example.it/OpenID4VP/redirect-uri?response_code=x",
    })
    assert ["redirect", "https://sso.example.it/OpenID4VP/redirect-uri?response_code=x"] in res["events"]
    # primo poll 1 s, 202 -> 1 s, poi 429/503/500/errore rete -> 2, 4, 8, 10 s, 202 azzera -> 1 s
    assert res["pollDelays"][:7] == [1000, 1000, 2000, 4000, 8000, 10000, 1000]


def test_cross_origin_redirect_is_refused():
    res = _run({"statuses": [200], "redirect": "https://evil.example/x"})
    assert not [e for e in res["events"] if e[0] == "redirect"]
    assert res["message"] == "itwallet.qr.failed"


def test_transient_errors_stop_when_qr_expires():
    res = _run({"statuses": [503] * 50, "expiration": 15})
    assert not [e for e in res["events"] if e[0] == "redirect"]
    assert res["message"] == "itwallet.qr.expired"
    # nessun poll oltre la scadenza (15 s): 1 + 2 + 4 + 8 = 15 -> al massimo 4 tentativi
    assert len([e for e in res["events"] if e[0] == "status"]) <= 5


def test_definitive_error_ends_flow():
    res = _run({"statuses": [401]})
    assert res["message"] == "itwallet.qr.failed"
    assert [e for e in res["events"] if e[0] == "status"] == [["status", 401]]
