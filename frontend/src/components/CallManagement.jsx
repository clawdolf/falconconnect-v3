import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

const API = '/api'
const BRIDGE_DISPLAY = 'Bridge number loads after session creation'
const FAVORITE_CARRIERS = [
  { label: 'Test Carrier 914', phone: '' },
  { label: 'Mutual of Omaha UW', phone: '' },
  { label: 'Manual number', phone: '' },
]

function CallManagement() {
  const [leadPhone, setLeadPhone] = useState('')
  const [leadId, setLeadId] = useState('')
  const [session, setSession] = useState(null)
  const [status, setStatus] = useState(null)
  const [sessions, setSessions] = useState([])
  const [carrierChoice, setCarrierChoice] = useState(FAVORITE_CARRIERS[0].label)
  const [carrierPhone, setCarrierPhone] = useState(FAVORITE_CARRIERS[0].phone)
  const [busy, setBusy] = useState('')
  const [error, setError] = useState('')
  const [log, setLog] = useState([{ ts: new Date(), msg: 'Cockpit ready.' }])
  const pollRef = useRef(null)

  const authHeaders = useCallback(() => {
    const token = document.cookie.match(/__session=([^;]+)/)?.[1] || ''
    return {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    }
  }, [])

  const active = status || session
  const confId = active?.conf_id
  const currentStatus = active?.status || 'idle'
  const bridgeNumber = active?.bridge_number || BRIDGE_DISPLAY

  const canUpgrade = currentStatus === 'close_connected'
  const conferenceLive = ['conference_live', 'carrier_connected', 'dialing_carrier', 'upgrade_pending'].includes(currentStatus)

  const addLog = useCallback((msg) => {
    setLog((prev) => [{ ts: new Date(), msg }, ...prev].slice(0, 80))
  }, [])

  const refreshStatus = useCallback(async (silent = false) => {
    if (!confId) return
    try {
      const res = await fetch(`${API}/conference/${confId}`, { headers: authHeaders() })
      if (!res.ok) throw new Error(`Status refresh failed (${res.status})`)
      const data = await res.json()
      setStatus((prev) => {
        if (prev?.status !== data.status && !silent) addLog(`Status changed: ${data.status}`)
        return data
      })
    } catch (err) {
      if (!silent) setError(err.message)
    }
  }, [addLog, authHeaders, confId])

  useEffect(() => {
    if (!confId || currentStatus === 'ended') return undefined
    pollRef.current = window.setInterval(() => refreshStatus(true), 2000)
    return () => window.clearInterval(pollRef.current)
  }, [confId, currentStatus, refreshStatus])

  useEffect(() => {
    loadSessions()
  }, [])

  async function loadSessions() {
    try {
      const res = await fetch(`${API}/conference/sessions`, { headers: authHeaders() })
      if (res.ok) setSessions(await res.json())
    } catch {
      // Recent sessions are non-critical for the live cockpit.
    }
  }

  async function findLiveBridge() {
    setBusy('find-live')
    setError('')
    try {
      const res = await fetch(`${API}/conference/bridge/live`, { headers: authHeaders() })
      if (!res.ok) {
        const body = await res.json().catch(() => ({}))
        throw new Error(body.detail || `No live bridge found (${res.status})`)
      }
      const data = await res.json()
      setSession(data)
      setStatus(data)
      addLog(`Live bridge found for ${data.lead_phone}.`)
      await loadSessions()
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy('')
    }
  }

  async function createSession(event) {
    event.preventDefault()
    setBusy('create')
    setError('')
    try {
      const res = await fetch(`${API}/conference/bridge/start`, {
        method: 'POST',
        headers: authHeaders(),
        body: JSON.stringify({ lead_phone: leadPhone, lead_id: leadId || null }),
      })
      if (!res.ok) {
        const body = await res.json().catch(() => ({}))
        throw new Error(body.detail || `Create failed (${res.status})`)
      }
      const data = await res.json()
      setSession(data)
      setStatus(data)
      addLog(`Transfer session created for ${data.lead_phone}.`)
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy('')
    }
  }

  async function postAction(path, label) {
    if (!confId) return
    setBusy(label)
    setError('')
    try {
      const res = await fetch(`${API}/conference/${confId}/${path}`, {
        method: 'POST',
        headers: authHeaders(),
      })
      if (!res.ok) {
        const body = await res.json().catch(() => ({}))
        throw new Error(body.detail || `${label} failed (${res.status})`)
      }
      addLog(label)
      await refreshStatus(true)
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy('')
    }
  }

  async function addCarrier() {
    if (!confId) return
    const phone = carrierPhone.trim()
    if (!phone) {
      setError('Enter a carrier phone number first.')
      return
    }
    setBusy('carrier')
    setError('')
    try {
      addLog(`Dialing carrier: ${phone}.`)
      const res = await fetch(`${API}/conference/${confId}/carrier`, {
        method: 'POST',
        headers: authHeaders(),
        body: JSON.stringify({ carrier_phone: phone, carrier_label: carrierChoice }),
      })
      if (!res.ok) {
        const body = await res.json().catch(() => ({}))
        throw new Error(body.detail || `Carrier failed (${res.status})`)
      }
      const data = await res.json()
      addLog(`Carrier dial started: ${data.carrier_phone}.`)
      await refreshStatus(true)
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy('')
    }
  }

  async function participantAction(action, participant) {
    if (action === 'drop' && participant !== 'carrier') {
      const label = participant === 'lead' ? 'client' : 'Seb'
      if (!window.confirm(`Drop ${label} from this bridge?`)) return
    }
    await postAction(`${action}/${participant}`, `${action} ${participant}`)
  }

  function selectCarrier(label) {
    setCarrierChoice(label)
    const found = FAVORITE_CARRIERS.find((carrier) => carrier.label === label)
    if (found?.phone) setCarrierPhone(found.phone)
  }

  const participants = useMemo(() => ([
    { key: 'lead', title: 'Client / Lead', phone: active?.lead_phone, data: active?.participants?.lead },
    { key: 'seb', title: 'Seb / Close', phone: active?.seb_phone, data: active?.participants?.seb },
    { key: 'carrier', title: 'Carrier', phone: active?.carrier_phone || carrierPhone, data: active?.participants?.carrier },
  ]), [active, carrierPhone])

  return (
    <div style={styles.page}>
      <header style={styles.header}>
        <div>
          <h1 style={styles.title}>3 Way Bridge</h1>
          <p style={styles.subtitle}>Close owns the lead. Twilio owns the call physics.</p>
        </div>
        <div style={styles.statusStrip}>
          {statusBadges(currentStatus).map((badge) => (
            <span key={badge.label} style={{ ...styles.badge, color: badge.active ? badge.color : 'var(--text-muted)', borderColor: badge.active ? badge.color : 'var(--border)' }}>
              {badge.label}
            </span>
          ))}
        </div>
      </header>

      <section style={styles.section}>
        <div style={styles.sectionHead}>
          <h2 style={styles.sectionTitle}>Live Workflow</h2>
          {confId && <span style={styles.monoMuted}>Session {confId.slice(0, 8)}</span>}
        </div>

        {!confId ? (
          <div>
            <form onSubmit={createSession} style={styles.formGrid}>
              <Field label="Lead phone number">
                <input style={styles.input} type="tel" value={leadPhone} onChange={(e) => setLeadPhone(e.target.value)} placeholder="Lead phone" required />
              </Field>
              <Field label="Close lead id optional">
                <input style={styles.input} type="text" value={leadId} onChange={(e) => setLeadId(e.target.value)} placeholder="lead_..." />
              </Field>
              <button style={styles.primaryButton} disabled={busy === 'create' || !leadPhone}>
                {busy === 'create' ? 'Creating...' : 'Create Transfer Session'}
              </button>
            </form>
            <div style={styles.liveFindRow}>
              <span style={styles.monoMuted}>Already transferred from Close? Attach the cockpit to the live bridge.</span>
              <button type="button" style={styles.secondaryButton} disabled={busy === 'find-live'} onClick={findLiveBridge}>
                {busy === 'find-live' ? 'Finding...' : 'Find Live Bridge'}
              </button>
            </div>
          </div>
        ) : (
          <div style={styles.workflowGrid}>
            <div style={styles.transferBox}>
              <span style={styles.kicker}>Transfer active Close call to</span>
              <strong style={styles.bridgeNumber}>{formatPhone(bridgeNumber)}</strong>
            </div>
            <button type="button" style={styles.secondaryButton} onClick={() => refreshStatus(false)}>Refresh Status</button>
            {canUpgrade && (
              <button type="button" style={styles.primaryButton} disabled={busy === 'Upgrade to conference'} onClick={() => postAction('upgrade', 'Upgrade to conference')}>
                Upgrade to Conference
              </button>
            )}
          </div>
        )}
        {error && <p style={styles.error}>{error}</p>}
      </section>

      {conferenceLive && (
        <section style={styles.section}>
          <div style={styles.sectionHead}>
            <h2 style={styles.sectionTitle}>Carrier</h2>
            <span style={styles.monoMuted}>Outbound caller ID stays on bridge number</span>
          </div>
          <div style={styles.carrierGrid}>
            <div style={styles.carrierFields}>
              <Field label="Favorite carrier">
                <select style={styles.input} value={carrierChoice} onChange={(e) => selectCarrier(e.target.value)}>
                  {FAVORITE_CARRIERS.map((carrier) => <option key={carrier.label}>{carrier.label}</option>)}
                </select>
              </Field>
              <Field label="Carrier phone">
                <input style={styles.input} type="tel" value={carrierPhone} onChange={(e) => setCarrierPhone(e.target.value)} placeholder="+1..." />
              </Field>
            </div>
            <button type="button" style={styles.primaryButton} disabled={busy === 'carrier' || !carrierPhone.trim()} onClick={addCarrier}>
              {busy === 'carrier' ? 'Dialing...' : 'Add Carrier'}
            </button>
          </div>
        </section>
      )}

      <section style={styles.participantGrid}>
        {participants.map((participant) => (
          <ParticipantCard
            key={participant.key}
            participant={participant}
            onAction={participantAction}
            disabled={!participant.data?.call_sid}
          />
        ))}
      </section>

      <section style={styles.section}>
        <h2 style={styles.sectionTitle}>Activity Log</h2>
        <div style={styles.logBox}>
          {log.map((item, index) => (
            <div key={`${item.ts.toISOString()}-${index}`} style={styles.logLine}>
              <span>{item.ts.toLocaleTimeString()}</span>
              <span>{item.msg}</span>
            </div>
          ))}
        </div>
      </section>

      <section style={styles.section}>
        <div style={styles.sectionHead}>
          <h2 style={styles.sectionTitle}>Recent Sessions</h2>
          <button type="button" style={styles.textButton} onClick={loadSessions}>Reload</button>
        </div>
        <div style={styles.table}>
          <div style={{ ...styles.row, ...styles.tableHead }}>
            <span>Lead</span><span>Carrier</span><span>Status</span><span>Started</span>
          </div>
          {sessions.length === 0 ? (
            <div style={styles.empty}>No bridge sessions yet.</div>
          ) : sessions.map((item) => (
            <div key={item.conf_id} style={styles.row}>
              <span>{formatPhone(item.lead_phone)}</span>
              <span>{formatPhone(item.carrier_phone) || '-'}</span>
              <span>{item.status}</span>
              <span>{item.started_at ? new Date(item.started_at).toLocaleString() : '-'}</span>
            </div>
          ))}
        </div>
      </section>
    </div>
  )
}

