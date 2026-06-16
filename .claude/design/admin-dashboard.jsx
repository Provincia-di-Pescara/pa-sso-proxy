// admin-dashboard.jsx — Dashboard screen

const DASH_DATA = {
  clients: { total: 4, enabled: 3 },
  idps: { total: 9, enabled: 7 },
  cert_days: 2821,
  access: {
    today:  { total: 47,   success: 45,   failure: 2  },
    week:   { total: 284,  success: 276,  failure: 8  },
    month:  { total: 1247, success: 1226, failure: 21 },
    by_provider: {
      spid:     { success: 945, failure: 15 },
      cie_oidc: { success: 224, failure: 4  },
      cie_saml: { success: 57,  failure: 2  },
    },
    by_client: {
      'Portale Servizi': { total: 612, success: 601 },
      'App Mobile':      { total: 338, success: 332 },
      'SUAP Online':     { total: 297, success: 293 },
    },
    recent: [
      { ts: '10/06 11:42', provider: 'spid',     client: 'Portale Servizi', result: 'success', error: null },
      { ts: '10/06 11:41', provider: 'cie_oidc', client: 'App Mobile',      result: 'success', error: null },
      { ts: '10/06 11:39', provider: 'spid',     client: 'SUAP Online',     result: 'success', error: null },
      { ts: '10/06 11:38', provider: 'spid',     client: 'Portale Servizi', result: 'failure', error: '19' },
      { ts: '10/06 11:35', provider: 'cie_oidc', client: 'Portale Servizi', result: 'success', error: null },
      { ts: '10/06 11:33', provider: 'spid',     client: 'App Mobile',      result: 'success', error: null },
      { ts: '10/06 11:28', provider: 'cie_saml', client: 'Portale Servizi', result: 'success', error: null },
      { ts: '10/06 11:21', provider: 'spid',     client: 'SUAP Online',     result: 'success', error: null },
    ],
  },
};

function DCard({ children, style }) {
  return (
    <div style={Object.assign({ background: '#fff', border: '1px solid #E2E8F0', borderRadius: 8,
      boxShadow: '0 1px 2px rgba(23,50,77,0.05)' }, style || {})}>
      {children}
    </div>
  );
}

function DCardHeader({ title, action }) {
  return (
    <div style={{ padding: '13px 20px', borderBottom: '1px solid #E2E8F0',
      display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
      <span style={{ fontSize: 13, fontWeight: 600, color: '#17324D', letterSpacing: '-0.01em' }}>{title}</span>
      {action}
    </div>
  );
}

function StatCard({ icon, label, value, sub, statusKind, onClick }) {
  const [hov, setHov] = React.useState(false);
  const statusColors = { ok: '#008758', warn: '#A66300', danger: '#D9364F' };
  const statusBgs   = { ok: '#E6F5EE', warn: '#FFF4D9', danger: '#FCE6E9' };
  const statusLabels = { ok: 'Regolare', warn: 'In scadenza', danger: 'Attenzione' };
  return (
    <DCard style={{ padding: '20px 22px', cursor: onClick ? 'pointer' : 'default',
      boxShadow: hov && onClick ? '0 3px 8px rgba(23,50,77,0.1)' : '0 1px 2px rgba(23,50,77,0.05)',
      transition: 'box-shadow 0.15s', transform: hov && onClick ? 'translateY(-1px)' : 'none' }}
      onClick={onClick}
      onMouseEnter={() => setHov(true)} onMouseLeave={() => setHov(false)}>
      <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 12 }}>
        <div style={{ minWidth: 0 }}>
          <div style={{ fontSize: 11, fontWeight: 700, textTransform: 'uppercase',
            letterSpacing: '0.07em', color: '#64748B', marginBottom: 8 }}>{label}</div>
          <div style={{ fontSize: 30, fontWeight: 700, color: '#17324D', lineHeight: 1,
            letterSpacing: '-0.02em' }}>{value}</div>
          {sub && <div style={{ fontSize: 12, color: '#64748B', marginTop: 6, lineHeight: 1.4 }}>{sub}</div>}
        </div>
        <div style={{ padding: 10, background: '#F1F5F9', borderRadius: 8, flexShrink: 0 }}>
          <window.Icon name={icon} size={20} color="#64748B" />
        </div>
      </div>
      {statusKind && (
        <div style={{ marginTop: 14, paddingTop: 12, borderTop: '1px solid #F1F5F9',
          display: 'flex', alignItems: 'center', gap: 5 }}>
          <span style={{ fontSize: 7, color: statusColors[statusKind], lineHeight: 1 }}>●</span>
          <span style={{ fontSize: 11, color: statusColors[statusKind], fontWeight: 600,
            background: statusBgs[statusKind], padding: '2px 8px', borderRadius: 99 }}>
            {statusLabels[statusKind]}
          </span>
        </div>
      )}
    </DCard>
  );
}

