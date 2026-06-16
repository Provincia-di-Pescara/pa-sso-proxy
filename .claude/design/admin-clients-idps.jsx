// admin-clients-idps.jsx — Clients + IdPs screens

const MOCK_CLIENTS = [
  { id: 1, client_id: 'client-Xr4K9mNp', name: 'Portale Servizi al Cittadino',
    scopes: ['openid','profile','email'], redirect_uris: ['https://servizi.provincia.pescara.it/callback'], enabled: true, created: '15/11/2024' },
  { id: 2, client_id: 'client-2bY7vLqR', name: 'App Mobile Istituzionale',
    scopes: ['openid','profile'], redirect_uris: ['app.pescara://callback','https://app.provincia.pescara.it/auth/callback'], enabled: true, created: '03/12/2024' },
  { id: 3, client_id: 'client-9tFzPkW1', name: 'Sportello SUAP Online',
    scopes: ['openid','profile','email'], redirect_uris: ['https://suap.provincia.pescara.it/oidc/callback'], enabled: true, created: '22/01/2025' },
  { id: 4, client_id: 'client-4hJcMnS8', name: 'Portale Trasparenza',
    scopes: ['openid'], redirect_uris: ['https://trasparenza.provincia.pescara.it/auth/return'], enabled: false, created: '07/03/2025' },
];

const MOCK_IDPS = [
  { id: 1, name: 'PosteID (Poste Italiane)',   alias: 'posteid',    url: 'https://identity.poste.it/spid/v1/metadata', enabled: true },
  { id: 2, name: 'SpidItalia (Register.it)',   alias: 'registerid', url: 'https://spid.register.it/login/idpSSOMetadata', enabled: true },
  { id: 3, name: 'InfoCert ID',                alias: 'infocertid', url: 'https://identity.infocert.it/metadata/metadata.xml', enabled: true },
  { id: 4, name: 'Namirial ID',                alias: 'namirialid', url: 'https://idp.namirialtsp.com/idp/metadata', enabled: true },
  { id: 5, name: 'Aruba ID',                   alias: 'arubaid',    url: 'https://loginspid.aruba.it/metadata', enabled: true },
  { id: 6, name: 'TIM id',                     alias: 'timid',      url: 'https://login.id.tim.it/affwebservices/public/saml2sso', enabled: true },
  { id: 7, name: 'LepidaID',                   alias: 'lepidaid',   url: 'https://id.lepida.it/idp/shibboleth', enabled: true },
  { id: 8, name: 'Sielte id',                  alias: 'sielteid',   url: 'https://identity.sieltecloud.it/', enabled: false },
  { id: 9, name: 'Intesa Sanpaolo ID',         alias: 'intesaid',   url: 'https://spid.intesasanpaolo.com/sso/metadata', enabled: false },
];

// ---- Shared primitives ----

function Card2({ children, style }) {
  return (
    <div style={Object.assign({ background: '#fff', border: '1px solid #E2E8F0',
      borderRadius: 8, boxShadow: '0 1px 2px rgba(23,50,77,0.05)' }, style || {})}>
      {children}
    </div>
  );
}

