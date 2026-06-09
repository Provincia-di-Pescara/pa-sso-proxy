/* global React */
// ============================================================================
// SSO Proxy — screens (white-label provider chooser + error states)
// Tutti i testi IT/EN via strings(lang). Esportati a window in fondo.
// ============================================================================

// ---- official SPID identity mark (white, federation-node glyph) ----
function SpidMark({ cls = "spid-mark" }) {
  return (
    <svg className={cls} viewBox="0 0 26 26" fill="none" aria-hidden="true">
      <circle cx="13" cy="6" r="3.1" fill="#fff" />
      <circle cx="6.6" cy="18.4" r="3.1" fill="#fff" />
      <circle cx="19.4" cy="18.4" r="3.1" fill="#fff" />
      <path d="M13 6 L6.6 18.4 M13 6 L19.4 18.4 M6.6 18.4 L19.4 18.4"
        stroke="#fff" strokeWidth="1.6" strokeLinecap="round" opacity=".85" />
    </svg>
  );
}

// ---- CIE card mark ----
function CieMark({ cls = "cie-mark" }) {
  return (
    <svg className={cls} viewBox="0 0 30 22" fill="none" aria-hidden="true">
      <rect x="1" y="1" width="28" height="20" rx="3" fill="#fff" stroke="#003366" strokeWidth="1.5" />
      <rect x="1" y="1" width="28" height="5.5" rx="3" fill="#003366" />
      <circle cx="8" cy="14" r="3.4" fill="#003366" />
      <rect x="14" y="11" width="11" height="1.8" rx=".9" fill="#94A3B8" />
      <rect x="14" y="15" width="8" height="1.8" rx=".9" fill="#94A3B8" />
    </svg>
  );
}

// ---- white-label ente crest placeholder (neutral institutional emblem) ----
function Crest({ cls = "sso-crest" }) {
  return (
    <svg className={cls} viewBox="0 0 64 64" fill="none" aria-label="Logo ente (segnaposto)" role="img">
      <rect x="2" y="2" width="60" height="60" rx="10" fill="#F1F5F9" stroke="#CBD5E1" strokeWidth="1.5" />
      <path d="M32 13 L48 21 H16 Z" fill="#64748B" />
      <rect x="17" y="21" width="30" height="3" fill="#64748B" />
      <rect x="20" y="26" width="4" height="18" fill="#94A3B8" />
      <rect x="30" y="26" width="4" height="18" fill="#94A3B8" />
      <rect x="40" y="26" width="4" height="18" fill="#94A3B8" />
      <rect x="15" y="45" width="34" height="4" rx="1" fill="#64748B" />
    </svg>
  );
}

// ---- icons ----
const I = {
  app: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/></svg>,
  chev: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round"><path d="m6 9 6 6 6-6"/></svg>,
  arrow: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M5 12h14"/><path d="m13 6 6 6-6 6"/></svg>,
  key: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="7.5" cy="15.5" r="4.5"/><path d="m11 12 8-8 3 3"/><path d="m17 6 2 2"/></svg>,
  retry: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M3 12a9 9 0 1 0 3-6.7L3 8"/><path d="M3 3v5h5"/></svg>,
  back: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M19 12H5"/><path d="m11 18-6-6 6-6"/></svg>,
  shield: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/><path d="m9 12 2 2 4-4"/></svg>,
  lock: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><rect x="4" y="11" width="16" height="10" rx="2"/><path d="M8 11V7a4 4 0 0 1 8 0v4"/></svg>,
  nopass: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="8" r="4"/><path d="M6 21v-1a6 6 0 0 1 12 0v1"/></svg>,
  alert: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z"/><path d="M12 9v4"/><path d="M12 17h.01"/></svg>,
  cancel: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="9"/><path d="m9 9 6 6"/><path d="m15 9-6 6"/></svg>,
  noentry: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="9"/><path d="M8 12h8"/></svg>,
};

// ---- official SPID identity providers (canonical AgID set) ----
const IDPS = [
  { name: "Aruba ID",      dot: "#7AB800" },
  { name: "Poste ID",      dot: "#003366" },
  { name: "TIM id",        dot: "#003E7E" },
  { name: "Lepida ID",     dot: "#E2001A" },
  { name: "InfoCert ID",   dot: "#0066B3" },
  { name: "Namirial ID",   dot: "#00A0C6" },
  { name: "Sielte id",     dot: "#ED1C24" },
  { name: "SpidItalia",    dot: "#2E7D32" },
  { name: "Intesi ID",     dot: "#5A2D82" },
  { name: "TeamSystem ID", dot: "#1F4E9B" },
  { name: "EtnaID",        dot: "#F47920" },
  { name: "InfoCamere ID", dot: "#1B3A6B" },
];