function ProviderBadge({ type }) {
  const map = {
    spid:     ['SPID',     '#E5F1FC', '#0066CC'],
    cie_oidc: ['CIE OIDC', '#EDE9F7', '#4A2A6E'],
    cie_saml: ['CIE SAML', '#F1F5F9', '#334155'],
  };
  const [label, bg, color] = map[type] || [type, '#F1F5F9', '#334155'];
  return (
    <span style={{ background: bg, color, padding: '2px 8px', borderRadius: 4,
      fontSize: 11, fontWeight: 700, fontFamily: 'var(--font-mono)', letterSpacing: '0.02em' }}>
      {label}
    </span>
  );
}

function ResultBadge({ result }) {
  const ok = result === 'success';
  return (
    <span style={{ background: ok ? '#E6F5EE' : '#FCE6E9', color: ok ? '#008758' : '#D9364F',
      padding: '2px 9px', borderRadius: 99, fontSize: 11, fontWeight: 600 }}>
      {ok ? 'OK' : 'Errore'}
    </span>
  );
}

function AccessStat({ label, total, success, failure }) {
  const pct = total > 0 ? Math.round((success / total) * 100) : 100;
  return (
    <DCard style={{ padding: '20px 22px' }}>
      <div style={{ fontSize: 11, fontWeight: 700, textTransform: 'uppercase',
        letterSpacing: '0.07em', color: '#64748B', marginBottom: 8 }}>{label}</div>
      <div style={{ fontSize: 34, fontWeight: 700, color: '#17324D', lineHeight: 1, letterSpacing: '-0.02em' }}>
        {total.toLocaleString('it-IT')}
      </div>
      <div style={{ marginTop: 8, display: 'flex', gap: 14, fontSize: 12 }}>
        <span style={{ color: '#008758', fontWeight: 600 }}>✓ {success.toLocaleString('it-IT')}</span>
        {failure > 0 && <span style={{ color: '#D9364F', fontWeight: 600 }}>✗ {failure}</span>}
      </div>
      <div style={{ marginTop: 12, height: 3, background: '#F1F5F9', borderRadius: 2, overflow: 'hidden' }}>
        <div style={{ height: '100%', width: pct + '%', background: '#0066CC', borderRadius: 2,
          transition: 'width 0.6s cubic-bezier(.2,.7,.3,1)' }} />
      </div>
      <div style={{ marginTop: 4, fontSize: 11, color: '#94A3B8', textAlign: 'right' }}>{pct}% successo</div>
    </DCard>
  );
}

