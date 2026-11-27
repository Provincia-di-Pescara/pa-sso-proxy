/* Pagine IT-Wallet (QR e errore) del backend OpenID4VP.
   - i18n: stessa precedenza della discovery (cookie sso_lang -> ?lang= -> navigator.languages -> it);
     fallback chiave: lingua -> en -> it. Catalogo: <static>i18n/<lang>.json.
   - QR: conto alla rovescia, polling dello status endpoint di pyeudiw
     (201/202 attesa, 200 {redirect_uri} -> redirect, 401 errore wallet, 403 scaduto). */
(function () {
  'use strict';

  var LANGS = ['it', 'en', 'fr', 'de', 'es'];
  var cfg = {};
  try { cfg = JSON.parse(document.getElementById('itw-config').textContent) || {}; } catch (e) { cfg = {}; }
  var STATIC = cfg.static || '/static/';
  var DICT = {};
  var LANG = 'it';

  function normLang(tag) {
    if (!tag) return null;
    var p = String(tag).replace('_', '-').split('-')[0].toLowerCase();
    return LANGS.indexOf(p) >= 0 ? p : null;
  }
  function cookieLang() {
    var m = document.cookie.match(/(?:^|;\s*)sso_lang=([^;]*)/);
    if (!m) return null;
    try { return normLang(decodeURIComponent(m[1])); } catch (e) { return null; }
  }
  function resolveLang() {
    var l = cookieLang() || normLang(new URLSearchParams(window.location.search).get('lang'));
    if (l) return l;
    var prefs = navigator.languages && navigator.languages.length ? navigator.languages : [navigator.language];
    for (var i = 0; i < prefs.length; i++) { l = normLang(prefs[i]); if (l) return l; }
    return 'it';
  }

  function t(key, vars) {
    var v = DICT[key] || key;
    if (vars) Object.keys(vars).forEach(function (k) { v = v.split('{' + k + '}').join(String(vars[k])); });
    return v;
  }

  function loadCatalog(lang) {
    /* merge it < en < lang: una chiave mancante ricade su en, poi su it */
    var order = lang === 'it' ? ['it'] : (lang === 'en' ? ['it', 'en'] : ['it', 'en', lang]);
    return Promise.all(order.map(function (l) {
      return fetch(STATIC + 'i18n/' + l + '.json').then(function (r) { return r.json(); }).catch(function () { return {}; });
    })).then(function (parts) {
      var d = {};
      parts.forEach(function (p) { Object.keys(p || {}).forEach(function (k) { d[k] = p[k]; }); });
      DICT = d;
      LANG = lang;
    });
  }

  var timerKey = null;
  var remaining = 0;
  var state = 'waiting'; /* waiting | expired | failed | done */

  function renderTimer() {
    var el = document.getElementById('itw-timer');
    if (el && state === 'waiting') el.textContent = t('itwallet.qr.expires_in', { seconds: Math.max(remaining, 0) });
  }

  function applyI18n() {
    document.documentElement.lang = LANG;
    document.querySelectorAll('[data-i18n]').forEach(function (el) {
      var v = DICT[el.getAttribute('data-i18n')];
      if (v) el.textContent = v;
    });
    document.querySelectorAll('[data-i18n-attr]').forEach(function (el) {
      var parts = el.getAttribute('data-i18n-attr').split(':');
      var v = DICT[parts[1]];
      if (v) el.setAttribute(parts[0], v);
    });
    if (cfg.page === 'qr') {
      document.title = t('itwallet.qr.page_title');
      renderTimer();
      if (state === 'expired') setMessage(t('itwallet.qr.expired'));
      else if (state === 'failed') setMessage(t('itwallet.qr.failed'));
      else if (state === 'done') setMessage(t('itwallet.qr.success'));
    } else {
      document.title = t('itwallet.error.page_title');
    }
    var sel = document.getElementById('sso-lang-select');
    if (sel) sel.value = LANG;
  }

  function setMessage(text) {
    var m = document.getElementById('itw-message');
    if (!m) return;
    m.textContent = text;
    m.hidden = false;
  }

  function loadBranding() {
    fetch('/static/locales/eid-' + LANG + '.json').then(function (r) { return r.json(); }).then(function (d) {
      var h = d && d.header;
      if (!h) return;
      if (h.favicon_url) { var f = document.getElementById('page-favicon'); if (f) { f.href = h.favicon_url; f.type = ''; } }
      if (h.region_name) { var n = document.getElementById('ente-name'); if (n) n.textContent = h.region_name; }
      if (h.logo_url) {
        var img = document.getElementById('ente-logo');
        var svg = document.getElementById('ente-crest-svg');
        if (img) { img.src = h.logo_url; img.style.display = ''; }
        if (svg) svg.style.display = 'none';
      }
    }).catch(function () {});
  }

  /* ---------- QR: countdown + polling ---------- */
  var pollTimer = null;
  var countTimer = null;

  function stopTimers() {
    if (pollTimer) clearTimeout(pollTimer);
    if (countTimer) clearInterval(countTimer);
    pollTimer = countTimer = null;
  }

  function finish(newState, msgKey) {
    state = newState;
    stopTimers();
    var timer = document.getElementById('itw-timer');
    if (timer) timer.hidden = true;
    var wrap = document.getElementById('itw-qr-wrap');
    if (wrap && newState !== 'done') wrap.classList.add('is-expired');
    var dev = document.getElementById('itw-same-device');
    if (dev) dev.hidden = true;
    setMessage(t(msgKey));
    if (newState !== 'done') {
      var actions = document.getElementById('itw-actions');
      if (actions) actions.hidden = false;
    }
  }

  /* Redirect accettato solo same-origin (get-response e' sullo stesso host): niente javascript:, data: o host esterni. */
  function safeRedirectUrl(value, loc) {
    if (typeof value !== 'string' || !value) return null;
    try {
      var u = new URL(value, loc.href);
      return u.origin === loc.origin && u.origin !== 'null' ? u.href : null;
    } catch (e) { return null; }
  }
  window.ItwQr = { safeRedirectUrl: safeRedirectUrl };

  function poll() {
    if (state !== 'waiting') return;
    fetch(cfg.status_endpoint, { credentials: 'same-origin', headers: { Accept: 'application/json' } })
      .then(function (r) {
        if (state !== 'waiting') return null;
        if (r.status === 200) {
          return r.json().then(function (d) {
            var target = d && safeRedirectUrl(d.redirect_uri, window.location);
            if (target) {
              finish('done', 'itwallet.qr.success');
              window.location.assign(target);
            } else {
              finish('failed', 'itwallet.qr.failed');
            }
          });
        }
        if (r.status === 201 || r.status === 202) { pollTimer = setTimeout(poll, 1000); return null; }
        if (r.status === 403) { finish('expired', 'itwallet.qr.expired'); return null; }
        finish('failed', 'itwallet.qr.failed');
        return null;
      })
      .catch(function () { if (state === 'waiting') pollTimer = setTimeout(poll, 2000); });
  }

  function initQr() {
    remaining = Number(cfg.expiration) > 0 ? Number(cfg.expiration) : 120;
    renderTimer();
    countTimer = setInterval(function () {
      remaining -= 1;
      if (remaining < 0) { finish('expired', 'itwallet.qr.expired'); return; }
      renderTimer();
    }, 1000);
    pollTimer = setTimeout(poll, 1000);

    var retry = document.getElementById('itw-retry');
    if (retry) retry.addEventListener('click', function () { window.location.reload(); });

    /* annulla: torna alla discovery mantenendo il contesto della richiesta (come upstream) */
    var cancel = document.getElementById('itw-cancel');
    if (cancel) {
      var p = new URLSearchParams(window.location.search);
      var kept = new URLSearchParams();
      ['return', 'entityID', 'lang'].forEach(function (k) { if (p.has(k)) kept.set(k, p.get(k)); });
      var qs = kept.toString();
      if (qs) cancel.href = cancel.getAttribute('href') + '?' + qs;
    }
  }

  document.addEventListener('DOMContentLoaded', function () {
    LANG = resolveLang();
    var sel = document.getElementById('sso-lang-select');
    if (sel) sel.addEventListener('change', function () {
      var l = normLang(sel.value);
      if (!l) return;
      document.cookie = 'sso_lang=' + l + '; Path=/; Max-Age=31536000; SameSite=Lax; Secure';
      loadCatalog(l).then(applyI18n);
    });
    if (cfg.page === 'qr') initQr();
    loadCatalog(LANG).then(function () { applyI18n(); loadBranding(); });
  });
})();
