import { useState, useEffect } from 'react'
import { useAuthSafe as useAuth } from '../hooks/useClerkSafe'

const TEMPLATE_LABELS = {
  confirmation: 'Confirmation',
  reminder_24hr: '24hr Reminder',
  reminder_1hr: '1hr Reminder',
}

const MERGE_FIELDS = ['{{name}}', '{{date}}', '{{time}}', '{{timezone}}', '{{phone}}']

const SMS_SEGMENT_LENGTH = 160

function charCount(text) {
  const len = text.length
  const segments = Math.ceil(len / SMS_SEGMENT_LENGTH) || 1
  return { len, segments }
}

export default function SmsTemplates() {
  const { getToken } = useAuth()
  const [templates, setTemplates] = useState([])
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState({})
  const [saved, setSaved] = useState({})
  const [error, setError] = useState('')

  async function getAuthHeaders() {
    const headers = { 'Content-Type': 'application/json' }
    try {
      const t = await getToken()
      if (t) headers['Authorization'] = `Bearer ${t}`
    } catch {}
    return headers
  }

  useEffect(() => {
    fetchTemplates()
  }, [])

  async function fetchTemplates() {
    setLoading(true)
    setError('')
    try {
      const headers = await getAuthHeaders()
      const resp = await fetch('/api/sms-templates', { headers })
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
      const data = await resp.json()
      setTemplates(data)
    } catch (err) {
      setError('Failed to load templates: ' + err.message)
    } finally {
      setLoading(false)
    }
  }

  async function saveTemplate(key, body) {
    setSaving((s) => ({ ...s, [key]: true }))
    setSaved((s) => ({ ...s, [key]: false }))
    setError('')
    try {
      const headers = await getAuthHeaders()
      const resp = await fetch(`/api/sms-templates/${key}`, {
        method: 'PUT',
        headers,
        body: JSON.stringify({ body }),
      })
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
      setSaved((s) => ({ ...s, [key]: true }))
      setTimeout(() => setSaved((s) => ({ ...s, [key]: false })), 2000)
    } catch (err) {
      setError(`Failed to save ${TEMPLATE_LABELS[key]}: ${err.message}`)
    } finally {
      setSaving((s) => ({ ...s, [key]: false }))
    }
  }

  function updateBody(key, newBody) {
    setTemplates((prev) =>
      prev.map((t) => (t.template_key === key ? { ...t, body: newBody } : t))
    )
  }

  if (loading) {
    return (
      <div style={{ padding: '2rem' }}>
        <h2 style={{ fontFamily: 'var(--font-mono)', fontSize: '0.85rem', fontWeight: 600, letterSpacing: '0.08em', color: 'var(--text)', marginBottom: '1rem' }}>
          SMS TEMPLATES
        </h2>
        <p style={{ fontFamily: 'var(--font-mono)', fontSize: '0.72rem', color: 'var(--text-muted)' }}>Loading...</p>
      </div>
    )
  }

  return (
    <div style={{ padding: '2rem', maxWidth: 720 }}>
      <h2 style={{
        fontFamily: 'var(--font-mono)',
        fontSize: '0.85rem',
        fontWeight: 600,
        letterSpacing: '0.08em',
        color: 'var(--text)',
        marginBottom: '0.25rem',
      }}>
        SMS TEMPLATES
      </h2>
      <p style={{
        fontFamily: 'var(--font-mono)',
        fontSize: '0.62rem',
        color: 'var(--text-muted)',
        marginBottom: '1.5rem',
        lineHeight: 1.5,
      }}>
        Edit appointment reminder SMS templates. Use merge fields to personalize messages.
      </p>

      {error && (
        <div style={{
          background: 'rgba(255,60,60,0.1)',
          border: '1px solid rgba(255,60,60,0.3)',
          borderRadius: 4,
          padding: '0.5rem 0.75rem',
          marginBottom: '1rem',
          fontFamily: 'var(--font-mono)',
          fontSize: '0.68rem',
          color: '#ff3c3c',
        }}>
          {error}
        </div>
      )}

      {templates.map((t) => {
        const { len, segments } = charCount(t.body)
        return (
          <div
            key={t.template_key}
            style={{
              marginBottom: '1.5rem',
              background: 'var(--surface)',
              border: '1px solid var(--border)',
              borderRadius: 4,
              padding: '1rem',
            }}
          >
            <label style={{
              display: 'block',
              fontFamily: 'var(--font-mono)',
              fontSize: '0.72rem',
              fontWeight: 600,
              color: 'var(--text)',
              letterSpacing: '0.06em',
              marginBottom: '0.5rem',
            }}>
              {TEMPLATE_LABELS[t.template_key] || t.template_key}
            </label>

            <textarea
              value={t.body}
              onChange={(e) => updateBody(t.template_key, e.target.value)}
              rows={4}
              style={{
                width: '100%',
                background: 'var(--bg)',
                color: 'var(--text)',
                border: '1px solid var(--border)',
                borderRadius: 4,
                padding: '0.5rem',
                fontFamily: 'var(--font-mono)',
                fontSize: '0.72rem',
                lineHeight: 1.6,
                resize: 'vertical',
                boxSizing: 'border-box',
              }}
            />

            <div style={{
              display: 'flex',
              justifyContent: 'space-between',
              alignItems: 'center',
              marginTop: '0.4rem',
              flexWrap: 'wrap',
              gap: '0.4rem',
            }}>
              <span style={{
                fontFamily: 'var(--font-mono)',
                fontSize: '0.6rem',
                color: len > SMS_SEGMENT_LENGTH ? 'var(--accent)' : 'var(--text-muted)',
              }}>
                {len} chars · {segments} segment{segments > 1 ? 's' : ''}
              </span>

              <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                {saved[t.template_key] && (
                  <span style={{
                    fontFamily: 'var(--font-mono)',
                    fontSize: '0.6rem',
                    color: '#4caf50',
                  }}>
                    Saved
                  </span>
                )}
                <button
                  onClick={() => saveTemplate(t.template_key, t.body)}
                  disabled={saving[t.template_key]}
                  style={{
                    background: 'var(--accent)',
                    color: '#000',
                    border: 'none',
                    borderRadius: 4,
                    padding: '0.35rem 0.75rem',
                    fontFamily: 'var(--font-mono)',
                    fontSize: '0.65rem',
                    fontWeight: 600,
                    letterSpacing: '0.06em',
                    cursor: 'pointer',
                    opacity: saving[t.template_key] ? 0.6 : 1,
                  }}
                >
                  {saving[t.template_key] ? 'SAVING...' : 'SAVE'}
                </button>
              </div>
            </div>
          </div>
        )
      })}

      <div style={{
        background: 'var(--surface)',
        border: '1px solid var(--border)',
        borderRadius: 4,
        padding: '0.75rem',
      }}>
        <p style={{
          fontFamily: 'var(--font-mono)',
          fontSize: '0.65rem',
          fontWeight: 600,
          color: 'var(--text)',
          letterSpacing: '0.06em',
          marginBottom: '0.4rem',
        }}>
          MERGE FIELDS
        </p>
        <div style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap' }}>
          {MERGE_FIELDS.map((field) => (
            <code
              key={field}
              style={{
                background: 'var(--bg)',
                border: '1px solid var(--border)',
                borderRadius: 3,
                padding: '0.15rem 0.4rem',
                fontFamily: 'var(--font-mono)',
                fontSize: '0.62rem',
                color: 'var(--accent)',
              }}
            >
              {field}
            </code>
          ))}
        </div>
        <p style={{
          fontFamily: 'var(--font-mono)',
          fontSize: '0.58rem',
          color: 'var(--text-muted)',
          marginTop: '0.4rem',
          lineHeight: 1.4,
        }}>
          These fields are replaced with actual values when the SMS is sent.
          SMS segments are 160 characters each — longer messages use multiple segments.
        </p>
      </div>
    </div>
  )
}