// ---- strings ----
function strings(lang) {
  const it = {
    gov: "Sito ufficiale della Pubblica Amministrazione",
    recognise: "Come riconoscerlo",
    kicker: "Accesso ai servizi",
    title: "Entra nell'area riservata",
    lead: "Scegli il sistema di identità digitale con cui vuoi accedere.",
    ctxLabel: "Stai accedendo a",
    spid: "Entra con SPID",
    cie: "Entra con CIE",
    other: "Altro gestore di identità",
    noSpid: "Non hai SPID? Scopri come richiederlo",
    help: "Hai bisogno di aiuto?",
    idpTitle: "Scegli il tuo gestore di identità",
    idpSub: "Accedi con le credenziali SPID che già possiedi.",
    learn: "Maggiori informazioni",
    fPrivacy: "Privacy", fLegal: "Note legali", fA11y: "Accessibilità", fSupport: "Assistenza",
    // variant B
    asideH: "Accedi ai servizi digitali dell'ente con la tua identità digitale.",
    asideP: "Un unico accesso sicuro per tutti i servizi online dell'ente, riconosciuto in tutta Italia.",
    r1: "Accesso sicuro riconosciuto dallo Stato",
    r2: "Nessuna nuova password da ricordare",
    r3: "I tuoi dati personali restano protetti",
    // variant C subs
    spidSub: "Sistema Pubblico di Identità Digitale",
    cieSub: "Carta d'Identità Elettronica",
    chooseMethod: "Come vuoi accedere?",
    // errors
    eGenT: "Non è stato possibile completare l'accesso",
    eGenL: "Si è verificato un problema durante l'autenticazione. Riprova oppure torna all'applicazione.",
    eCanT: "Accesso annullato",
    eCanL: "Hai interrotto l'accesso prima di completarlo. Nessun dato è stato condiviso con l'ente.",
    eDenT: "Accesso negato",
    eDenL: "Non è stato fornito il consenso alla condivisione dei dati necessari per accedere al servizio.",
    retry: "Riprova ad accedere",
    backTo: "Torna a",
    ref: "Riferimento",
  };
  const en = {
    gov: "Official website of the Public Administration",
    recognise: "How to recognise it",
    kicker: "Service access",
    title: "Sign in to your account",
    lead: "Choose the digital identity you want to sign in with.",
    ctxLabel: "You are signing in to",
    spid: "Sign in with SPID",
    cie: "Sign in with CIE",
    other: "Other identity provider",
    noSpid: "Don't have SPID? Find out how to get it",
    help: "Need help?",
    idpTitle: "Choose your identity provider",
    idpSub: "Sign in with the SPID credentials you already have.",
    learn: "Learn more",
    fPrivacy: "Privacy", fLegal: "Legal notes", fA11y: "Accessibility", fSupport: "Support",
    asideH: "Access the digital services with your national digital identity.",
    asideP: "One secure sign-in for all the online services, recognised across Italy.",
    r1: "Secure access recognised by the State",
    r2: "No new password to remember",
    r3: "Your personal data stays protected",
    spidSub: "Public Digital Identity System",
    cieSub: "Electronic Identity Card",
    chooseMethod: "How would you like to sign in?",
    eGenT: "We couldn't complete the sign-in",
    eGenL: "A problem occurred during authentication. Try again or go back to the application.",
    eCanT: "Sign-in cancelled",
    eCanL: "You stopped the sign-in before completing it. No data was shared with the entity.",
    eDenT: "Access denied",
    eDenL: "Consent was not given to share the data required to access the service.",
    retry: "Try signing in again",
    backTo: "Back to",
    ref: "Reference",
  };
  return lang === "en" ? en : it;
}

// ---- shared chrome ----
function SlimBar({ t, lang }) {
  return (
    <div className="sso-slim">
      <div className="sso-slim-in">
        <span className="gov"><span className="gov-dot" /><span>{t.gov}</span></span>
        <span className="sso-lang">
          <b className={lang === "en" ? "off" : "on"}>IT</b>
          <b className={lang === "en" ? "on" : "off"}>EN</b>
        </span>
      </div>
    </div>
  );
}

