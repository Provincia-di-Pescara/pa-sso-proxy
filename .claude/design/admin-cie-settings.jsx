// admin-cie-settings.jsx — CIE, Settings, Cert, Log, Backup, Test screens

const CIE_MOCK = {
  saml_metadata_url: 'https://idserver.servizicie.interno.gov.it/idpms/SAML2/METADATA/idp.xml',
  oidc_enabled: true,
  oidc_environment: 'produzione',
  oidc_provider_url: 'https://oidc.idserver.servizicie.interno.gov.it',
  trust_anchor_url: 'https://oidc.registry.servizicie.interno.gov.it',
  authority_hint_url: 'https://oidc.registry.servizicie.interno.gov.it',
  contact_pec: 'digitale@pec.provincia.pescara.it',
  homepage_uri: 'https://www.provincia.pescara.it',
  trust_mark: 'eyJhbGciOiJSUzI1NiIsInR5cCI6InRydXN0LW1hcmsrand...',
  jwk_keys: [
    { id: 1, name: 'cie-federation-a1b2c3d4', use: 'federation', created: '01/03/2025', kid: 'fed-a1b2c3d4' },
    { id: 2, name: 'cie-sig-a1b2c3d4',        use: 'sig',        created: '01/03/2025', kid: 'sig-a1b2c3d4' },
    { id: 3, name: 'cie-enc-a1b2c3d4',        use: 'enc',        created: '01/03/2025', kid: 'enc-a1b2c3d4' },
  ],
};

const SETTINGS_MOCK = {
  org_display_name: 'Provincia di Pescara',
  org_name: 'provincia-pescara',
  org_url: 'https://www.provincia.pescara.it',
  proxy_hostname: 'sso.provincia.pescara.it',
  ipa_code: 'pe_prov',
  contact_email: 'digitale@pec.provincia.pescara.it',
  contact_phone: '+39 085 4521',
  org_city: 'Pescara',
  privacy_url: 'https://www.provincia.pescara.it/privacy',
  legal_notes_url: '',
  accessibility_url: '',
  support_url: '',
};

const CERT_MOCK = {
  cn: 'sso.provincia.pescara.it',
  org: 'Provincia di Pescara',
  valid_from: '01/03/2024',
  valid_to: '01/03/2034',
  days_remaining: 2821,
  serial: 'A4:F2:9C:11:33:BB:DE:07:4F:2A',
  ipa_code: 'PA:IT-pe_prov',
};

const LOG_MOCK = [
  { ts: '10/06/2026 11:42:33', provider: 'spid',     client: 'client-Xr4K9mNp', result: 'success', error: '' },
  { ts: '10/06/2026 11:41:17', provider: 'cie_oidc', client: 'client-2bY7vLqR', result: 'success', error: '' },
  { ts: '10/06/2026 11:39:52', provider: 'spid',     client: 'client-9tFzPkW1', result: 'success', error: '' },
  { ts: '10/06/2026 11:38:01', provider: 'spid',     client: 'client-Xr4K9mNp', result: 'failure', error: '19' },
  { ts: '10/06/2026 11:35:44', provider: 'cie_oidc', client: 'client-Xr4K9mNp', result: 'success', error: '' },
  { ts: '10/06/2026 11:33:12', provider: 'spid',     client: 'client-2bY7vLqR', result: 'success', error: '' },
  { ts: '10/06/2026 11:28:55', provider: 'cie_saml', client: 'client-Xr4K9mNp', result: 'success', error: '' },
  { ts: '10/06/2026 11:21:08', provider: 'spid',     client: 'client-9tFzPkW1', result: 'success', error: '' },
  { ts: '10/06/2026 11:15:33', provider: 'spid',     client: 'client-2bY7vLqR', result: 'failure', error: '20' },
  { ts: '10/06/2026 11:09:44', provider: 'cie_oidc', client: 'client-Xr4K9mNp', result: 'success', error: '' },
];