function CardHeader2({ title, action }) {
  return (
    <div style={{ padding: '13px 24px', borderBottom: '1px solid #E2E8F0',
      display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
      <span style={{ fontSize: 13, fontWeight: 600, color: '#17324D' }}>{title}</span>
      {action}
    </div>
  );
}

function BtnPrimary({ children, onClick, small, disabled: dis }) {
  const [hov, setHov] = React.useState(false);
  return (
    <button onClick={dis ? undefined : onClick}
      onMouseEnter={() => setHov(true)} onMouseLeave={() => setHov(false)}
      style={{ background: dis ? '#94A3B8' : hov ? '#004080' : '#0066CC',
        color: '#fff', border: 'none',
        padding: small ? '5px 12px' : '8px 18px', borderRadius: 4,
        fontSize: small ? 12 : 13.5, fontWeight: 600, cursor: dis ? 'default' : 'pointer',
        fontFamily: 'var(--font-sans)', transition: 'background 0.12s',
        display: 'inline-flex', alignItems: 'center', gap: 6, lineHeight: 1 }}>
      {children}
    </button>
  );
}

function BtnSecondary({ children, onClick, small }) {
  const [hov, setHov] = React.useState(false);
  return (
    <button onClick={onClick}
      onMouseEnter={() => setHov(true)} onMouseLeave={() => setHov(false)}
      style={{ background: hov ? '#EBF3FF' : '#fff',
        color: '#0066CC', border: '1.5px solid #0066CC',
        padding: small ? '4px 11px' : '7px 17px', borderRadius: 4,
        fontSize: small ? 12 : 13.5, fontWeight: 600, cursor: 'pointer',
        fontFamily: 'var(--font-sans)', transition: 'background 0.12s',
        display: 'inline-flex', alignItems: 'center', gap: 6, lineHeight: 1 }}>
      {children}
    </button>
  );
}

function BtnDanger({ children, onClick, small }) {
  const [hov, setHov] = React.useState(false);
  return (
    <button onClick={onClick}
      onMouseEnter={() => setHov(true)} onMouseLeave={() => setHov(false)}
      style={{ background: hov ? '#B02039' : '#D9364F', color: '#fff', border: 'none',
        padding: small ? '4px 10px' : '7px 17px', borderRadius: 4,
        fontSize: small ? 12 : 13.5, fontWeight: 600, cursor: 'pointer',
        fontFamily: 'var(--font-sans)', transition: 'background 0.12s',
        display: 'inline-flex', alignItems: 'center', gap: 6, lineHeight: 1 }}>
      {children}
    </button>
  );
}

function StatusPill({ enabled }) {
  return (
    <span style={{ background: enabled ? '#E6F5EE' : '#F1F5F9',
      color: enabled ? '#008758' : '#64748B',
      padding: '3px 10px', borderRadius: 99, fontSize: 11, fontWeight: 600,
      letterSpacing: '0.01em' }}>
      {enabled ? 'Attivo' : 'Disabilitato'}
    </span>
  );
}

function Toggle({ checked, onChange }) {
  return (
    <button onClick={() => onChange(!checked)}
      style={{ width: 34, height: 18, borderRadius: 9, border: 'none', cursor: 'pointer',
        background: checked ? '#0066CC' : '#CBD5E1',
        position: 'relative', transition: 'background 0.18s', padding: 0, flexShrink: 0 }}>
      <span style={{ position: 'absolute', top: 2, left: checked ? 16 : 2,
        width: 14, height: 14, borderRadius: 7, background: '#fff',
        transition: 'left 0.18s', display: 'block',
        boxShadow: '0 1px 2px rgba(0,0,0,0.15)' }} />
    </button>
  );
}

const TH2 = ({ children, right }) => (
  <th style={{ padding: '9px 20px', textAlign: right ? 'right' : 'left', fontSize: 10, fontWeight: 700,
    textTransform: 'uppercase', letterSpacing: '0.08em', color: '#64748B',
    background: '#F8FAFC', whiteSpace: 'nowrap' }}>{children}</th>
);

// ---- Client Form ----
function ClientForm({ client, onCancel, onSave }) {
  const [name, setName]   = React.useState(client ? client.name : '');
  const [uris, setUris]   = React.useState(client ? client.redirect_uris.join('\n') : '');
  const [scopes, setScopes] = React.useState(client ? client.scopes : ['openid']);
  const ALL_SCOPES = ['openid','profile','email','offline_access'];
  const toggleScope = s => setScopes(p => p.includes(s) ? p.filter(x => x !== s) : [...p, s]);

  const inp = { width: '100%', padding: '8px 12px', border: '1.5px solid #CBD5E1',
    borderRadius: 4, fontSize: 13, fontFamily: 'var(--font-sans)', color: '#17324D',
    outline: 'none', boxSizing: 'border-box', lineHeight: 1.4 };
  const lbl = { fontSize: 12, fontWeight: 600, color: '#334155', display: 'block',
    marginBottom: 5, textTransform: 'uppercase', letterSpacing: '0.05em' };
  const hint = { fontSize: 11, color: '#64748B', marginTop: 4 };

  return (
    <div style={{ maxWidth: 560 }}>
      <div style={{ marginBottom: 20 }}>
        <label style={lbl}>Nome applicazione</label>
        <input style={inp} value={name} onChange={e => setName(e.target.value)}
          placeholder="es. Portale Servizi al Cittadino"
          onFocus={e => e.target.style.borderColor='#0066CC'}
          onBlur={e => e.target.style.borderColor='#CBD5E1'} />
      </div>
      <div style={{ marginBottom: 20 }}>
        <label style={lbl}>Redirect URI</label>
        <textarea style={Object.assign({}, inp, { height: 90, resize: 'vertical' })}
          value={uris} onChange={e => setUris(e.target.value)}
          placeholder={'https://app.example.it/callback\napp.example://callback'}
          onFocus={e => e.target.style.borderColor='#0066CC'}
          onBlur={e => e.target.style.borderColor='#CBD5E1'} />
        <p style={hint}>Una URI per riga. Deve corrispondere esattamente all'URI usata dall'app.</p>
      </div>
      <div style={{ marginBottom: 20 }}>
        <label style={lbl}>Scope consentiti</label>
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginTop: 6 }}>
          {ALL_SCOPES.map(s => (
            <label key={s} style={{ display: 'flex', alignItems: 'center', gap: 6,
              padding: '5px 12px', borderRadius: 4, cursor: 'pointer', fontSize: 13,
              border: '1.5px solid ' + (scopes.includes(s) ? '#0066CC' : '#CBD5E1'),
              background: scopes.includes(s) ? '#E5F1FC' : '#fff',
              color: scopes.includes(s) ? '#0066CC' : '#475569', fontWeight: 500,
              userSelect: 'none' }}>
              <input type="checkbox" style={{ display: 'none' }}
                checked={scopes.includes(s)} onChange={() => toggleScope(s)} />
              {s}
            </label>
          ))}
        </div>
      </div>
      {client && (
        <div style={{ marginBottom: 20, padding: '10px 14px', background: '#F8FAFC',
          borderRadius: 4, border: '1px solid #E2E8F0' }}>
          <div style={{ fontSize: 10, fontWeight: 700, color: '#64748B', textTransform: 'uppercase',
            letterSpacing: '0.08em', marginBottom: 5 }}>Client ID</div>
          <code style={{ fontFamily: 'var(--font-mono)', fontSize: 12, color: '#17324D' }}>
            {client.client_id}
          </code>
        </div>
      )}
      <div style={{ display: 'flex', gap: 8 }}>
        <BtnPrimary onClick={() => onSave({ name, uris, scopes })}>
          {client ? 'Salva modifiche' : 'Crea client'}
        </BtnPrimary>
        <BtnSecondary onClick={onCancel}>Annulla</BtnSecondary>
      </div>
    </div>
  );
}