function DashboardScreen({ onNav, satosaOk }) {
  const d = DASH_DATA;
  const { by_provider, by_client, recent, today, week, month } = d.access;
  const totalMonth = month.total;
  const spidTot    = (by_provider.spid?.success     || 0) + (by_provider.spid?.failure     || 0);
  const cieOidcTot = (by_provider.cie_oidc?.success || 0) + (by_provider.cie_oidc?.failure || 0);
  const cieSamlTot = (by_provider.cie_saml?.success || 0) + (by_provider.cie_saml?.failure || 0);

  const TH = ({ children, right }) => (
    <th style={{ padding: '9px 20px', textAlign: right ? 'right' : 'left', fontSize: 10, fontWeight: 700,
      textTransform: 'uppercase', letterSpacing: '0.08em', color: '#64748B',
      background: '#F8FAFC', whiteSpace: 'nowrap' }}>
      {children}
    </th>
  );
  const TD = ({ children, mono, right, style: s }) => (
    <td style={Object.assign({ padding: '11px 20px', textAlign: right ? 'right' : 'left',
      fontFamily: mono ? 'var(--font-mono)' : 'var(--font-sans)', fontSize: mono ? 12 : 13,
      color: '#334155', verticalAlign: 'middle' }, s || {})}>
      {children}
    </td>
  );

  return (
    <div style={{ maxWidth: 1180, margin: '0 auto' }}>

      {/* Status cards */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 14, marginBottom: 20 }}>
        <StatCard icon="dashboard" label="SATOSA"
          value={satosaOk ? 'Attivo' : 'Offline'}
          sub="Ultima verifica: adesso" statusKind={satosaOk ? 'ok' : 'danger'} />
        <StatCard icon="clients" label="Client OIDC"
          value={d.clients.enabled + '/' + d.clients.total}
          sub={d.clients.total - d.clients.enabled + ' disabilitato'}
          statusKind="ok" onClick={() => onNav('clients')} />
        <StatCard icon="shield" label="IdP SPID"
          value={d.idps.enabled + '/' + d.idps.total}
          sub={d.idps.total - d.idps.enabled + ' disabilitati'}
          statusKind="ok" onClick={() => onNav('idps')} />
        <StatCard icon="document" label="Certificato SPID"
          value={d.cert_days.toLocaleString('it-IT') + 'gg'}
          sub="Scade 01/03/2034" statusKind="ok" onClick={() => onNav('certs')} />
      </div>

      {/* Access stats */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 14, marginBottom: 20 }}>
        <AccessStat label="Oggi" {...today} />
        <AccessStat label="Ultimi 7 giorni" {...week} />
        <AccessStat label="Ultimi 30 giorni" {...month} />
      </div>

      {/* Provider breakdown + top clients */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 14, marginBottom: 20 }}>
        <DCard>
          <DCardHeader title="Distribuzione provider — 30 giorni" />
          <div style={{ padding: '18px 20px', display: 'flex', flexDirection: 'column', gap: 14 }}>
            {[
              { label: 'SPID',     total: spidTot,    color: '#0066CC', bg: '#E5F1FC' },
              { label: 'CIE OIDC', total: cieOidcTot, color: '#4A2A6E', bg: '#EDE9F7' },
              { label: 'CIE SAML', total: cieSamlTot, color: '#475569', bg: '#F1F5F9' },
            ].map(({ label, total, color }) => {
              const pct = totalMonth > 0 ? Math.round((total / totalMonth) * 100) : 0;
              return (
                <div key={label}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 5, alignItems: 'baseline' }}>
                    <span style={{ fontSize: 13, fontWeight: 500, color: '#17324D' }}>{label}</span>
                    <span style={{ fontSize: 12, color: '#64748B' }}>
                      {total.toLocaleString('it-IT')}
                      <span style={{ color: '#94A3B8', marginLeft: 5 }}>({pct}%)</span>
                    </span>
                  </div>
                  <div style={{ height: 6, background: '#F1F5F9', borderRadius: 3, overflow: 'hidden' }}>
                    <div style={{ height: '100%', width: pct + '%', background: color, borderRadius: 3 }} />
                  </div>
                </div>
              );
            })}
          </div>
        </DCard>

        <DCard>
          <DCardHeader title="Client più attivi — 30 giorni" />
          <table style={{ width: '100%', borderCollapse: 'collapse' }}>
            <thead>
              <tr style={{ borderBottom: '1px solid #E2E8F0' }}>
                <TH>Client</TH><TH right>Autenticazioni</TH><TH right>Tasso successo</TH>
              </tr>
            </thead>
            <tbody>
              {Object.entries(by_client).map(([name, s]) => (
                <tr key={name} style={{ borderBottom: '1px solid #F1F5F9' }}>
                  <TD><span style={{ fontWeight: 500, color: '#17324D' }}>{name}</span></TD>
                  <TD right>{s.total.toLocaleString('it-IT')}</TD>
                  <TD right style={{ color: '#008758', fontWeight: 600 }}>
                    {Math.round((s.success / s.total) * 100)}%
                  </TD>
                </tr>
              ))}
            </tbody>
          </table>
        </DCard>
      </div>

      {/* Recent activity */}
      <DCard>
        <DCardHeader title="Attività recente"
          action={
            <button onClick={() => onNav('log')}
              style={{ background: 'none', border: 'none', cursor: 'pointer',
                fontSize: 12, color: '#0066CC', fontFamily: 'var(--font-sans)', fontWeight: 500,
                padding: '2px 0' }}>
              Vedi tutto →
            </button>
          } />
        <table style={{ width: '100%', borderCollapse: 'collapse' }}>
          <thead>
            <tr style={{ borderBottom: '1px solid #E2E8F0' }}>
              <TH>Ora</TH><TH>Provider</TH><TH>Client</TH><TH>Esito</TH><TH>Err.</TH>
            </tr>
          </thead>
          <tbody>
            {recent.map((r, i) => (
              <tr key={i} style={{ borderBottom: '1px solid #F1F5F9' }}
                onMouseEnter={e => e.currentTarget.style.background = '#FAFBFC'}
                onMouseLeave={e => e.currentTarget.style.background = ''}>
                <TD mono>{r.ts}</TD>
                <TD><ProviderBadge type={r.provider} /></TD>
                <TD><span style={{ color: '#17324D', fontWeight: 500 }}>{r.client}</span></TD>
                <TD><ResultBadge result={r.result} /></TD>
                <TD mono style={{ color: '#94A3B8' }}>{r.error || '—'}</TD>
              </tr>
            ))}
          </tbody>
        </table>
      </DCard>
    </div>
  );
}

Object.assign(window, { DashboardScreen });
