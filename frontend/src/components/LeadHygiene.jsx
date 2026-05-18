import { useState, useEffect, useCallback, useRef, useMemo } from 'react'
import { useAuthSafe as useAuth } from '../hooks/useClerkSafe'

const API_BASE = '/api/admin/lead-hygiene'

const STATUS_PRESETS = ['Voicemail', 'Contacted', 'Re-Engage', 'Not Interested', 'All']
const LIMIT_PRESETS = [200, 1000, 2500, 7500]

const PREVIEW_FILTERS = [
  { value: 'all', label: 'All buckets' },
  { value: 'reengage-ready', label: 'Re-engage ready' },
  { value: 'needs-review', label: 'Needs review' },
  { value: 'do-not-contact', label: 'Do not contact' },
  { value: 'recently-contacted', label: 'Recently contacted' },
  { value: 'already-automated', label: 'Already automated' },
  { value: 'client', label: 'Existing clients' },
]

const BUCKET_TONES = {
  'reengage-ready':           { color: 'var(--green)',  label: 'Re-engage ready' },
  'already-automated':        { color: 'var(--accent)', label: 'Already automated' },
  'recently-contacted':       { color: 'var(--accent)', label: 'Recently contacted' },
  'previous-outreach-detected':{ color: 'var(--text)',   label: 'Previous outreach' },
  'needs-review':             { color: 'var(--amber)',  label: 'Needs review' },
  'duplicate':                { color: 'var(--amber)',  label: 'Duplicate phone' },
  'missing-phone':            { color: 'var(--amber)',  label: 'Missing phone' },
  'client':                   { color: 'var(--green)',  label: 'Existing client' },
  'invalid':                  { color: 'var(--red)',    label: 'Invalid' },
  'not-interested':           { color: 'var(--red)',    label: 'Not interested' },
  'do-not-contact':           { color: 'var(--red)',    label: 'Do not contact' },
}

const POLL_MS = 3000

function dot(color) {
  return {
    display: 'inline-block', width: 6, height: 6, borderRadius: '50%',
    background: color, flexShrink: 0,
  }
}

function fmtTime(iso) {
  if (!iso) return '—'
  try { return new Date(iso).toLocaleString() } catch { return iso }
}

function shortId(s) {
  return s ? String(s).slice(0, 8) : ''
}

function maskPhone(s) {
  if (!s) return ''
  const digits = String(s).replace(/\D/g, '').slice(-10)
  if (digits.length !== 10) return s
  return `(${digits.slice(0, 3)}) ${digits.slice(3, 6)}-${digits.slice(6)}`
}

function maskEmail(s) {
  if (!s || !s.includes('@')) return s || ''
  const [u, d] = s.split('@')
  if (u.length <= 2) return s
  return `${u.slice(0, 2)}…@${d}`
}

function BucketPill({ bucket }) {
  const t = BUCKET_TONES[bucket] || { color: 'var(--text-muted)', label: bucket || '—' }
  return (
    <span style={{
      display: 'inline-flex', alignItems: 'center', gap: 6,
      padding: '0.15rem 0.5rem', border: `1px solid ${t.color}`,
      borderRadius: 2, fontFamily: 'var(--font-mono)', fontSize: '0.6rem',
      letterSpacing: '0.04em', textTransform: 'uppercase', color: t.color,
    }}>
      <span style={dot(t.color)} />
      {t.label}
    </span>
  )
}

function SourceCard({ name, available, mode }) {
  const tone = available ? 'var(--green)' : 'var(--text-muted)'
  return (
    <div className="stat-box" style={{ padding: '0.85rem 0.75rem' }}>
      <div className="stat-label" style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
        <span style={dot(tone)} />
        {name}
      </div>
      <div className="stat-value" style={{ fontSize: '0.95rem' }}>
        {available ? 'Connected' : 'Unavailable'}
      </div>
      <div style={{ fontFamily: 'var(--font-mono)', fontSize: '0.58rem', color: 'var(--text-muted)', letterSpacing: '0.04em', textTransform: 'uppercase' }}>
        {mode || ''}
      </div>
    </div>
  )
}

