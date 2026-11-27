/*
 * Comportamenti della WebUI admin.
 *
 * Niente JavaScript inline nei template (né <script> né onclick/onsubmit):
 * la CSP di /admin è `script-src 'self'` (nginx/templates/proxy.conf.template),
 * quindi un eventuale markup iniettato non può eseguire codice.
 * I template agganciano i comportamenti con attributi data-*:
 *
 *   data-confirm="testo"        form (submit) o link/bottone (click): chiede conferma
 *   data-submit="nome"          form: handler dedicato (SUBMIT_HANDLERS), prima di data-confirm
 *   data-copy="testo"           bottone: copia il testo negli appunti
 *   data-copy-from="id"         bottone: copia il textContent dell'elemento con quell'id
 *   data-chip-toggle            checkbox: classe .selected sul .a-check-chip che la contiene
 *   data-tabs[="hash"]          contenitore di .a-tab[data-tab]; il pannello è l'elemento
 *                               con id = data-tab. "hash": tab attiva sincronizzata con #hash
 *
 * I valori arrivano da Jinja con autoescape negli attributi HTML: non passano
 * mai da una stringa JavaScript (prima `onclick="copyText('{{ x }}')"` era
 * un'iniezione JS con un apice nel valore).
 */
(function () {
  "use strict";

  // ---------------------------------------------------------------- copia
  function flash(btn) {
    var prevText = btn.textContent;
    var prevColor = btn.style.color;
    var prevBorder = btn.style.borderColor;
    btn.textContent = "Copiato!";
    btn.style.color = "#10B981";
    btn.style.borderColor = "#10B981";
    setTimeout(function () {
      btn.textContent = prevText;
      btn.style.color = prevColor;
      btn.style.borderColor = prevBorder;
    }, 1500);
  }

  function copy(text, btn) {
    if (!text) return;
    if (navigator.clipboard && window.isSecureContext) {
      navigator.clipboard.writeText(text).then(
        function () { flash(btn); },
        function (err) { console.error("Errore copia:", err); }
      );
      return;
    }
    // Fallback senza HTTPS (es. sviluppo su http://localhost con IP)
    var ta = document.createElement("textarea");
    ta.value = text;
    ta.style.position = "fixed";
    ta.style.opacity = "0";
    document.body.appendChild(ta);
    ta.focus();
    ta.select();
    try {
      if (document.execCommand("copy")) flash(btn);
    } catch (err) {
      console.error("Errore copia:", err);
    }
    document.body.removeChild(ta);
  }

  // -------------------------------------------------- handler dei form
  // Toggle eIDAS / persona giuridica: conferma solo se lo stato cambia,
  // poi confirmed=yes (il server ignora il toggle senza conferma).
  function toggleSubmit(form, checkboxId, confirmedId, enableMsg, disableMsg) {
    var enabled = document.getElementById(checkboxId).checked;
    var initial = form.getAttribute("data-initial-enabled") === "true";
    var msg = null;
    if (enabled && !initial) msg = enableMsg();
    else if (!enabled && initial) msg = disableMsg;
    if (msg && !window.confirm(msg)) return false;
    document.getElementById(confirmedId).value = "yes";
    return true;
  }

  var SUBMIT_HANDLERS = {
    // IT-Wallet attivo portato in produzione: conferma (sparisce la restrizione
    // ai client di test, tutti gli applicativi vedono il wallet).
    "itwallet-settings": function (form) {
      var env = form.querySelector("[name=environment]");
      var toProduction = env && env.value === "produzione" &&
        form.getAttribute("data-initial-environment") !== "produzione";
      if (!toProduction || form.getAttribute("data-wallet-enabled") !== "true") return true;
      return window.confirm(form.getAttribute("data-confirm-production"));
    },
    eidas: function (form) {
      return toggleSubmit(form, "eidas-enabled", "eidas-confirmed", function () {
        var sel = document.getElementById("eidas-env");
        var envLabel = sel.options[sel.selectedIndex].text;
        return "Abilitare l'integrazione eIDAS in ambiente " + envLabel + "?\n\n" +
          "Questo renderà visibile il pulsante di login eIDAS sulla pagina di scelta provider " +
          "e modifica il metadata SP pubblicato (richiede ri-validazione AgID).\n\n" +
          "L'accesso SPID già validato continua a funzionare; eIDAS funziona solo " +
          "dopo l'aggiornamento del metadata sul registro AgID.";
      }, "Disabilitare l'integrazione eIDAS?\n\n" +
         "Questo nasconderà il pulsante di login eIDAS dalla pagina di scelta provider.");
    },

    "legal-entity": function (form) {
      return toggleSubmit(form, "legal-entity-enabled", "legal-entity-confirmed", function () {
        return "Abilitare l'accesso SPID persona giuridica?\n\n" +
          "Questo modifica il metadata SP pubblicato (nuovi attributi opzionali azienda) " +
          "e richiede ri-validazione presso AgID.\n\n" +
          "Persona fisica continua a funzionare; persona giuridica funziona solo " +
          "dopo l'aggiornamento del metadata sul registro AgID.";
      }, "Disabilitare l'accesso SPID persona giuridica?");
    },

    // Ripristino profilo metadata: se cambia il certificato serve confirm_cert=yes.
    "restore-profile": function (form) {
      var certChange = form.getAttribute("data-cert-change") === "true";
      var msg = "Ripristinare la configurazione del profilo? SATOSA rigenera il metadata.";
      if (certChange) {
        msg += "\n\nATTENZIONE: il profilo usa il certificato #" + form.getAttribute("data-cert-id") +
          ", diverso da quello attivo. Verrà riattivato: la firma delle richieste SPID tornerà a quella chiave.";
      }
      if (!window.confirm(msg)) return false;
      if (certChange) form.querySelector("input[name=confirm_cert]").value = "yes";
      return true;
    }
  };

  document.addEventListener("submit", function (e) {
    var form = e.target;
    var name = form.getAttribute("data-submit");
    if (name) {
      var handler = SUBMIT_HANDLERS[name];
      if (!handler || !handler(form)) { e.preventDefault(); return; }
    }
    var msg = form.getAttribute("data-confirm");
    if (msg && !window.confirm(msg)) e.preventDefault();
  });

  // ------------------------------------------------------------- click
  document.addEventListener("click", function (e) {
    var el = e.target.closest("[data-copy], [data-copy-from], a[data-confirm], button[data-confirm]");
    if (!el) return;
    if (el.hasAttribute("data-copy")) {
      copy(el.getAttribute("data-copy"), el);
    } else if (el.hasAttribute("data-copy-from")) {
      var src = document.getElementById(el.getAttribute("data-copy-from"));
      if (src) copy(src.textContent, el);
    } else if (!window.confirm(el.getAttribute("data-confirm"))) {
      e.preventDefault();
    }
  });

  // ------------------------------------------------------------ change
  document.addEventListener("change", function (e) {
    var el = e.target;
    if (el.hasAttribute && el.hasAttribute("data-chip-toggle")) {
      var chip = el.closest(".a-check-chip");
      if (chip) chip.classList.toggle("selected", el.checked);
    }
  });

  // -------------------------------------------------------------- tab
  function initTabs(container) {
    var tabs = Array.prototype.slice.call(container.querySelectorAll(".a-tab[data-tab]"));
    if (!tabs.length) return;
    var names = tabs.map(function (t) { return t.getAttribute("data-tab"); });
    var useHash = container.getAttribute("data-tabs") === "hash";

    function activate(name) {
      if (names.indexOf(name) === -1) name = names[0];
      tabs.forEach(function (t) {
        var on = t.getAttribute("data-tab") === name;
        t.classList.toggle("active", on);
        var panel = document.getElementById(t.getAttribute("data-tab"));
        if (panel) panel.hidden = !on;
      });
    }

    tabs.forEach(function (t) {
      t.addEventListener("click", function () {
        var name = t.getAttribute("data-tab");
        if (useHash) history.replaceState(null, "", "#" + name);
        activate(name);
      });
    });

    if (useHash) {
      activate((window.location.hash || "#").slice(1));
    } else {
      var current = container.querySelector(".a-tab.active[data-tab]");
      activate(current ? current.getAttribute("data-tab") : names[0]);
    }
  }

  // -------------------------------------- CIE: anteprima URL ambiente
  function initCieEnvironments() {
    var data = document.getElementById("cie-environments");
    var sel = document.getElementById("oidc_environment");
    var preview = document.getElementById("env-urls-preview");
    if (!data || !sel || !preview) return;
    var envs = JSON.parse(data.textContent);

    function render() {
      preview.textContent = "";
      var env = envs[sel.value];
      if (!env) return;
      [["Provider", env.provider_url], ["Trust Anchor", env.trust_anchor_url],
       ["Authority Hint", env.authority_hint_url]].forEach(function (row, i) {
        if (i) preview.appendChild(document.createElement("br"));
        preview.appendChild(document.createTextNode(row[0] + ": " + row[1]));
      });
    }

    sel.addEventListener("change", render);
    render();
  }

  function init() {
    Array.prototype.forEach.call(document.querySelectorAll("[data-tabs]"), initTabs);
    initCieEnvironments();
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})();
