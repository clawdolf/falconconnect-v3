import { useState, useEffect } from 'react'
import { ClerkProvider, SignedIn, SignedOut, UserButton, useSignIn } from '@clerk/clerk-react'
import Dashboard from './components/Dashboard'
import LeadImport from './components/LeadImport'
import Licenses from './components/Licenses'
import SyncManagement from './components/SyncManagement'
import Analytics from './components/Analytics'

const PUBLISHABLE_KEY = import.meta.env.VITE_CLERK_PUBLISHABLE_KEY
const DEV_BYPASS = import.meta.env.VITE_DEV_BYPASS === 'true'

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
            <UserButton appearance={{ elements: { avatarBox: { width: 28, height: 28 } } }} />
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
