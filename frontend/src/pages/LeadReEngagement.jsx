import { useCallback, useEffect, useMemo, useState } from 'react'
import { useAuthSafe as useAuth } from '../hooks/useClerkSafe'
import LeadHygiene from '../components/LeadHygiene'
import { Badge, Empty, RiskBadge, Stat } from '../components/registry/RegistryBadges'

const API_BASE = '/api/admin/registry'
const POOLS = [
  { key: 'eligible', label: 'Never Responded, Safe' },
  { key: 'needs_review', label: 'Needs Review' },
  { key: 'do_not_touch', label: 'Do Not Touch' },
  { key: 'excluded', label: 'Recent / Automated' },
]
const CHANNELS = [
  { value: 'export_only', label: 'CSV export only' },
  { value: 'sms_only', label: 'CSV columns: SMS' },
  { value: 'rvm_only', label: 'CSV columns: RVM' },
  { value: 'sms_rvm', label: 'CSV columns: SMS + RVM' },
]

function fmtDate(value) {
  if (!value) return '-'
  try {
    return new Date(value).toLocaleString()
  } catch {
    return String(value)
  }
}

function boundedNumber(value, fallback, min, max) {
  const parsed = Number(value)
  if (!Number.isFinite(parsed)) return fallback
  return Math.min(max, Math.max(min, parsed))
}

function evidenceItems(row) {
  return [
    row.never_responded ? { label: 'Never responded', tone: 'green' } : null,
    row.eligibility_reason ? { label: row.eligibility_reason, tone: 'green' } : null,
    row.last_appointment ? { label: `Last appt ${row.last_appointment}`, tone: 'amber' } : null,
  ].filter(Boolean)
}

