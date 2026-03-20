import { useState, useEffect, useRef, useCallback } from 'react'

const API = '/api'

function CallManagement() {
  const [tab, setTab] = useState('conference') // conference | callerid | history
  const [callerIds, setCallerIds] = useState([])
  const [callerIdsLoading, setCallerIdsLoading] = useState(false)

  // Conference form
  const [leadPhone, setLeadPhone] = useState('')
  const [carrierPhone, setCarrierPhone] = useState('')
  const [selectedNumber, setSelectedNumber] = useState('+18446813690') // FC toll-free — fixed until A2P clears
  const [leadId, setLeadId] = useState('')
  const [starting, setStarting] = useState(false)
  const [error, setError] = useState('')

  // Active conference
  const [activeConf, setActiveConf] = useState(null)
  const [confStatus, setConfStatus] = useState(null)
  const pollRef = useRef(null)

  // History
  const [sessions, setSessions] = useState([])
  const [sessionsLoading, setSessionsLoading] = useState(false)

  // Caller ID verification
  const [verifying, setVerifying] = useState(null) // phone number being verified
  const [verifyCode, setVerifyCode] = useState('')
  const [verifyMsg, setVerifyMsg] = useState('')

  const token = () => {
    try {
      return window.__clerk_session?.getToken?.() || ''
    } catch { return '' }
  }

  const authHeaders = useCallback(() => {
    const t = document.cookie.match(/__session=([^;]+)/)?.[1] || ''
    return {
      'Content-Type': 'application/json',
      ...(t ? { 'Authorization': `Bearer ${t}` } : {}),
    }
  }, [])

  // Load caller IDs on mount
  useEffect(() => {
    loadCallerIds()
  }, [])

  async function loadCallerIds() {
    setCallerIdsLoading(true)
    try {
      const res = await fetch(`${API}/conference/caller-id/list`, { headers: authHeaders() })
      if (res.ok) {
        const data = await res.json()
        setCallerIds(data.numbers || [])
        // Auto-select first verified number
        const firstVerified = (data.numbers || []).find(n => n.verified)
        if (firstVerified && !selectedNumber) {
          setSelectedNumber(firstVerified.phone_number)
        }
      }
    } catch (e) {
      console.error('Failed to load caller IDs:', e)
    } finally {
      setCallerIdsLoading(false)
    }
  }

  // Poll conference status
  useEffect(() => {
    if (activeConf && activeConf.status !== 'ended') {
      pollRef.current = setInterval(async () => {
        try {
          const res = await fetch(`${API}/conference/${activeConf.conf_id}`, { headers: authHeaders() })
          if (res.ok) {
            const data = await res.json()
            setConfStatus(data)
            if (data.status === 'ended') {
              clearInterval(pollRef.current)
              setActiveConf(null)
            }
          }
        } catch (e) {
          console.error('Poll error:', e)
        }
      }, 2000)
      return () => clearInterval(pollRef.current)
    }
  }, [activeConf])

  async function startConference(e) {
    e.preventDefault()
    setError('')
    setStarting(true)
    try {
      const res = await fetch(`${API}/conference/start`, {
        method: 'POST',
        headers: authHeaders(),
        body: JSON.stringify({
          lead_phone: leadPhone,
          carrier_phone: carrierPhone,
          seb_close_number: selectedNumber,
          lead_id: leadId || null,
        }),
      })
      if (!res.ok) {
        const err = await res.json().catch(() => ({}))
        throw new Error(err.detail || `HTTP ${res.status}`)
      }
      const data = await res.json()
      setActiveConf(data)
      setConfStatus(null)
    } catch (e) {
      setError(e.message)
    } finally {
      setStarting(false)
    }
  }

  async function dialCarrier() {
    if (!activeConf) return
    try {
      await fetch(`${API}/conference/${activeConf.conf_id}/dial-carrier`, {
        method: 'POST',
        headers: authHeaders(),
      })
    } catch (e) {
      console.error('Dial carrier error:', e)
    }
  }

  async function conferenceAction(action, participant) {
    if (!activeConf) return
    try {
      await fetch(`${API}/conference/${activeConf.conf_id}/${action}/${participant}`, {
        method: 'POST',
        headers: authHeaders(),
      })
    } catch (e) {
      console.error(`${action} ${participant} error:`, e)
    }
  }

  async function endConference() {
    if (!activeConf) return
    try {
      await fetch(`${API}/conference/${activeConf.conf_id}/end`, {
        method: 'POST',
        headers: authHeaders(),
      })
      clearInterval(pollRef.current)
      setActiveConf(null)
      setConfStatus(null)
    } catch (e) {
      console.error('End conference error:', e)
    }
  }

  async function loadSessions() {
    setSessionsLoading(true)
    try {
      const res = await fetch(`${API}/conference/sessions`, { headers: authHeaders() })
      if (res.ok) {
        const data = await res.json()
        setSessions(data)
      }
    } catch (e) {
      console.error('Load sessions error:', e)
    } finally {
      setSessionsLoading(false)
    }
  }

  async function initiateVerify(phoneNumber) {
    setVerifying(phoneNumber)
    setVerifyCode('')
    setVerifyMsg('')
    try {
      const res = await fetch(`${API}/conference/caller-id/verify`, {
        method: 'POST',
        headers: authHeaders(),
        body: JSON.stringify({ phone_number: phoneNumber }),
      })
      if (res.ok) {
        const data = await res.json()
        setVerifyMsg(`Twilio is calling ${phoneNumber}. Listen for the 6-digit code.`)
        // In test mode, Twilio returns the code directly
        if (data.validation_code) {
          setVerifyMsg(`Verification code: ${data.validation_code}`)
        }
      } else {
        const err = await res.json().catch(() => ({}))
        setVerifyMsg(`Error: ${err.detail || 'Verification failed'}`)
      }
    } catch (e) {
      setVerifyMsg(`Error: ${e.message}`)
    }
  }

  async function confirmVerify() {
    if (!verifying) return
    try {
      const res = await fetch(`${API}/conference/caller-id/confirm`, {
        method: 'POST',
        headers: authHeaders(),
        body: JSON.stringify({ phone_number: verifying, code: verifyCode }),
      })
      if (res.ok) {
        const data = await res.json()
        if (data.verified) {
          setVerifyMsg('Number verified.')
          setVerifying(null)
          loadCallerIds()
        } else {
          setVerifyMsg('Not yet verified. The code is entered during the Twilio call, not here. Wait for the call and enter the code when prompted.')
        }
      }
    } catch (e) {
      setVerifyMsg(`Error: ${e.message}`)
    }
  }

  function formatPhone(num) {
    if (!num) return ''
    const d = num.replace(/\D/g, '')
    if (d.length === 11 && d[0] === '1') {
      return `(${d.slice(1,4)}) ${d.slice(4,7)}-${d.slice(7)}`
    }
    return num
  }

  function participantStatusColor(status) {
    if (!status) return 'c-amber'
    switch (status) {
      case 'in-progress': return 'c-green'
      case 'completed': return 'c-red'
      case 'ringing': return 'c-amber'
      case 'queued': return 'c-amber'
      case 'no-answer': return 'c-red'
      case 'busy': return 'c-red'
      case 'failed': return 'c-red'
      default: return 'c-amber'
    }
  }

  function participantStatusLabel(p) {
    if (!p) return 'Not Connected'
    if (p.hold) return 'On Hold'
    if (p.muted) return 'Muted'
    if (p.status === 'in-progress') return 'Connected'
    if (p.status === 'completed') return 'Disconnected'
    if (p.status === 'ringing') return 'Ringing...'
    if (p.status === 'queued') return 'Queued'
    if (p.status === 'no-answer') return 'No Answer'
    return p.status || 'Unknown'
  }

  const verifiedNumbers = callerIds.filter(n => n.verified)

  return (
    <div className="call-management">
      {/* Tab navigation */}
      <div style={{ display: 'flex', gap: '0.5rem', marginBottom: '1.5rem' }}>
        {[
          { key: 'conference', label: 'Conference Bridge' },
          { key: 'history', label: 'Recent Sessions' },
        ].map(t => (
          <button
            key={t.key}
            onClick={() => {
              setTab(t.key)
              if (t.key === 'history') loadSessions()
            }}
            style={{
              padding: '0.4rem 0.75rem',
              background: tab === t.key ? 'var(--accent)' : 'var(--surface)',
              color: tab === t.key ? 'oklch(15% 0.01 85)' : 'var(--text-muted)',
              border: `1px solid ${tab === t.key ? 'var(--accent)' : 'var(--border)'}`,
              borderRadius: 2,
              fontFamily: 'var(--font-mono)',
              fontSize: '0.72rem',
              fontWeight: tab === t.key ? 600 : 400,
              letterSpacing: '0.04em',
              cursor: 'pointer',
              textTransform: 'uppercase',
            }}
          >
            {t.label}
          </button>
        ))}
      </div>

      {/* ── Conference Bridge Tab ── */}
      {tab === 'conference' && (
        <>
          {!activeConf ? (
            <section className="section">
              <h2 className="section-title">Start Conference Bridge</h2>
              <form onSubmit={startConference} style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem', maxWidth: 480 }}>
                <div>
                  <label className="form-label">Lead Phone Number</label>
                  <input
                    className="custom-signin-input"
                    type="tel"
                    placeholder="+1 (555) 123-4567"
                    value={leadPhone}
                    onChange={e => setLeadPhone(e.target.value)}
                    required
                  />
                </div>
                <div>
                  <label className="form-label">Carrier Phone Number</label>
                  <input
                    className="custom-signin-input"
                    type="tel"
                    placeholder="+1 (800) 555-0100"
                    value={carrierPhone}
                    onChange={e => setCarrierPhone(e.target.value)}
                    required
                  />
                </div>
                <div>
                  <label className="form-label">Caller ID</label>
                  <div className="custom-signin-input" style={{ opacity: 0.6, cursor: 'default', userSelect: 'none' }}>
                    +1 (844) 681-3690 — FC toll-free
                  </div>
                </div>
                <div>
                  <label className="form-label">Close Lead ID (optional)</label>
                  <input
                    className="custom-signin-input"
                    type="text"
                    placeholder="lead_abc123..."
                    value={leadId}
                    onChange={e => setLeadId(e.target.value)}
                  />
                </div>
                {error && (
                  <p style={{ fontFamily: 'var(--font-mono)', fontSize: '0.7rem', color: 'var(--red)' }}>{error}</p>
                )}
                <button
                  type="submit"
                  disabled={starting || !leadPhone || !carrierPhone}
                  style={{
                    padding: '0.6rem 1.25rem',
                    background: 'var(--accent)',
                    color: 'oklch(15% 0.01 85)',
                    border: '1px solid var(--accent)',
                    borderRadius: 2,
                    fontFamily: 'var(--font-mono)',
                    fontSize: '0.8rem',
                    fontWeight: 600,
                    letterSpacing: '0.06em',
                    textTransform: 'uppercase',
                    cursor: starting ? 'not-allowed' : 'pointer',
                    opacity: starting ? 0.6 : 1,
                    marginTop: '0.25rem',
                  }}
                >
                  {starting ? 'STARTING...' : 'START CONFERENCE'}
                </button>
              </form>
            </section>
          ) : (
            <section className="section">
              <h2 className="section-title">Active Conference</h2>
              <div style={{ display: 'flex', gap: '1rem', flexWrap: 'wrap', marginBottom: '1rem' }}>
                {/* Participant cards */}
                {['seb', 'lead', 'carrier'].map(role => {
                  const p = confStatus?.participants?.[role]
                  const label = role === 'seb' ? 'Seb' : role === 'lead' ? 'Lead' : 'Carrier'
                  const phone = role === 'seb' ? confStatus?.seb_phone
                    : role === 'lead' ? confStatus?.lead_phone
                    : confStatus?.carrier_phone

                  return (
                    <div key={role} style={{
                      flex: '1 1 200px',
                      background: 'var(--surface)',
                      border: '1px solid var(--border)',
                      borderRadius: 2,
                      padding: '1rem',
                    }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginBottom: '0.5rem' }}>
                        <span style={{
                          width: 8, height: 8, borderRadius: '50%',
                          background: p?.status === 'in-progress' ? 'var(--green)' :
                            p?.status === 'ringing' ? 'var(--amber)' :
                            p?.status === 'completed' || p?.status === 'no-answer' ? 'var(--red)' :
                            'var(--text-muted)',
                          flexShrink: 0,
                        }} />
                        <span style={{ fontFamily: 'var(--font-display)', fontSize: '0.85rem', fontWeight: 600 }}>{label}</span>
                      </div>
                      <div style={{ fontFamily: 'var(--font-mono)', fontSize: '0.68rem', color: 'var(--text-muted)', marginBottom: '0.5rem' }}>
                        {formatPhone(phone) || 'Not dialed'}
                      </div>
                      <div style={{
                        fontFamily: 'var(--font-mono)', fontSize: '0.65rem',
                        color: p?.hold ? 'var(--amber)' : p?.muted ? 'var(--amber)' : p?.status === 'in-progress' ? 'var(--green)' : 'var(--text-muted)',
                        marginBottom: '0.75rem',
                      }}>
                        {participantStatusLabel(p)}
                      </div>

                      {/* Controls */}
                      <div style={{ display: 'flex', gap: '0.35rem', flexWrap: 'wrap' }}>
                        {p?.muted ? (
                          <ControlBtn label="Unmute" onClick={() => conferenceAction('unmute', role)} />
                        ) : (
                          <ControlBtn label="Mute" onClick={() => conferenceAction('mute', role)} />
                        )}
                        {p?.hold ? (
                          <ControlBtn label="Unhold" onClick={() => conferenceAction('unhold', role)} />
                        ) : (
                          <ControlBtn label="Hold" onClick={() => conferenceAction('hold', role)} />
                        )}
                      </div>

                      {/* Dial Carrier button */}
                      {role === 'carrier' && !p?.call_sid && (
                        <button
                          onClick={dialCarrier}
                          style={{
                            marginTop: '0.5rem',
                            padding: '0.35rem 0.7rem',
                            background: 'var(--green)',
                            color: 'oklch(15% 0.01 145)',
                            border: 'none',
                            borderRadius: 2,
                            fontFamily: 'var(--font-mono)',
                            fontSize: '0.65rem',
                            fontWeight: 600,
                            cursor: 'pointer',
                            textTransform: 'uppercase',
                            letterSpacing: '0.04em',
                          }}
                        >
                          Dial Carrier
                        </button>
                      )}
                    </div>
                  )
                })}
              </div>

              {/* Conference info bar */}
              <div style={{
                display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                background: 'var(--surface)', border: '1px solid var(--border)',
                borderRadius: 2, padding: '0.5rem 1rem', marginBottom: '0.75rem',
              }}>
                <div style={{ fontFamily: 'var(--font-mono)', fontSize: '0.65rem', color: 'var(--text-muted)' }}>
                  Status: <span style={{ color: confStatus?.status === 'active' ? 'var(--green)' : 'var(--text)' }}>{confStatus?.status || activeConf.status}</span>
                </div>
                <div style={{ fontFamily: 'var(--font-mono)', fontSize: '0.65rem', color: 'var(--text-muted)' }}>
                  {confStatus?.conference_sid ? `SID: ${confStatus.conference_sid.slice(0, 20)}...` : ''}
                </div>
              </div>

              <button
                onClick={endConference}
                style={{
                  padding: '0.5rem 1rem',
                  background: 'var(--red)',
                  color: 'var(--text)',
                  border: 'none',
                  borderRadius: 2,
                  fontFamily: 'var(--font-mono)',
                  fontSize: '0.75rem',
                  fontWeight: 600,
                  cursor: 'pointer',
                  textTransform: 'uppercase',
                  letterSpacing: '0.06em',
                }}
              >
                End Conference
              </button>
            </section>
          )}
        </>
      )}

      {/* ── Caller ID Verification Tab ── */}
      {tab === 'callerid' && (
        <section className="section">
          <h2 className="section-title">Caller ID Verification</h2>
          <p style={{ fontFamily: 'var(--font-mono)', fontSize: '0.7rem', color: 'var(--text-muted)', marginBottom: '1rem', lineHeight: 1.6 }}>
            Verify your Close numbers so FC can use them as caller ID when dialing. 
            Click Verify — Twilio calls the number and plays a 6-digit code. Enter the code when prompted.
          </p>

          {callerIdsLoading ? (
            <p className="loading-text">Loading numbers...</p>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
              {callerIds.map(n => (
                <div key={n.phone_number} style={{
                  display: 'flex', alignItems: 'center', gap: '0.75rem',
                  background: 'var(--surface)', border: '1px solid var(--border)',
                  borderRadius: 2, padding: '0.5rem 0.75rem',
                }}>
                  <span style={{
                    width: 8, height: 8, borderRadius: '50%',
                    background: n.verified ? 'var(--green)' : 'var(--red)',
                    flexShrink: 0,
                  }} />
                  <span style={{ fontFamily: 'var(--font-mono)', fontSize: '0.75rem', flex: 1 }}>
                    {formatPhone(n.phone_number)}
                  </span>
                  <span style={{
                    fontFamily: 'var(--font-mono)', fontSize: '0.6rem',
                    color: n.verified ? 'var(--green)' : 'var(--text-muted)',
                    textTransform: 'uppercase', letterSpacing: '0.04em',
                    minWidth: 70,
                  }}>
                    {n.verified ? 'Verified' : 'Unverified'}
                  </span>
                  {!n.verified && (
                    <button
                      onClick={() => initiateVerify(n.phone_number)}
                      disabled={verifying === n.phone_number}
                      style={{
                        padding: '0.25rem 0.5rem',
                        background: 'var(--accent)',
                        color: 'oklch(15% 0.01 85)',
                        border: 'none',
                        borderRadius: 2,
                        fontFamily: 'var(--font-mono)',
                        fontSize: '0.6rem',
                        fontWeight: 600,
                        cursor: 'pointer',
                        textTransform: 'uppercase',
                        letterSpacing: '0.04em',
                        opacity: verifying === n.phone_number ? 0.6 : 1,
                      }}
                    >
                      {verifying === n.phone_number ? 'Calling...' : 'Verify'}
                    </button>
                  )}
                </div>
              ))}
            </div>
          )}

          {/* Verification modal/message */}
          {verifying && verifyMsg && (
            <div style={{
              marginTop: '1rem', padding: '0.75rem',
              background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 2,
            }}>
              <p style={{ fontFamily: 'var(--font-mono)', fontSize: '0.7rem', color: 'var(--text)', marginBottom: '0.5rem' }}>
                {verifyMsg}
              </p>
              <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center' }}>
                <button
                  onClick={() => { setVerifying(null); setVerifyMsg(''); loadCallerIds() }}
                  style={{
                    padding: '0.3rem 0.6rem',
                    background: 'var(--surface-hover)',
                    color: 'var(--text-muted)',
                    border: '1px solid var(--border)',
                    borderRadius: 2,
                    fontFamily: 'var(--font-mono)',
                    fontSize: '0.65rem',
                    cursor: 'pointer',
                  }}
                >
                  Done / Refresh
                </button>
              </div>
            </div>
          )}
        </section>
      )}

      {/* ── Recent Sessions Tab ── */}
      {tab === 'history' && (
        <section className="section">
          <h2 className="section-title">Recent Conference Sessions</h2>
          {sessionsLoading ? (
            <p className="loading-text">Loading...</p>
          ) : sessions.length === 0 ? (
            <p style={{ fontFamily: 'var(--font-mono)', fontSize: '0.7rem', color: 'var(--text-muted)' }}>
              No conference sessions yet.
            </p>
          ) : (
            <div style={{ overflowX: 'auto' }}>
              <div style={{ display: 'flex', flexDirection: 'column', gap: '0.35rem' }}>
                {/* Header */}
                <div style={{
                  display: 'grid', gridTemplateColumns: '1fr 1fr 1fr 80px 120px 60px',
                  gap: '0.5rem', padding: '0.4rem 0.75rem',
                  fontFamily: 'var(--font-mono)', fontSize: '0.6rem',
                  color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.04em',
                  borderBottom: '1px solid var(--border)',
                }}>
                  <span>Lead</span>
                  <span>Carrier</span>
                  <span>Seb Number</span>
                  <span>Status</span>
                  <span>Date</span>
                  <span>Duration</span>
                </div>
                {sessions.map(s => (
                  <div key={s.conf_id} style={{
                    display: 'grid', gridTemplateColumns: '1fr 1fr 1fr 80px 120px 60px',
                    gap: '0.5rem', padding: '0.4rem 0.75rem',
                    background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 2,
                    fontFamily: 'var(--font-mono)', fontSize: '0.68rem',
                  }}>
                    <span>{formatPhone(s.lead_phone)}</span>
                    <span>{formatPhone(s.carrier_phone)}</span>
                    <span>{formatPhone(s.seb_phone)}</span>
                    <span style={{
                      color: s.status === 'active' ? 'var(--green)' : s.status === 'ended' ? 'var(--text-muted)' : 'var(--amber)',
                    }}>{s.status}</span>
                    <span style={{ color: 'var(--text-muted)', fontSize: '0.6rem' }}>
                      {s.started_at ? new Date(s.started_at).toLocaleString('en-US', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' }) : ''}
                    </span>
                    <span style={{ color: 'var(--text-muted)' }}>
                      {s.duration_seconds != null ? `${Math.floor(s.duration_seconds / 60)}m${s.duration_seconds % 60}s` : '-'}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </section>
      )}
    </div>
  )
}

function ControlBtn({ label, onClick }) {
  return (
    <button
      onClick={onClick}
      style={{
        padding: '0.2rem 0.45rem',
        background: 'var(--surface-hover)',
        color: 'var(--text-muted)',
        border: '1px solid var(--border)',
        borderRadius: 2,
        fontFamily: 'var(--font-mono)',
        fontSize: '0.6rem',
        cursor: 'pointer',
        textTransform: 'uppercase',
        letterSpacing: '0.03em',
      }}
    >
      {label}
    </button>
  )
}

export default CallManagement