// ---- Secret Reveal ----
function SecretReveal({ clientId, secret, onClose }) {
  const [copied, setCopied] = React.useState(false);
  const copy = () => { navigator.clipboard && navigator.clipboard.writeText(secret); setCopied(true); setTimeout(() => setCopied(false), 2000); };
  return (
    <div style={{ maxWidth: 540 }}>
      <div style={{ padding: '14px 18px', background: '#FFF4D9', border: '1px solid #E4BD56',
        borderRadius: 6, marginBottom: 22, display: 'flex', gap: 10, alignItems: 'flex-start' }}>
        <window.Icon name="warning" size={16} color="#A66300" style={{ marginTop: 1, flexShrink: 0 }} />
        <p style={{ fontSize: 13, color: '#6B4400', lineHeight: 1.55, margin: 0 }}>
          Il client secret viene mostrato una sola volta. Conservarlo in un vault sicuro — non sarà più recuperabile dal pannello.
        </p>
      </div>
      <div style={{ marginBottom: 14 }}>
        <div style={{ fontSize: 10, fontWeight: 700, color: '#64748B', textTransform: 'uppercase',
          letterSpacing: '0.08em', marginBottom: 5 }}>Client ID</div>
        <code style={{ fontFamily: 'var(--font-mono)', fontSize: 13, color: '#17324D',
          background: '#F8FAFC', padding: '8px 12px', borderRadius: 4,
          border: '1px solid #E2E8F0', display: 'block' }}>{clientId}</code>
      </div>
      <div style={{ marginBottom: 24 }}>
        <div style={{ fontSize: 10, fontWeight: 700, color: '#64748B', textTransform: 'uppercase',
          letterSpacing: '0.08em', marginBottom: 5 }}>Client Secret</div>
        <div style={{ display: 'flex', gap: 8, alignItems: 'stretch' }}>
          <code style={{ fontFamily: 'var(--font-mono)', fontSize: 12, color: '#17324D',
            background: '#F8FAFC', padding: '8px 12px', borderRadius: 4,
            border: '1px solid #E2E8F0', flex: 1, wordBreak: 'break-all', lineHeight: 1.6 }}>{secret}</code>
          <button onClick={copy} title="Copia"
            style={{ background: copied ? '#E6F5EE' : '#F1F5F9',
              border: '1px solid ' + (copied ? '#2E7D32' : '#E2E8F0'),
              borderRadius: 4, padding: '0 14px', cursor: 'pointer',
              color: copied ? '#008758' : '#475569', fontSize: 13, fontWeight: 600,
              transition: 'all 0.12s', flexShrink: 0 }}>
            {copied ? '✓' : 'Copia'}
          </button>
        </div>
      </div>
      <BtnPrimary onClick={onClose}>Ho salvato il secret — chiudi</BtnPrimary>
    </div>
  );
}

