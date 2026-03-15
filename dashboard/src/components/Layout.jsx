import { NavLink, Outlet } from 'react-router-dom';

const navItems = [
  { to: '/', label: 'Dashboard', icon: '\u{1F4CA}' },
  { to: '/bracket', label: 'Bracket', icon: '\u{1F3C0}' },
  { to: '/agents', label: 'Agents', icon: '\u{1F916}' },
  { to: '/upsets', label: 'Upset Watch', icon: '\u{1F525}' },
];

const sidebarStyle = {
  position: 'fixed',
  top: 0,
  left: 0,
  width: 220,
  height: '100vh',
  background: '#111111',
  borderRight: '1px solid #1e1e1e',
  display: 'flex',
  flexDirection: 'column',
  padding: '20px 0',
  zIndex: 100,
};

const logoStyle = {
  padding: '0 20px 24px',
  borderBottom: '1px solid #1e1e1e',
  marginBottom: 16,
};

const logoText = {
  fontSize: 15,
  fontWeight: 700,
  color: '#fff',
  lineHeight: 1.3,
  letterSpacing: '-0.3px',
};

const logoSub = {
  fontSize: 11,
  color: '#666',
  marginTop: 2,
  textTransform: 'uppercase',
  letterSpacing: '1px',
};

const navLinkStyle = (isActive) => ({
  display: 'flex',
  alignItems: 'center',
  gap: 10,
  padding: '10px 20px',
  textDecoration: 'none',
  fontSize: 14,
  fontWeight: isActive ? 600 : 400,
  color: isActive ? '#fff' : '#888',
  background: isActive ? 'rgba(255,255,255,0.06)' : 'transparent',
  borderLeft: isActive ? '3px solid #4A90D9' : '3px solid transparent',
  transition: 'all 0.15s',
});

const mainStyle = {
  marginLeft: 220,
  minHeight: '100vh',
  background: '#0a0a0a',
};

export default function Layout() {
  return (
    <div style={{ display: 'flex' }}>
      <nav style={sidebarStyle}>
        <div style={logoStyle}>
          <div style={logoText}>{'\u{1F3C0}'} March Madness</div>
          <div style={logoText}>Agent Swarm</div>
          <div style={logoSub}>2026</div>
        </div>
        {navItems.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            end={item.to === '/'}
            style={({ isActive }) => navLinkStyle(isActive)}
          >
            <span style={{ fontSize: 18 }}>{item.icon}</span>
            <span>{item.label}</span>
          </NavLink>
        ))}
      </nav>
      <main style={mainStyle}>
        <Outlet />
      </main>
    </div>
  );
}