function EnteBrand({ ente, center }) {
  return (
    <div className={"sso-brand" + (center ? " center" : "")}>
      <Crest cls={center ? "sso-crest lg" : "sso-crest"} />
      <div>
        <p className="sso-brand-eyebrow">{ente.eyebrow}</p>
        <p className="sso-brand-title">{ente.name}</p>
        {ente.sub ? <p className="sso-brand-sub">{ente.sub}</p> : null}
      </div>
    </div>
  );
}

function Footer({ t }) {
  return (
    <div className="sso-foot">
      <span className="agid">{I_small()}{"SPID · CIE · AgID"}</span>
      <span className="links">
        <a href="#">{t.fPrivacy}</a>
        <a href="#">{t.fLegal}</a>
        <a href="#">{t.fA11y}</a>
        <a href="#">{t.fSupport}</a>
      </span>
    </div>
  );
}
function I_small() {
  return <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={{ flex: "0 0 auto" }}><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/></svg>;
}

// ---- buttons ----
function SpidButton({ label, expanded }) {
  return (
    <button className="spid-btn" aria-expanded={expanded ? "true" : "false"}>
      <SpidMark />
      <span className="spid-word">{label}</span>
      <span className="chev">{I.chev}</span>
    </button>
  );
}
function CieButton({ label }) {
  return (
    <button className="cie-btn"><CieMark /><span>{label}</span></button>
  );
}
function FedButton({ label }) {
  return (
    <button className="fed-btn">
      <span className="fed-ico">{I.key}</span>
      <span>{label}</span>
      <span className="fed-arrow">{I.arrow}</span>
    </button>
  );
}

// ---- SPID expanded IdP panel ----
function IdpPanel({ t, providers }) {
  return (
    <div className="idp-panel">
      <div className="idp-panel-head">
        <p className="t">{t.idpTitle}</p>
        <p className="s">{t.idpSub}</p>
      </div>
      <div className="idp-grid">
        {providers.map((p) => (
          <div className="idp-tile" key={p.name}>
            <span className="idp-dot" style={{ background: p.dot }} />
            <span className="idp-name">{p.name}</span>
          </div>
        ))}
      </div>
      <div className="idp-foot">
        <a href="#">{t.noSpid.split("?")[0]}?</a>
        <span className="sep">·</span>
        <a href="#">{t.learn}</a>
      </div>
    </div>
  );
}

// ---- app-context chip ----
function AppCtx({ t, app }) {
  return (
    <div className="sso-appctx">
      <span className="ico">{I.app}</span>
      <div>
        <p className="lbl">{t.ctxLabel}</p>
        <p className="val">{app}</p>
      </div>
    </div>
  );
}

// ---- method stacks (reused) ----
function MethodStack({ t, showCie, showOther, spidExpanded, providers }) {
  return (
    <div className="sso-methods">
      <SpidButton label={t.spid} expanded={spidExpanded} />
      {spidExpanded ? <IdpPanel t={t} providers={providers} /> : null}
      {showCie && !spidExpanded ? <CieButton label={t.cie} /> : null}
      {showOther && !spidExpanded ? <FedButton label={t.other} /> : null}
    </div>
  );
}

function HelpLinks({ t }) {
  return (
    <div className="sso-help">
      <a href="#">{t.noSpid}</a>
      <a href="#" className="muted" style={{ color: "var(--fg-3)" }}>{t.help}</a>
    </div>
  );
}

// =====================================================================
// SCREEN: Variant A — centered card
// =====================================================================
function ScreenCardCentered({ lang = "it", ente, app, showCie = true, showOther = false, spidExpanded = false }) {
  const t = strings(lang);
  return (
    <div className="sso">
      <SlimBar t={t} lang={lang} />
      <EnteBrand ente={ente} center />
      <div className="sso-main top">
        <div className="sso-card">
          <p className="sso-kicker">{t.kicker}</p>
          <h1 className="sso-title">{t.title}</h1>
          <p className="sso-lead">{t.lead}</p>
          <AppCtx t={t} app={app} />
          <MethodStack t={t} showCie={showCie} showOther={showOther} spidExpanded={spidExpanded} providers={IDPS} />
          {!spidExpanded ? <HelpLinks t={t} /> : null}
        </div>
      </div>
      <Footer t={t} />
    </div>
  );
}