// ---- shared input helpers ----
const INP = { width: '100%', padding: '8px 12px', border: '1.5px solid #CBD5E1',
  borderRadius: 4, fontSize: 13, fontFamily: 'var(--font-sans)', color: '#17324D',
  outline: 'none', boxSizing: 'border-box', lineHeight: 1.4 };
const INP_RO = Object.assign({}, INP, { background: '#F8FAFC', color: '#64748B', cursor: 'default' });
const LBL = { fontSize: 11, fontWeight: 700, color: '#475569', display: 'block',
  marginBottom: 5, textTransform: 'uppercase', letterSpacing: '0.06em' };

function Field({ label, value, onChange, readonly, hint, mono }) {
  return (
    <div style={{ marginBottom: 18 }}>
      <label style={LBL}>{label}</label>
      <input readOnly={!!readonly}
        style={Object.assign({}, readonly ? INP_RO : INP,
          mono ? { fontFamily: 'var(--font-mono)', fontSize: 12 } : {})}
        value={value}
        onChange={onChange ? e => onChange(e.target.value) : undefined}
        onFocus={e => { if (!readonly) e.target.style.borderColor = '#0066CC'; }}
        onBlur={e => { if (!readonly) e.target.style.borderColor = '#CBD5E1'; }} />
      {hint && <p style={{ fontSize: 11, color: '#64748B', marginTop: 4 }}>{hint}</p>}
    </div>
  );
}

function SavedToast() {
  return (
    <div style={{ padding: '10px 16px', background: '#E6F5EE', borderRadius: 4,
      border: '1px solid #2E7D32', fontSize: 13, color: '#008758', fontWeight: 500, marginBottom: 16,
      display: 'flex', alignItems: 'center', gap: 8 }}>
      ✓ Salvato correttamente
    </div>
  );
}