function ParticipantCard({ participant, onAction, disabled }) {
  const data = participant.data || {}
  const connected = Boolean(data.call_sid)
  const label = participant.key
  return (
    <article style={styles.participantCard}>
      <div style={styles.participantTop}>
        <div>
          <h3 style={styles.participantTitle}>{participant.title}</h3>
          <p style={styles.monoMuted}>{formatPhone(participant.phone) || 'Not connected'}</p>
        </div>
        <span style={{ ...styles.dot, background: connected ? 'var(--green)' : 'var(--border)' }} />
      </div>
      <div style={styles.badgeLine}>
        <span style={styles.smallBadge}>{statusLabel(data.status)}</span>
        {data.muted && <span style={styles.smallBadgeWarn}>Muted</span>}
        {data.hold && <span style={styles.smallBadgeWarn}>Held</span>}
      </div>
      <div style={styles.controls}>
        <button type="button" style={styles.controlButton} disabled={disabled} onClick={() => onAction(data.muted ? 'unmute' : 'mute', label)}>
          {data.muted ? 'Unmute' : 'Mute'}
        </button>
        <button type="button" style={styles.controlButton} disabled={disabled} onClick={() => onAction(data.hold ? 'unhold' : 'hold', label)}>
          {data.hold ? 'Unhold' : 'Hold'}
        </button>
        <button type="button" style={label === 'carrier' ? styles.dropPrimary : styles.dropButton} disabled={disabled} onClick={() => onAction('drop', label)}>
          Drop
        </button>
      </div>
    </article>
  )
}