// =====================================================================
// SCREEN: Variant B — split (aside + methods)
// =====================================================================
function ScreenSplit({ lang = "it", ente, app, showCie = true }) {
  const t = strings(lang);
  return (
    <div className="sso">
      <SlimBar t={t} lang={lang} />
      <div className="sso-split">
        <div className="sso-split-aside">
          <div className="crest-row">
            <Crest cls="sso-crest" />
            <div>
              <p className="et">{ente.eyebrow}</p>
              <p className="nm">{ente.name}</p>
            </div>
          </div>
          <h2>{t.asideH}</h2>
          <p>{t.asideP}</p>
          <div className="sso-reassure">
            <div className="item">{I.shield}<p>{t.r1}</p></div>
            <div className="item">{I.nopass}<p>{t.r2}</p></div>
            <div className="item">{I.lock}<p>{t.r3}</p></div>
          </div>
        </div>
        <div className="sso-split-main">
          <p className="sso-kicker">{t.kicker}</p>
          <h1 className="sso-title">{t.title}</h1>
          <p className="sso-lead">{t.lead}</p>
          <AppCtx t={t} app={app} />
          <MethodStack t={t} showCie={showCie} showOther={false} spidExpanded={false} providers={IDPS} />
          <HelpLinks t={t} />
        </div>
      </div>
      <Footer t={t} />
    </div>
  );
}

// =====================================================================
// SCREEN: Variant C — guided method tiles
// =====================================================================
function ScreenTiles({ lang = "it", ente, app, showCie = true }) {
  const t = strings(lang);
  return (
    <div className="sso">
      <SlimBar t={t} lang={lang} />
      <EnteBrand ente={ente} center />
      <div className="sso-main top">
        <div className="sso-card">
          <p className="sso-kicker">{t.kicker}</p>
          <h1 className="sso-title">{t.chooseMethod}</h1>
          <AppCtx t={t} app={app} />
          <div className="sso-methods">
            <button className="sso-bigtile">
              <span className="bt-badge spid"><SpidMark /></span>
              <span><span className="bt-t" style={{ display: "block" }}>SPID</span><span className="bt-s">{t.spidSub}</span></span>
              <span className="bt-arrow">{I.arrow}</span>
            </button>
            {showCie ? (
              <button className="sso-bigtile">
                <span className="bt-badge cie"><CieMark /></span>
                <span><span className="bt-t" style={{ display: "block" }}>CIE</span><span className="bt-s">{t.cieSub}</span></span>
                <span className="bt-arrow">{I.arrow}</span>
              </button>
            ) : null}
          </div>
          <HelpLinks t={t} />
        </div>
      </div>
      <Footer t={t} />
    </div>
  );
}

// =====================================================================
// SCREEN: Error
// =====================================================================
function ScreenError({ lang = "it", ente, app, kind = "generic" }) {
  const t = strings(lang);
  const map = {
    generic: { icon: I.alert, tone: "warn", title: t.eGenT, lead: t.eGenL, code: `${t.ref}: SSO-503 · 09/06/2026 14:32` },
    cancelled: { icon: I.cancel, tone: "neutral", title: t.eCanT, lead: t.eCanL, code: null },
    denied: { icon: I.noentry, tone: "danger", title: t.eDenT, lead: t.eDenL, code: null },
  };
  const e = map[kind];
  return (
    <div className="sso">
      <SlimBar t={t} lang={lang} />
      <EnteBrand ente={ente} center />
      <div className="sso-main">
        <div className="sso-card err">
          <div className={"sso-err-icon " + e.tone}>{e.icon}</div>
          <h1 className="sso-title">{e.title}</h1>
          <p className="sso-lead">{e.lead}</p>
          <div className="sso-btn-row">
            <button className="btn-primary">{I.retry}{t.retry}</button>
            <a className="btn-outline" href="#">{I.back}{t.backTo} {app}</a>
          </div>
          {e.code ? <span className="sso-err-code">{e.code}</span> : null}
        </div>
      </div>
      <Footer t={t} />
    </div>
  );
}

Object.assign(window, {
  ScreenCardCentered, ScreenSplit, ScreenTiles, ScreenError,
  SpidButton, CieButton, IdpPanel, IDPS,
});