function PoolTable({ rows }) {
  if (!rows?.length) return <Empty label="No leads in this pool for the current filters." />
  return (
    <div style={{ overflowX: 'auto', borderTop: '1px solid var(--border-subtle)' }}>
      <table style={{ width: '100%', minWidth: 1080, borderCollapse: 'collapse' }}>
        <thead>
          <tr>
            {['Lead', 'Risk', 'Masked Contact', 'Bucket', 'Safety Evidence', 'Sources', 'Last Touch'].map((label) => (
              <th key={label} style={thStyle}>{label}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={`${row.household_id}-${row.recommendation_id || 'household'}-${row.source_snapshot_id || 'snapshot'}`}>
              <td style={tdStyle}>
                <div style={{ display: 'grid', gap: '0.18rem' }}>
                  <span>{row.display_name}</span>
                  {row.close_lead_id && <span style={mutedStyle}>Close {row.close_lead_id}</span>}
                  {row.ghl_contact_id && <span style={mutedStyle}>GHL {row.ghl_contact_id}</span>}
                </div>
              </td>
              <td style={tdStyle}><RiskBadge value={row.risk_level} /></td>
              <td style={tdStyle}>
                <div style={{ display: 'grid', gap: '0.18rem' }}>
                  <span>{row.masked_phone || '-'}</span>
                  <span style={mutedStyle}>{row.masked_email || '-'}</span>
                </div>
              </td>
              <td style={tdStyle}><Badge tone={row.pool === 'eligible' ? 'green' : row.pool === 'do_not_touch' ? 'red' : 'amber'}>{row.bucket}</Badge></td>
              <td style={tdStyle}>
                <div style={{ display: 'grid', gap: '0.25rem' }}>
                  <span>{row.reason || '-'}</span>
                  <div style={{ display: 'flex', gap: '0.25rem', flexWrap: 'wrap' }}>
                    {evidenceItems(row).map((item) => <Badge key={item.label} tone={item.tone}>{item.label}</Badge>)}
                    {(row.risk_flags || []).slice(0, 4).map((flag) => <Badge key={flag}>{flag}</Badge>)}
                    {(row.excluded_reasons || []).slice(0, 4).map((reason) => <Badge key={reason} tone="amber">{reason}</Badge>)}
                  </div>
                  {row.locked_reason && <span style={{ ...mutedStyle, color: 'var(--amber)' }}>{row.locked_reason}</span>}
                </div>
              </td>
              <td style={tdStyle}>
                <div style={{ display: 'flex', gap: '0.25rem', flexWrap: 'wrap' }}>
                  {(row.sources || []).map((source) => <Badge key={source}>{source}</Badge>)}
                </div>
              </td>
              <td style={tdStyle}>
                <div style={{ display: 'grid', gap: '0.18rem' }}>
                  <span>Out: {row.last_outbound_touch || '-'}</span>
                  <span style={mutedStyle}>In: {row.last_inbound_touch || '-'}</span>
                  {row.last_appointment && <span style={mutedStyle}>Appt: {row.last_appointment}</span>}
                </div>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function PreviewTable({ rows }) {
  if (!rows?.length) return <Empty label="No never-responded safe rows selected for this preview." />
  return (
    <div style={{ overflowX: 'auto', borderTop: '1px solid var(--border-subtle)' }}>
      <table style={{ width: '100%', minWidth: 1080, borderCollapse: 'collapse' }}>
        <thead>
          <tr>
            {['Lead', 'Masked Phone', 'Risk', 'Bucket', 'Safety Evidence', 'Tag', 'Source Ref'].map((label) => <th key={label} style={thStyle}>{label}</th>)}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={`${row.household_id}-${row.recommendation_id || 'household'}-${row.source_snapshot_id || 'preview'}`}>
              <td style={tdStyle}>{row.display_name}</td>
              <td style={tdStyle}>{row.masked_phone || '-'}</td>
              <td style={tdStyle}><RiskBadge value={row.risk_level} /></td>
              <td style={tdStyle}>{row.bucket}</td>
              <td style={tdStyle}>
                <div style={{ display: 'grid', gap: '0.25rem' }}>
                  <div style={{ display: 'flex', gap: '0.25rem', flexWrap: 'wrap' }}>
                    {evidenceItems(row).map((item) => <Badge key={item.label} tone={item.tone}>{item.label}</Badge>)}
                  </div>
                  <span style={mutedStyle}>In: {row.last_inbound_touch || '-'}</span>
                </div>
              </td>
              <td style={tdStyle}><Badge tone="green">{row.proposed_tag}</Badge></td>
              <td style={tdStyle}>{row.source_ref || '-'}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

export default function LeadReEngagement() {
  const { getToken } = useAuth()
  const [summary, setSummary] = useState(null)
  const [pool, setPool] = useState([])
  const [reports, setReports] = useState([])
  const [selectedReportId, setSelectedReportId] = useState('')
  const [activePool, setActivePool] = useState('eligible')
  const [section, setSection] = useState('dashboard')
  const [recentWindow, setRecentWindow] = useState(30)
  const [batchSize, setBatchSize] = useState(50)
  const [channelMode, setChannelMode] = useState('export_only')
  const [preview, setPreview] = useState(null)
  const [message, setMessage] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  const authFetch = useCallback(async (url, opts = {}) => {
    const token = getToken ? await getToken() : null
    const res = await fetch(url, {
      ...opts,
      headers: {
        ...(opts.body ? { 'Content-Type': 'application/json' } : {}),
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
        ...(opts.headers || {}),
      },
    })
    if (!res.ok) {
      let detail = ''
      try { detail = (await res.json()).detail } catch {}
      throw new Error(detail || `HTTP ${res.status}`)
    }
    return res
  }, [getToken])

  const loadPool = useCallback(async (view = activePool) => {
    const res = await authFetch(`${API_BASE}/reengagement/pool?view=${view}&limit=100&recent_window_days=${recentWindow}`)
    setPool(await res.json())
  }, [activePool, authFetch, recentWindow])

  const loadCore = useCallback(async () => {
    setError('')
    try {
      const [summaryRes, reportsRes] = await Promise.all([
        authFetch(`${API_BASE}/reengagement/summary?recent_window_days=${recentWindow}`),
        authFetch(`${API_BASE}/lead-hygiene-reports?limit=25`),
      ])
      const nextSummary = await summaryRes.json()
      const nextReports = await reportsRes.json()
      setSummary(nextSummary)
      setReports(nextReports)
      setSelectedReportId((current) => current || nextReports.find((report) => report.importable)?.job_id || nextReports[0]?.job_id || '')
      await loadPool(activePool)
    } catch (err) {
      setError(err.message)
    }
  }, [activePool, authFetch, loadPool, recentWindow])

  useEffect(() => { loadCore() }, [loadCore])

  const selectedReport = useMemo(
    () => reports.find((report) => report.job_id === selectedReportId) || null,
    [reports, selectedReportId],
  )

  async function switchPool(nextPool) {
    setActivePool(nextPool)
    setSection(nextPool)
    setPreview(null)
    try {
      await loadPool(nextPool)
    } catch (err) {
      setError(err.message)
    }
  }

  async function importReport(e) {
    e.preventDefault()
    if (!selectedReport?.importable) {
      setMessage('Selected report is not importable.')
      return
    }
    setLoading(true)
    setError('')
    setMessage('')
    try {
      const res = await authFetch(`${API_BASE}/imports/lead-hygiene/${selectedReport.job_id}`, { method: 'POST', body: '{}' })
      const body = await res.json()
      setMessage(`Imported ${body.rows_seen} rows into the local Lead Re-Engagement pool.`)
      await loadCore()
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  async function runPreview() {
    setLoading(true)
    setError('')
    setMessage('')
    try {
      const res = await authFetch(`${API_BASE}/reengagement/campaign-preview`, {
        method: 'POST',
        body: JSON.stringify({
          batch_size: boundedNumber(batchSize, 50, 1, 1000),
          channel_mode: channelMode,
          recent_window_days: boundedNumber(recentWindow, 30, 1, 365),
          source_ref: summary?.latest_source_ref || undefined,
        }),
      })
      setPreview(await res.json())
      setSection('campaign')
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  async function exportCsv() {
    setLoading(true)
    setError('')
    try {
      const res = await authFetch(`${API_BASE}/reengagement/export`, {
        method: 'POST',
        body: JSON.stringify({
          batch_size: boundedNumber(batchSize, 50, 1, 1000),
          channel_mode: channelMode,
          recent_window_days: boundedNumber(recentWindow, 30, 1, 365),
          source_ref: summary?.latest_source_ref || undefined,
        }),
      })
      const blob = await res.blob()
      const url = URL.createObjectURL(blob)
      const link = document.createElement('a')
      link.href = url
      link.download = `lead-reengagement-${channelMode}-${batchSize}.csv`
      document.body.appendChild(link)
      link.click()
      link.remove()
      URL.revokeObjectURL(url)
      setMessage('CSV export generated locally by FC. Close, GHL, Twilio, SMS, and RVM were not touched.')
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="dashboard" style={{ maxWidth: 1480 }}>
      <section style={{ marginBottom: '1rem' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', gap: '1rem', flexWrap: 'wrap', alignItems: 'flex-start' }}>
          <div>
            <div style={{ marginBottom: '0.5rem', display: 'flex', gap: '0.45rem', flexWrap: 'wrap' }}>
              <Badge tone="accent">EXPORT ONLY</Badge>
              <Badge tone="green">Never Responded</Badge>
              <Badge>local projection</Badge>
            </div>
            <h1 style={{ fontFamily: 'var(--font-display)', fontSize: '1.85rem', lineHeight: 1.05, margin: 0 }}>Lead Re-Engagement</h1>
            <p style={{ color: 'var(--text-muted)', fontFamily: 'var(--font-mono)', fontSize: '0.78rem', marginTop: '0.45rem', maxWidth: 780 }}>
              Build a safe never-responded call list from local Lead Hygiene and Registry evidence. CSV export only; this page does not write to Close, GHL, Twilio, SMS, or RVM.
            </p>
          </div>
          <div style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap', justifyContent: 'flex-end' }}>
            <label style={{ ...labelStyle, display: 'grid', gap: '0.25rem' }}>
              Recent touch window
              <input className="input" type="number" min="1" max="365" value={recentWindow} onChange={(e) => setRecentWindow(e.target.value)} style={{ width: 120 }} />
            </label>
            <button className="btn-secondary" type="button" onClick={loadCore} disabled={loading}>{loading ? 'Loading...' : 'Refresh'}</button>
          </div>
        </div>
        {error && <p style={{ color: 'var(--red)', fontFamily: 'var(--font-mono)', fontSize: '0.78rem' }}>{error}</p>}
        {message && <p style={{ color: 'var(--green)', fontFamily: 'var(--font-mono)', fontSize: '0.78rem' }}>{message}</p>}
      </section>

      <section style={{ marginBottom: '1rem', display: 'flex', gap: '0.45rem', flexWrap: 'wrap' }}>
        {['dashboard', 'eligible', 'needs_review', 'do_not_touch', 'excluded', 'campaign', 'history', 'safety'].map((key) => (
          <button
            key={key}
            type="button"
            className={section === key ? 'btn-primary' : 'btn-secondary'}
            onClick={() => {
              if (['eligible', 'needs_review', 'do_not_touch', 'excluded'].includes(key)) switchPool(key)
              else setSection(key)
            }}
            style={{ padding: '0.42rem 0.65rem' }}
          >
            {sectionLabels[key]}
          </button>
        ))}
      </section>

      {section === 'dashboard' && (
        <>
          <section className="stats-grid" style={{ marginBottom: '1rem' }}>
            <Stat label="Never Responded, Safe" value={summary?.eligible} />
            <Stat label="Needs Review" value={summary?.needs_review} />
            <Stat label="Do Not Touch" value={summary?.do_not_touch} />
            <Stat label="Recent / Automated" value={summary?.excluded_recent_or_automated} />
          </section>
          <section className="section" style={{ marginBottom: '1rem' }}>
            <div className="section-title">Dataset Freshness</div>
            <div style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap', alignItems: 'center' }}>
              <Badge>{summary?.latest_source_ref || 'no import'}</Badge>
              <span style={mutedStyle}>Latest local import: {fmtDate(summary?.latest_import_at)}</span>
              <Badge tone="green">{summary?.proposed_tag || 'reengage-staging'}</Badge>
            </div>
          </section>
        </>
      )}

      {['eligible', 'needs_review', 'do_not_touch', 'excluded'].includes(section) && (
        <section className="section" style={{ marginBottom: '1rem' }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '0.75rem', flexWrap: 'wrap', marginBottom: '0.75rem' }}>
            <div>
              <div className="section-title" style={{ marginBottom: '0.25rem' }}>{sectionLabels[section]}</div>
              <div style={{ display: 'flex', gap: '0.35rem', flexWrap: 'wrap' }}>
                {POOLS.map((poolItem) => (
                  <button
                    key={poolItem.key}
                    className={activePool === poolItem.key ? 'btn-primary' : 'btn-secondary'}
                    type="button"
                    onClick={() => switchPool(poolItem.key)}
                    style={{ padding: '0.35rem 0.55rem' }}
                  >
                    {poolItem.label}
                  </button>
                ))}
              </div>
            </div>
            <Badge tone={section === 'eligible' ? 'green' : section === 'do_not_touch' ? 'red' : 'amber'}>{pool.length} rows</Badge>
          </div>
          <PoolTable rows={pool} />
        </section>
      )}

      {section === 'campaign' && (
        <section className="section" style={{ marginBottom: '1rem' }}>
          <div className="section-title">CSV Builder</div>
          <p style={{ color: 'var(--text-muted)', fontFamily: 'var(--font-mono)', fontSize: '0.76rem', margin: '0 0 0.85rem' }}>
            Builds a local CSV for Seb to review and call from. Preview and export do not create tasks, tags, notes, messages, RVM drops, or contact updates in Close, GHL, Twilio, or any external system.
          </p>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(190px, 1fr))', gap: '0.75rem', marginBottom: '0.85rem' }}>
            <label style={fieldStyle}>
              <span style={labelStyle}>Batch size</span>
              <input className="input" type="number" min="1" max="1000" value={batchSize} onChange={(e) => setBatchSize(e.target.value)} />
            </label>
            <label style={fieldStyle}>
              <span style={labelStyle}>CSV format</span>
              <select className="input" value={channelMode} onChange={(e) => setChannelMode(e.target.value)}>
                {CHANNELS.map((channel) => <option key={channel.value} value={channel.value}>{channel.label}</option>)}
              </select>
            </label>
            <label style={fieldStyle}>
              <span style={labelStyle}>Source reference</span>
              <input className="input" value={summary?.latest_source_ref || ''} readOnly />
            </label>
          </div>
          <div style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap', marginBottom: '1rem' }}>
            <button className="btn-primary" type="button" onClick={runPreview} disabled={loading}>{loading ? 'Previewing...' : 'Preview CSV'}</button>
            <button className="btn-secondary" type="button" onClick={exportCsv} disabled={loading || !preview?.selected_count}>Export CSV</button>
            <Badge>CSV only</Badge>
            <Badge>no Close write</Badge>
            <Badge>no GHL write</Badge>
            <Badge>no Twilio / SMS / RVM send</Badge>
          </div>
          {preview && (
            <div style={{ display: 'grid', gap: '1rem' }}>
              <div style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap' }}>
                <Badge tone="green">{preview.selected_count} selected</Badge>
                <Badge>{preview.total_eligible} never responded safe</Badge>
                <Badge>{preview.channel_mode}</Badge>
                <Badge tone="green">{preview.proposed_tag}</Badge>
              </div>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(260px, 1fr))', gap: '0.75rem' }}>
                <CopyCard label="SMS Opener" value={preview.copy_preview?.sms_opener} />
                <CopyCard label="Follow-up SMS" value={preview.copy_preview?.follow_up_sms} />
                <CopyCard label="RVM Script" value={preview.copy_preview?.rvm_script} />
              </div>
              <p style={{ color: 'var(--amber)', fontFamily: 'var(--font-mono)', fontSize: '0.76rem', margin: 0 }}>{preview.confirmation_copy}</p>
              <PreviewTable rows={preview.rows} />
            </div>
          )}
        </section>
      )}

      {section === 'history' && (
        <section className="section" style={{ marginBottom: '1rem' }}>
          <div className="section-title">History</div>
          {reports.length === 0 ? <Empty label="No Lead Hygiene reports found." /> : (
            <div style={{ display: 'grid', gap: '0.5rem' }}>
              {reports.map((report) => (
                <div key={report.job_id} style={{ borderTop: '1px solid var(--border-subtle)', paddingTop: '0.55rem', display: 'flex', gap: '0.5rem', flexWrap: 'wrap', alignItems: 'center' }}>
                  <Badge tone={report.importable ? 'green' : 'amber'}>{report.status}</Badge>
                  <span style={{ fontFamily: 'var(--font-mono)', fontSize: '0.76rem' }}>{report.label}</span>
                </div>
              ))}
            </div>
          )}
        </section>
      )}

      {section === 'safety' && (
        <>
          <section className="section" style={{ marginBottom: '1rem' }}>
            <div className="section-title">Safety / Source Controls</div>
            <form onSubmit={importReport} style={{ display: 'grid', gridTemplateColumns: 'minmax(240px, 1fr) auto', gap: '0.5rem', alignItems: 'center' }}>
              <select className="input" value={selectedReportId} onChange={(e) => setSelectedReportId(e.target.value)}>
                {reports.length === 0 && <option value="">No reports found</option>}
                {reports.map((report) => (
                  <option key={report.job_id} value={report.job_id}>
                    {report.label}{report.importable ? '' : ' - not importable'}
                  </option>
                ))}
              </select>
              <button className="btn-primary" type="submit" disabled={loading || !selectedReport?.importable}>{loading ? 'Importing...' : 'Import Selected'}</button>
            </form>
          </section>
          <LeadHygiene />
        </>
      )}
    </div>
  )
}

function CopyCard({ label, value }) {
  return (
    <div style={{ border: '1px solid var(--border-subtle)', padding: '0.75rem', borderRadius: 6 }}>
      <div style={labelStyle}>{label}</div>
      <p style={{ margin: '0.4rem 0 0', fontFamily: 'var(--font-mono)', fontSize: '0.75rem', color: 'var(--text)' }}>{value || '-'}</p>
    </div>
  )
}

const sectionLabels = {
  dashboard: 'Dashboard',
  eligible: 'Never Responded, Safe',
  needs_review: 'Needs Review',
  do_not_touch: 'Do Not Touch',
  excluded: 'Recent / Automated',
  campaign: 'CSV Builder',
  history: 'History',
  safety: 'Safety / Source Controls',
}

const thStyle = {
  textAlign: 'left',
  padding: '0.55rem 0.35rem',
  borderBottom: '1px solid var(--border-subtle)',
  color: 'var(--text-muted)',
  fontFamily: 'var(--font-mono)',
  fontSize: '0.62rem',
  textTransform: 'uppercase',
  letterSpacing: '0.04em',
}

const tdStyle = {
  padding: '0.55rem 0.35rem',
  borderBottom: '1px solid var(--border-subtle)',
  color: 'var(--text)',
  fontFamily: 'var(--font-mono)',
  fontSize: '0.73rem',
  verticalAlign: 'top',
}

const mutedStyle = {
  color: 'var(--text-muted)',
  fontFamily: 'var(--font-mono)',
  fontSize: '0.7rem',
}

const labelStyle = {
  color: 'var(--text-muted)',
  fontFamily: 'var(--font-mono)',
  fontSize: '0.64rem',
  textTransform: 'uppercase',
  letterSpacing: '0.04em',
}

const fieldStyle = {
  display: 'grid',
  gap: '0.3rem',
}