function Field({ label, children }) {
  return (
    <label style={styles.field}>
      <span style={styles.label}>{label}</span>
      {children}
    </label>
  )
}

function statusBadges(status) {
  return [
    { label: 'Waiting for transfer', active: status === 'waiting_for_transfer', color: 'var(--amber)' },
    { label: 'Close connected', active: status === 'close_connected', color: 'var(--green)' },
    { label: 'Conference live', active: ['conference_live', 'carrier_connected', 'dialing_carrier', 'upgrade_pending'].includes(status), color: 'var(--green)' },
    { label: 'Carrier connected', active: status === 'carrier_connected', color: 'var(--green)' },
  ]
}

function statusLabel(status) {
  if (!status || status === 'not_connected') return 'Not connected'
  if (status === 'known') return 'Leg captured'
  return status.replaceAll('_', ' ')
}

function formatPhone(value) {
  if (!value) return ''
  const digits = value.replace(/\D/g, '')
  if (digits.length === 11 && digits[0] === '1') {
    return `+1 (${digits.slice(1, 4)}) ${digits.slice(4, 7)}-${digits.slice(7)}`
  }
  return value
}

const buttonBase = {
  borderRadius: 2,
  fontFamily: 'var(--font-mono)',
  fontSize: '0.72rem',
  fontWeight: 600,
  letterSpacing: '0.04em',
  textTransform: 'uppercase',
  cursor: 'pointer',
  padding: '0.58rem 0.8rem',
}

