// admin-shell.jsx — Sidebar, Topbar, AdminShell layout

const _ICO = {
  dashboard: "M3.75 6A2.25 2.25 0 0 1 6 3.75h2.25A2.25 2.25 0 0 1 10.5 6v2.25a2.25 2.25 0 0 1-2.25 2.25H6a2.25 2.25 0 0 1-2.25-2.25V6ZM3.75 15.75A2.25 2.25 0 0 1 6 13.5h2.25a2.25 2.25 0 0 1 2.25 2.25V18a2.25 2.25 0 0 1-2.25 2.25H6A2.25 2.25 0 0 1 3.75 18v-2.25ZM13.5 6a2.25 2.25 0 0 1 2.25-2.25H18A2.25 2.25 0 0 1 20.25 6v2.25A2.25 2.25 0 0 1 18 10.5h-2.25a2.25 2.25 0 0 1-2.25-2.25V6ZM13.5 15.75a2.25 2.25 0 0 1 2.25-2.25H18a2.25 2.25 0 0 1 2.25 2.25V18A2.25 2.25 0 0 1 18 20.25h-2.25A2.25 2.25 0 0 1 13.5 18v-2.25Z",
  clients: "M9 17.25v1.007a3 3 0 0 1-.879 2.122L7.5 21h9l-.621-.621A3 3 0 0 1 15 18.257V17.25m6-12V15a2.25 2.25 0 0 1-2.25 2.25H5.25A2.25 2.25 0 0 1 3 15V5.25m18 0A2.25 2.25 0 0 0 18.75 3H5.25A2.25 2.25 0 0 0 3 5.25m18 0H3",
  shield: "M9 12.75 11.25 15 15 9.75m-3-7.036A11.959 11.959 0 0 1 3.598 6 11.99 11.99 0 0 0 3 9.749c0 5.592 3.824 10.29 9 11.623 5.176-1.332 9-6.03 9-11.622 0-1.31-.21-2.571-.598-3.751h-.152c-3.196 0-6.1-1.248-8.25-3.285Z",
  cie: "M15 9h3.75M15 12h3.75M15 15h3.75M4.5 19.5h15a2.25 2.25 0 0 0 2.25-2.25V6.75A2.25 2.25 0 0 0 19.5 4.5h-15a2.25 2.25 0 0 0-2.25 2.25v10.5A2.25 2.25 0 0 0 4.5 19.5Zm6-10.125a1.875 1.875 0 1 1-3.75 0 1.875 1.875 0 0 1 3.75 0Zm1.294 6.336a6.721 6.721 0 0 1-3.17.789 6.721 6.721 0 0 1-3.168-.789 3.376 3.376 0 0 1 6.338 0Z",
  chart: "M3 13.125C3 12.504 3.504 12 4.125 12h2.25c.621 0 1.125.504 1.125 1.125v6.75C7.5 20.496 6.996 21 6.375 21h-2.25A1.125 1.125 0 0 1 3 19.875v-6.75ZM9.75 8.625c0-.621.504-1.125 1.125-1.125h2.25c.621 0 1.125.504 1.125 1.125v11.25c0 .621-.504 1.125-1.125 1.125h-2.25a1.125 1.125 0 0 1-1.125-1.125V8.625ZM16.5 4.125c0-.621.504-1.125 1.125-1.125h2.25C20.496 3 21 3.504 21 4.125v15.75c0 .621-.504 1.125-1.125 1.125h-2.25a1.125 1.125 0 0 1-1.125-1.125V4.125Z",
  beaker: "M9.75 3.104v5.714a2.25 2.25 0 0 1-.659 1.591L5 14.5M9.75 3.104c-.251.023-.501.05-.75.082m.75-.082a24.301 24.301 0 0 1 4.5 0m0 0v5.714c0 .597.237 1.17.659 1.591L19.8 15.3M14.25 3.104c.251.023.501.05.75.082M19.8 15.3l-1.57.393A9.065 9.065 0 0 1 12 15a9.065 9.065 0 0 1-6.23-.693L5 14.5m14.8.8 1.402 1.402c1.232 1.232.65 3.318-1.067 3.611A48.309 48.309 0 0 1 12 21c-2.773 0-5.491-.235-8.135-.687-1.718-.293-2.3-2.379-1.067-3.61L5 14.5",
  document: "M19.5 14.25v-2.625a3.375 3.375 0 0 0-3.375-3.375h-1.5A1.125 1.125 0 0 1 13.5 7.125v-1.5a3.375 3.375 0 0 0-3.375-3.375H8.25m0 12.75h7.5m-7.5 3H12M10.5 2.25H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 0 0-9-9Z",
  cog: "M9.594 3.94c.09-.542.56-.94 1.11-.94h2.593c.55 0 1.02.398 1.11.94l.213 1.281c.063.374.313.686.645.87.074.04.147.083.22.127.325.196.72.257 1.075.124l1.217-.456a1.125 1.125 0 0 1 1.37.49l1.296 2.247a1.125 1.125 0 0 1-.26 1.431l-1.003.827c-.293.241-.438.613-.43.992a7.723 7.723 0 0 1 0 .255c-.008.378.137.75.43.991l1.004.827c.424.35.534.955.26 1.43l-1.298 2.247a1.125 1.125 0 0 1-1.369.491l-1.217-.456c-.355-.133-.75-.072-1.076.124a6.47 6.47 0 0 1-.22.128c-.331.183-.581.495-.644.869l-.213 1.281c-.09.543-.56.94-1.11.94h-2.594c-.55 0-1.019-.398-1.11-.94l-.213-1.281c-.062-.374-.312-.686-.644-.87a6.52 6.52 0 0 1-.22-.127c-.325-.196-.72-.257-1.076-.124l-1.217.456a1.125 1.125 0 0 1-1.369-.49l-1.297-2.247a1.125 1.125 0 0 1 .26-1.431l1.004-.827c.292-.24.437-.613.43-.991a6.932 6.932 0 0 1 0-.255c.007-.38-.138-.751-.43-.992l-1.004-.827a1.125 1.125 0 0 1-.26-1.43l1.297-2.247a1.125 1.125 0 0 1 1.37-.491l1.216.456c.356.133.751.072 1.076-.124.072-.044.146-.086.22-.128.332-.183.582-.495.644-.869l.214-1.28ZM15 12a3 3 0 1 1-6 0 3 3 0 0 1 6 0Z",
  archive: "m20.25 7.5-.625 10.632a2.25 2.25 0 0 1-2.247 2.118H6.622a2.25 2.25 0 0 1-2.247-2.118L3.75 7.5M10 11.25h4M3.375 7.5h17.25c.621 0 1.125-.504 1.125-1.125v-1.5c0-.621-.504-1.125-1.125-1.125H3.375c-.621 0-1.125.504-1.125 1.125v1.5c0 .621.504 1.125 1.125 1.125Z",
  globe: "M12 21a9.004 9.004 0 0 0 8.716-6.747M12 21a9.004 9.004 0 0 1-8.716-6.747M12 21c2.485 0 4.5-4.03 4.5-9S14.485 3 12 3m0 18c-2.485 0-4.5-4.03-4.5-9S9.515 3 12 3m0 0a8.997 8.997 0 0 1 7.843 4.582M12 3a8.997 8.997 0 0 0-7.843 4.582m15.686 0A11.953 11.953 0 0 1 12 10.5c-2.998 0-5.74-1.1-7.843-2.918m15.686 0A8.959 8.959 0 0 1 21 12c0 .778-.099 1.533-.284 2.253m0 0A17.919 17.919 0 0 1 12 16.5c-3.162 0-6.133-.815-8.716-2.247m0 0A9.015 9.015 0 0 1 3 12c0-1.605.42-3.113 1.157-4.418",
  wallet: "M21 12a2.25 2.25 0 0 0-2.25-2.25H15a3 3 0 1 1-6 0H5.25A2.25 2.25 0 0 0 3 12m18 0v6a2.25 2.25 0 0 1-2.25 2.25H5.25A2.25 2.25 0 0 1 3 18v-6m18 0V9M3 12V9m18-3a2.25 2.25 0 0 0-2.25-2.25H5.25A2.25 2.25 0 0 0 3 6v3m18 0H3",
  logout: "M15.75 9V5.25A2.25 2.25 0 0 0 13.5 3h-6a2.25 2.25 0 0 0-2.25 2.25v13.5A2.25 2.25 0 0 0 7.5 21h6a2.25 2.25 0 0 0 2.25-2.25V15m3 0 3-3m0 0-3-3m3 3H9",
  key: "M15.75 5.25a3 3 0 0 1 3 3m3 0a6 6 0 0 1-7.029 5.912c-.563-.097-1.159.026-1.563.43L10.5 17.25H8.25v2.25H6v2.25H2.25v-2.818c0-.597.237-1.17.659-1.591l6.499-6.499c.404-.404.527-1 .43-1.563A6 6 0 0 1 21.75 8.25Z",
  warning: "M12 9v3.75m-9.303 3.376c-.866 1.5.217 3.374 1.948 3.374h14.71c1.73 0 2.813-1.874 1.948-3.374L13.949 3.378c-.866-1.5-3.032-1.5-3.898 0L2.697 16.126ZM12 15.75h.007v.008H12v-.008Z",
  plus: "M12 4.5v15m7.5-7.5h-15",
};

