/*
 * Research Dashboard — API Endpoint Map
 * GET  /api/research/status              → Engine status + last cycle summary (PostgreSQL)
 * GET  /api/research/ads                 → Ad variants (PostgreSQL: research_ads table)
 * POST /api/research/ads/:id/approve     → Approve ad (PostgreSQL)
 * POST /api/research/ads/:id/reject      → Reject ad (PostgreSQL)
 * GET  /api/research/hypotheses          → Hypothesis log (PostgreSQL: research_hypotheses table)
 * GET  /api/research/cycles              → Cycle history (PostgreSQL: research_cycles table)
 * GET  /api/research/playbook            → Playbook markdown (local file)
 * GET  /api/research/dag/nodes           → DAG nodes (SQLite: falconleads.db)
 * GET  /api/research/dag/syntheses       → DAG cross-domain syntheses (SQLite)
 * GET  /api/research/dag/lineage/:id     → DAG lineage traversal (SQLite)
 * GET  /api/research/performance/split   → SAC vs NONSAC performance (SQLite)
 * POST /api/research/cycle/trigger       → Queue a cycle (PostgreSQL: research_triggers table)
 * POST /api/research/sync                → Push cycle results to PostgreSQL (loop auth)
 * GET  /api/research/triggers/pending    → Check for pending triggers (loop auth)
 * POST /api/research/triggers/:id/consume → Mark trigger consumed (loop auth)
 */
import React, { useState, useEffect, useCallback, useRef } from 'react'
import { useAuthSafe as useAuth } from '../hooks/useClerkSafe'

const fmtCurr = (v) => v == null || isNaN(v) ? '$0' : '$' + Number(v).toLocaleString('en-US', { maximumFractionDigits: 0 })
const fmtCpl = (v) => v == null || isNaN(v) ? '$0.00' : '$' + Number(v).toFixed(2)

function timeAgo(dateStr) {
  if (!dateStr) return '—'
  const diff = Math.floor((new Date() - new Date(dateStr)) / 1000)
  if (diff < 60) return 'just now'
  if (diff < 3600) return Math.floor(diff / 60) + 'm ago'
  if (diff < 86400) return Math.floor(diff / 3600) + 'h ago'
  const d = Math.floor(diff / 86400)
  return d === 1 ? '1 day ago' : d < 30 ? d + ' days ago' : Math.floor(d / 30) + 'mo ago'
}

const BC = {
  proposed:'rgba(59,130,246,0.15)', testing:'rgba(234,179,8,0.15)', winner:'rgba(34,197,94,0.15)',
  loser:'rgba(239,68,68,0.15)', inconclusive:'rgba(156,163,175,0.15)',
  sac:'rgba(34,197,94,0.15)', nonsac:'rgba(59,130,246,0.15)',
  observation:'rgba(168,85,247,0.15)', experiment:'rgba(234,179,8,0.15)', synthesis:'rgba(6,182,212,0.15)',
  ad_copy:'rgba(59,130,246,0.12)', landing_page:'rgba(168,85,247,0.12)', audience:'rgba(234,179,8,0.12)',
  format:'rgba(6,182,212,0.12)', close_rate:'rgba(34,197,94,0.12)', show_rate:'rgba(239,68,68,0.12)',
  cross_domain:'rgba(156,163,175,0.12)', hook_swap:'rgba(239,68,68,0.15)',
  emotional_frame_shift:'rgba(168,85,247,0.15)', specificity_change:'rgba(234,179,8,0.15)',
  question_vs_statement:'rgba(59,130,246,0.15)', length_variant:'rgba(6,182,212,0.15)',
}
const TC = {
  proposed:'#3b82f6', testing:'#eab308', winner:'#22c55e', loser:'#ef4444', inconclusive:'#9ca3af',
  sac:'#22c55e', nonsac:'#3b82f6', observation:'#a855f7', experiment:'#eab308', synthesis:'#06b6d4',
  ad_copy:'#3b82f6', landing_page:'#a855f7', audience:'#eab308', format:'#06b6d4',
  close_rate:'#22c55e', show_rate:'#ef4444', cross_domain:'#9ca3af',
  hook_swap:'#ef4444', emotional_frame_shift:'#a855f7', specificity_change:'#eab308',
  question_vs_statement:'#3b82f6', length_variant:'#06b6d4',
}

function Badge({ label, colorKey }) {
  const k = colorKey || (label || '').toLowerCase()
  return (
    <span style={{
      fontFamily: 'var(--font-mono)', fontSize: '0.52rem', fontWeight: 600,
      letterSpacing: '0.06em', padding: '0.1rem 0.35rem', borderRadius: 2,
      background: BC[k] || 'rgba(156,163,175,0.15)', color: TC[k] || '#9ca3af',
      textTransform: 'uppercase', whiteSpace: 'nowrap',
    }}>
      {(label || '').replace(/_/g, ' ')}
    </span>
  )
}