// ---- Clients Screen ----
function ClientsScreen({ onNav }) {
  const [view, setView]       = React.useState('list');
  const [clients, setClients] = React.useState(MOCK_CLIENTS);
  const [editTarget, setEdit] = React.useState(null);
  const [revealData, setReveal] = React.useState(null);

  const handleCreate = data => {
    const uid = Math.random().toString(36).slice(2, 10);
    const newC = { id: Date.now(), client_id: 'client-' + uid, name: data.name,
      scopes: data.scopes, redirect_uris: data.uris.split('\n').filter(Boolean),
      enabled: true, created: new Date().toLocaleDateString('it-IT') };
    const secret = 'sk-' + [1,2,3,4,5].map(() => Math.random().toString(36).slice(2,7)).join('-');
    setClients(p => [newC, ...p]);
    setReveal({ clientId: newC.client_id, secret });
    setView('reveal');
  };

  const handleEdit = data => {
    setClients(p => p.map(c => c.id === editTarget.id
      ? { ...c, name: data.name, scopes: data.scopes, redirect_uris: data.uris.split('\n').filter(Boolean) } : c));
    setView('list');
  };

  const Crumb = ({ label, onClick: click }) => (
    <button onClick={click} style={{ background: 'none', border: 'none', cursor: 'pointer',
      fontSize: 12, color: '#0066CC', padding: 0, fontFamily: 'var(--font-sans)' }}>{label}</button>
  );

  if (view === 'new') return (
    <div style={{ maxWidth: 1180, margin: '0 auto' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 12, color: '#64748B', marginBottom: 20 }}>
        <Crumb label="Client OIDC" onClick={() => setView('list')} />
        <span>›</span><span>Nuovo client</span>
      </div>
      <Card2 style={{ padding: '26px 32px', maxWidth: 660 }}>
        <div style={{ fontSize: 17, fontWeight: 700, color: '#17324D', marginBottom: 24 }}>Registra nuovo client</div>
        <ClientForm client={null} onCancel={() => setView('list')} onSave={handleCreate} />
      </Card2>
    </div>
  );

  if (view === 'edit' && editTarget) return (
    <div style={{ maxWidth: 1180, margin: '0 auto' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 12, color: '#64748B', marginBottom: 20 }}>
        <Crumb label="Client OIDC" onClick={() => setView('list')} />
        <span>›</span><span>Modifica</span>
      </div>
      <Card2 style={{ padding: '26px 32px', maxWidth: 660 }}>
        <div style={{ fontSize: 17, fontWeight: 700, color: '#17324D', marginBottom: 24 }}>Modifica — {editTarget.name}</div>
        <ClientForm client={editTarget} onCancel={() => setView('list')} onSave={handleEdit} />
      </Card2>
    </div>
  );

  if (view === 'reveal' && revealData) return (
    <div style={{ maxWidth: 1180, margin: '0 auto' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 12, color: '#64748B', marginBottom: 20 }}>
        <Crumb label="Client OIDC" onClick={() => setView('list')} />
        <span>›</span><span>Client creato</span>
      </div>
      <Card2 style={{ padding: '26px 32px', maxWidth: 660 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 24 }}>
          <span style={{ width: 28, height: 28, background: '#E6F5EE', borderRadius: 99,
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            fontSize: 14, color: '#008758', fontWeight: 700 }}>✓</span>
          <div style={{ fontSize: 17, fontWeight: 700, color: '#17324D' }}>Client registrato con successo</div>
        </div>
        <SecretReveal {...revealData} onClose={() => setView('list')} />
      </Card2>
    </div>
  );

  return (
    <div style={{ maxWidth: 1180, margin: '0 auto' }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 16 }}>
        <span style={{ fontSize: 12, color: '#64748B' }}>
          {clients.filter(c => c.enabled).length} attivi · {clients.length} totali
        </span>
        <BtnPrimary onClick={() => setView('new')}>
          <window.Icon name="plus" size={15} color="#fff" /> Nuovo client
        </BtnPrimary>
      </div>

      <Card2 style={{ marginBottom: 16 }}>
        <table style={{ width: '100%', borderCollapse: 'collapse' }}>
          <thead>
            <tr style={{ borderBottom: '1px solid #E2E8F0' }}>
              <TH2>Nome</TH2><TH2>Client ID</TH2><TH2>Scope</TH2><TH2>URI</TH2><TH2>Stato</TH2><TH2></TH2>
            </tr>
          </thead>
          <tbody>
            {clients.map(c => (
              <tr key={c.id} style={{ borderBottom: '1px solid #F1F5F9' }}
                onMouseEnter={e => e.currentTarget.style.background = '#FAFBFC'}
                onMouseLeave={e => e.currentTarget.style.background = ''}>
                <td style={{ padding: '13px 20px', verticalAlign: 'middle' }}>
                  <div style={{ fontWeight: 600, color: '#17324D', fontSize: 13 }}>{c.name}</div>
                  <div style={{ fontSize: 11, color: '#94A3B8', marginTop: 2 }}>{c.created}</div>
                </td>
                <td style={{ padding: '13px 20px', verticalAlign: 'middle' }}>
                  <code style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: '#475569',
                    background: '#F1F5F9', padding: '2px 7px', borderRadius: 3 }}>{c.client_id}</code>
                </td>
                <td style={{ padding: '13px 20px', verticalAlign: 'middle' }}>
                  <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>
                    {c.scopes.map(s => (
                      <span key={s} style={{ background: '#F1F5F9', color: '#334155',
                        padding: '2px 7px', borderRadius: 3, fontSize: 11, fontWeight: 500 }}>{s}</span>
                    ))}
                  </div>
                </td>
                <td style={{ padding: '13px 20px', verticalAlign: 'middle', fontSize: 12, color: '#64748B' }}>
                  {c.redirect_uris.length} {c.redirect_uris.length === 1 ? 'URI' : 'URI'}
                </td>
                <td style={{ padding: '13px 20px', verticalAlign: 'middle' }}>
                  <StatusPill enabled={c.enabled} />
                </td>
                <td style={{ padding: '13px 20px', verticalAlign: 'middle' }}>
                  <div style={{ display: 'flex', gap: 5 }}>
                    <button title={c.enabled ? 'Disabilita' : 'Abilita'}
                      onClick={() => setClients(p => p.map(x => x.id === c.id ? {...x, enabled: !x.enabled} : x))}
                      style={{ background: '#F1F5F9', border: 'none', borderRadius: 4, padding: '5px 9px',
                        cursor: 'pointer', color: '#64748B', fontSize: 13, lineHeight: 1 }}>
                      {c.enabled ? '⏸' : '▶'}
                    </button>
                    <button title="Modifica"
                      onClick={() => { setEdit(c); setView('edit'); }}
                      style={{ background: '#F1F5F9', border: 'none', borderRadius: 4, padding: '5px 9px',
                        cursor: 'pointer', color: '#64748B', fontSize: 13, lineHeight: 1 }}>✏</button>
                    <button title="Elimina"
                      onClick={() => window.confirm('Eliminare il client "' + c.name + '"?') && setClients(p => p.filter(x => x.id !== c.id))}
                      style={{ background: '#FCE6E9', border: 'none', borderRadius: 4, padding: '5px 9px',
                        cursor: 'pointer', color: '#D9364F', fontSize: 13, lineHeight: 1 }}>✕</button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card2>

      <Card2 style={{ padding: '14px 20px' }}>
        <div style={{ fontSize: 10, fontWeight: 700, color: '#64748B', textTransform: 'uppercase',
          letterSpacing: '0.08em', marginBottom: 10 }}>Endpoint OIDC del proxy</div>
        <div style={{ display: 'grid', gridTemplateColumns: 'max-content 1fr', gap: '5px 16px', fontSize: 12 }}>
          {[['Authorization','https://sso.provincia.pescara.it/authorize'],
            ['Token','https://sso.provincia.pescara.it/token'],
            ['JWKS','https://sso.provincia.pescara.it/jwks'],
            ['Issuer','https://sso.provincia.pescara.it']].map(([k,v]) => (
            <React.Fragment key={k}>
              <span style={{ color: '#64748B', fontWeight: 500, whiteSpace: 'nowrap' }}>{k}</span>
              <code style={{ fontFamily: 'var(--font-mono)', color: '#17324D' }}>{v}</code>
            </React.Fragment>
          ))}
        </div>
      </Card2>
    </div>
  );
}