function Icon({ name, size, color, style }) {
  size = size || 20;
  color = color || 'currentColor';
  style = style || {};
  const d = _ICO[name];
  if (!d) return null;
  return (
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none"
      stroke={color} strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"
      width={size} height={size} style={Object.assign({ flexShrink: 0 }, style)}>
      <path strokeLinecap="round" strokeLinejoin="round" d={d} />
    </svg>
  );
}

function NavGroup({ label }) {
  return (
    <div style={{ padding: '16px 16px 4px', fontSize: 10, fontWeight: 700,
      textTransform: 'uppercase', letterSpacing: '0.1em',
      color: 'rgba(255,255,255,0.32)', fontFamily: 'var(--font-sans)' }}>
      {label}
    </div>
  );
}

function NavItem({ icon, label, active, badge, disabled, onClick }) {
  const [hov, setHov] = React.useState(false);
  const bg = active ? 'rgba(0,102,204,0.18)' : hov ? 'rgba(255,255,255,0.07)' : 'transparent';
  const clr = active ? '#fff' : disabled ? 'rgba(255,255,255,0.28)' : hov ? 'rgba(255,255,255,0.9)' : 'rgba(255,255,255,0.65)';
  return (
    <button onClick={disabled ? undefined : onClick}
      onMouseEnter={() => setHov(true)} onMouseLeave={() => setHov(false)}
      style={{ display: 'flex', alignItems: 'center', gap: 10, width: '100%', border: 'none',
        borderLeft: '3px solid ' + (active ? '#0066CC' : 'transparent'),
        background: bg, color: clr,
        paddingLeft: 13, paddingRight: 12, paddingTop: 0, paddingBottom: 0,
        cursor: disabled ? 'default' : 'pointer',
        height: 38, fontSize: 13.5, fontFamily: 'var(--font-sans)',
        fontWeight: active ? 600 : 400,
        transition: 'background 0.12s, color 0.12s', textAlign: 'left' }}>
      <Icon name={icon} size={17} color={clr} />
      <span style={{ flex: 1, lineHeight: 1 }}>{label}</span>
      {badge && (
        <span style={{ background: 'rgba(0,102,204,0.5)', color: '#fff',
          borderRadius: 10, padding: '1px 7px', fontSize: 10, fontWeight: 700 }}>
          {badge}
        </span>
      )}
      {disabled && (
        <span style={{ fontSize: 9, color: 'rgba(255,255,255,0.22)',
          letterSpacing: '0.04em', textTransform: 'uppercase' }}>presto</span>
      )}
    </button>
  );
}