// ---- CIE Screen ----
function CieScreen() {
  const [tab, setTab]   = React.useState('saml');
  const [cfg, setCfg]   = React.useState(CIE_MOCK);
  const [saved, setSaved] = React.useState(false);
  const set = k => v => setCfg(p => Object.assign({}, p, { [k]: v }));
  const save = () => { setSaved(true); setTimeout(() => setSaved(false), 2500); };

  const UseColors = { federation: ['#EDE9F7','#4A2A6E'], sig: ['#E5F1FC','#0066CC'], enc: ['#E6F5EE','#008758'] };

  return (
    <div style={{ maxWidth: 860, margin: '0 auto' }}>
      <div style={{ display: 'flex', borderBottom: '2px solid #E2E8F0', marginBottom: 24 }}>
        {[['saml','SAML'],['oidc','OIDC Federation'],['jwk','Chiavi JWK']].map(([id, lbl]) => (
          <button key={id} onClick={() => setTab(id)}
            style={{ padding: '10px 24px', border: 'none', background: 'none', cursor: 'pointer',
              fontSize: 14, fontWeight: tab === id ? 600 : 400, fontFamily: 'var(--font-sans)',
              color: tab === id ? '#0066CC' : '#64748B',
              borderBottom: '2px solid ' + (tab === id ? '#0066CC' : 'transparent'),
              marginBottom: -2, transition: 'color 0.12s' }}>
            {lbl}
          </button>
        ))}
      </div>

      {tab === 'saml' && (
        <window.Card2 style={{ padding: '24px 32px' }}>
          <div style={{ fontSize: 15, fontWeight: 700, color: '#17324D', marginBottom: 22 }}>Configurazione CIE SAML</div>
          {saved && <SavedToast />}
          <Field label="Metadata URL IdP CIE" value={cfg.saml_metadata_url}
            onChange={set('saml_metadata_url')}
            hint="URL del metadata SAML del Ministero dell'Interno per CIE." mono />
          <div style={{ marginBottom: 22 }}>
            <label style={LBL}>Client ID derivato (CIE OIDC)</label>
            <code style={{ display: 'block', fontFamily: 'var(--font-mono)', fontSize: 12,
              background: '#F8FAFC', padding: '8px 12px', borderRadius: 4,
              border: '1px solid #E2E8F0', color: '#17324D' }}>
              https://sso.provincia.pescara.it/CieOidcRp
            </code>
            <p style={{ fontSize: 11, color: '#64748B', marginTop: 4 }}>
              Derivato dal proxy_hostname. Da usare come Entity ID nel portale CIE.
            </p>
          </div>
          <window.BtnPrimary onClick={save}>{saved ? '✓ Salvato' : 'Salva'}</window.BtnPrimary>
        </window.Card2>
      )}

      {tab === 'oidc' && (
        <window.Card2 style={{ padding: '24px 32px' }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 22 }}>
            <div style={{ fontSize: 15, fontWeight: 700, color: '#17324D' }}>OIDC Federation 1.0</div>
            <label style={{ display: 'flex', alignItems: 'center', gap: 10, cursor: 'pointer' }}>
              <span style={{ fontSize: 13, color: '#334155', fontWeight: 500 }}>Abilitata</span>
              <window.Toggle checked={cfg.oidc_enabled} onChange={set('oidc_enabled')} />
            </label>
          </div>
          {saved && <SavedToast />}
          <div style={{ marginBottom: 18 }}>
            <label style={LBL}>Ambiente</label>
            <div style={{ display: 'flex', gap: 10 }}>
              {[['collaudo','Collaudo (preprod)'],['produzione','Produzione']].map(([env, lbl]) => (
                <label key={env} style={{ display: 'flex', alignItems: 'center', gap: 8,
                  padding: '8px 16px', borderRadius: 4, cursor: 'pointer',
                  border: '1.5px solid ' + (cfg.oidc_environment === env ? '#0066CC' : '#CBD5E1'),
                  background: cfg.oidc_environment === env ? '#E5F1FC' : '#fff',
                  fontSize: 13, fontWeight: 500,
                  color: cfg.oidc_environment === env ? '#0066CC' : '#334155', userSelect: 'none' }}>
                  <input type="radio" style={{ display: 'none' }}
                    checked={cfg.oidc_environment === env}
                    onChange={() => setCfg(p => Object.assign({}, p, { oidc_environment: env }))} />
                  {lbl}
                </label>
              ))}
            </div>
          </div>
          <Field label="Provider URL" value={cfg.oidc_provider_url} readonly mono />
          <Field label="Trust Anchor URL" value={cfg.trust_anchor_url} readonly mono />
          <Field label="Authority Hint URL" value={cfg.authority_hint_url} readonly mono />
          <Field label="Contatto PEC" value={cfg.contact_pec} onChange={set('contact_pec')} mono
            hint="Email di contatto PEC dell'ente. Obbligatoria per l'entity configuration." />
          <Field label="Homepage URI" value={cfg.homepage_uri} onChange={set('homepage_uri')} />
          <div style={{ marginBottom: 18 }}>
            <label style={LBL}>Trust Mark</label>
            <textarea style={Object.assign({}, INP, { height: 72, resize: 'vertical',
              fontFamily: 'var(--font-mono)', fontSize: 11 })}
              value={cfg.trust_mark} onChange={e => setCfg(p => Object.assign({}, p, { trust_mark: e.target.value }))} />
            <p style={{ fontSize: 11, color: '#64748B', marginTop: 4 }}>
              JWT emesso dal portale CIE dopo accettazione della registrazione.
            </p>
          </div>
          <window.BtnPrimary onClick={save}>{saved ? '✓ Salvato' : 'Salva configurazione'}</window.BtnPrimary>
        </window.Card2>
      )}

      {tab === 'jwk' && (
        <div>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 14 }}>
            <p style={{ fontSize: 13, color: '#64748B', margin: 0 }}>
              3 keypair RSA — federation, sig, enc. Rigenera solo se strettamente necessario.
            </p>
            <window.BtnSecondary small
              onClick={() => window.confirm('Rigenerare TUTTE e 3 le chiavi? Richiede ri-registrazione sul portale CIE.') && null}>
              Rigenera tutto
            </window.BtnSecondary>
          </div>
          {cfg.jwk_keys.map(key => {
            const [bg, color] = UseColors[key.use] || ['#F1F5F9', '#334155'];
            return (
              <window.Card2 key={key.id} style={{ marginBottom: 10, padding: '18px 22px' }}>
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 14 }}>
                    <div style={{ padding: 10, background: bg, borderRadius: 8 }}>
                      <window.Icon name="key" size={18} color={color} />
                    </div>
                    <div>
                      <div style={{ fontWeight: 600, color: '#17324D', fontSize: 13, display: 'flex', alignItems: 'center', gap: 8 }}>
                        <span style={{ background: bg, color, padding: '2px 9px',
                          borderRadius: 4, fontSize: 10, fontWeight: 700, letterSpacing: '0.06em',
                          textTransform: 'uppercase' }}>
                          {key.use}
                        </span>
                        {key.name}
                      </div>
                      <div style={{ fontSize: 11, color: '#64748B', marginTop: 4, fontFamily: 'var(--font-mono)' }}>
                        kid: {key.kid} · generata: {key.created}
                      </div>
                    </div>
                  </div>
                  <window.BtnDanger small
                    onClick={() => window.confirm('Eliminare la chiave ' + key.use + '?') && null}>
                    Elimina
                  </window.BtnDanger>
                </div>
              </window.Card2>
            );
          })}
          <div style={{ marginTop: 14, padding: '14px 18px', background: '#FFF4D9',
            borderRadius: 6, border: '1px solid #E4BD56', fontSize: 13, color: '#6B4400', lineHeight: 1.6 }}>
            <strong>Attenzione:</strong> la chiave <code style={{ fontFamily: 'var(--font-mono)', fontSize: 12 }}>federation</code> è
            registrata sul portale CIE. Rigenerarla richiede una nuova registrazione e approvazione ministeriale.
          </div>
        </div>
      )}
    </div>
  );
}

