import { useState, useEffect } from 'react'
import { useAuthSafe as useAuth } from '../hooks/useClerkSafe'

// Appointment SMS section templates
const APPOINTMENT_TEMPLATES = [
  { key: 'confirmation', label: 'Confirmation', hint: 'sent immediately on booking' },
  { key: 'reminder_24hr', label: '24hr Reminder', hint: 'sent 24 hours before appointment' },
  { key: 'reminder_1hr', label: '1hr Reminder', hint: 'sent 1 hour before appointment' },
]

// Workflow SMS section templates
const WORKFLOW_TEMPLATES = [
  { key: 'r1_done', label: 'R1 Done', hint: 'fires after you mark r1-done, sent next morning' },
  { key: 'r2_done', label: 'R2 Done', hint: 'fires after you mark r2-done, sent next morning' },
  { key: 'r3_done', label: 'R3 Done', hint: 'fires after you mark r3-done, sent next morning — then auto-moves lead to nurture' },
]

const APPOINTMENT_MERGE_FIELDS = ['{{name}}', '{{date}}', '{{time}}', '{{timezone}}', '{{phone}}']
const WORKFLOW_MERGE_FIELDS = ['{first_name}', '{state}']

const SMS_SEGMENT_LENGTH = 160

function charCount(text) {
  const len = text.length
  const segments = Math.ceil(len / SMS_SEGMENT_LENGTH) || 1
  return { len, segments }
}

function ChevronIcon({ open }) {
  return (
    <svg
      width="12"
      height="12"
      viewBox="0 0 12 12"
      fill="none"
      style={{
        transform: open ? 'rotate(180deg)' : 'rotate(0deg)',
        transition: 'transform 0.15s ease',
        flexShrink: 0,
      }}
    >
      <path
        d="M2 4L6 8L10 4"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  )
}

function TemplateCard({ template, body, onUpdate, onSave, saving, saved }) {
  const { len, segments } = charCount(body || '')
  return (
    <div
      style={{
        marginBottom: '1rem',
        background: 'var(--surface)',
        border: '1px solid var(--border)',
        borderRadius: 4,
        padding: '1rem',
      }}
    >
      <div style={{ marginBottom: '0.4rem' }}>
        <span style={{
          fontFamily: 'var(--font-mono)',
          fontSize: '0.72rem',
          fontWeight: 600,
          color: 'var(--text)',
          letterSpacing: '0.06em',
        }}>
          {template.label}
        </span>
        {template.hint && (
          <span style={{
            fontFamily: 'var(--font-mono)',
            fontSize: '0.6rem',
            color: 'var(--text-muted)',
            marginLeft: '0.5rem',
          }}>
            — {template.hint}
          </span>
        )}
      </div>

      <textarea
        value={body || ''}
        onChange={(e) => onUpdate(template.key, e.target.value)}
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
          {saved && (
            <span style={{
              fontFamily: 'var(--font-mono)',
              fontSize: '0.6rem',
              color: '#4caf50',
            }}>
              Saved
            </span>
          )}
          <button
            onClick={() => onSave(template.key, body)}
            disabled={saving}
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
              opacity: saving ? 0.6 : 1,
            }}
          >
            {saving ? 'SAVING...' : 'SAVE'}
          </button>
        </div>
      </div>
    </div>
  )
}

function CollapsibleSection({ title, subtitle, mergeFields, templates, bodies, onUpdate, onSave, saving, saved, defaultOpen }) {
  const [open, setOpen] = useState(defaultOpen !== false)

  return (
    <div style={{ marginBottom: '1.5rem' }}>
      <button
        onClick={() => setOpen((o) => !o)}
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: '0.5rem',
          width: '100%',
          background: 'none',
          border: 'none',
          borderBottom: '1px solid var(--border)',
          borderRadius: 0,
          padding: '0.5rem 0',
          cursor: 'pointer',
          textAlign: 'left',
          color: 'var(--text)',
          marginBottom: open ? '1rem' : 0,
        }}
      >
        <span style={{
          fontFamily: 'var(--font-mono)',
          fontSize: '0.78rem',
          fontWeight: 700,
          letterSpacing: '0.08em',
          color: 'var(--text)',
          flex: 1,
        }}>
          {title}
        </span>
        {subtitle && (
          <span style={{
            fontFamily: 'var(--font-mono)',
            fontSize: '0.58rem',
            color: 'var(--text-muted)',
            marginRight: '0.5rem',
          }}>
            {subtitle}
          </span>
        )}
        <ChevronIcon open={open} />
      </button>

      {open && (
        <div>
          {templates.map((t) => (
            <TemplateCard
              key={t.key}
              template={t}
              body={bodies[t.key] || ''}
              onUpdate={onUpdate}
              onSave={onSave}
              saving={saving[t.key]}
              saved={saved[t.key]}
            />
          ))}

          <div style={{
            background: 'var(--surface)',
            border: '1px solid var(--border)',
            borderRadius: 4,
            padding: '0.6rem 0.75rem',
            marginBottom: '0.5rem',
          }}>
            <p style={{
              fontFamily: 'var(--font-mono)',
              fontSize: '0.6rem',
              fontWeight: 600,
              color: 'var(--text-muted)',
              letterSpacing: '0.06em',
              marginBottom: '0.35rem',
            }}>
              AVAILABLE VARIABLES
            </p>
            <div style={{ display: 'flex', gap: '0.4rem', flexWrap: 'wrap' }}>
              {mergeFields.map((field) => (
                <code
                  key={field}
                  style={{
                    background: 'var(--bg)',
                    border: '1px solid var(--border)',
                    borderRadius: 3,
                    padding: '0.1rem 0.35rem',
                    fontFamily: 'var(--font-mono)',
                    fontSize: '0.62rem',
                    color: 'var(--accent)',
                  }}
                >
                  {field}
                </code>
              ))}
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

export default function SmsTemplates() {
  const { getToken } = useAuth()
  const [bodies, setBodies] = useState({})
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
      const map = {}
      data.forEach((t) => { map[t.template_key] = t.body })
      setBodies(map)
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
      setError(`Failed to save template: ${err.message}`)
    } finally {
      setSaving((s) => ({ ...s, [key]: false }))
    }
  }

  function updateBody(key, newBody) {
    setBodies((prev) => ({ ...prev, [key]: newBody }))
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
        Edit SMS templates for appointments and cadence workflow. Changes take effect immediately.
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

      <CollapsibleSection
        title="APPOINTMENT SMS"
        subtitle="booking confirmations & reminders"
        mergeFields={APPOINTMENT_MERGE_FIELDS}
        templates={APPOINTMENT_TEMPLATES}
        bodies={bodies}
        onUpdate={updateBody}
        onSave={saveTemplate}
        saving={saving}
        saved={saved}
        defaultOpen={true}
      />

      <CollapsibleSection
        title="WORKFLOW SMS"
        subtitle="cadence blitz follow-ups"
        mergeFields={WORKFLOW_MERGE_FIELDS}
        templates={WORKFLOW_TEMPLATES}
        bodies={bodies}
        onUpdate={updateBody}
        onSave={saveTemplate}
        saving={saving}
        saved={saved}
        defaultOpen={true}
      />
    </div>
  )
}