function BucketRow({ bucket, count }) {
  const t = BUCKET_TONES[bucket] || { color: 'var(--text-muted)', label: bucket }
  return (
    <div style={{
      display: 'flex', alignItems: 'center', justifyContent: 'space-between',
      padding: '0.4rem 0', borderBottom: '1px solid var(--border-subtle)',
    }}>
      <span style={{ display: 'inline-flex', alignItems: 'center', gap: 8, fontFamily: 'var(--font-mono)', fontSize: '0.72rem', color: 'var(--text)' }}>
        <span style={dot(t.color)} />
        {t.label}
      </span>
      <span style={{ fontFamily: 'var(--font-display)', fontSize: '1rem', fontWeight: 600, color: 'var(--text)' }}>
        {count}
      </span>
    </div>
  )
}

function LeadHygiene() {
  const { getToken } = useAuth()

  const [sources, setSources] = useState(null)
  const [runs, setRuns] = useState([])
  const [runsLoading, setRunsLoading] = useState(false)
  const [error, setError] = useState(null)

  const [statusLabel, setStatusLabel] = useState('Voicemail')
  const [statusFreeText, setStatusFreeText] = useState('')
  const [limit, setLimit] = useState(200)
  const [includeGhl, setIncludeGhl] = useState(true)
  const [recentWindow, setRecentWindow] = useState(30)
  const [notionFile, setNotionFile] = useState(null)
  const [notionToken, setNotionToken] = useState(null)
  const [uploading, setUploading] = useState(false)
  const [starting, setStarting] = useState(false)

  const [activeJobId, setActiveJobId] = useState(null)
  const [activeJob, setActiveJob] = useState(null)
  const [selectedJobId, setSelectedJobId] = useState(null)
  const [selectedJob, setSelectedJob] = useState(null)
  const [preview, setPreview] = useState(null)
  const [previewLoading, setPreviewLoading] = useState(false)
  const [previewFilter, setPreviewFilter] = useState('all')

  const fileInputRef = useRef(null)

  // ── auth-aware fetch ──
  const authFetch = useCallback(async (url, opts = {}) => {
    const token = getToken ? await getToken() : null
    const res = await fetch(url, {
      ...opts,
      headers: {
        ...(opts.body && !(opts.body instanceof FormData) ? { 'Content-Type': 'application/json' } : {}),
        ...(token ? { 'Authorization': 'Bearer ' + token } : {}),
        ...(opts.headers || {}),
      },
    })
    if (res.status === 401) {
      throw new Error('Session expired — please refresh and sign in again.')
    }
    if (!res.ok) {
      let detail
      try { detail = (await res.json()).detail } catch {}
      throw new Error(detail || `HTTP ${res.status}`)
    }
    if (res.headers.get('content-type')?.includes('application/json')) {
      return res.json()
    }
    return res
  }, [getToken])

  const downloadUrl = useCallback(async (jobId, kind) => {
    const token = getToken ? await getToken() : null
    const res = await fetch(`${API_BASE}/runs/${jobId}/report/${kind}`, {
      headers: token ? { 'Authorization': 'Bearer ' + token } : {},
    })
    if (!res.ok) {
      throw new Error(`Download failed (HTTP ${res.status})`)
    }
    const blob = await res.blob()
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `lead_hygiene_${kind}_${shortId(jobId)}.${kind === 'csv' ? 'csv' : 'json'}`
    document.body.appendChild(a)
    a.click()
    a.remove()
    URL.revokeObjectURL(url)
  }, [getToken])

  // ── initial load ──
  const loadSources = useCallback(async () => {
    try {
      const data = await authFetch(`${API_BASE}/sources`)
      setSources(data)
      if (!data.ghl?.available) setIncludeGhl(false)
    } catch (e) { setError(e.message) }
  }, [authFetch])

  const loadRuns = useCallback(async () => {
    setRunsLoading(true)
    try {
      const data = await authFetch(`${API_BASE}/runs?limit=25`)
      setRuns(data.runs || [])
    } catch (e) { setError(e.message) }
    finally { setRunsLoading(false) }
  }, [authFetch])

  useEffect(() => { loadSources(); loadRuns() }, [loadSources, loadRuns])

  // ── poll active job ──
  useEffect(() => {
    if (!activeJobId) return
    let cancelled = false
    let timer = null
    const tick = async () => {
      try {
        const data = await authFetch(`${API_BASE}/runs/${activeJobId}`)
        if (cancelled) return
        setActiveJob(data)
        if (data.status === 'completed' || data.status === 'failed') {
          // refresh the list and select the finished run for inspection
          loadRuns()
          setSelectedJobId(activeJobId)
          setActiveJobId(null)
          return
        }
        timer = setTimeout(tick, POLL_MS)
      } catch (e) {
        if (!cancelled) {
          setError(e.message)
          setActiveJobId(null)
        }
      }
    }
    tick()
    return () => { cancelled = true; if (timer) clearTimeout(timer) }
  }, [activeJobId, authFetch, loadRuns])

  // ── load selected report ──
  useEffect(() => {
    if (!selectedJobId) { setSelectedJob(null); setPreview(null); setPreviewFilter('all'); return }
    let cancelled = false
    const load = async () => {
      setPreviewLoading(true)
      try {
        const detail = await authFetch(`${API_BASE}/runs/${selectedJobId}`)
        if (cancelled) return
        setSelectedJob(detail)
        if (detail.status === 'completed') {
          const qs = new URLSearchParams({ limit: '100' })
          if (previewFilter !== 'all') qs.set('category', previewFilter)
          const p = await authFetch(`${API_BASE}/runs/${selectedJobId}/preview?${qs.toString()}`)
          if (!cancelled) setPreview(p)
        } else {
          setPreview(null)
        }
      } catch (e) {
        if (!cancelled) setError(e.message)
      } finally {
        if (!cancelled) setPreviewLoading(false)
      }
    }
    load()
    return () => { cancelled = true }
  }, [selectedJobId, previewFilter, authFetch])

  // ── upload notion csv ──
  const onPickCsv = (e) => {
    const f = e.target.files?.[0]
    setNotionFile(f || null)
    setNotionToken(null)
  }

  const uploadNotion = async () => {
    if (!notionFile) return
    setUploading(true)
    setError(null)
    try {
      const form = new FormData()
      form.append('file', notionFile)
      const res = await authFetch(`${API_BASE}/upload-notion-csv`, {
        method: 'POST',
        body: form,
      })
      setNotionToken(res.token)
    } catch (e) { setError(e.message) }
    finally { setUploading(false) }
  }

  // ── start a run ──
  const startRun = async () => {
    setStarting(true)
    setError(null)
    try {
      const body = {
        limit,
        status_label: statusLabel === 'Custom' ? (statusFreeText.trim() || null) : (statusLabel === 'All' ? null : statusLabel),
        include_ghl: includeGhl,
        recent_window_days: recentWindow,
        notion_upload_token: notionToken || null,
      }
      const job = await authFetch(`${API_BASE}/runs`, {
        method: 'POST',
        body: JSON.stringify(body),
      })
      setActiveJobId(job.job_id)
      setActiveJob(job)
      setRuns((prev) => [job, ...prev.filter(r => r.job_id !== job.job_id)])
    } catch (e) { setError(e.message) }
    finally { setStarting(false) }
  }

  // ── derived data ──
  const lastCompleted = useMemo(
    () => runs.find(r => r.status === 'completed') || null,
    [runs]
  )

  const summaryBuckets = useMemo(() => {
    const s = selectedJob?.summary?.by_bucket || lastCompleted?.summary?.by_bucket || {}
    return Object.entries(s).sort((a, b) => b[1] - a[1])
  }, [selectedJob, lastCompleted])

  const overviewCounts = useMemo(() => {
    const buckets = (selectedJob?.summary?.by_bucket || lastCompleted?.summary?.by_bucket || {})
    const total = (selectedJob?.summary?.total) ?? (lastCompleted?.summary?.total) ?? 0
    const reengage = buckets['reengage-ready'] || 0
    const needsReview = (buckets['needs-review'] || 0) + (buckets['duplicate'] || 0) + (buckets['missing-phone'] || 0)
    const hardStop = (buckets['do-not-contact'] || 0) + (buckets['not-interested'] || 0) + (buckets['invalid'] || 0)
    const recent = (buckets['recently-contacted'] || 0) + (buckets['previous-outreach-detected'] || 0)
    const automated = buckets['already-automated'] || 0
    const client = buckets['client'] || 0
    return { total, reengage, needsReview, hardStop, recent, automated, client }
  }, [selectedJob, lastCompleted])

  const statusOptions = [...STATUS_PRESETS, 'Custom']

  // ── input styles (existing tokens have no native dark select) ──
  const inputStyle = {
    padding: '0.4rem 0.55rem',
    background: 'var(--bg)',
    border: '1px solid var(--border)',
    borderRadius: 2,
    fontFamily: 'var(--font-mono)',
    fontSize: '0.72rem',
    color: 'var(--text)',
  }

  const labelStyle = {
    fontFamily: 'var(--font-mono)',
    fontSize: '0.6rem',
    letterSpacing: '0.08em',
    textTransform: 'uppercase',
    color: 'var(--text-muted)',
    marginBottom: '0.25rem',
  }

  return (
    <div className="dashboard lead-hygiene-dashboard">
      {/* ── A. Overview ── */}
      <section className="section">
        <div className="section-header-row">
          <h2 className="section-title" style={{ marginBottom: 0, paddingBottom: 0, borderBottom: 'none' }}>
            Lead Hygiene
            <span style={{ marginLeft: '0.75rem', fontFamily: 'var(--font-mono)', fontSize: '0.6rem', color: 'var(--accent)', letterSpacing: '0.06em' }}>
              DRY-RUN ONLY
            </span>
          </h2>
          <div style={{ display: 'flex', gap: '0.5rem' }}>
            <button className="btn btn-sm" onClick={loadSources}>Refresh sources</button>
            <button className="btn btn-sm" onClick={loadRuns} disabled={runsLoading}>
              {runsLoading ? 'Loading…' : 'Refresh runs'}
            </button>
          </div>
        </div>

        <p className="form-hint" style={{ margin: '0.5rem 0 1rem' }}>
          Scans old leads across Close, GHL, and an optional Notion CSV export. Classifies into
          re-engage / needs-review / hard-stop buckets. Never writes to upstream systems.
        </p>

        <div className="stat-row" style={{ marginBottom: '1rem' }}>
          <SourceCard name="CLOSE"  available={!!sources?.close?.available}  mode={sources?.close?.mode} />
          <SourceCard name="GHL"    available={!!sources?.ghl?.available}    mode={sources?.ghl?.mode} />
          <SourceCard name="NOTION" available={!!sources?.notion?.available} mode={sources?.notion?.mode} />
        </div>

        <div className="stat-row">
          <div className="stat-box"><div className="stat-label">Last scan</div>
            <div className="stat-value" style={{ fontSize: '0.95rem' }}>{lastCompleted ? fmtTime(lastCompleted.finished_at) : '—'}</div>
          </div>
          <div className="stat-box"><div className="stat-label">Leads scanned</div>
            <div className="stat-value">{overviewCounts.total.toLocaleString()}</div>
          </div>
          <div className="stat-box"><div className="stat-label">Re-engage ready</div>
            <div className="stat-value" style={{ color: 'var(--green)' }}>{overviewCounts.reengage}</div>
          </div>
          <div className="stat-box"><div className="stat-label">Needs review</div>
            <div className="stat-value" style={{ color: 'var(--amber)' }}>{overviewCounts.needsReview}</div>
          </div>
          <div className="stat-box"><div className="stat-label">Hard stop / DNC</div>
            <div className="stat-value" style={{ color: 'var(--red)' }}>{overviewCounts.hardStop}</div>
          </div>
          <div className="stat-box"><div className="stat-label">Recently contacted</div>
            <div className="stat-value">{overviewCounts.recent}</div>
          </div>
          <div className="stat-box"><div className="stat-label">Already automated</div>
            <div className="stat-value">{overviewCounts.automated}</div>
          </div>
          <div className="stat-box"><div className="stat-label">Existing clients</div>
            <div className="stat-value">{overviewCounts.client}</div>
          </div>
        </div>

        {error && <div className="alert alert-error" style={{ marginTop: '0.75rem' }}>{error}</div>}
      </section>

      {/* ── B. Run Audit Panel ── */}
      <section className="section">
        <h2 className="section-title">Run Dry Audit</h2>

        <div style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))',
          gap: '0.75rem',
          marginBottom: '0.75rem',
        }}>
          <div>
            <div style={labelStyle}>Close status filter</div>
            <select style={inputStyle} value={statusLabel} onChange={(e) => setStatusLabel(e.target.value)}>
              {statusOptions.map(o => <option key={o} value={o}>{o}</option>)}
            </select>
            {statusLabel === 'Custom' && (
              <input
                style={{ ...inputStyle, marginTop: '0.4rem', width: '100%' }}
                placeholder="e.g. Contacted"
                value={statusFreeText}
                onChange={(e) => setStatusFreeText(e.target.value)}
              />
            )}
          </div>

          <div>
            <div style={labelStyle}>Lead limit</div>
            <select style={inputStyle} value={limit} onChange={(e) => setLimit(Number(e.target.value))}>
              {LIMIT_PRESETS.map(n => <option key={n} value={n}>{n === 7500 ? '7500 (full)' : n.toLocaleString()}</option>)}
            </select>
          </div>

          <div>
            <div style={labelStyle}>Recent-touch window (days)</div>
            <input
              style={inputStyle}
              type="number"
              min={1}
              max={365}
              value={recentWindow}
              onChange={(e) => setRecentWindow(Number(e.target.value) || 30)}
            />
          </div>

          <div>
            <div style={labelStyle}>Include GHL</div>
            <label style={{
              display: 'inline-flex', alignItems: 'center', gap: 8,
              padding: '0.4rem 0.55rem', border: '1px solid var(--border)', borderRadius: 2,
              fontFamily: 'var(--font-mono)', fontSize: '0.7rem', color: sources?.ghl?.available ? 'var(--text)' : 'var(--text-muted)',
              cursor: sources?.ghl?.available ? 'pointer' : 'not-allowed',
            }}>
              <input
                type="checkbox"
                checked={includeGhl}
                disabled={!sources?.ghl?.available}
                onChange={(e) => setIncludeGhl(e.target.checked)}
              />
              {sources?.ghl?.available ? 'Enabled' : 'GHL credentials missing'}
            </label>
          </div>

          <div>
            <div style={labelStyle}>Notion CSV (optional)</div>
            <div style={{ display: 'flex', gap: '0.4rem', alignItems: 'center' }}>
              <input
                ref={fileInputRef}
                type="file"
                accept=".csv"
                onChange={onPickCsv}
                style={{ ...inputStyle, padding: '0.25rem' }}
              />
              <button
                className="btn btn-sm"
                onClick={uploadNotion}
                disabled={!notionFile || uploading}
              >
                {uploading ? 'Uploading…' : notionToken ? 'Uploaded' : 'Upload'}
              </button>
            </div>
            {notionToken && (
              <p style={{ fontFamily: 'var(--font-mono)', fontSize: '0.58rem', color: 'var(--green)', margin: '0.25rem 0 0' }}>
                Ready for this run • token {shortId(notionToken)}…
              </p>
            )}
          </div>
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', flexWrap: 'wrap' }}>
          <button
            className="btn btn-primary"
            onClick={startRun}
            disabled={starting || !!activeJobId || !sources?.close?.available}
            style={{ marginTop: 0 }}
          >
            {starting ? 'STARTING…' : activeJobId ? 'AUDIT RUNNING…' : 'START DRY AUDIT'}
          </button>
          {activeJob && (
            <span style={{ fontFamily: 'var(--font-mono)', fontSize: '0.7rem', color: 'var(--text-muted)' }}>
              {activeJob.status} • {activeJob.phase} • job {shortId(activeJob.job_id)}…
            </span>
          )}
          {!sources?.close?.available && (
            <span style={{ fontFamily: 'var(--font-mono)', fontSize: '0.65rem', color: 'var(--red)' }}>
              Close API credentials missing — fix env vars before running.
            </span>
          )}
        </div>
      </section>

      {/* ── C. Reports list ── */}
      <section className="section">
        <h2 className="section-title">Recent Runs</h2>
        {runs.length === 0 ? (
          <p className="no-results">No runs yet. Start one above.</p>
        ) : (
          <div className="table-scroll-wrapper">
            <table className="results-table">
              <thead>
                <tr>
                  <th>Started</th>
                  <th>Status</th>
                  <th>Status filter</th>
                  <th>Limit</th>
                  <th>Total</th>
                  <th>DNC / HS</th>
                  <th>Re-engage</th>
                  <th>Job</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {runs.map(r => {
                  const buckets = r.summary?.by_bucket || {}
                  const dnc = (buckets['do-not-contact']||0) + (buckets['not-interested']||0) + (buckets['invalid']||0)
                  const isSel = selectedJobId === r.job_id
                  return (
                    <tr key={r.job_id} style={{ background: isSel ? 'var(--surface-hover)' : undefined }}>
                      <td>{fmtTime(r.started_at)}</td>
                      <td>
                        <span style={{ color: r.status === 'completed' ? 'var(--green)' : r.status === 'failed' ? 'var(--red)' : 'var(--amber)' }}>
                          {r.status}
                        </span>
                      </td>
                      <td>{r.params?.status_label || 'all'}</td>
                      <td>{r.params?.limit}</td>
                      <td>{r.summary?.total ?? '—'}</td>
                      <td style={{ color: 'var(--red)' }}>{r.summary ? dnc : '—'}</td>
                      <td style={{ color: 'var(--green)' }}>{r.summary ? (buckets['reengage-ready']||0) : '—'}</td>
                      <td style={{ fontSize: '0.7rem', color: 'var(--text-muted)' }}>{shortId(r.job_id)}…</td>
                      <td>
                        <button className="btn btn-sm" onClick={() => setSelectedJobId(r.job_id)}>
                          {isSel ? 'Selected' : 'Open'}
                        </button>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {/* ── Selected report detail ── */}
      {selectedJobId && (
        <section className="section">
          <div className="section-header-row">
            <h2 className="section-title" style={{ marginBottom: 0, paddingBottom: 0, borderBottom: 'none' }}>
              Report Detail
              <span style={{ marginLeft: '0.75rem', fontFamily: 'var(--font-mono)', fontSize: '0.6rem', color: 'var(--text-muted)' }}>
                job {shortId(selectedJobId)}…
              </span>
            </h2>
            <div style={{ display: 'flex', gap: '0.5rem' }}>
              <button className="btn btn-sm" disabled={selectedJob?.status !== 'completed'} onClick={() => downloadUrl(selectedJobId, 'csv')}>
                Download CSV
              </button>
              <button className="btn btn-sm" disabled={selectedJob?.status !== 'completed'} onClick={() => downloadUrl(selectedJobId, 'json')}>
                Download JSON
              </button>
              <button className="btn btn-sm" onClick={() => setSelectedJobId(null)}>Close</button>
            </div>
          </div>

          {previewLoading && <p className="loading-text">Loading…</p>}

          {selectedJob?.status === 'failed' && (
            <div className="alert alert-error" style={{ marginTop: '0.75rem' }}>
              Audit failed: {selectedJob.error || 'unknown error'}
            </div>
          )}

          {selectedJob?.status === 'completed' && (
            <>
              <div style={{
                display: 'grid',
                gridTemplateColumns: 'minmax(220px, 0.32fr) minmax(0, 1fr)',
                gap: '1.25rem',
                marginTop: '0.75rem',
              }}>
                <div>
                  <div style={labelStyle}>Bucket counts</div>
                  <div>
                    {summaryBuckets.length === 0
                      ? <p className="no-results">No rows.</p>
                      : summaryBuckets.map(([b, n]) => <BucketRow key={b} bucket={b} count={n} />)}
                  </div>
                </div>

                <div>
                  <div style={{ display: 'flex', alignItems: 'end', justifyContent: 'space-between', gap: '0.75rem', flexWrap: 'wrap', marginBottom: '0.4rem' }}>
                    <div style={labelStyle}>
                      Preview ({preview?.rows?.length || 0} of {preview?.total_rows ?? 0} rows)
                    </div>
                    <div>
                      <div style={labelStyle}>Filter report</div>
                      <select
                        style={inputStyle}
                        value={previewFilter}
                        onChange={(e) => setPreviewFilter(e.target.value)}
                      >
                        {PREVIEW_FILTERS.map((f) => (
                          <option key={f.value} value={f.value}>{f.label}</option>
                        ))}
                      </select>
                    </div>
                  </div>
                  <div className="table-scroll-wrapper">
                    <table className="results-table">
                      <thead>
                        <tr>
                          <th>Name</th>
                          <th>Phone</th>
                          <th>Email</th>
                          <th>Bucket</th>
                          <th>Close</th>
                          <th>GHL</th>
                          <th>Reason</th>
                        </tr>
                      </thead>
                      <tbody>
                        {(preview?.rows || []).map((row, i) => (
                          <tr key={(row.close_lead_id || '') + i}>
                            <td>{row.lead_name || '—'}</td>
                            <td>{maskPhone(row.phone)}</td>
                            <td style={{ fontSize: '0.65rem' }}>{maskEmail(row.email)}</td>
                            <td><BucketPill bucket={row.recommended_bucket} /></td>
                            <td style={{ fontSize: '0.62rem', color: 'var(--text-muted)' }}>{shortId(row.close_lead_id)}</td>
                            <td style={{ fontSize: '0.62rem', color: 'var(--text-muted)' }}>{shortId(row.ghl_contact_id)}</td>
                            <td style={{ fontSize: '0.65rem', color: 'var(--text-muted)' }}>{row.reason}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                  {preview && preview.total_rows > preview.rows.length && (
                    <p className="form-hint" style={{ marginTop: '0.5rem' }}>
                      Showing first {preview.rows.length} of {preview.total_rows} {preview.category && preview.category !== 'all' ? 'filtered ' : ''}rows. Download CSV for the full report.
                    </p>
                  )}
                </div>
              </div>
            </>
          )}
        </section>
      )}

      {/* ── D. Apply Mode locked ── */}
      <section className="section" style={{ borderStyle: 'dashed' }}>
        <h2 className="section-title" style={{ color: 'var(--amber)' }}>
          Apply Mode • Locked
        </h2>
        <p className="form-hint" style={{ margin: 0 }}>
          Live tagging is disabled. Once a recent dry-run report is reviewed and trusted,
          Apply Mode will write the recommended GHL tags (<code>rvm-staging</code>,{' '}
          <code>do-not-contact</code>) and Close field updates for the selected buckets.
          Explicit confirmation will be required per run.
        </p>
        <button className="btn" disabled style={{ marginTop: '0.75rem' }}>
          Apply Recommendations (disabled)
        </button>
      </section>
    </div>
  )
}

export default LeadHygiene
