import { useState, useEffect, useRef } from 'react'
import { ClerkProvider, SignedIn, SignedOut, useSignIn, useUser, useClerk, AuthenticateWithRedirectCallback, UserProfile } from '@clerk/clerk-react'
import Dashboard from './components/Dashboard'
import LeadImport from './components/LeadImport'
import Licenses from './components/Licenses'
import Team from './components/Team'
import SyncManagement from './components/SyncManagement'
import Analytics from './components/Analytics'
import Campaigns from './components/Campaigns'

const PUBLISHABLE_KEY = import.meta.env.VITE_CLERK_PUBLISHABLE_KEY
const DEV_BYPASS = import.meta.env.VITE_DEV_BYPASS === 'true'

const NAV_ITEMS = [
  { key: 'dashboard', label: 'Dashboard' },
  { key: 'leads', label: 'Lead Import' },
  { key: 'licenses', label: 'Licenses' },
  { key: 'team', label: 'Team' },
  { key: 'sync', label: 'Sync' },
  { key: 'analytics', label: 'Analytics' },
  { key: 'campaigns', label: 'Campaigns' },
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
    case 'campaigns':
      return <Campaigns />
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

  async function handleOAuthSignIn(strategy) {
    if (!isLoaded) return
    setError('')
    setLoading(true)
    try {
      await signIn.authenticateWithRedirect({
        strategy,
        redirectUrl: '/sso-callback',
        redirectUrlComplete: '/',
      })
    } catch (err) {
      const msg = err?.errors?.[0]?.longMessage || err?.errors?.[0]?.message || 'Sign-in failed.'
      setError(msg)
      setLoading(false)
    }
  }

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

      <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', margin: '0.75rem 0' }}>
        <div style={{ flex: 1, height: 1, background: 'var(--border)' }} />
        <span style={{ fontFamily: 'var(--font-mono)', fontSize: '0.6rem', color: 'var(--text-muted)', letterSpacing: '0.05em' }}>OR</span>
        <div style={{ flex: 1, height: 1, background: 'var(--border)' }} />
      </div>

      <button
        type="button"
        onClick={() => handleOAuthSignIn('oauth_google')}
        disabled={loading}
        style={{
          width: '100%',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          gap: '0.5rem',
          background: '#fff',
          color: '#3c4043',
          border: '1px solid var(--border)',
          borderRadius: 4,
          padding: '0.6rem 1rem',
          fontFamily: 'var(--font-mono)',
          fontSize: '0.72rem',
          letterSpacing: '0.05em',
          cursor: 'pointer',
          touchAction: 'manipulation',
          marginBottom: '0.5rem',
        }}
      >
        <svg width="16" height="16" viewBox="0 0 48 48" xmlns="http://www.w3.org/2000/svg">
          <path fill="#4285F4" d="M47.5 24.5c0-1.6-.1-3.1-.4-4.5H24v8.5h13.2c-.6 3-2.3 5.5-4.9 7.2v6h7.9c4.6-4.2 7.3-10.5 7.3-17.2z"/>
          <path fill="#34A853" d="M24 48c6.5 0 11.9-2.1 15.9-5.8l-7.9-6c-2.1 1.4-4.9 2.3-8 2.3-6.1 0-11.3-4.1-13.2-9.7H2.6v6.2C6.5 42.8 14.7 48 24 48z"/>
          <path fill="#FBBC05" d="M10.8 28.8c-.5-1.4-.7-2.8-.7-4.3s.2-3 .7-4.3v-6.2H2.6C1 17.1 0 20.4 0 24s1 6.9 2.6 9.9l8.2-6.1z"/>
          <path fill="#EA4335" d="M24 9.5c3.5 0 6.6 1.2 9 3.5l6.7-6.7C35.9 2.4 30.4 0 24 0 14.7 0 6.5 5.2 2.6 14.1l8.2 6.2C12.7 13.6 17.9 9.5 24 9.5z"/>
        </svg>
        SIGN IN WITH GOOGLE
      </button>

      <button
        type="button"
        onClick={() => handleOAuthSignIn('oauth_apple')}
        disabled={loading}
        style={{
          width: '100%',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          gap: '0.5rem',
          background: '#000',
          color: '#fff',
          border: '1px solid var(--border)',
          borderRadius: 4,
          padding: '0.6rem 1rem',
          fontFamily: 'var(--font-mono)',
          fontSize: '0.72rem',
          letterSpacing: '0.05em',
          cursor: 'pointer',
          touchAction: 'manipulation',
        }}
      >
        <svg width="16" height="16" viewBox="0 0 814 1000" fill="white" xmlns="http://www.w3.org/2000/svg">
          <path d="M788.1 340.9c-5.8 4.5-108.2 62.2-108.2 190.5 0 148.4 130.3 200.9 134.2 202.2-.6 3.2-20.7 71.9-68.7 141.9-42.8 61.6-87.5 123.1-155.5 123.1s-85.5-39.5-164-39.5c-76 0-103.7 40.8-165.9 40.8s-105-57.8-155.5-127.4C46 411.6 8.1 251.9 8.1 99.5c0-89.9 30.8-182.6 87.7-247.2C150.3-201.4 225.4-240 306.6-240c81.2 0 132.7 53.8 196.7 53.8 61.9 0 99.9-53.8 189.8-53.8 72.3 0 141 32.5 194.4 88.3zm-234-181.4c31.1-36.9 53.1-88.1 53.1-139.3 0-7.1-.6-14.3-1.9-20.1-50.6 1.9-110.8 33.7-147.1 75.8-28.5 32.4-55.1 83.6-55.1 135.5 0 7.8 1.3 15.6 1.9 18.1 3.2.6 8.4 1.3 13.6 1.3 45.4 0 102.5-30.4 135.5-71.3z"/>
        </svg>
        SIGN IN WITH APPLE
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
  const [showProfile, setShowProfile] = useState(false)
  const menuRef = useRef(null)
  const btnRef = useRef(null)
  const [dropdownPos, setDropdownPos] = useState({ bottom: 0, left: 0 })

  const hasApple = user?.externalAccounts?.some(a => a.provider === 'apple')
  const hasGoogle = user?.externalAccounts?.some(a => a.provider === 'google')

  async function connectOAuth(strategy) {
    try {
      await user.createExternalAccount({
        strategy,
        redirectUrl: `${window.location.origin}/sso-callback`,
        additionalScopes: ['email', 'name'],
      })
    } catch (err) {
      console.error('OAuth connect failed', err)
    }
  }

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

  // Compute dropdown position from button's viewport coords
  function handleToggle() {
    if (!open && btnRef.current) {
      const rect = btnRef.current.getBoundingClientRect()
      setDropdownPos({
        bottom: window.innerHeight - rect.top + 8,
        left: rect.left,
      })
    }
    setOpen((o) => !o)
  }

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
        ref={btnRef}
        onClick={handleToggle}
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

      {/* Dropdown — fixed position to escape sidebar overflow clipping */}
      {open && (
        <div
          style={{
            position: 'fixed',
            bottom: dropdownPos.bottom,
            left: dropdownPos.left,
            minWidth: 200,
            maxWidth: 'calc(100vw - 2rem)',
            background: 'var(--surface)',
            border: '1px solid var(--border)',
            borderRadius: 4,
            boxShadow: '0 8px 24px rgba(0,0,0,0.5)',
            zIndex: 9999,
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

          {/* Manage account — first action, always visible */}
          <button
            onClick={() => { setOpen(false); setShowProfile(true) }}
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
              touchAction: 'manipulation',
            }}
            onMouseEnter={(e) => { e.currentTarget.style.color = 'var(--text)' }}
            onMouseLeave={(e) => { e.currentTarget.style.color = 'var(--text-muted)' }}
          >
            Manage account
          </button>

          {/* Sign out — second action, right after manage account */}
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
              touchAction: 'manipulation',
            }}
            onMouseEnter={(e) => { e.currentTarget.style.color = 'var(--text)' }}
            onMouseLeave={(e) => { e.currentTarget.style.color = 'var(--text-muted)' }}
          >
            Sign out
          </button>

          <hr style={{ border: 'none', borderTop: '1px solid var(--border)', margin: '0.5rem 0' }} />

          {/* Connect Google (if not yet linked) */}
          {!hasGoogle && (
            <button
              onClick={() => connectOAuth('oauth_google')}
              style={{ width: '100%', textAlign: 'left', background: 'none', border: 'none', cursor: 'pointer', fontFamily: 'var(--font-mono)', fontSize: '0.72rem', color: 'var(--text-muted)', padding: '0.25rem 0', letterSpacing: '0.05em', display: 'flex', alignItems: 'center', gap: '0.4rem', touchAction: 'manipulation' }}
              onMouseEnter={(e) => { e.currentTarget.style.color = 'var(--text)' }}
              onMouseLeave={(e) => { e.currentTarget.style.color = 'var(--text-muted)' }}
            >
              <svg width="12" height="12" viewBox="0 0 48 48"><path fill="#4285F4" d="M47.5 24.5c0-1.6-.1-3.1-.4-4.5H24v8.5h13.2c-.6 3-2.3 5.5-4.9 7.2v6h7.9c4.6-4.2 7.3-10.5 7.3-17.2z"/><path fill="#34A853" d="M24 48c6.5 0 11.9-2.1 15.9-5.8l-7.9-6c-2.1 1.4-4.9 2.3-8 2.3-6.1 0-11.3-4.1-13.2-9.7H2.6v6.2C6.5 42.8 14.7 48 24 48z"/><path fill="#FBBC05" d="M10.8 28.8c-.5-1.4-.7-2.8-.7-4.3s.2-3 .7-4.3v-6.2H2.6C1 17.1 0 20.4 0 24s1 6.9 2.6 9.9l8.2-6.1z"/><path fill="#EA4335" d="M24 9.5c3.5 0 6.6 1.2 9 3.5l6.7-6.7C35.9 2.4 30.4 0 24 0 14.7 0 6.5 5.2 2.6 14.1l8.2 6.2C12.7 13.6 17.9 9.5 24 9.5z"/></svg>
              Connect Google
            </button>
          )}
          {hasGoogle && (
            <p style={{ fontFamily: 'var(--font-mono)', fontSize: '0.62rem', color: 'var(--text-muted)', margin: 0, padding: '0.25rem 0', display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
              <svg width="12" height="12" viewBox="0 0 48 48"><path fill="#4285F4" d="M47.5 24.5c0-1.6-.1-3.1-.4-4.5H24v8.5h13.2c-.6 3-2.3 5.5-4.9 7.2v6h7.9c4.6-4.2 7.3-10.5 7.3-17.2z"/><path fill="#34A853" d="M24 48c6.5 0 11.9-2.1 15.9-5.8l-7.9-6c-2.1 1.4-4.9 2.3-8 2.3-6.1 0-11.3-4.1-13.2-9.7H2.6v6.2C6.5 42.8 14.7 48 24 48z"/><path fill="#FBBC05" d="M10.8 28.8c-.5-1.4-.7-2.8-.7-4.3s.2-3 .7-4.3v-6.2H2.6C1 17.1 0 20.4 0 24s1 6.9 2.6 9.9l8.2-6.1z"/><path fill="#EA4335" d="M24 9.5c3.5 0 6.6 1.2 9 3.5l6.7-6.7C35.9 2.4 30.4 0 24 0 14.7 0 6.5 5.2 2.6 14.1l8.2 6.2C12.7 13.6 17.9 9.5 24 9.5z"/></svg>
              Google linked
            </p>
          )}

          {/* Connect Apple (if not yet linked) */}
          {!hasApple && (
            <button
              onClick={() => connectOAuth('oauth_apple')}
              style={{ width: '100%', textAlign: 'left', background: 'none', border: 'none', cursor: 'pointer', fontFamily: 'var(--font-mono)', fontSize: '0.72rem', color: 'var(--text-muted)', padding: '0.25rem 0', letterSpacing: '0.05em', display: 'flex', alignItems: 'center', gap: '0.4rem', touchAction: 'manipulation' }}
              onMouseEnter={(e) => { e.currentTarget.style.color = 'var(--text)' }}
              onMouseLeave={(e) => { e.currentTarget.style.color = 'var(--text-muted)' }}
            >
              <svg width="12" height="12" viewBox="0 0 814 1000" fill="currentColor"><path d="M788.1 340.9c-5.8 4.5-108.2 62.2-108.2 190.5 0 148.4 130.3 200.9 134.2 202.2-.6 3.2-20.7 71.9-68.7 141.9-42.8 61.6-87.5 123.1-155.5 123.1s-85.5-39.5-164-39.5c-76 0-103.7 40.8-165.9 40.8s-105-57.8-155.5-127.4C46 411.6 8.1 251.9 8.1 99.5c0-89.9 30.8-182.6 87.7-247.2C150.3-201.4 225.4-240 306.6-240c81.2 0 132.7 53.8 196.7 53.8 61.9 0 99.9-53.8 189.8-53.8 72.3 0 141 32.5 194.4 88.3zm-234-181.4c31.1-36.9 53.1-88.1 53.1-139.3 0-7.1-.6-14.3-1.9-20.1-50.6 1.9-110.8 33.7-147.1 75.8-28.5 32.4-55.1 83.6-55.1 135.5 0 7.8 1.3 15.6 1.9 18.1 3.2.6 8.4 1.3 13.6 1.3 45.4 0 102.5-30.4 135.5-71.3z"/></svg>
              Connect Apple ID
            </button>
          )}
          {hasApple && (
            <p style={{ fontFamily: 'var(--font-mono)', fontSize: '0.62rem', color: 'var(--text-muted)', margin: 0, padding: '0.25rem 0', display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
              <svg width="12" height="12" viewBox="0 0 814 1000" fill="currentColor"><path d="M788.1 340.9c-5.8 4.5-108.2 62.2-108.2 190.5 0 148.4 130.3 200.9 134.2 202.2-.6 3.2-20.7 71.9-68.7 141.9-42.8 61.6-87.5 123.1-155.5 123.1s-85.5-39.5-164-39.5c-76 0-103.7 40.8-165.9 40.8s-105-57.8-155.5-127.4C46 411.6 8.1 251.9 8.1 99.5c0-89.9 30.8-182.6 87.7-247.2C150.3-201.4 225.4-240 306.6-240c81.2 0 132.7 53.8 196.7 53.8 61.9 0 99.9-53.8 189.8-53.8 72.3 0 141 32.5 194.4 88.3zm-234-181.4c31.1-36.9 53.1-88.1 53.1-139.3 0-7.1-.6-14.3-1.9-20.1-50.6 1.9-110.8 33.7-147.1 75.8-28.5 32.4-55.1 83.6-55.1 135.5 0 7.8 1.3 15.6 1.9 18.1 3.2.6 8.4 1.3 13.6 1.3 45.4 0 102.5-30.4 135.5-71.3z"/></svg>
              Apple ID linked
            </p>
          )}

        </div>
      )}

      {/* Clerk UserProfile modal */}
      {showProfile && (
        <div
          onClick={(e) => { if (e.target === e.currentTarget) setShowProfile(false) }}
          style={{
            position: 'fixed',
            inset: 0,
            background: 'rgba(0,0,0,0.7)',
            zIndex: 9999,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            padding: '1rem',
          }}
        >
          <div style={{ position: 'relative', maxWidth: '100%', maxHeight: '90vh', overflow: 'auto' }}>
            <button
              onClick={() => setShowProfile(false)}
              style={{
                position: 'absolute',
                top: 8,
                right: 8,
                zIndex: 1,
                background: 'none',
                border: 'none',
                cursor: 'pointer',
                color: 'var(--text-muted)',
                fontFamily: 'var(--font-mono)',
                fontSize: '0.72rem',
                touchAction: 'manipulation',
              }}
            >
              ✕
            </button>
            <UserProfile />
          </div>
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

  // Handle SSO callback (Apple/Google redirect)
  if (window.location.pathname === '/sso-callback') {
    return (
      <ClerkProvider publishableKey={PUBLISHABLE_KEY}>
        <AuthenticateWithRedirectCallback />
      </ClerkProvider>
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
