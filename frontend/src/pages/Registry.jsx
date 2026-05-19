import { useCallback, useEffect, useMemo, useState } from 'react'
import { useAuthSafe as useAuth } from '../hooks/useClerkSafe'
import LeadHygiene from '../components/LeadHygiene'

const API_BASE = '/api/admin/registry'
const TABS = ['Overview', 'Search', 'Households', 'People', 'Hygiene', 'Conflicts', 'Apply Queue', 'Audit Log', 'Connections']

function fmt(value) {
  if (value === null || value === undefined || value === '') return '-'
  return String(value)
}

function Badge({ children, tone = 'muted' }) {
  const colors = {
    muted: 'var(--text-muted)',
    green: 'var(--green)',
    amber: 'var(--amber)',
    red: 'var(--red)',
    accent: 'var(--accent)',
  }
  return (
    <span style={{
      display: 'inline-flex',
      alignItems: 'center',
      border: `1px solid ${colors[tone] || colors.muted}`,
      color: colors[tone] || colors.muted,
      borderRadius: 2,
      padding: '0.1rem 0.45rem',
      fontFamily: 'var(--font-mono)',
      fontSize: '0.58rem',
      textTransform: 'uppercase',
      letterSpacing: '0.04em',
      whiteSpace: 'nowrap',
    }}>
      {children}
    </span>
  )
}

function Stat({ label, value }) {
  return (
    <div className="stat-box" style={{ minHeight: 92 }}>
      <div className="stat-label">{label}</div>
      <div className="stat-value">{value ?? 0}</div>
    </div>
  )
}

function Empty({ label }) {
  return <p style={{ color: 'var(--text-muted)', fontFamily: 'var(--font-mono)', fontSize: '0.78rem', margin: 0 }}>{label}</p>
}

function importSummaryText(result) {
  if (!result) return ''
  return `Imported ${result.rows_seen} rows. New households: ${result.households_created}; people: ${result.people_created}; contacts: ${result.contact_methods_created}; recommendations: ${result.recommendations_created}.`
}