// ---- Settings Screen ----
function SettingsScreen() {
  const [s, setS]     = React.useState(SETTINGS_MOCK);
  const [saved, setSaved] = React.useState(false);
  const set = k => v => setS(p => Object.assign({}, p, { [k]: v }));
  const save = () => { setSaved(true); setTimeout(() => setSaved(false), 2500); };

  return (
    <div style={{ maxWidth: 860, margin: '0 auto' }}>
      {saved && <SavedToast />}

      <window.Card2 style={{ padding: '22px 28px', marginBottom: 16 }}>
        <div style={{ fontSize: 14, fontWeight: 700, color: '#17324D', marginBottom: 18 }}>Dati ente</div>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0 24px' }}>
          <Field label="Nome per esteso" value={s.org_display_name} onChange={set('org_display_name')} />
          <Field label="Slug / IPA name" value={s.org_name} onChange={set('org_name')} mono
            hint="Usato internamente nei metadata SPID." />
          <Field label="Codice IPA" value={s.ipa_code} onChange={set('ipa_code')} mono
            hint="Dalla banca dati IndicePA." />
          <Field label="Città sede" value={s.org_city} onChange={set('org_city')}
            hint="Usata nel SubjectDN del certificato SPID." />
          <Field label="URL sito istituzionale" value={s.org_url} onChange={set('org_url')} />
        </div>
      </window.Card2>

      <window.Card2 style={{ padding: '22px 28px', marginBottom: 16 }}>
        <div style={{ fontSize: 14, fontWeight: 700, color: '#17324D', marginBottom: 18 }}>Endpoint proxy</div>
        <Field label="Hostname pubblico" value={s.proxy_hostname} onChange={set('proxy_hostname')} mono
          hint="Dominio con HTTPS (es. sso.ente.it). Usato in redirect URI SPID/CIE, metadata e entity configuration." />
      </window.Card2>

      <window.Card2 style={{ padding: '22px 28px', marginBottom: 16 }}>
        <div style={{ fontSize: 14, fontWeight: 700, color: '#17324D', marginBottom: 18 }}>Contatti</div>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0 24px' }}>
          <Field label="Email contatto tecnico" value={s.contact_email} onChange={set('contact_email')} mono />
          <Field label="Telefono" value={s.contact_phone} onChange={set('contact_phone')} />
        </div>
      </window.Card2>

      <window.Card2 style={{ padding: '22px 28px', marginBottom: 22 }}>
        <div style={{ fontSize: 14, fontWeight: 700, color: '#17324D', marginBottom: 18 }}>URL istituzionali</div>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0 24px' }}>
          <Field label="Privacy policy" value={s.privacy_url} onChange={set('privacy_url')} />
          <Field label="Note legali" value={s.legal_notes_url} onChange={set('legal_notes_url')} />
          <Field label="Dichiarazione accessibilità" value={s.accessibility_url} onChange={set('accessibility_url')} />
          <Field label="Supporto" value={s.support_url} onChange={set('support_url')} />
        </div>
      </window.Card2>

      <window.BtnPrimary onClick={save}>Salva impostazioni</window.BtnPrimary>
    </div>
  );
}

