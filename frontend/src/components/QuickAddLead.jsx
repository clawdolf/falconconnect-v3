import { useState } from 'react'
import { useAuthSafe as useAuth } from '../hooks/useClerkSafe'

function QuickAddLead() {
  const [open, setOpen] = useState(false)
  const [firstName, setFirstName] = useState('')
  const [lastName, setLastName] = useState('')
  const [phone, setPhone] = useState('')
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState(null) // { ok: bool, message: str }

  const { getToken } = useAuth()

  async function authHeaders() {
    const h = { 'Content-Type': 'application/json' }
    try { const t = await getToken(); if (t) h['Authorization'] = 'Bearer ' + t } catch { /* no-op */ }
    return h
  }

  function reset() {
    setFirstName('')
    setLastName('')
    setPhone('')
    setResult(null)
    setLoading(false)
  }

  function close() {
    setOpen(false)
    reset()
  }

  async function handleSubmit(e) {
    e.preventDefault()
    setLoading(true)
    setResult(null)

    try {
      const headers = await authHeaders()
      const resp = await fetch('/leads/bulk', {
        method: 'POST',
        headers,
        body: JSON.stringify({
          dry_run: false,
          leads: [{
            first_name: firstName.trim(),
            last_name: lastName.trim(),
            phone: phone.trim(),
          }],
        }),
      })

      const data = await resp.json()

      if (!resp.ok) {
        setResult({ ok: false, message: data?.detail || `Error ${resp.status}` })
      } else {
        const created = data?.created ?? 0
        const errors = data?.errors ?? []
        if (created > 0) {
          setResult({ ok: true, message: `Imported. Notion + GHL updated.` })
          // auto-close after 2s on success
          setTimeout(close, 2000)
        } else if (errors.length > 0) {
          setResult({ ok: false, message: errors[0]?.error || 'Import failed.' })
        } else {
          setResult({ ok: false, message: 'No leads created. Check logs.' })
        }
      }
    } catch (err) {
      setResult({ ok: false, message: err.message || 'Network error.' })
    } finally {
      setLoading(false)
    }
  }

  return (
    <>
      {/* Trigger — small + button, sits in top-right of whatever parent renders it */}
      <button
        onClick={() => setOpen(true)}
        title="Quick add lead"
        style={{
          background: 'none',
          border: '1px solid var(--border)',
          borderRadius: 3,
          color: 'var(--text-muted)',
          fontFamily: 'var(--font-mono)',
          fontSize: '0.75rem',
          lineHeight: 1,
          padding: '2px 7px 3px',
          cursor: 'pointer',
          letterSpacing: '0.05em',
          transition: 'color 0.1s, border-color 0.1s',
        }}
        onMouseEnter={(e) => { e.currentTarget.style.color = 'var(--accent)'; e.currentTarget.style.borderColor = 'var(--accent)' }}
        onMouseLeave={(e) => { e.currentTarget.style.color = 'var(--text-muted)'; e.currentTarget.style.borderColor = 'var(--border)' }}
      >
        +
      </button>

      {/* Modal backdrop */}
      {open && (
        <div
          onClick={(e) => { if (e.target === e.currentTarget) close() }}
          style={{
            position: 'fixed',
            inset: 0,
            background: 'rgba(0,0,0,0.6)',
            zIndex: 9999,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
          }}
        >
          <div style={{
            background: 'var(--surface)',
            border: '1px solid var(--border)',
            borderRadius: 4,
            padding: '1.5rem',
            width: 320,
            maxWidth: 'calc(100vw - 2rem)',
          }}>
            {/* Header */}
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1.25rem' }}>
              <span style={{ fontFamily: 'var(--font-mono)', fontSize: '0.72rem', fontWeight: 600, letterSpacing: '0.1em', color: 'var(--text)', textTransform: 'uppercase' }}>
                Quick Add Lead
              </span>
              <button
                onClick={close}
                style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'var(--text-muted)', fontFamily: 'var(--font-mono)', fontSize: '0.75rem', padding: 0, lineHeight: 1 }}
              >
                ✕
              </button>
            </div>

            <form onSubmit={handleSubmit}>
              {/* First name */}
              <label style={{ display: 'block', fontFamily: 'var(--font-mono)', fontSize: '0.65rem', color: 'var(--text-muted)', letterSpacing: '0.08em', textTransform: 'uppercase', marginBottom: '0.3rem' }}>
                First Name
              </label>
              <input
                type="text"
                required
                value={firstName}
                onChange={e => setFirstName(e.target.value)}
                placeholder="Sebastien"
                autoFocus
                style={{
                  width: '100%',
                  background: 'var(--surface-hover)',
                  border: '1px solid var(--border)',
                  borderRadius: 3,
                  color: 'var(--text)',
                  fontFamily: 'var(--font-mono)',
                  fontSize: '0.78rem',
                  padding: '0.4rem 0.6rem',
                  marginBottom: '0.75rem',
                  boxSizing: 'border-box',
                  outline: 'none',
                }}
              />

              {/* Last name */}
              <label style={{ display: 'block', fontFamily: 'var(--font-mono)', fontSize: '0.65rem', color: 'var(--text-muted)', letterSpacing: '0.08em', textTransform: 'uppercase', marginBottom: '0.3rem' }}>
                Last Name
              </label>
              <input
                type="text"
                required
                value={lastName}
                onChange={e => setLastName(e.target.value)}
                placeholder="Taillieu"
                style={{
                  width: '100%',
                  background: 'var(--surface-hover)',
                  border: '1px solid var(--border)',
                  borderRadius: 3,
                  color: 'var(--text)',
                  fontFamily: 'var(--font-mono)',
                  fontSize: '0.78rem',
                  padding: '0.4rem 0.6rem',
                  marginBottom: '0.75rem',
                  boxSizing: 'border-box',
                  outline: 'none',
                }}
              />

              {/* Phone */}
              <label style={{ display: 'block', fontFamily: 'var(--font-mono)', fontSize: '0.65rem', color: 'var(--text-muted)', letterSpacing: '0.08em', textTransform: 'uppercase', marginBottom: '0.3rem' }}>
                Phone
              </label>
              <input
                type="tel"
                required
                value={phone}
                onChange={e => setPhone(e.target.value)}
                placeholder="4804897756"
                style={{
                  width: '100%',
                  background: 'var(--surface-hover)',
                  border: '1px solid var(--border)',
                  borderRadius: 3,
                  color: 'var(--text)',
                  fontFamily: 'var(--font-mono)',
                  fontSize: '0.78rem',
                  padding: '0.4rem 0.6rem',
                  marginBottom: '1rem',
                  boxSizing: 'border-box',
                  outline: 'none',
                }}
              />

              {/* Result message */}
              {result && (
                <p style={{
                  fontFamily: 'var(--font-mono)',
                  fontSize: '0.68rem',
                  color: result.ok ? 'var(--c-green, #4ade80)' : 'var(--c-red, #f87171)',
                  margin: '0 0 0.75rem',
                  lineHeight: 1.4,
                }}>
                  {result.message}
                </p>
              )}

              {/* Submit */}
              <button
                type="submit"
                disabled={loading}
                style={{
                  width: '100%',
                  background: loading ? 'var(--surface-hover)' : 'var(--accent)',
                  color: loading ? 'var(--text-muted)' : '#000',
                  border: 'none',
                  borderRadius: 3,
                  fontFamily: 'var(--font-mono)',
                  fontSize: '0.72rem',
                  fontWeight: 600,
                  letterSpacing: '0.08em',
                  padding: '0.5rem 1rem',
                  cursor: loading ? 'not-allowed' : 'pointer',
                  textTransform: 'uppercase',
                  transition: 'background 0.1s',
                }}
              >
                {loading ? 'IMPORTING...' : 'IMPORT LEAD'}
              </button>
            </form>
          </div>
        </div>
      )}
    </>
  )
}

export default QuickAddLead