function Csec({ id, title, badge, open: initOpen, sRef, children }) {
  const [open, setOpen] = useState(initOpen !== false)
  return (
    <section className="section" ref={sRef} id={id}>
      <div className="section-header-row" style={{ cursor: 'pointer', userSelect: 'none' }}
        onClick={() => setOpen(o => !o)}>
        <h2 className="section-title" style={{
          marginBottom: 0, paddingBottom: 0, borderBottom: 'none',
          display: 'flex', alignItems: 'center', gap: '0.5rem'
        }}>
          <span style={{
            fontFamily: 'var(--font-mono)', fontSize: '0.6rem', color: 'var(--text-muted)',
            transition: 'transform 0.15s', transform: open ? 'rotate(90deg)' : 'rotate(0deg)',
            display: 'inline-block'
          }}>&#9654;</span>
          {title}
          {badge != null && (
            <span style={{
              fontFamily: 'var(--font-mono)', fontSize: '0.56rem', fontWeight: 600,
              background: 'rgba(239,68,68,0.2)', color: '#ef4444',
              padding: '0.05rem 0.35rem', borderRadius: 2, marginLeft: '0.25rem'
            }}>{badge}</span>
          )}
        </h2>
      </div>
      {open && <div style={{ marginTop: '0.75rem' }}>{children}</div>}
    </section>
  )
}

function Ftabs({ tabs, active, onChange }) {
  return (
    <div style={{ display: 'flex', gap: '0.25rem', flexWrap: 'wrap', marginBottom: '0.75rem' }}>
      {tabs.map(t => (
        <button key={t} onClick={() => onChange(t)} style={{
          fontFamily: 'var(--font-mono)', fontSize: '0.56rem', fontWeight: 600,
          letterSpacing: '0.06em', padding: '0.2rem 0.5rem', borderRadius: 2,
          border: '1px solid var(--border)', cursor: 'pointer',
          background: active === t ? 'var(--accent)' : 'var(--surface)',
          color: active === t ? 'oklch(15% 0.01 85)' : 'var(--text-muted)',
          textTransform: 'uppercase',
        }}>{t.replace(/_/g, ' ')}</button>
      ))}
    </div>
  )
}

function Cbar({ value }) {
  const p = Math.min(Math.max((value || 0) * 100, 0), 100)
  return (
    <div style={{ width: 60, height: 4, background: 'var(--border)', borderRadius: 2, overflow: 'hidden' }}>
      <div style={{
        width: p + '%', height: '100%', borderRadius: 2,
        background: p > 60 ? '#22c55e' : p > 30 ? '#eab308' : '#ef4444',
      }} />
    </div>
  )
}