const styles = {
  page: { display: 'flex', flexDirection: 'column', gap: '1rem', maxWidth: 1180 },
  header: { display: 'flex', justifyContent: 'space-between', gap: '1rem', alignItems: 'flex-start', borderBottom: '1px solid var(--border)', paddingBottom: '1rem' },
  title: { fontFamily: 'var(--font-display)', fontSize: '1.9rem', lineHeight: 1, letterSpacing: 0, margin: 0 },
  subtitle: { color: 'var(--text-muted)', fontSize: '0.78rem', marginTop: '0.35rem' },
  statusStrip: { display: 'flex', gap: '0.45rem', flexWrap: 'wrap', justifyContent: 'flex-end' },
  badge: { border: '1px solid var(--border)', padding: '0.25rem 0.45rem', fontFamily: 'var(--font-mono)', fontSize: '0.62rem', textTransform: 'uppercase' },
  section: { background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 2, padding: '1rem' },
  sectionHead: { display: 'flex', justifyContent: 'space-between', gap: '1rem', alignItems: 'center', marginBottom: '0.8rem' },
  sectionTitle: { fontFamily: 'var(--font-display)', fontSize: '0.95rem', margin: 0, letterSpacing: 0 },
  formGrid: { display: 'grid', gridTemplateColumns: 'minmax(220px, 1fr) minmax(220px, 1fr) auto', gap: '0.75rem', alignItems: 'end' },
  liveFindRow: { display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: '0.75rem', marginTop: '0.75rem', paddingTop: '0.75rem', borderTop: '1px solid var(--border-subtle)', flexWrap: 'wrap' },
  workflowGrid: { display: 'grid', gridTemplateColumns: 'minmax(260px, 1fr) auto auto', gap: '0.75rem', alignItems: 'stretch' },
  carrierGrid: { display: 'grid', gridTemplateColumns: '1fr auto', gap: '0.75rem', alignItems: 'end' },
  carrierFields: { display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0.75rem', alignItems: 'end' },
  field: { display: 'flex', flexDirection: 'column', gap: '0.25rem' },
  label: { color: 'var(--text-muted)', fontFamily: 'var(--font-mono)', fontSize: '0.66rem', textTransform: 'uppercase', letterSpacing: '0.04em' },
  input: { width: '100%', background: 'var(--bg)', border: '1px solid var(--border)', borderRadius: 2, color: 'var(--text)', fontFamily: 'var(--font-mono)', fontSize: '0.8rem', padding: '0.55rem 0.6rem' },
  primaryButton: { ...buttonBase, background: 'var(--accent)', border: '1px solid var(--accent)', color: 'oklch(15% 0.01 85)' },
  secondaryButton: { ...buttonBase, background: 'var(--surface-hover)', border: '1px solid var(--border)', color: 'var(--text)' },
  textButton: { ...buttonBase, padding: '0.25rem 0.4rem', background: 'transparent', border: '1px solid var(--border)', color: 'var(--text-muted)' },
  error: { color: 'var(--red)', fontFamily: 'var(--font-mono)', fontSize: '0.72rem', marginTop: '0.75rem' },
  transferBox: { border: '1px solid var(--border)', background: 'var(--bg)', padding: '0.6rem 0.75rem', display: 'flex', flexDirection: 'column', justifyContent: 'center' },
  kicker: { color: 'var(--text-muted)', fontFamily: 'var(--font-mono)', fontSize: '0.62rem', textTransform: 'uppercase' },
  bridgeNumber: { fontFamily: 'var(--font-display)', fontSize: '1.25rem', letterSpacing: 0 },
  participantGrid: { display: 'grid', gridTemplateColumns: 'repeat(3, minmax(0, 1fr))', gap: '1rem' },
  participantCard: { background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 2, padding: '1rem', minWidth: 0 },
  participantTop: { display: 'flex', justifyContent: 'space-between', gap: '0.75rem', marginBottom: '0.75rem' },
  participantTitle: { fontFamily: 'var(--font-display)', fontSize: '0.92rem', margin: 0, letterSpacing: 0 },
  monoMuted: { color: 'var(--text-muted)', fontFamily: 'var(--font-mono)', fontSize: '0.68rem', overflowWrap: 'anywhere' },
  dot: { width: 10, height: 10, flex: '0 0 auto', marginTop: 6 },
  badgeLine: { display: 'flex', flexWrap: 'wrap', gap: '0.35rem', minHeight: 26 },
  smallBadge: { border: '1px solid var(--border)', color: 'var(--text-muted)', padding: '0.14rem 0.35rem', fontSize: '0.62rem', fontFamily: 'var(--font-mono)', textTransform: 'uppercase' },
  smallBadgeWarn: { border: '1px solid var(--amber)', color: 'var(--amber)', padding: '0.14rem 0.35rem', fontSize: '0.62rem', fontFamily: 'var(--font-mono)', textTransform: 'uppercase' },
  controls: { display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '0.4rem', marginTop: '0.75rem' },
  controlButton: { ...buttonBase, padding: '0.38rem 0.35rem', background: 'var(--surface-hover)', border: '1px solid var(--border)', color: 'var(--text-muted)', fontSize: '0.62rem' },
  dropButton: { ...buttonBase, padding: '0.38rem 0.35rem', background: 'transparent', border: '1px solid var(--red)', color: 'var(--red)', fontSize: '0.62rem' },
  dropPrimary: { ...buttonBase, padding: '0.38rem 0.35rem', background: 'var(--red)', border: '1px solid var(--red)', color: 'var(--text)', fontSize: '0.62rem' },
  logBox: { marginTop: '0.75rem', background: 'var(--bg)', border: '1px solid var(--border)', maxHeight: 180, overflow: 'auto', padding: '0.5rem' },
  logLine: { display: 'grid', gridTemplateColumns: '92px 1fr', gap: '0.75rem', color: 'var(--text-muted)', fontFamily: 'var(--font-mono)', fontSize: '0.66rem', lineHeight: 1.5 },
  table: { overflowX: 'auto' },
  row: { display: 'grid', gridTemplateColumns: '1fr 1fr 0.8fr 1.2fr', gap: '0.75rem', minWidth: 680, borderBottom: '1px solid var(--border-subtle)', padding: '0.45rem 0', fontFamily: 'var(--font-mono)', fontSize: '0.68rem' },
  tableHead: { color: 'var(--text-muted)', textTransform: 'uppercase', fontSize: '0.6rem' },
  empty: { color: 'var(--text-muted)', fontFamily: 'var(--font-mono)', fontSize: '0.72rem', paddingTop: '0.75rem' },
}

export default CallManagement
