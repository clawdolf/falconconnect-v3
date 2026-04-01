import { useEffect, useState } from 'react'
import { useUser } from '@clerk/clerk-react'

const THEME_KEY = 'fc_theme'

function applyTheme(theme) {
  if (theme === 'light') {
    document.documentElement.classList.add('theme-light')
  } else {
    document.documentElement.classList.remove('theme-light')
  }
}

export default function Settings() {
  const { user } = useUser()

  const [isLight, setIsLight] = useState(() => {
    const stored = localStorage.getItem(THEME_KEY)
    return stored === 'light'
  })

  // Apply on mount immediately
  useEffect(() => {
    applyTheme(isLight ? 'light' : 'dark')
  }, [])

  function handleThemeToggle() {
    const next = !isLight
    setIsLight(next)
    const theme = next ? 'light' : 'dark'
    localStorage.setItem(THEME_KEY, theme)
    applyTheme(theme)
  }

  const name = user?.fullName || user?.firstName || 'Agent'
  const email = user?.primaryEmailAddress?.emailAddress || ''

  const integrations = [
    { name: 'Close.com', key: 'close' },
    { name: 'Google Calendar', key: 'gcal' },
    { name: 'GoHighLevel', key: 'ghl' },
  ]

  return (
    <div style={{ maxWidth: 620 }}>
      <h1 style={{
        fontFamily: 'var(--font-mono)',
        fontSize: '0.75rem',
        fontWeight: 600,
        textTransform: 'uppercase',
        letterSpacing: '0.1em',
        color: 'var(--text-muted)',
        marginBottom: '2rem',
      }}>
        Settings
      </h1>

      {/* Appearance */}
      <div className="section" style={{ marginBottom: '1.25rem' }}>
        <div className="section-title">Appearance</div>

        <div style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          paddingTop: '0.25rem',
        }}>
          <div>
            <div style={{
              fontFamily: 'var(--font-mono)',
              fontSize: '0.8rem',
              color: 'var(--text)',
            }}>
              Light mode
            </div>
            <div style={{
              fontFamily: 'var(--font-mono)',
              fontSize: '0.65rem',
              color: 'var(--text-muted)',
              marginTop: '0.2rem',
            }}>
              Dark is the default. Preference saved in browser.
            </div>
          </div>

          {/* Toggle switch */}
          <button
            onClick={handleThemeToggle}
            role="switch"
            aria-checked={isLight}
            aria-label="Toggle light mode"
            style={{
              position: 'relative',
              width: 40,
              height: 22,
              borderRadius: 11,
              border: '1px solid var(--border)',
              background: isLight ? 'var(--accent)' : 'var(--surface-hover)',
              cursor: 'pointer',
              flexShrink: 0,
              transition: 'background 0.2s, border-color 0.2s',
              padding: 0,
            }}
          >
            <span style={{
              position: 'absolute',
              top: 3,
              left: isLight ? 21 : 3,
              width: 14,
              height: 14,
              borderRadius: '50%',
              background: isLight ? 'oklch(15% 0.01 85)' : 'var(--text-muted)',
              transition: 'left 0.2s',
            }} />
          </button>
        </div>
      </div>

      {/* Account */}
      <div className="section" style={{ marginBottom: '1.25rem' }}>
        <div className="section-title">Account</div>

        <div style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
          <div style={{ display: 'flex', gap: '1rem' }}>
            <span style={{
              fontFamily: 'var(--font-mono)',
              fontSize: '0.65rem',
              textTransform: 'uppercase',
              letterSpacing: '0.08em',
              color: 'var(--text-muted)',
              minWidth: 60,
            }}>
              Name
            </span>
            <span style={{
              fontFamily: 'var(--font-mono)',
              fontSize: '0.8rem',
              color: 'var(--text)',
            }}>
              {name}
            </span>
          </div>
          <div style={{ display: 'flex', gap: '1rem' }}>
            <span style={{
              fontFamily: 'var(--font-mono)',
              fontSize: '0.65rem',
              textTransform: 'uppercase',
              letterSpacing: '0.08em',
              color: 'var(--text-muted)',
              minWidth: 60,
            }}>
              Email
            </span>
            <span style={{
              fontFamily: 'var(--font-mono)',
              fontSize: '0.8rem',
              color: 'var(--text)',
            }}>
              {email || '—'}
            </span>
          </div>
        </div>
      </div>

      {/* Integrations */}
      <div className="section" style={{ marginBottom: '1.25rem' }}>
        <div className="section-title">Integrations</div>

        <div style={{ display: 'flex', flexDirection: 'column', gap: 0 }}>
          {integrations.map((integration, idx) => (
            <div
              key={integration.key}
              style={{
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                padding: '0.625rem 0',
                borderBottom: idx < integrations.length - 1 ? '1px solid var(--border-subtle)' : 'none',
              }}
            >
              <span style={{
                fontFamily: 'var(--font-mono)',
                fontSize: '0.8rem',
                color: 'var(--text)',
              }}>
                {integration.name}
              </span>
              <span style={{
                display: 'flex',
                alignItems: 'center',
                gap: '0.4rem',
                fontFamily: 'var(--font-mono)',
                fontSize: '0.65rem',
                color: 'var(--green)',
              }}>
                <span style={{
                  width: 6,
                  height: 6,
                  borderRadius: '50%',
                  background: 'var(--green)',
                  display: 'inline-block',
                  flexShrink: 0,
                }} />
                connected
              </span>
            </div>
          ))}
        </div>
      </div>

      {/* Notifications */}
      <div className="section" style={{ marginBottom: '1.25rem' }}>
        <div className="section-title">Notifications</div>
        <p style={{
          fontFamily: 'var(--font-mono)',
          fontSize: '0.8rem',
          color: 'var(--text-muted)',
          margin: 0,
        }}>
          Telegram alerts enabled via FalconConnect bot
        </p>
      </div>

      {/* Version */}
      <div className="section">
        <div className="section-title">Version</div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: '0.375rem' }}>
          <div style={{ display: 'flex', gap: '1rem' }}>
            <span style={{
              fontFamily: 'var(--font-mono)',
              fontSize: '0.65rem',
              textTransform: 'uppercase',
              letterSpacing: '0.08em',
              color: 'var(--text-muted)',
              minWidth: 80,
            }}>
              Version
            </span>
            <span style={{
              fontFamily: 'var(--font-mono)',
              fontSize: '0.8rem',
              color: 'var(--text)',
            }}>
              {__APP_VERSION__}
            </span>
          </div>
          <div style={{ display: 'flex', gap: '1rem' }}>
            <span style={{
              fontFamily: 'var(--font-mono)',
              fontSize: '0.65rem',
              textTransform: 'uppercase',
              letterSpacing: '0.08em',
              color: 'var(--text-muted)',
              minWidth: 80,
            }}>
              Built
            </span>
            <span style={{
              fontFamily: 'var(--font-mono)',
              fontSize: '0.8rem',
              color: 'var(--text-muted)',
            }}>
              {__BUILD_DATE__}
            </span>
          </div>
        </div>
      </div>
    </div>
  )
}