function CycleProgressBar({ cycleRunning, cycleStartTime, cycleComplete }) {
  const [elapsed, setElapsed] = useState(0)
  const CYCLE_DURATION_MS = 15 * 60 * 1000

  useEffect(() => {
    if (!cycleRunning || !cycleStartTime) return
    const tick = setInterval(() => {
      setElapsed(Date.now() - cycleStartTime)
    }, 1000)
    return () => clearInterval(tick)
  }, [cycleRunning, cycleStartTime])

  if (!cycleRunning) return null

  const progress = cycleComplete ? 100 : Math.min(95, (elapsed / CYCLE_DURATION_MS) * 95)
  const elapsedSec = Math.floor(elapsed / 1000)
  const minutes = Math.floor(elapsedSec / 60)
  const seconds = elapsedSec % 60
  const timeStr = String(minutes).padStart(2, '0') + ':' + String(seconds).padStart(2, '0')
  const stalled = !cycleComplete && elapsed >= CYCLE_DURATION_MS

  const cycleLabel = cycleStartTime
    ? new Date(cycleStartTime).toLocaleDateString('en-US', { year: 'numeric', month: '2-digit', day: '2-digit' }).replace(/\//g, '-')
      + '_' + String(new Date(cycleStartTime).getHours()).padStart(2, '0') + String(new Date(cycleStartTime).getMinutes()).padStart(2, '0')
    : ''

  const statusText = cycleComplete
    ? '✓ CYCLE COMPLETE — Approval Queue updated'
    : stalled
      ? 'STILL RUNNING...'
      : 'CYCLE RUNNING — ' + cycleLabel

  return (
    <div style={{
      background: 'var(--surface)',
      border: '1px solid var(--border)',
      borderLeft: cycleComplete ? '3px solid #22c55e' : '3px solid var(--accent)',
      borderRadius: 4,
      padding: '0.6rem 0.85rem',
      marginBottom: '0.75rem',
      transition: 'all 0.3s ease',
    }}>
      <div style={{
        display: 'flex', justifyContent: 'space-between', alignItems: 'center',
        marginBottom: '0.4rem',
      }}>
        <span style={{
          fontFamily: 'var(--font-mono)', fontSize: '0.56rem', fontWeight: 600,
          letterSpacing: '0.06em', textTransform: 'uppercase',
          color: cycleComplete ? '#22c55e' : 'var(--text-muted)',
        }}>
          {statusText}
        </span>
        {!cycleComplete && (
          <span style={{
            fontFamily: 'var(--font-mono)', fontSize: '0.52rem',
            color: 'var(--text-muted)',
          }}>
            {timeStr} / 15:00
          </span>
        )}
      </div>
      <div style={{
        width: '100%', height: 6, background: 'var(--border)',
        borderRadius: 3, overflow: 'hidden',
      }}>
        <div style={{
          width: progress + '%', height: '100%', borderRadius: 3,
          background: cycleComplete ? '#22c55e' : 'var(--accent)',
          transition: cycleComplete ? 'width 0.5s ease' : 'width 1s linear',
        }} />
      </div>
      <div style={{
        display: 'flex', justifyContent: 'flex-end', marginTop: '0.2rem',
      }}>
        <span style={{
          fontFamily: 'var(--font-mono)', fontSize: '0.48rem',
          color: 'var(--text-muted)',
        }}>
          {cycleComplete ? '100' : Math.round(progress)}%
        </span>
      </div>
    </div>
  )
}

function Research({ onNavigate }) {
  const { getToken } = useAuth()
  const [err, setErr] = useState(null)
  const [st, setSt] = useState(null)
  const [pend, setPend] = useState([])
  const [hypos, setHypos] = useState([])
  const [pb, setPb] = useState(null)
  const [dagN, setDagN] = useState([])
  const [dagS, setDagS] = useState([])
  const [spl, setSpl] = useState(null)
  const [cyc, setCyc] = useState([])
  const [hf, setHf] = useState('all')
  const [dd, setDd] = useState('all')
  const [dt2, setDt2] = useState('all')
  const [exH, setExH] = useState(null)
  const [exN, setExN] = useState(null)
  const [exC, setExC] = useState(null)
  const [lin, setLin] = useState({})
  const [loading, setLoading] = useState(true)
  const [tmsg, setTmsg] = useState(null)
  const [al, setAl] = useState({})
  const [cycleRunning, setCycleRunning] = useState(false)
  const [cycleStartTime, setCycleStartTime] = useState(null)
  const [cycleComplete, setCycleComplete] = useState(false)
  const preTriggerCycleIds = useRef(new Set())
  const rr = {
    approvals: useRef(null), hypotheses: useRef(null), playbook: useRef(null),
    dag: useRef(null), split: useRef(null), cycles: useRef(null),
  }

  const af = useCallback(async (url, opts = {}) => {
    const token = await getToken()
    const res = await fetch(url, {
      ...opts,
      headers: { 'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json', ...opts.headers },
    })
    if (!res.ok) { const b = await res.json().catch(() => ({})); throw new Error(b.detail || 'HTTP ' + res.status) }
    return res.json()
  }, [getToken])

  const fetchAll = useCallback(async () => {
    setLoading(true); setErr(null)
    try {
      const [a, b, c, d, e, f, g, h] = await Promise.all([
        af('/api/research/status'), af('/api/research/ads?status=pending_approval'),
        af('/api/research/hypotheses?limit=100'), af('/api/research/playbook'),
        af('/api/research/dag/nodes?limit=100'), af('/api/research/dag/syntheses?limit=10'),
        af('/api/research/performance/split'), af('/api/research/cycles?limit=5'),
      ])
      setSt(a); setPend(Array.isArray(b) ? b : b.pending || []); setHypos(c.hypotheses || []); setPb(d)
      setDagN(e.nodes || []); setDagS(f.syntheses || []); setSpl(g); setCyc(h.cycles || [])
    } catch (e) { setErr(e.message) } finally { setLoading(false) }
  }, [af])

  useEffect(() => { fetchAll() }, [fetchAll])

  useEffect(() => {
    if (loading) return
    const p = new URLSearchParams(window.location.search)
    const sec = p.get('section'), hid = p.get('hypothesis'), nid = p.get('node')
    if (sec && rr[sec]?.current) rr[sec].current.scrollIntoView({ behavior: 'smooth', block: 'start' })
    if (hid) { setExH(parseInt(hid)); rr.hypotheses.current?.scrollIntoView({ behavior: 'smooth', block: 'start' }) }
    if (nid) { setExN(nid); rr.dag.current?.scrollIntoView({ behavior: 'smooth', block: 'start' }) }
  }, [loading])

  const fH = hf === 'all' ? hypos : hypos.filter(h => h.status === hf)
  const fD = dagN.filter(n => (dd === 'all' || n.domain === dd) && (dt2 === 'all' || n.type === dt2))

  const trigger = async () => {
    try {
      // Capture current cycle IDs before triggering
      const currentCycles = await af('/api/research/cycles?limit=20')
      const ids = new Set((currentCycles.cycles || []).map(c => c.cycle_id))
      preTriggerCycleIds.current = ids

      await af('/api/research/cycle/trigger', { method: 'POST' })
      setTmsg('Cycle queued.')
      setTimeout(() => setTmsg(null), 4000)

      // Start progress bar
      setCycleRunning(true)
      setCycleStartTime(Date.now())
      setCycleComplete(false)
    }
    catch (e) { setErr(e.message) }
  }

  // Polling for new cycle completion
  useEffect(() => {
    if (!cycleRunning || cycleComplete) return
    const poll = setInterval(async () => {
      try {
        const data = await af('/api/research/cycles?limit=20')
        const newCycles = (data.cycles || []).filter(c => !preTriggerCycleIds.current.has(c.cycle_id))
        if (newCycles.length > 0) {
          setCycleComplete(true)
          // Refresh all data
          fetchAll()
          // Hide bar after 3 seconds
          setTimeout(() => {
            setCycleRunning(false)
            setCycleComplete(false)
            setCycleStartTime(null)
          }, 3000)
        }
      } catch (e) { /* silent polling failure */ }
    }, 10000)
    return () => clearInterval(poll)
  }, [cycleRunning, cycleComplete, af, fetchAll])
  const approve = async id => {
    setAl(p => ({ ...p, ['a' + id]: true }))
    try { await af('/api/research/ads/' + id + '/approve', { method: 'POST' }); setPend(p => p.filter(x => x.id !== id)) }
    catch (e) { setErr(e.message) } finally { setAl(p => ({ ...p, ['a' + id]: false })) }
  }
  const reject = async id => {
    setAl(p => ({ ...p, ['r' + id]: true }))
    try { await af('/api/research/ads/' + id + '/reject', { method: 'POST' }); setPend(p => p.filter(x => x.id !== id)) }
    catch (e) { setErr(e.message) } finally { setAl(p => ({ ...p, ['r' + id]: false })) }
  }
  const fLin = async nid => {
    if (lin[nid]) return
    try { const d = await af('/api/research/dag/lineage/' + nid); setLin(p => ({ ...p, [nid]: d.lineage || [] })) }
    catch (e) { /* silent */ }
  }

  const cs = { background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 4, padding: '0.75rem 1rem' }
  const ths = { fontFamily: 'var(--font-mono)', fontSize: '0.54rem', fontWeight: 600, color: 'var(--text-muted)', letterSpacing: '0.06em', textTransform: 'uppercase', padding: '0.4rem 0.5rem', textAlign: 'left', borderBottom: '1px solid var(--border)' }
  const tds = { fontFamily: 'var(--font-mono)', fontSize: '0.64rem', color: 'var(--text)', padding: '0.4rem 0.5rem', borderBottom: '1px solid var(--border)' }
  const sbs = { display: 'inline-flex', alignItems: 'center', gap: '0.2rem', padding: '0.2rem 0.5rem', background: 'none', border: '1px solid var(--border)', borderRadius: 3, fontFamily: 'var(--font-mono)', fontSize: '0.56rem', color: 'var(--text-muted)', cursor: 'pointer', letterSpacing: '0.04em', touchAction: 'manipulation' }

  if (loading) return (
    <div className="dashboard"><section className="section">
      <span style={{ fontFamily: 'var(--font-mono)', fontSize: '0.72rem', color: 'var(--text-muted)' }}>Loading Research Engine...</span>
    </section></div>
  )

  return (
    <div className="dashboard">
      {err && (
        <div className="alert alert-error" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.75rem' }}>
          <span>{err}</span>
          <button onClick={() => setErr(null)} style={{ background: 'none', border: 'none', color: 'inherit', cursor: 'pointer', fontFamily: 'var(--font-mono)', fontSize: '0.72rem' }}>x</button>
        </div>
      )}

      {/* CYCLE PROGRESS BAR */}
      <CycleProgressBar cycleRunning={cycleRunning} cycleStartTime={cycleStartTime} cycleComplete={cycleComplete} />

      {/* A. STATUS BAR */}
      <section className="section">
        <div className="section-header-row">
          <h2 className="section-title" style={{ marginBottom: 0, paddingBottom: 0, borderBottom: 'none' }}>Research Engine</h2>
          <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center' }}>
            <button className="btn btn-sm" onClick={fetchAll}>Refresh</button>
            <button className="btn btn-sm btn-primary" onClick={trigger} style={{ marginTop: 0 }}>Trigger Cycle</button>
          </div>
        </div>
        {tmsg && <div style={{ marginTop: '0.5rem', fontFamily: 'var(--font-mono)', fontSize: '0.62rem', color: '#22c55e' }}>{tmsg}</div>}
        <div className="stat-row" style={{ marginTop: '0.75rem' }}>
          <div className="stat-box">
            <span className="stat-label">Last Cycle</span>
            <span className="stat-value" style={{ fontSize: '0.85rem' }}>
              {st?.last_cycle_id || '—'}
              <span style={{ fontFamily: 'var(--font-mono)', fontSize: '0.52rem', color: 'var(--text-muted)', marginLeft: '0.35rem' }}>{timeAgo(st?.last_run)}</span>
            </span>
          </div>
          <div className="stat-box"><span className="stat-label">Next Run</span><span className="stat-value" style={{ fontSize: '0.85rem' }}>{st?.next_run ? new Date(st.next_run).toLocaleDateString('en-US', { weekday: 'short', month: 'short', day: 'numeric' }) : '—'}</span></div>
          <div className="stat-box"><span className="stat-label">Total Cycles</span><span className="stat-value">{st?.cycles_total || 0}</span></div>
          <div className="stat-box"><span className="stat-label">Hypotheses</span><span className="stat-value">{st?.hypotheses_total || 0}</span></div>
          <div className="stat-box"><span className="stat-label">Winners</span><span className="stat-value" style={{ color: 'var(--green)' }}>{st?.winners_total || 0}</span></div>
        </div>
      </section>

      {/* B. APPROVAL QUEUE */}
      <Csec id="approvals" title="Pending Approval" badge={pend.length > 0 ? pend.length : null} open={true} sRef={rr.approvals}>
        {pend.length === 0 ? (
          <p style={{ fontFamily: 'var(--font-mono)', fontSize: '0.68rem', color: 'var(--text-muted)', padding: '1rem 0' }}>
            No pending approvals. The engine is running clean.
          </p>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
            {pend.map(ad => (
              <div key={ad.id} style={{ ...cs, transition: 'opacity 0.3s', opacity: al['a' + ad.id] || al['r' + ad.id] ? 0.4 : 1 }}>
                <div style={{ display: 'flex', gap: '0.4rem', alignItems: 'center', marginBottom: '0.5rem', flexWrap: 'wrap' }}>
                  {ad.angle && <Badge label={ad.angle} />}
                  {ad.variant && <Badge label={'V' + ad.variant} />}
                  <Badge label={ad.account_type || 'sac'} colorKey={ad.account_type || 'sac'} />
                </div>
                <p style={{ fontFamily: 'var(--font-mono)', fontSize: '0.68rem', color: 'var(--text)', margin: '0 0 0.35rem', lineHeight: 1.5 }}>{ad.ad_copy ? (ad.ad_copy.length > 140 ? ad.ad_copy.slice(0, 140) + '…' : ad.ad_copy) : '(no copy)'}</p>
                {ad.headline && <p style={{ fontFamily: 'var(--font-mono)', fontSize: '0.62rem', color: 'var(--text)', fontWeight: 600, margin: '0 0 0.15rem' }}>{ad.headline}</p>}
                {ad.description && <p style={{ fontFamily: 'var(--font-mono)', fontSize: '0.58rem', color: 'var(--text-muted)', margin: '0 0 0.5rem' }}>{ad.description}</p>}
                <div style={{ display: 'flex', gap: '0.4rem' }}>
                  <button style={{ ...sbs, background: 'rgba(34,197,94,0.15)', borderColor: '#22c55e', color: '#22c55e' }} onClick={() => approve(ad.id)} disabled={al['a' + ad.id]}>{al['a' + ad.id] ? '...' : 'APPROVE'}</button>
                  <button style={{ ...sbs, background: 'rgba(239,68,68,0.08)' }} onClick={() => reject(ad.id)} disabled={al['r' + ad.id]}>{al['r' + ad.id] ? '...' : 'REJECT'}</button>
                </div>
              </div>
            ))}
          </div>
        )}
      </Csec>

      {/* C. HYPOTHESIS LOG */}
      <Csec id="hypotheses" title="Hypothesis Log" sRef={rr.hypotheses}>
        <Ftabs tabs={['all', 'proposed', 'testing', 'winner', 'loser', 'inconclusive']} active={hf} onChange={setHf} />
        {fH.length === 0 ? (
          <p style={{ fontFamily: 'var(--font-mono)', fontSize: '0.68rem', color: 'var(--text-muted)' }}>No hypotheses{hf !== 'all' ? ' with status "' + hf + '"' : ''}.</p>
        ) : (
          <div style={{ overflowX: 'auto' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse' }}>
              <thead><tr>
                <th style={ths}>Hypothesis</th><th style={ths}>Account</th><th style={ths}>Status</th>
                <th style={ths}>Confidence</th><th style={ths}>Cycle</th><th style={ths}>Created</th>
              </tr></thead>
              <tbody>
                {fH.map(h => {
                  const ex = exH === h.id
                  const bg = h.status === 'winner' ? 'rgba(34,197,94,0.06)' : h.status === 'loser' ? 'rgba(239,68,68,0.06)' : 'transparent'
                  const hText = h.hypothesis_text || ''
                  return (
                    <React.Fragment key={h.id}>
                      <tr style={{ cursor: 'pointer', background: bg }} onClick={() => setExH(ex ? null : h.id)}>
                        <td style={{ ...tds, maxWidth: 280, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                          {hText.slice(0, 80)}{hText.length > 80 ? '...' : ''}
                        </td>
                        <td style={tds}>{h.account_type ? <Badge label={h.account_type} colorKey={h.account_type} /> : '—'}</td>
                        <td style={tds}><Badge label={h.status} /></td>
                        <td style={tds}><Cbar value={h.confidence} /></td>
                        <td style={tds}><span style={{ fontFamily: 'var(--font-mono)', fontSize: '0.52rem', color: 'var(--text-muted)' }}>{h.cycle_id || '—'}</span></td>
                        <td style={tds}><span style={{ fontFamily: 'var(--font-mono)', fontSize: '0.52rem', color: 'var(--text-muted)' }}>{timeAgo(h.created_at)}</span></td>
                      </tr>
                      {ex && (
                        <tr><td colSpan={6} style={{ padding: '0.75rem', background: 'var(--bg)', borderBottom: '1px solid var(--border)' }}>
                          <p style={{ fontFamily: 'var(--font-mono)', fontSize: '0.68rem', color: 'var(--text)', margin: '0 0 0.5rem', lineHeight: 1.5 }}>{hText}</p>
                          <div style={{ display: 'flex', gap: '1rem', fontFamily: 'var(--font-mono)', fontSize: '0.58rem', color: 'var(--text-muted)' }}>
                            {h.cycle_id && <span>Cycle: {h.cycle_id}</span>}
                            {h.created_at && <span>Created: {new Date(h.created_at).toLocaleDateString()}</span>}
                            {h.confidence != null && <span>Confidence: {(h.confidence * 100).toFixed(0)}%</span>}
                          </div>
                        </td></tr>
                      )}
                    </React.Fragment>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
      </Csec>

      {/* D. PLAYBOOK */}
      <Csec id="playbook" title="Playbook" sRef={rr.playbook}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.75rem', flexWrap: 'wrap', gap: '0.5rem' }}>
          <span style={{ fontFamily: 'var(--font-display)', fontSize: '0.78rem', fontWeight: 600, letterSpacing: '0.06em', color: 'var(--text)' }}>FALCON FINANCIAL AD PLAYBOOK</span>
          <div style={{ display: 'flex', gap: '0.75rem', alignItems: 'center' }}>
            {pb?.last_updated && <span style={{ fontFamily: 'var(--font-mono)', fontSize: '0.52rem', color: 'var(--text-muted)' }}>Updated: {timeAgo(pb.last_updated)}</span>}
            {pb?.rules_count > 0 && <span style={{ fontFamily: 'var(--font-mono)', fontSize: '0.52rem', fontWeight: 600, background: 'rgba(34,197,94,0.15)', color: '#22c55e', padding: '0.08rem 0.35rem', borderRadius: 2 }}>{pb.rules_count} RULES</span>}
          </div>
        </div>
        {(!pb?.content || pb.rules_count === 0) ? (
          <p style={{ fontFamily: 'var(--font-mono)', fontSize: '0.68rem', color: 'var(--text-muted)', padding: '1rem 0' }}>
            No rules generated yet. Run the first cycle to begin building the playbook.
          </p>
        ) : (() => {
          const lines = pb.content.split('\n')
          const els = []
          for (let i = 0; i < lines.length; i++) {
            const t = lines[i].trim()
            if (t.startsWith('RULE:')) {
              const rule = t.substring(5).trim()
              let ev = '', cp = ''
              if (i + 1 < lines.length && lines[i + 1].trim().startsWith('EVIDENCE:')) { ev = lines[i + 1].trim().substring(9).trim(); i++ }
              if (i + 1 < lines.length && lines[i + 1].trim().startsWith('CPL IMPACT:')) { cp = lines[i + 1].trim().substring(11).trim(); i++ }
              els.push(
                <div key={'r' + i} style={{ borderLeft: '3px solid var(--accent)', marginBottom: '0.75rem', background: 'rgba(255,255,255,0.02)', padding: '0.5rem 0.75rem' }}>
                  <p style={{ fontFamily: 'var(--font-mono)', fontSize: '0.68rem', color: 'var(--text)', fontWeight: 600, margin: '0 0 0.25rem' }}>{rule}</p>
                  {ev && <p style={{ fontFamily: 'var(--font-mono)', fontSize: '0.58rem', color: 'var(--text-muted)', margin: '0 0 0.15rem' }}>{ev}</p>}
                  {cp && <span style={{ fontFamily: 'var(--font-mono)', fontSize: '0.52rem', fontWeight: 600, background: 'rgba(34,197,94,0.15)', color: '#22c55e', padding: '0.08rem 0.35rem', borderRadius: 2 }}>CPL: {cp}</span>}
                </div>
              )
            } else if (t.startsWith('## ')) {
              els.push(<h3 key={'h' + i} style={{ fontFamily: 'var(--font-mono)', fontSize: '0.68rem', fontWeight: 600, color: 'var(--accent)', margin: '1rem 0 0.5rem' }}>{t.substring(3)}</h3>)
            } else if (!t.startsWith('# ') && !t.startsWith('---') && !t.startsWith('EVIDENCE:') && !t.startsWith('CPL IMPACT:') && t.length > 0) {
              els.push(<p key={'p' + i} style={{ fontFamily: 'var(--font-mono)', fontSize: '0.62rem', color: 'var(--text-muted)', margin: '0.15rem 0' }}>{t}</p>)
            }
          }
          return <div>{els}</div>
        })()}
      </Csec>

      {/* E. RESEARCH DAG */}
      <Csec id="dag" title="Research DAG" sRef={rr.dag}>
        <Ftabs tabs={['all', 'ad_copy', 'landing_page', 'audience', 'format', 'close_rate', 'show_rate', 'cross_domain']} active={dd} onChange={setDd} />
        <Ftabs tabs={['all', 'observation', 'experiment', 'winner', 'loser', 'synthesis']} active={dt2} onChange={setDt2} />

        {dagS.length > 0 && (dt2 === 'all' || dt2 === 'synthesis') && (
          <div style={{ marginBottom: '0.75rem' }}>
            {dagS.map(s => (
              <div key={s.id} style={{ ...cs, borderLeft: '3px solid #06b6d4', marginBottom: '0.5rem' }}>
                <div style={{ display: 'flex', gap: '0.4rem', marginBottom: '0.35rem' }}>
                  <Badge label="synthesis" colorKey="synthesis" />
                  {s.cycle_id && <span style={{ fontFamily: 'var(--font-mono)', fontSize: '0.5rem', color: 'var(--text-muted)' }}>Cycle: {s.cycle_id}</span>}
                </div>
                <p style={{ fontFamily: 'var(--font-mono)', fontSize: '0.64rem', color: 'var(--text)', lineHeight: 1.5, margin: 0 }}>{s.synthesis_text}</p>
              </div>
            ))}
          </div>
        )}

        {fD.length === 0 ? (
          <p style={{ fontFamily: 'var(--font-mono)', fontSize: '0.68rem', color: 'var(--text-muted)' }}>No DAG nodes found.</p>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 0 }}>
            {fD.map(n => {
              const ex = exN === n.id
              return (
                <React.Fragment key={n.id}>
                  <div style={{
                    display: 'flex', alignItems: 'center', gap: '0.5rem', padding: '0.4rem 0.5rem',
                    background: ex ? 'var(--bg)' : 'transparent', borderBottom: '1px solid var(--border)',
                    cursor: 'pointer', flexWrap: 'wrap',
                  }} onClick={() => { setExN(ex ? null : n.id); if (!ex) fLin(n.id) }}>
                    <Badge label={n.type} />
                    <Badge label={n.domain} />
                    <span style={{ fontFamily: 'var(--font-mono)', fontSize: '0.62rem', color: 'var(--text)', flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                      {(n.content || '').slice(0, 100)}
                    </span>
                    {n.metric_value != null && (
                      <span style={{ fontFamily: 'var(--font-mono)', fontSize: '0.52rem', color: '#22c55e', fontWeight: 600 }}>
                        {n.metric_name}={Number(n.metric_value).toFixed(2)}
                      </span>
                    )}
                    <span style={{ fontFamily: 'var(--font-mono)', fontSize: '0.48rem', color: 'var(--text-muted)' }}>{timeAgo(n.created_at)}</span>
                  </div>
                  {ex && (
                    <div style={{ padding: '0.75rem', background: 'var(--bg)', borderBottom: '1px solid var(--border)' }}>
                      <p style={{ fontFamily: 'var(--font-mono)', fontSize: '0.68rem', color: 'var(--text)', margin: '0 0 0.5rem', lineHeight: 1.5 }}>{n.content}</p>
                      <div style={{ display: 'flex', gap: '1rem', fontFamily: 'var(--font-mono)', fontSize: '0.56rem', color: 'var(--text-muted)', marginBottom: '0.5rem' }}>
                        {n.metric_value != null && <span>{n.metric_name}: {Number(n.metric_value).toFixed(2)}</span>}
                        {n.cycle_id && <span>Cycle: {n.cycle_id}</span>}
                      </div>
                      {lin[n.id] && lin[n.id].length > 1 && (
                        <div style={{ display: 'flex', alignItems: 'center', gap: '0.35rem', flexWrap: 'wrap' }}>
                          <span style={{ fontFamily: 'var(--font-mono)', fontSize: '0.52rem', color: 'var(--text-muted)' }}>Lineage:</span>
                          {[...lin[n.id]].reverse().map((a, i) => (
                            <React.Fragment key={a.id}>
                              {i > 0 && <span style={{ fontFamily: 'var(--font-mono)', fontSize: '0.48rem', color: 'var(--text-muted)' }}>&rarr;</span>}
                              <span style={{ fontFamily: 'var(--font-mono)', fontSize: '0.52rem', color: a.id === n.id ? 'var(--accent)' : 'var(--text)', fontWeight: a.id === n.id ? 600 : 400 }}>
                                {(a.content || '').slice(0, 40)}...
                              </span>
                            </React.Fragment>
                          ))}
                        </div>
                      )}
                    </div>
                  )}
                </React.Fragment>
              )
            })}
          </div>
        )}
      </Csec>

      {/* F. SAC vs NONSAC SPLIT */}
      <Csec id="split" title="SAC vs NONSAC Split" sRef={rr.split}>
        {!spl ? (
          <p style={{ fontFamily: 'var(--font-mono)', fontSize: '0.68rem', color: 'var(--text-muted)' }}>No performance data available.</p>
        ) : (() => {
          const sacCpl = spl.sac?.avg_cpl || 0
          const nonCpl = spl.nonsac?.avg_cpl || 0
          const maxCpl = Math.max(sacCpl, nonCpl, 1)
          return (
            <div>
              <div style={{ display: 'flex', gap: '1rem', flexWrap: 'wrap', marginBottom: '1rem' }}>
                {['sac', 'nonsac'].map(type => {
                  const d = spl[type] || {}
                  return (
                    <div key={type} style={{ flex: 1, minWidth: 200, ...cs }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '0.4rem', marginBottom: '0.5rem' }}>
                        <Badge label={type} colorKey={type} />
                        <span style={{ fontFamily: 'var(--font-mono)', fontSize: '0.6rem', color: 'var(--text-muted)' }}>
                          {type === 'sac' ? 'Special Ad Category' : 'Standard Account'}
                        </span>
                      </div>
                      <div className="stat-row">
                        <div className="stat-box"><span className="stat-label">Spend</span><span className="stat-value" style={{ fontSize: '0.9rem' }}>{fmtCurr(d.total_spend)}</span></div>
                        <div className="stat-box"><span className="stat-label">Leads</span><span className="stat-value" style={{ fontSize: '0.9rem', color: 'var(--green)' }}>{d.total_leads || 0}</span></div>
                        <div className="stat-box"><span className="stat-label">Avg CPL</span><span className="stat-value" style={{ fontSize: '0.9rem', color: d.avg_cpl > 30 ? '#ef4444' : d.avg_cpl > 0 ? '#22c55e' : 'var(--text)' }}>{fmtCpl(d.avg_cpl)}</span></div>
                      </div>
                      <div style={{ display: 'flex', gap: '1rem', marginTop: '0.5rem', fontFamily: 'var(--font-mono)', fontSize: '0.56rem', color: 'var(--text-muted)' }}>
                        <span>Active: {d.active_ads || 0}</span>
                        <span>Top: {d.top_angle || '—'}</span>
                      </div>
                    </div>
                  )
                })}
              </div>
              <div style={{ marginTop: '0.5rem' }}>
                <div style={{ fontFamily: 'var(--font-mono)', fontSize: '0.52rem', color: 'var(--text-muted)', marginBottom: '0.35rem' }}>CPL COMPARISON</div>
                <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginBottom: '0.25rem' }}>
                  <span style={{ fontFamily: 'var(--font-mono)', fontSize: '0.52rem', color: '#22c55e', width: 45 }}>SAC</span>
                  <div style={{ flex: 1, height: 8, background: 'var(--border)', borderRadius: 2, overflow: 'hidden' }}>
                    <div style={{ width: (sacCpl / maxCpl * 100) + '%', height: '100%', background: '#22c55e', borderRadius: 2 }} />
                  </div>
                  <span style={{ fontFamily: 'var(--font-mono)', fontSize: '0.52rem', color: 'var(--text)', width: 50, textAlign: 'right' }}>{fmtCpl(sacCpl)}</span>
                </div>
                <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                  <span style={{ fontFamily: 'var(--font-mono)', fontSize: '0.52rem', color: '#3b82f6', width: 45 }}>NONSAC</span>
                  <div style={{ flex: 1, height: 8, background: 'var(--border)', borderRadius: 2, overflow: 'hidden' }}>
                    <div style={{ width: (nonCpl / maxCpl * 100) + '%', height: '100%', background: '#3b82f6', borderRadius: 2 }} />
                  </div>
                  <span style={{ fontFamily: 'var(--font-mono)', fontSize: '0.52rem', color: 'var(--text)', width: 50, textAlign: 'right' }}>{fmtCpl(nonCpl)}</span>
                </div>
              </div>
            </div>
          )
        })()}
      </Csec>

      {/* G. RECENT CYCLES */}
      <Csec id="cycles" title="Recent Cycles" sRef={rr.cycles}>
        {cyc.length === 0 ? (
          <p style={{ fontFamily: 'var(--font-mono)', fontSize: '0.68rem', color: 'var(--text-muted)' }}>No research cycles run yet.</p>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 0 }}>
            {cyc.map(c => {
              const ex = exC === c.cycle_id
              return (
                <React.Fragment key={c.cycle_id}>
                  <div style={{
                    display: 'flex', alignItems: 'center', gap: '0.75rem', padding: '0.5rem 0.5rem',
                    borderBottom: '1px solid var(--border)', cursor: 'pointer',
                    background: ex ? 'var(--bg)' : 'transparent',
                  }} onClick={() => setExC(ex ? null : c.cycle_id)}>
                    <span style={{ fontFamily: 'var(--font-mono)', fontSize: '0.68rem', fontWeight: 600, color: 'var(--text)' }}>{c.cycle_id}</span>
                    <span style={{ fontFamily: 'var(--font-mono)', fontSize: '0.52rem', color: 'var(--text-muted)' }}>{timeAgo(c.created_at)}</span>
                    <span style={{ fontFamily: 'var(--font-mono)', fontSize: '0.52rem', color: 'var(--text-muted)' }}>{c.ads_generated} ads</span>
                    <span style={{ fontFamily: 'var(--font-mono)', fontSize: '0.52rem', color: 'var(--text-muted)' }}>{c.hypotheses_formed} hypotheses</span>
                  </div>
                  {ex && c.log && (
                    <div style={{ padding: '0.75rem', background: 'var(--bg)', borderBottom: '1px solid var(--border)' }}>
                      <pre style={{ fontFamily: 'var(--font-mono)', fontSize: '0.58rem', color: 'var(--text-muted)', whiteSpace: 'pre-wrap', margin: 0, lineHeight: 1.5 }}>
                        {c.log}
                      </pre>
                    </div>
                  )}
                </React.Fragment>
              )
            })}
          </div>
        )}
      </Csec>

    </div>
  )
}

export default Research