function Stemma() {
  return (
    <svg viewBox="0 0 36 44" fill="none" xmlns="http://www.w3.org/2000/svg" width="30" height="36" style={{ flexShrink: 0 }}>
      <path d="M2 3h32v25c0 9-7 15-16 18C9 43 2 37 2 28V3z" fill="#4A2A6E"/>
      <path d="M2 3h32v5H2z" fill="rgba(201,161,59,0.5)"/>
      <path d="M16 7h4v26h-4z" fill="rgba(255,255,255,0.75)"/>
      <path d="M4 22h28v4H4z" fill="rgba(255,255,255,0.75)"/>
      <path d="M5 28 12 19 19 28 24 21 32 28" stroke="#2E7D32" strokeWidth="2" fill="none" strokeLinecap="round" strokeLinejoin="round"/>
      <path d="M11 3h14v2.5l-3 2.5H14L11 5.5z" fill="#C9A13B"/>
    </svg>
  );
}

function Sidebar({ screen, onNav, enteName, sidebarBg }) {
  const bg = sidebarBg || '#17324D';
  return (
    <div style={{ width: 256, minWidth: 256, background: bg, height: '100vh',
      position: 'fixed', left: 0, top: 0, display: 'flex', flexDirection: 'column',
      zIndex: 100, borderRight: '1px solid rgba(255,255,255,0.06)', overflowY: 'auto' }}>

      <div style={{ padding: '18px 14px 16px', display: 'flex', gap: 11, alignItems: 'center',
        borderBottom: '1px solid rgba(255,255,255,0.08)', flexShrink: 0 }}>
        <Stemma />
        <div>
          <div style={{ fontSize: 14, fontWeight: 700, color: '#fff', lineHeight: 1.2,
            fontFamily: 'var(--font-sans)', letterSpacing: '-0.01em' }}>SSO Proxy</div>
          <div style={{ fontSize: 11, color: 'rgba(255,255,255,0.45)', marginTop: 3,
            fontFamily: 'var(--font-sans)', lineHeight: 1.3, maxWidth: 150,
            overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
            {enteName || 'Ente PA'}
          </div>
        </div>
      </div>

      <nav style={{ flex: 1, padding: '6px 0' }}>
        <NavGroup label="Monitoraggio" />
        <NavItem icon="dashboard" label="Dashboard" active={screen === 'dashboard'} onClick={() => onNav('dashboard')} />
        <NavItem icon="chart" label="Log Accessi" active={screen === 'log'} onClick={() => onNav('log')} />

        <NavGroup label="Configurazione" />
        <NavItem icon="clients" label="Client OIDC" active={screen === 'clients'} onClick={() => onNav('clients')} />
        <NavItem icon="shield" label="IdP SPID" active={screen === 'idps'} onClick={() => onNav('idps')} />
        <NavItem icon="cie" label="CIE" active={screen === 'cie'} onClick={() => onNav('cie')} />

        <NavGroup label="Sistema" />
        <NavItem icon="document" label="Certificato SPID" active={screen === 'certs'} onClick={() => onNav('certs')} />
        <NavItem icon="cog" label="Impostazioni" active={screen === 'settings'} onClick={() => onNav('settings')} />
        <NavItem icon="archive" label="Backup" active={screen === 'backup'} onClick={() => onNav('backup')} />
        <NavItem icon="beaker" label="Test Client" active={screen === 'test'} onClick={() => onNav('test')} />

        <NavGroup label="In arrivo" />
        <NavItem icon="globe" label="eIDAS" disabled={true} />
        <NavItem icon="wallet" label="IT Wallet" disabled={true} />
      </nav>

      <div style={{ padding: '10px 16px', borderTop: '1px solid rgba(255,255,255,0.07)',
        fontSize: 10, color: 'rgba(255,255,255,0.25)', fontFamily: 'var(--font-mono)', flexShrink: 0 }}>
        pa-sso-proxy · v1.0.0
      </div>
    </div>
  );
}

function Topbar({ title, subtitle, actions, satosaOk }) {
  return (
    <div style={{ height: 56, background: '#fff', borderBottom: '1px solid #E2E8F0',
      display: 'flex', alignItems: 'center', padding: '0 28px',
      position: 'sticky', top: 0, zIndex: 10, gap: 16, flexShrink: 0 }}>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontSize: 17, fontWeight: 700, color: '#17324D',
          fontFamily: 'var(--font-sans)', lineHeight: 1, whiteSpace: 'nowrap',
          overflow: 'hidden', textOverflow: 'ellipsis' }}>{title}</div>
        {subtitle && (
          <div style={{ fontSize: 11, color: '#64748B', marginTop: 2,
            whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{subtitle}</div>
        )}
      </div>
      {actions && <div style={{ display: 'flex', gap: 8, flexShrink: 0 }}>{actions}</div>}
      <div style={{ display: 'flex', alignItems: 'center', gap: 14, flexShrink: 0 }}>
        <span style={{ display: 'flex', alignItems: 'center', gap: 5, fontSize: 12,
          padding: '3px 10px', borderRadius: 99,
          background: satosaOk ? '#E6F5EE' : '#FCE6E9',
          color: satosaOk ? '#008758' : '#D9364F',
          fontWeight: 600, fontFamily: 'var(--font-sans)' }}>
          <span style={{ fontSize: 7, lineHeight: 1 }}>●</span>
          {satosaOk ? 'SATOSA attivo' : 'SATOSA non raggiungibile'}
        </span>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8,
          paddingLeft: 14, borderLeft: '1px solid #E2E8F0' }}>
          <span style={{ fontSize: 13, color: '#334155', fontFamily: 'var(--font-sans)', fontWeight: 500 }}>
            admin
          </span>
          <button title="Esci" style={{ background: 'none', border: 'none', cursor: 'pointer',
            color: '#94A3B8', display: 'flex', padding: 4, borderRadius: 4,
            transition: 'color 0.12s' }}
            onMouseEnter={e => e.currentTarget.style.color = '#475569'}
            onMouseLeave={e => e.currentTarget.style.color = '#94A3B8'}>
            <Icon name="logout" size={15} color="currentColor" />
          </button>
        </div>
      </div>
    </div>
  );
}

function AdminShell({ screen, onNav, title, subtitle, actions, enteName, sidebarBg, satosaOk, children }) {
  return (
    <div style={{ display: 'flex', height: '100vh', overflow: 'hidden',
      fontFamily: 'var(--font-sans)', background: '#F8FAFC' }}>
      <Sidebar screen={screen} onNav={onNav} enteName={enteName} sidebarBg={sidebarBg} />
      <div style={{ flex: 1, marginLeft: 256, display: 'flex', flexDirection: 'column',
        minWidth: 0, height: '100vh', overflow: 'hidden' }}>
        <Topbar title={title} subtitle={subtitle} actions={actions} satosaOk={satosaOk} />
        <main style={{ flex: 1, overflowY: 'auto', padding: '28px 32px' }}>
          {children}
        </main>
      </div>
    </div>
  );
}

Object.assign(window, { AdminShell, Icon });