// ---- IdPs Screen ----
function IdpsScreen() {
  const [idps, setIdps]   = React.useState(MOCK_IDPS);
  const [filter, setFilter] = React.useState('all');
  const shown = filter === 'all' ? idps : idps.filter(i => filter === 'enabled' ? i.enabled : !i.enabled);
  const enabledCount = idps.filter(i => i.enabled).length;
  const toggle = id => setIdps(p => p.map(i => i.id === id ? {...i, enabled: !i.enabled} : i));

  return (
    <div style={{ maxWidth: 1100, margin: '0 auto' }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 16 }}>
        <span style={{ fontSize: 12, color: '#64748B' }}>
          {enabledCount} abilitati · {idps.length - enabledCount} disabilitati
        </span>
        <div style={{ display: 'flex', gap: 2, background: '#F1F5F9', padding: 3, borderRadius: 6 }}>
          {[['all','Tutti'],['enabled','Abilitati'],['disabled','Disabilitati']].map(([f, lbl]) => (
            <button key={f} onClick={() => setFilter(f)}
              style={{ padding: '4px 14px', borderRadius: 4, border: 'none', cursor: 'pointer',
                fontSize: 12, fontWeight: filter === f ? 600 : 400, fontFamily: 'var(--font-sans)',
                background: filter === f ? '#fff' : 'transparent',
                color: filter === f ? '#17324D' : '#64748B',
                boxShadow: filter === f ? '0 1px 2px rgba(0,0,0,0.06)' : 'none',
                transition: 'all 0.12s' }}>
              {lbl}
            </button>
          ))}
        </div>
      </div>

      <Card2>
        <table style={{ width: '100%', borderCollapse: 'collapse' }}>
          <thead>
            <tr style={{ borderBottom: '1px solid #E2E8F0' }}>
              <TH2>Identity Provider</TH2>
              <TH2>Metadata URL</TH2>
              <TH2>Abilitato</TH2>
            </tr>
          </thead>
          <tbody>
            {shown.map(idp => (
              <tr key={idp.id} style={{ borderBottom: '1px solid #F1F5F9',
                opacity: idp.enabled ? 1 : 0.55, transition: 'opacity 0.15s' }}
                onMouseEnter={e => e.currentTarget.style.background = '#FAFBFC'}
                onMouseLeave={e => e.currentTarget.style.background = ''}>
                <td style={{ padding: '13px 20px', verticalAlign: 'middle' }}>
                  <div style={{ fontWeight: 600, color: '#17324D', fontSize: 13 }}>{idp.name}</div>
                  <code style={{ fontSize: 11, color: '#64748B', fontFamily: 'var(--font-mono)' }}>{idp.alias}</code>
                </td>
                <td style={{ padding: '13px 20px', verticalAlign: 'middle' }}>
                  <code style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: '#475569',
                    wordBreak: 'break-all', lineHeight: 1.5 }}>{idp.url}</code>
                </td>
                <td style={{ padding: '13px 20px', verticalAlign: 'middle' }}>
                  <Toggle checked={idp.enabled} onChange={() => toggle(idp.id)} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card2>
    </div>
  );
}

Object.assign(window, { ClientsScreen, IdpsScreen, BtnPrimary, BtnSecondary, BtnDanger, Card2, CardHeader2, StatusPill, Toggle });