function DataTable({ columns, rows, onRowClick }) {
  if (!rows?.length) return <Empty label="No records yet." />
  return (
    <div style={{ overflowX: 'auto', borderTop: '1px solid var(--border-subtle)' }}>
      <table style={{ width: '100%', borderCollapse: 'collapse', minWidth: 640 }}>
        <thead>
          <tr>
            {columns.map((col) => (
              <th key={col.key} style={{
                textAlign: 'left',
                padding: '0.55rem 0.35rem',
                borderBottom: '1px solid var(--border-subtle)',
                color: 'var(--text-muted)',
                fontFamily: 'var(--font-mono)',
                fontSize: '0.62rem',
                textTransform: 'uppercase',
                letterSpacing: '0.06em',
              }}>{col.label}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr
              key={`${row.id}-${row.external_id || row.display_name || row.recommendation_type || row.event_type}`}
              onClick={() => onRowClick?.(row)}
              style={{ cursor: onRowClick ? 'pointer' : 'default' }}
            >
              {columns.map((col) => (
                <td key={col.key} style={{
                  padding: '0.55rem 0.35rem',
                  borderBottom: '1px solid var(--border-subtle)',
                  color: 'var(--text)',
                  fontFamily: 'var(--font-mono)',
                  fontSize: '0.74rem',
                  verticalAlign: 'top',
                }}>
                  {col.render ? col.render(row) : fmt(row[col.key])}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function DetailPanel({ title, detail }) {
  if (!detail) return null
  return (
    <section className="section" style={{ marginTop: '1rem' }}>
      <div className="section-title">{title}</div>
      <div style={{ display: 'grid', gap: '1rem' }}>
        <div style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap', alignItems: 'center' }}>
          <strong style={{ fontFamily: 'var(--font-display)', fontSize: '1.15rem' }}>{detail.display_name}</strong>
          <Badge tone={detail.risk_level === 'high' ? 'red' : detail.risk_level === 'medium' ? 'amber' : 'green'}>{detail.risk_level || 'unknown'}</Badge>
          <Badge>{detail.status || detail.role || 'registry'}</Badge>
        </div>
        {'people' in detail && <DataTable columns={[
          { key: 'display_name', label: 'Person' },
          { key: 'role', label: 'Role' },
          { key: 'consent_status', label: 'Consent' },
          { key: 'dnc_status', label: 'DNC' },
        ]} rows={detail.people} />}
        <DataTable columns={[
          { key: 'kind', label: 'Type' },
          { key: 'normalized_value', label: 'Value' },
          { key: 'validity_status', label: 'Valid' },
          { key: 'consent_status', label: 'Consent' },
        ]} rows={detail.contact_methods || []} />
        <DataTable columns={[
          { key: 'source', label: 'Source' },
          { key: 'external_type', label: 'Type' },
          { key: 'external_id', label: 'External ID' },
          { key: 'match_basis', label: 'Match' },
        ]} rows={detail.external_records || []} />
        <DataTable columns={[
          { key: 'recommendation_type', label: 'Recommendation' },
          { key: 'status', label: 'Status', render: (r) => <Badge tone="accent">{r.status}</Badge> },
          { key: 'risk_level', label: 'Risk' },
          { key: 'confidence', label: 'Confidence' },
        ]} rows={detail.recommendations || []} />
        <DataTable columns={[
          { key: 'event_type', label: 'Event' },
          { key: 'source', label: 'Source' },
          { key: 'evidence', label: 'Evidence' },
        ]} rows={detail.consent_events || []} />
      </div>
    </section>
  )
}

export default function Registry() {
  const { getToken } = useAuth()
  const [tab, setTab] = useState('Overview')
  const [summary, setSummary] = useState(null)
  const [households, setHouseholds] = useState([])
  const [people, setPeople] = useState([])
  const [recommendations, setRecommendations] = useState([])
  const [events, setEvents] = useState([])
  const [connections, setConnections] = useState([])
  const [leadHygieneReports, setLeadHygieneReports] = useState([])
  const [selectedReportId, setSelectedReportId] = useState('')
  const [query, setQuery] = useState('')
  const [searchResults, setSearchResults] = useState(null)
  const [detail, setDetail] = useState(null)
  const [importResult, setImportResult] = useState(null)
  const [importMessage, setImportMessage] = useState('')
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
      let detailText = ''
      try { detailText = (await res.json()).detail } catch {}
      throw new Error(detailText || `HTTP ${res.status}`)
    }
    return res.json()
  }, [getToken])

  const loadCore = useCallback(async () => {
    setError('')
    try {
      const [sum, hh, pp, recs, evs, conns, hygieneReports] = await Promise.all([
        authFetch(`${API_BASE}/summary`),
        authFetch(`${API_BASE}/households?limit=50`),
        authFetch(`${API_BASE}/people?limit=50`),
        authFetch(`${API_BASE}/recommendations?limit=50`),
        authFetch(`${API_BASE}/consent-events?limit=50`),
        authFetch(`${API_BASE}/connections`),
        authFetch(`${API_BASE}/lead-hygiene-reports?limit=50`),
      ])
      setSummary(sum)
      setHouseholds(hh)
      setPeople(pp)
      setRecommendations(recs)
      setEvents(evs)
      setConnections(conns)
      setLeadHygieneReports(hygieneReports)
    } catch (e) {
      setError(e.message)
    }
  }, [authFetch])

  useEffect(() => { loadCore() }, [loadCore])

  useEffect(() => {
    if (selectedReportId && leadHygieneReports.some((report) => report.job_id === selectedReportId)) return
    const firstImportable = leadHygieneReports.find((report) => report.importable)
    setSelectedReportId(firstImportable?.job_id || leadHygieneReports[0]?.job_id || '')
  }, [leadHygieneReports, selectedReportId])

  const counts = summary?.counts || {}
  const highRisk = useMemo(() => recommendations.filter((r) => r.risk_level === 'high'), [recommendations])
  const selectedReport = useMemo(
    () => leadHygieneReports.find((report) => report.job_id === selectedReportId) || null,
    [leadHygieneReports, selectedReportId],
  )

  async function runSearch(e) {
    e?.preventDefault()
    if (!query.trim()) return
    setLoading(true)
    setError('')
    try {
      setSearchResults(await authFetch(`${API_BASE}/search?q=${encodeURIComponent(query.trim())}`))
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  async function loadHousehold(row) {
    setError('')
    try {
      setDetail(await authFetch(`${API_BASE}/households/${row.household_id || row.id}`))
    } catch (e) {
      setError(e.message)
    }
  }

  async function importReport(e) {
    e.preventDefault()
    if (!selectedReport) {
      setImportMessage('No Lead Hygiene report is selected.')
      return
    }
    if (!selectedReport.importable) {
      setImportMessage(selectedReport.has_json_report
        ? 'Selected Lead Hygiene job is not completed yet.'
        : 'Selected Lead Hygiene job does not have a completed JSON report yet.')
      return
    }
    setLoading(true)
    setError('')
    setImportResult(null)
    setImportMessage('')
    try {
      const data = await authFetch(`${API_BASE}/imports/lead-hygiene/${selectedReport.job_id}`, { method: 'POST', body: '{}' })
      setImportResult(data)
      setImportMessage(importSummaryText(data))
      await loadCore()
    } catch (err) {
      setImportMessage(err.message)
    } finally {
      setLoading(false)
    }
  }

  const importPanel = (
    <section className="section" style={{ marginBottom: '1rem' }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '0.75rem', flexWrap: 'wrap', marginBottom: '0.75rem' }}>
        <div className="section-title" style={{ marginBottom: 0 }}>Lead Hygiene Reports</div>
        <Badge>local DB only</Badge>
      </div>
      {leadHygieneReports.length === 0 ? (
        <Empty label="No Lead Hygiene reports found yet. Run a hygiene audit below, then refresh this list to import it into Registry." />
      ) : (
        <form onSubmit={importReport} style={{ display: 'grid', gap: '0.75rem' }}>
          <div style={{ display: 'grid', gridTemplateColumns: 'minmax(260px, 1fr) auto', gap: '0.5rem', alignItems: 'center' }}>
            <select
              className="input"
              value={selectedReportId}
              onChange={(e) => {
                setSelectedReportId(e.target.value)
                setImportMessage('')
              }}
              style={{ minWidth: 0 }}
            >
              {leadHygieneReports.map((report) => (
                <option key={report.job_id} value={report.job_id}>
                  {report.label}{report.importable ? '' : ' - not importable'}
                </option>
              ))}
            </select>
            <button className="btn-primary" type="submit" disabled={loading || !selectedReport?.importable}>
              {loading ? 'Importing...' : 'Import Selected'}
            </button>
          </div>
          {selectedReport && (
            <div style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap', alignItems: 'center' }}>
              <Badge tone={selectedReport.importable ? 'green' : 'amber'}>{selectedReport.status}</Badge>
              <Badge>{selectedReport.source_label || 'Lead Hygiene'}</Badge>
              <span style={{ color: 'var(--text-muted)', fontFamily: 'var(--font-mono)', fontSize: '0.72rem' }}>
                Job {selectedReport.short_job_id}
              </span>
            </div>
          )}
          {selectedReport && !selectedReport.importable && (
            <p style={{ color: 'var(--amber)', fontFamily: 'var(--font-mono)', fontSize: '0.75rem', margin: 0 }}>
              {selectedReport.has_json_report
                ? 'This report cannot be imported until the job is completed.'
                : 'This job has no completed JSON report yet. Import is disabled.'}
            </p>
          )}
          {importMessage && (
            <p style={{ color: importResult ? 'var(--green)' : 'var(--amber)', fontFamily: 'var(--font-mono)', fontSize: '0.75rem', margin: 0 }}>
              {importMessage}
            </p>
          )}
        </form>
      )}
    </section>
  )

  return (
    <div className="dashboard" style={{ maxWidth: 1180 }}>
      <section style={{ marginBottom: '1rem' }}>
        <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: '1rem', flexWrap: 'wrap' }}>
          <div>
            <div style={{ marginBottom: '0.5rem' }}><Badge tone="accent">REGISTRY V1 REVIEW ONLY</Badge></div>
            <h1 style={{ fontFamily: 'var(--font-display)', fontSize: '1.75rem', lineHeight: 1.1, margin: 0 }}>Lead Registry</h1>
            <p style={{ color: 'var(--text-muted)', fontFamily: 'var(--font-mono)', fontSize: '0.78rem', marginTop: '0.4rem' }}>
              Parent identity workspace for households, people, source links, recommendations, and consent evidence.
            </p>
          </div>
          <button className="btn-secondary" type="button" onClick={loadCore}>Refresh</button>
        </div>
        {error && <p style={{ color: 'var(--red)', marginTop: '0.75rem', fontFamily: 'var(--font-mono)', fontSize: '0.78rem' }}>{error}</p>}
      </section>

      <section style={{ marginBottom: '1rem' }}>
        <div style={{ display: 'flex', gap: '0.45rem', flexWrap: 'wrap' }}>
          {TABS.map((name) => (
            <button
              key={name}
              type="button"
              onClick={() => setTab(name)}
              className={tab === name ? 'btn-primary' : 'btn-secondary'}
              style={{ padding: '0.4rem 0.65rem' }}
            >
              {name}
            </button>
          ))}
        </div>
      </section>

      {tab === 'Overview' && (
        <>
          <section className="stats-grid" style={{ marginBottom: '1rem' }}>
            <Stat label="Households" value={counts.households} />
            <Stat label="People" value={counts.people} />
            <Stat label="Contacts" value={counts.contact_methods} />
            <Stat label="Recommendations" value={counts.recommendations} />
          </section>
          {importPanel}
          <section className="section">
            <div className="section-title">Recent Recommendations</div>
            <DataTable columns={[
              { key: 'recommendation_type', label: 'Type' },
              { key: 'risk_level', label: 'Risk', render: (r) => <Badge tone={r.risk_level === 'high' ? 'red' : r.risk_level === 'medium' ? 'amber' : 'green'}>{r.risk_level}</Badge> },
              { key: 'status', label: 'Status' },
              { key: 'confidence', label: 'Confidence' },
            ]} rows={recommendations.slice(0, 8)} onRowClick={loadHousehold} />
          </section>
        </>
      )}

      {tab === 'Search' && (
        <section className="section">
          <div className="section-title">Search Registry</div>
          <form onSubmit={runSearch} style={{ display: 'flex', gap: '0.5rem', marginBottom: '1rem', flexWrap: 'wrap' }}>
            <input className="input" value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Name, phone, email, or external ID" style={{ minWidth: 320 }} />
            <button className="btn-primary" type="submit" disabled={loading}>{loading ? 'Searching...' : 'Search'}</button>
          </form>
          {searchResults && (
            <div style={{ display: 'grid', gap: '1rem' }}>
              <DataTable columns={[{ key: 'display_name', label: 'Household' }, { key: 'risk_level', label: 'Risk' }, { key: 'primary_phone', label: 'Phone' }, { key: 'primary_email', label: 'Email' }]} rows={searchResults.households} onRowClick={loadHousehold} />
              <DataTable columns={[{ key: 'display_name', label: 'People' }, { key: 'role', label: 'Role' }, { key: 'consent_status', label: 'Consent' }]} rows={searchResults.people} onRowClick={loadHousehold} />
              <DataTable columns={[{ key: 'kind', label: 'Contact' }, { key: 'normalized_value', label: 'Value' }, { key: 'consent_status', label: 'Consent' }]} rows={searchResults.contact_methods} onRowClick={loadHousehold} />
            </div>
          )}
          <DetailPanel title="Selected Household" detail={detail} />
        </section>
      )}

      {tab === 'Households' && (
        <>
          <section className="section">
            <div className="section-title">Households</div>
            <DataTable columns={[
              { key: 'display_name', label: 'Name' },
              { key: 'risk_level', label: 'Risk', render: (r) => <Badge tone={r.risk_level === 'high' ? 'red' : r.risk_level === 'medium' ? 'amber' : 'green'}>{r.risk_level}</Badge> },
              { key: 'primary_phone', label: 'Phone' },
              { key: 'primary_email', label: 'Email' },
              { key: 'derived_from', label: 'Source' },
            ]} rows={households} onRowClick={loadHousehold} />
          </section>
          <DetailPanel title="Household Detail" detail={detail} />
        </>
      )}

      {tab === 'People' && (
        <section className="section">
          <div className="section-title">People</div>
          <DataTable columns={[
            { key: 'display_name', label: 'Name' },
            { key: 'role', label: 'Role' },
            { key: 'dnc_status', label: 'DNC' },
            { key: 'consent_status', label: 'Consent' },
          ]} rows={people} onRowClick={loadHousehold} />
        </section>
      )}

      {tab === 'Hygiene' && (
        <>
          {importPanel}
          <LeadHygiene onReportsChanged={loadCore} />
        </>
      )}

      {tab === 'Conflicts' && (
        <section className="section">
          <div className="section-title">Conflicts</div>
          <DataTable columns={[
            { key: 'recommendation_type', label: 'Conflict' },
            { key: 'risk_level', label: 'Risk' },
            { key: 'status', label: 'Status' },
            { key: 'confidence', label: 'Confidence' },
          ]} rows={highRisk} onRowClick={loadHousehold} />
        </section>
      )}

      {tab === 'Apply Queue' && (
        <section className="section">
          <div className="section-title">Apply Queue</div>
          <p style={{ color: 'var(--text-muted)', fontFamily: 'var(--font-mono)', fontSize: '0.78rem', marginBottom: '1rem' }}>
            Review only. External writes and automated merges are locked in Registry v1.
          </p>
          <DataTable columns={[
            { key: 'recommendation_type', label: 'Action' },
            { key: 'risk_level', label: 'Risk' },
            { key: 'status', label: 'Status' },
            { key: 'locked', label: 'Apply', render: () => <button className="btn-secondary" disabled>Locked</button> },
          ]} rows={recommendations} />
        </section>
      )}

      {tab === 'Audit Log' && (
        <section className="section">
          <div className="section-title">Consent Evidence</div>
          <DataTable columns={[
            { key: 'event_type', label: 'Event' },
            { key: 'source', label: 'Source' },
            { key: 'evidence', label: 'Evidence' },
            { key: 'observed_at', label: 'Observed' },
          ]} rows={events} onRowClick={loadHousehold} />
        </section>
      )}

      {tab === 'Connections' && (
        <section className="section">
          <div className="section-title">Connections</div>
          <DataTable columns={[
            { key: 'source', label: 'Source' },
            { key: 'configured', label: 'Configured', render: (r) => <Badge tone={r.configured ? 'green' : 'muted'}>{r.configured ? 'yes' : 'no'}</Badge> },
            { key: 'mode', label: 'Mode' },
            { key: 'secret', label: 'Secret' },
          ]} rows={connections} />
          <div style={{ display: 'grid', gap: '0.6rem', marginTop: '1rem', maxWidth: 520 }}>
            {connections.map((conn) => (
              <label key={conn.source} style={{ display: 'grid', gap: '0.25rem', color: 'var(--text-muted)', fontFamily: 'var(--font-mono)', fontSize: '0.68rem', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
                {conn.source} credential
                <input className="input" disabled value={conn.configured ? 'Configured in server environment' : 'Not configured'} readOnly />
              </label>
            ))}
          </div>
        </section>
      )}
    </div>
  )
}
