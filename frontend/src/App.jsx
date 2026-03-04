import { useState, useEffect } from 'react'
import { ClerkProvider, SignedIn, SignedOut, UserButton, useSignIn } from '@clerk/clerk-react'
import Dashboard from './components/Dashboard'
import LeadImport from './components/LeadImport'
import Licenses from './components/Licenses'
import SyncManagement from './components/SyncManagement'
import Analytics from './components/Analytics'

const PUBLISHABLE_KEY = import.meta.env.VITE_CLERK_PUBLISHABLE_KEY

const NAV_ITEMS = [
  { key: 'dashboard', label: 'Dashboard' },
  { key: 'leads', label: 'Lead Import' },
  { key: 'licenses', label: 'Licenses' },
  { key: 'sync', label: 'Sync' },
  { key: 'analytics', label: 'Analytics' },
]

function PageContent({ currentPage }) {
  switch (currentPage) {
    case 'leads':
      return <LeadImport />
    case 'licenses':
      return <Licenses />
    case 'sync':
      return <SyncManagement />
    case 'analytics':
      return <Analytics />
    default:
      return <Dashboard />
  }
}

/* ── Custom Sign-In Form (no Clerk branding) ── */
function CustomSignIn() {
  const { isLoaded, signIn, setActive } = useSignIn()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  async function handleSubmit(e) {
    e.preventDefault()
    if (!isLoaded) return

    setError('')
    setLoading(true)

    try {
      const result = await signIn.create({
        identifier: email,
        password,
      })

      if (result.status === 'complete') {
        await setActive({ session: result.createdSessionId })
      } else {
        setError('Sign-in incomplete. Check your credentials.')
      }
    } catch (err) {
      const msg =
        err?.errors?.[0]?.longMessage ||
        err?.errors?.[0]?.message ||
        'Authentication failed.'
      setError(msg)
    } finally {
      setLoading(false)
    }
  }

  if (!isLoaded) {
    return <p className="loading-text">Loading...</p>
  }

  return (
    <form className="custom-signin-form" onSubmit={handleSubmit}>
      <label className="form-label" htmlFor="signin-email">
        Email
      </label>
      <input
        id="signin-email"
        className="custom-signin-input"
        type="email"
        autoComplete="email"
        required
        value={email}
        onChange={(e) => setEmail(e.target.value)}
        placeholder="agent@falconfinancial.org"
        disabled={loading}
      />

      <label className="form-label" htmlFor="signin-password" style={{ marginTop: '0.75rem' }}>
        Password
      </label>
      <input
        id="signin-password"
        className="custom-signin-input"
        type="password"
        autoComplete="current-password"
        required
        value={password}
        onChange={(e) => setPassword(e.target.value)}
        placeholder="••••••••"
        disabled={loading}
      />

      <button
        type="submit"
        className="custom-signin-btn"
        disabled={loading}
      >
        {loading ? 'AUTHENTICATING...' : 'SIGN IN'}
      </button>

      {error && <p className="custom-signin-error">{error}</p>}
    </form>
  )
}

/* ── App Layout with Collapsible Mobile Nav ── */
function AppLayout() {
  const [currentPage, setCurrentPage] = useState('dashboard')
  const [mobileNavOpen, setMobileNavOpen] = useState(false)

  // Close mobile nav on page change
  useEffect(() => {
    setMobileNavOpen(false)
  }, [currentPage])

  const currentLabel = NAV_ITEMS.find((i) => i.key === currentPage)?.label || 'Dashboard'

  return (
    <div className="app-shell">
      <aside className="sidebar">
        {/* Desktop sidebar header */}
        <div className="sidebar-header desktop-only">
          <div className="sidebar-wordmark">
            FALCON<br />CONNECT
          </div>
        </div>

        {/* Mobile nav header */}
        <div
          className="mobile-nav-header mobile-only"
          onClick={() => setMobileNavOpen((o) => !o)}
        >
          <span className="mobile-nav-label">
            {currentLabel}
            <span className={`mobile-nav-chevron ${mobileNavOpen ? 'open' : ''}`}>
              ›
            </span>
          </span>
        </div>

        {/* Desktop nav — always visible on desktop, hidden on mobile */}
        <nav className="sidebar-nav desktop-only">
          {NAV_ITEMS.map((item) => (
            <button
              key={item.key}
              className={`nav-item ${currentPage === item.key ? 'active' : ''}`}
              onClick={() => setCurrentPage(item.key)}
            >
              <span className="nav-indicator" />
              {item.label}
            </button>
          ))}
        </nav>

        {/* Mobile dropdown nav */}
        {mobileNavOpen && (
          <nav className="mobile-nav-dropdown mobile-only">
            {NAV_ITEMS.map((item) => (
              <button
                key={item.key}
                className={`mobile-nav-item ${currentPage === item.key ? 'active' : ''}`}
                onClick={() => setCurrentPage(item.key)}
              >
                {item.label}
              </button>
            ))}
          </nav>
        )}

        <div className="sidebar-footer">
          <UserButton
            appearance={{
              elements: {
                avatarBox: {
                  width: 28,
                  height: 28,
                },
              },
            }}
          />
        </div>
      </aside>
      <main className="main-content">
        <PageContent currentPage={currentPage} />
      </main>
    </div>
  )
}

function App() {
  // No Clerk key — show dashboard without auth
  if (!PUBLISHABLE_KEY) {
    return (
      <div className="app-noauth">
        <header className="header-noauth">
          <span className="header-noauth-title">FalconConnect</span>
          <span className="badge-noauth">Auth not configured</span>
        </header>
        <Dashboard />
      </div>
    )
  }

  return (
    <ClerkProvider publishableKey={PUBLISHABLE_KEY}>
      <SignedOut>
        <div className="auth-screen">
          <div className="auth-card">
            <h1 className="auth-wordmark">FALCONCONNECT</h1>
            <hr className="auth-rule" />
            <p className="auth-subtitle">Internal System</p>
            <CustomSignIn />
          </div>
        </div>
      </SignedOut>
      <SignedIn>
        <AppLayout />
      </SignedIn>
    </ClerkProvider>
  )
}

export default App