// ---- Cert Screen ----
function CertScreen() {
  const cert = CERT_MOCK;
  const kindMap = cert.days_remaining > 90 ? ['ok','#008758','#E6F5EE','Valido'] :
                  cert.days_remaining > 0  ? ['warn','#A66300','#FFF4D9','In scadenza'] :
                                             ['danger','#D9364F','#FCE6E9','Scaduto'];
  const [, sColor, sBg, sLabel] = kindMap;

  return (
    <div style={{ maxWidth: 680, margin: '0 auto' }}>
      <window.Card2 style={{ padding: '26px 30px', marginBottom: 16 }}>
        <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', marginBottom: 22 }}>
          <div style={{ fontSize: 15, fontWeight: 700, color: '#17324D' }}>Certificato SPID corrente</div>
          <span style={{ background: sBg, color: sColor, padding: '4px 12px',
            borderRadius: 99, fontSize: 11, fontWeight: 700 }}>{sLabel}</span>
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: 'max-content 1fr', gap: '10px 20px',
          fontSize: 13, paddingTop: 16, borderTop: '1px solid #E2E8F0', marginBottom: 22 }}>
          {[
            ['CN', cert.cn, true],
            ['O', cert.org, false],
            ['Codice IPA', cert.ipa_code, true],
            ['Valido dal', cert.valid_from, false],
            ['Valido fino al', cert.valid_to, false],
            ['Giorni rimanenti', cert.days_remaining.toLocaleString('it-IT') + ' giorni', false],
            ['Seriale', cert.serial, true],
          ].map(([k, v, mono]) => (
            <React.Fragment key={k}>
              <span style={{ color: '#64748B', fontWeight: 500, whiteSpace: 'nowrap',
                paddingTop: 1 }}>{k}</span>
              <span style={{ fontFamily: mono ? 'var(--font-mono)' : 'var(--font-sans)',
                fontSize: mono ? 12 : 13, color: '#17324D',
                fontWeight: k === 'Giorni rimanenti' ? 700 : 400 }}>{v}</span>
            </React.Fragment>
          ))}
        </div>
        <div style={{ display: 'flex', gap: 8 }}>
          <window.BtnSecondary small onClick={() => {}}>Scarica .pem</window.BtnSecondary>
          <window.BtnSecondary small onClick={() => {}}>Scarica .crt</window.BtnSecondary>
        </div>
      </window.Card2>

      <window.Card2 style={{ padding: '22px 30px' }}>
        <div style={{ fontSize: 14, fontWeight: 700, color: '#17324D', marginBottom: 8 }}>Rigenera certificato</div>
        <p style={{ fontSize: 13, color: '#64748B', lineHeight: 1.6, margin: '0 0 16px' }}>
          Genera un nuovo certificato SPID RSA-2048 valido 10 anni, con SubjectDN conforme AgID.
          Dopo la rigenerazione è necessario scaricare il metadata SPID aggiornato e inviarlo ad AgID.
        </p>
        <div style={{ padding: '11px 15px', background: '#FFF4D9', border: '1px solid #E4BD56',
          borderRadius: 4, fontSize: 12, color: '#6B4400', marginBottom: 18, lineHeight: 1.5 }}>
          ⚠ Completare la re-registrazione AgID prima di mettere in produzione il nuovo certificato.
        </div>
        <window.BtnDanger
          onClick={() => window.confirm('Confermi la rigenerazione del certificato SPID?')}>
          Rigenera certificato SPID
        </window.BtnDanger>
      </window.Card2>
    </div>
  );
}

