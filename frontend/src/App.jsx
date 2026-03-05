import { useState, useEffect, useRef } from 'react'
import { ClerkProvider, SignedIn, SignedOut, useSignIn, useUser, useClerk } from '@clerk/clerk-react'
import Dashboard from './components/Dashboard'
import LeadImport from './components/LeadImport'
import Licenses from './components/Licenses'
import Team from './components/Team'
import SyncManagement from './components/SyncManagement'
import Analytics from './components/Analytics'

const PUBLISHABLE_KEY = import.meta.env.VITE_CLERK_PUBLISHABLE_KEY
const DEV_BYPASS = import.meta.env.VITE_DEV_BYPASS === 'true'

const NAV_ITEMS = [
  { key: 'dashboard', label: 'Dashboard' },
  { key: 'leads', label: 'Lead Import' },
  { key: 'licenses', label: 'Licenses' },
  { key: 'team', label: 'Team' },
  { key: 'sync', label: 'Sync' },
  { key: 'analytics', label: 'Analytics' },
]

function PageContent({ currentPage }) {
  switch (currentPage) {
    case 'leads':
      return <LeadImport />
    case 'licenses':
      return <Licenses />
    case 'team':
      return <Team />
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
  const [otpCode, setOtpCode] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const [step, setStep] = useState('password') // 'password' | 'otp'

  async function handlePasswordSubmit(e) {
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
      } else if (result.status === 'needs_second_factor') {
        // Clerk requires email OTP as second factor
        await signIn.prepareSecondFactor({ strategy: 'email_code' })
        setStep('otp')
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

  async function handleOtpSubmit(e) {
    e.preventDefault()
    if (!isLoaded) return

    setError('')
    setLoading(true)

    try {
      const result = await signIn.attemptSecondFactor({
        strategy: 'email_code',
        code: otpCode,
      })

      if (result.status === 'complete') {
        await setActive({ session: result.createdSessionId })
      } else {
        setError('Verification incomplete. Try again.')
      }
    } catch (err) {
      const msg =
        err?.errors?.[0]?.longMessage ||
        err?.errors?.[0]?.message ||
        'Invalid verification code.'
      setError(msg)
    } finally {
      setLoading(false)
    }
  }

  async function handleResendCode() {
    if (!isLoaded) return
    setError('')

    try {
      await signIn.prepareSecondFactor({ strategy: 'email_code' })
      setError('') // Clear any previous error
    } catch (err) {
      const msg =
        err?.errors?.[0]?.longMessage ||
        err?.errors?.[0]?.message ||
        'Failed to resend code.'
      setError(msg)
    }
  }

  if (!isLoaded) {
    return <p className="loading-text">Loading...</p>
  }

  /* ── OTP Step ── */
  if (step === 'otp') {
    return (
      <form className="custom-signin-form" onSubmit={handleOtpSubmit}>
        <label className="form-label" htmlFor="signin-otp">
          Verification Code
        </label>
        <input
          id="signin-otp"
          className="custom-signin-input"
          type="text"
          inputMode="numeric"
          autoComplete="one-time-code"
          maxLength={6}
          required
          value={otpCode}
          onChange={(e) => setOtpCode(e.target.value.replace(/\D/g, '').slice(0, 6))}
          placeholder="000000"
          disabled={loading}
          autoFocus
        />
        <p className="custom-signin-hint">A verification code was sent to {email}</p>

        <button
          type="submit"
          className="custom-signin-btn"
          disabled={loading || otpCode.length < 6}
        >
          {loading ? 'VERIFYING...' : 'VERIFY'}
        </button>

        <button
          type="button"
          className="custom-signin-hint"
          style={{ cursor: 'pointer', background: 'none', border: 'none', marginTop: '0.75rem', textDecoration: 'underline' }}
          onClick={handleResendCode}
          disabled={loading}
        >
          Resend code
        </button>

        {error && <p className="custom-signin-error">{error}</p>}
      </form>
    )
  }

  /* ── Password Step ── */
  return (
    <form className="custom-signin-form" onSubmit={handlePasswordSubmit}>
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

/* ── Custom User Menu (no Clerk branding) ── */
function UserMenu() {
  const { user } = useUser()
  const { signOut } = useClerk()
  const [open, setOpen] = useState(false)
  const menuRef = useRef(null)

  // Close on outside click
  useEffect(() => {
    function handleOutsideClick(e) {
      if (menuRef.current && !menuRef.current.contains(e.target)) {
        setOpen(false)
      }
    }
    if (open) document.addEventListener('mousedown', handleOutsideClick)
    return () => document.removeEventListener('mousedown', handleOutsideClick)
  }, [open])

  // Derive initials or fallback
  const name = user?.fullName || user?.firstName || 'Seb'
  const email = user?.primaryEmailAddress?.emailAddress || ''
  const imageUrl = user?.imageUrl || null
  const initials = name
    .split(' ')
    .map((w) => w[0])
    .join('')
    .toUpperCase()
    .slice(0, 2) || 'S'

  return (
    <div ref={menuRef} style={{ position: 'relative', display: 'inline-block' }}>
      {/* Avatar trigger */}
      <button
        onClick={() => setOpen((o) => !o)}
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          width: 28,
          height: 28,
          borderRadius: '50%',
          border: '1px solid var(--border)',
          background: imageUrl ? 'transparent' : 'var(--surface-hover)',
          cursor: 'pointer',
          padding: 0,
          overflow: 'hidden',
          flexShrink: 0,
          touchAction: 'manipulation',
        }}
        aria-label="User menu"
      >
        {imageUrl ? (
          <img src={imageUrl} alt={name} style={{ width: '100%', height: '100%', objectFit: 'cover' }} />
        ) : (
          <span style={{ fontFamily: 'var(--font-mono)', fontSize: '0.6rem', fontWeight: 600, color: 'var(--accent)', letterSpacing: 0.5 }}>
            {initials}
          </span>
        )}
      </button>

      {/* Dropdown */}
      {open && (
        <div
          style={{
            position: 'absolute',
            top: '36px',
            right: 0,
            minWidth: 200,
            maxWidth: 'calc(100vw - 2rem)',
            background: 'var(--surface)',
            border: '1px solid var(--border)',
            borderRadius: 4,
            boxShadow: '0 8px 24px rgba(0,0,0,0.5)',
            zIndex: 1000,
            padding: '0.75rem',
          }}
        >
          {/* User info */}
          <div style={{ marginBottom: '0.5rem' }}>
            <p style={{ fontFamily: 'var(--font-mono)', fontSize: '0.72rem', fontWeight: 600, color: 'var(--text)', margin: 0 }}>
              {name}
            </p>
            {email && (
              <p style={{ fontFamily: 'var(--font-mono)', fontSize: '0.62rem', color: 'var(--text-muted)', margin: '0.15rem 0 0' }}>
                {email}
              </p>
            )}
          </div>

          <hr style={{ border: 'none', borderTop: '1px solid var(--border)', margin: '0.5rem 0' }} />

          {/* Sign out */}
          <button
            onClick={() => signOut()}
            style={{
              width: '100%',
              textAlign: 'left',
              background: 'none',
              border: 'none',
              cursor: 'pointer',
              fontFamily: 'var(--font-mono)',
              fontSize: '0.72rem',
              color: 'var(--text-muted)',
              padding: '0.25rem 0',
              letterSpacing: '0.05em',
            }}
            onMouseEnter={(e) => { e.currentTarget.style.color = 'var(--text)' }}
            onMouseLeave={(e) => { e.currentTarget.style.color = 'var(--text-muted)' }}
          >
            Sign out
          </button>
        </div>
      )}
    </div>
  )
}

/* ── App Layout ── */
function AppLayout() {
  const [currentPage, setCurrentPage] = useState('dashboard')
  const [mobileNavOpen, setMobileNavOpen] = useState(false)

  useEffect(() => { setMobileNavOpen(false) }, [currentPage])

  const currentLabel = NAV_ITEMS.find((i) => i.key === currentPage)?.label || 'Dashboard'

  return (
    <div className="app-shell">
      <aside className="sidebar">
        {/* Wordmark — desktop */}
        <div className="sidebar-wordmark-wrap">
          <div className="sidebar-wordmark">FALCON<br />CONNECT</div>
        </div>

        {/* Desktop nav — always visible */}
        <nav className="sidebar-nav">
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

        {/* Mobile: current page label + chevron (shown only on small screens via CSS) */}
        <div className="mobile-nav-toggle" onClick={() => setMobileNavOpen((o) => !o)}>
          <span className="mobile-nav-label">
            {currentLabel}
            <span className={`mobile-nav-chevron ${mobileNavOpen ? 'open' : ''}`}>›</span>
          </span>
        </div>

        {mobileNavOpen && (
          <nav className="mobile-nav-dropdown">
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

        {!DEV_BYPASS && PUBLISHABLE_KEY && (
          <div className="sidebar-footer">
            <UserMenu />
          </div>
        )}
      </aside>
      <main className="main-content">
        <PageContent currentPage={currentPage} />
      </main>
    </div>
  )
}

function App() {
  // Dev bypass or no Clerk key — skip auth entirely
  if (DEV_BYPASS || !PUBLISHABLE_KEY) {
    return <AppLayout />
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