// ---- Log Screen ----
function LogScreen() {
  const [logs]    = React.useState(LOG_MOCK);
  const [prov, setProv] = React.useState('');
  const [res, setRes]   = React.useState('');
  const filtered = logs.filter(l => (!prov || l.provider === prov) && (!res || l.result === res));

  const ProvBadge = ({ type }) => {
    const m = { spid: ['SPID','#E5F1FC','#0066CC'], cie_oidc: ['CIE OIDC','#EDE9F7','#4A2A6E'], cie_saml: ['CIE SAML','#F1F5F9','#334155'] };
    const [lbl, bg, color] = m[type] || [type, '#F1F5F9', '#334155'];
    return <span style={{ background: bg, color, padding: '2px 8px', borderRadius: 4,
      fontSize: 11, fontWeight: 700, fontFamily: 'var(--font-mono)' }}>{lbl}</span>;
  };

  const sel = { padding: '6px 12px', border: '1.5px solid #CBD5E1', borderRadius: 4,
    fontSize: 13, fontFamily: 'var(--font-sans)', color: '#17324D', background: '#fff', cursor: 'pointer',
    outline: 'none' };
  const TH3 = ({ c }) => (
    <th style={{ padding: '9px 20px', textAlign: 'left', fontSize: 10, fontWeight: 700,
      textTransform: 'uppercase', letterSpacing: '0.08em', color: '#64748B',
      background: '#F8FAFC', whiteSpace: 'nowrap' }}>{c}</th>
  );

  return (
    <div style={{ maxWidth: 1100, margin: '0 auto' }}>
      <div style={{ display: 'flex', gap: 10, alignItems: 'center', marginBottom: 16,
        padding: '12px 18px', background: '#fff', borderRadius: 8, border: '1px solid #E2E8F0' }}>
        <span style={{ fontSize: 10, fontWeight: 700, color: '#64748B',
          textTransform: 'uppercase', letterSpacing: '0.08em' }}>Filtri</span>
        <select style={sel} value={prov} onChange={e => setProv(e.target.value)}>
          <option value="">Tutti i provider</option>
          <option value="spid">SPID</option>
          <option value="cie_oidc">CIE OIDC</option>
          <option value="cie_saml">CIE SAML</option>
        </select>
        <select style={sel} value={res} onChange={e => setRes(e.target.value)}>
          <option value="">Tutti gli esiti</option>
          <option value="success">Successo</option>
          <option value="failure">Errore</option>
        </select>
        <button onClick={() => { setProv(''); setRes(''); }}
          style={{ background: 'none', border: 'none', cursor: 'pointer',
            fontSize: 12, color: '#64748B', padding: '4px 8px', borderRadius: 4 }}>
          Azzera
        </button>
        <div style={{ flex: 1 }} />
        <window.BtnSecondary small onClick={() => {}}>Esporta CSV</window.BtnSecondary>
      </div>

      <window.Card2>
        <div style={{ padding: '8px 20px', borderBottom: '1px solid #E2E8F0',
          fontSize: 11, color: '#94A3B8', fontWeight: 500 }}>
          {filtered.length} accessi
        </div>
        <table style={{ width: '100%', borderCollapse: 'collapse' }}>
          <thead>
            <tr style={{ borderBottom: '1px solid #E2E8F0' }}>
              <TH3 c="Timestamp" /><TH3 c="Provider" /><TH3 c="Client ID" /><TH3 c="Esito" /><TH3 c="Err." />
            </tr>
          </thead>
          <tbody>
            {filtered.map((r, i) => (
              <tr key={i} style={{ borderBottom: '1px solid #F1F5F9' }}
                onMouseEnter={e => e.currentTarget.style.background = '#FAFBFC'}
                onMouseLeave={e => e.currentTarget.style.background = ''}>
                <td style={{ padding: '10px 20px', fontFamily: 'var(--font-mono)', fontSize: 11, color: '#64748B' }}>{r.ts}</td>
                <td style={{ padding: '10px 20px' }}><ProvBadge type={r.provider} /></td>
                <td style={{ padding: '10px 20px', fontFamily: 'var(--font-mono)', fontSize: 11, color: '#475569' }}>{r.client}</td>
                <td style={{ padding: '10px 20px' }}>
                  <span style={{ background: r.result === 'success' ? '#E6F5EE' : '#FCE6E9',
                    color: r.result === 'success' ? '#008758' : '#D9364F',
                    padding: '2px 9px', borderRadius: 99, fontSize: 11, fontWeight: 600 }}>
                    {r.result === 'success' ? 'OK' : 'Errore'}
                  </span>
                </td>
                <td style={{ padding: '10px 20px', fontFamily: 'var(--font-mono)', fontSize: 11, color: '#94A3B8' }}>
                  {r.error || '—'}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </window.Card2>
    </div>
  );
}

// ---- Backup Screen ----
function BackupScreen() {
  const [fileSelected, setFile] = React.useState(false);
  return (
    <div style={{ maxWidth: 600, margin: '0 auto' }}>
      <window.Card2 style={{ padding: '24px 28px', marginBottom: 16 }}>
        <div style={{ fontSize: 14, fontWeight: 700, color: '#17324D', marginBottom: 8 }}>Esporta configurazione</div>
        <p style={{ fontSize: 13, color: '#64748B', lineHeight: 1.6, margin: '0 0 18px' }}>
          Esporta l'intera configurazione del proxy in un file JSON (client OIDC, impostazioni ente,
          IdP abilitati). I client secret in chiaro e le chiavi JWK private sono inclusi.
        </p>
        <window.BtnPrimary onClick={() => {}}>Scarica backup JSON</window.BtnPrimary>
      </window.Card2>

      <window.Card2 style={{ padding: '24px 28px' }}>
        <div style={{ fontSize: 14, fontWeight: 700, color: '#17324D', marginBottom: 8 }}>Importa configurazione</div>
        <div style={{ padding: '11px 15px', background: '#FCE6E9', border: '1px solid #D9364F',
          borderRadius: 4, fontSize: 12, color: '#8B1A2A', marginBottom: 16, lineHeight: 1.5 }}>
          ⚠ L'importazione sovrascrive tutta la configurazione esistente. Effettuare prima un backup.
        </div>
        <p style={{ fontSize: 13, color: '#64748B', lineHeight: 1.6, margin: '0 0 14px' }}>
          Selezionare un file JSON esportato da questa interfaccia.
        </p>
        <div style={{ border: '2px dashed #CBD5E1', borderRadius: 6, padding: '22px',
          textAlign: 'center', marginBottom: 14, background: '#F8FAFC' }}>
          <div style={{ fontSize: 13, color: '#64748B', marginBottom: 10 }}>Trascina il file qui oppure</div>
          <label style={{ cursor: 'pointer' }}>
            <span style={{ background: '#fff', border: '1.5px solid #0066CC', color: '#0066CC',
              padding: '6px 16px', borderRadius: 4, fontSize: 13, fontWeight: 600 }}>
              Seleziona file
            </span>
            <input type="file" accept=".json" style={{ display: 'none' }}
              onChange={() => setFile(true)} />
          </label>
        </div>
        {fileSelected && (
          <div style={{ padding: '9px 14px', background: '#E6F5EE', borderRadius: 4,
            fontSize: 12, color: '#008758', marginBottom: 14, fontWeight: 500 }}>
            ✓ File selezionato. Pronto per l'importazione.
          </div>
        )}
        <window.BtnDanger disabled={!fileSelected}
          onClick={() => fileSelected && window.confirm('Confermi? Sovrascriverà tutta la configurazione.')}>
          Importa e sovrascrivi
        </window.BtnDanger>
      </window.Card2>
    </div>
  );
}

// ---- Test Screen ----
function TestScreen() {
  const [clientId, setClientId]     = React.useState('client-Xr4K9mNp');
  const [redirectUri, setRedirectUri] = React.useState('https://servizi.provincia.pescara.it/callback');
  const [scope, setScope]           = React.useState('openid profile email');
  const [url, setUrl]               = React.useState('');
  const [copied, setCopied]         = React.useState(false);

  const generate = () => {
    const challenge = 'jHkWEdUXMU1BIjeiYv9me2y7-KqTg1K9FMNeGTiy8ok';
    const state = Math.random().toString(36).slice(2, 10);
    const nonce = Math.random().toString(36).slice(2, 10);
    setUrl('https://sso.provincia.pescara.it/authorize' +
      '?client_id=' + encodeURIComponent(clientId) +
      '&response_type=code' +
      '&redirect_uri=' + encodeURIComponent(redirectUri) +
      '&scope=' + encodeURIComponent(scope) +
      '&state=' + state +
      '&nonce=' + nonce +
      '&code_challenge=' + challenge +
      '&code_challenge_method=S256');
  };

  const copyUrl = () => { navigator.clipboard && navigator.clipboard.writeText(url); setCopied(true); setTimeout(() => setCopied(false), 2000); };

  return (
    <div style={{ maxWidth: 660, margin: '0 auto' }}>
      <window.Card2 style={{ padding: '24px 28px', marginBottom: 16 }}>
        <div style={{ fontSize: 14, fontWeight: 700, color: '#17324D', marginBottom: 20 }}>
          Genera Authorization URL — PKCE
        </div>
        <Field label="Client ID" value={clientId} onChange={setClientId} mono />
        <Field label="Redirect URI" value={redirectUri} onChange={setRedirectUri} />
        <Field label="Scope" value={scope} onChange={setScope}
          hint="Separati da spazio: openid profile email offline_access" />
        <window.BtnPrimary onClick={generate}>Genera URL</window.BtnPrimary>
      </window.Card2>

      {url && (
        <window.Card2 style={{ padding: '22px 28px' }}>
          <div style={{ fontSize: 13, fontWeight: 600, color: '#17324D', marginBottom: 12 }}>
            Authorization URL
          </div>
          <div style={{ background: '#F8FAFC', border: '1px solid #E2E8F0', borderRadius: 4,
            padding: '12px 14px', marginBottom: 14, wordBreak: 'break-all',
            fontFamily: 'var(--font-mono)', fontSize: 11, color: '#334155', lineHeight: 1.7 }}>
            {url}
          </div>
          <div style={{ display: 'flex', gap: 8 }}>
            <window.BtnPrimary onClick={() => window.open(url, '_blank')}>Apri nel browser</window.BtnPrimary>
            <window.BtnSecondary onClick={copyUrl}>{copied ? '✓ Copiato' : 'Copia URL'}</window.BtnSecondary>
          </div>
        </window.Card2>
      )}
    </div>
  );
}

// ---- Placeholder Screen ----
function PlaceholderScreen({ title }) {
  return (
    <div style={{ maxWidth: 500, margin: '80px auto 0', textAlign: 'center' }}>
      <div style={{ width: 64, height: 64, background: '#F1F5F9', borderRadius: 16,
        margin: '0 auto 22px', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
        <window.Icon name="globe" size={28} color="#94A3B8" />
      </div>
      <div style={{ fontSize: 20, fontWeight: 700, color: '#17324D', marginBottom: 10 }}>{title}</div>
      <p style={{ fontSize: 14, color: '#64748B', lineHeight: 1.6, margin: 0 }}>
        Sezione in sviluppo. Disponibile in una versione futura del proxy SSO.
      </p>
    </div>
  );
}

Object.assign(window, { CieScreen, SettingsScreen, CertScreen, LogScreen, BackupScreen, TestScreen, PlaceholderScreen });
