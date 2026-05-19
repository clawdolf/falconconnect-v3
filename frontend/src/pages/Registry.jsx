import { useCallback, useEffect, useMemo, useState } from 'react'
import { useAuthSafe as useAuth } from '../hooks/useClerkSafe'
import LeadHygiene from '../components/LeadHygiene'
import ActiveFilterBanner from '../components/registry/ActiveFilterBanner'
import HouseholdDrawer from '../components/registry/HouseholdDrawer'
import HouseholdTable from '../components/registry/HouseholdTable'
import RegistryFlow from '../components/registry/RegistryFlow'
import SourceCoverage from '../components/registry/SourceCoverage'
import { Badge, DataTable, Empty, RiskBadge, Stat } from '../components/registry/RegistryBadges'

const API_BASE = '/api/admin/registry'
const TABS = ['Overview', 'Households', 'Hygiene', 'Conflicts', 'Connections']

function importSummaryText(result) {
  if (!result) return ''
  return `Imported ${result.rows_seen} rows. New households: ${result.households_created}; people: ${result.people_created}; contacts: ${result.contact_methods_created}; recommendations: ${result.recommendations_created}.`
}

function paramsFromFilters(filters) {
  const params = new URLSearchParams({ limit: '100', sort: filters.sort || 'latest' })
  for (const key of ['q', 'risk', 'source', 'bucket']) {
    if (filters[key]) params.set(key, filters[key])
  }
  if (filters.has_conflict) params.set('has_conflict', 'true')
  return params.toString()
}

export default function Registry() {
  const { getToken } = useAuth()
  const [tab, setTab] = useState('Overview')
  const [summary, setSummary] = useState(null)
  const [flow, setFlow] = useState(null)
  const [households, setHouseholds] = useState([])
  const [recommendations, setRecommendations] = useState([])
  const [connections, setConnections] = useState([])
  const [leadHygieneReports, setLeadHygieneReports] = useState([])
  const [selectedReportId, setSelectedReportId] = useState('')
  const [query, setQuery] = useState('')
  const [searchResults, setSearchResults] = useState(null)
  const [detail, setDetail] = useState(null)
  const [filters, setFilters] = useState({ sort: 'latest' })
  const [activeFilter, setActiveFilter] = useState(null)
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

  const loadHouseholds = useCallback(async (nextFilters = filters) => {
    const data = await authFetch(`${API_BASE}/households?${paramsFromFilters(nextFilters)}`)
    setHouseholds(data)
  }, [authFetch, filters])

  const loadCore = useCallback(async () => {
    setError('')
    try {
      const [sum, sankey, recs, conns, hygieneReports] = await Promise.all([
        authFetch(`${API_BASE}/summary`),
        authFetch(`${API_BASE}/sankey`),
        authFetch(`${API_BASE}/recommendations?limit=50`),
        authFetch(`${API_BASE}/connections`),
        authFetch(`${API_BASE}/lead-hygiene-reports?limit=50`),
      ])
      setSummary(sum)
      setFlow(sankey)
      setRecommendations(recs)
      setConnections(conns)
      setLeadHygieneReports(hygieneReports)
      await loadHouseholds(filters)
    } catch (e) {
      setError(e.message)
    }
  }, [authFetch, filters, loadHouseholds])

  useEffect(() => { loadCore() }, [loadCore])

  useEffect(() => {
    if (selectedReportId && leadHygieneReports.some((report) => report.job_id === selectedReportId)) return
    const firstImportable = leadHygieneReports.find((report) => report.importable)
    setSelectedReportId(firstImportable?.job_id || leadHygieneReports[0]?.job_id || '')
  }, [leadHygieneReports, selectedReportId])

  const counts = summary?.counts || {}
  const highRisk = useMemo(() => recommendations.filter((row) => row.risk_level === 'high'), [recommendations])
  const selectedReport = useMemo(
    () => leadHygieneReports.find((report) => report.job_id === selectedReportId) || null,
    [leadHygieneReports, selectedReportId],
  )

  async function applyFilters(nextFilters, filterMeta) {
    const merged = { ...filters, ...nextFilters }
    setFilters(merged)
    if (filterMeta !== undefined) setActiveFilter(filterMeta)
    setTab('Households')
    setError('')
    try {
      await loadHouseholds(merged)
    } catch (err) {
      setError(err.message)
    }
  }

  async function clearFilters() {
    const next = { sort: 'latest' }
    setFilters(next)
    setActiveFilter(null)
    await loadHouseholds(next)
  }

  async function runSearch(e) {
    e?.preventDefault()
    const trimmed = query.trim()
    if (!trimmed) return
    setLoading(true)
    setError('')
    try {
      const data = await authFetch(`${API_BASE}/search?q=${encodeURIComponent(trimmed)}`)
      setSearchResults(data)
      setTab('Households')
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
            <select className="input" value={selectedReportId} onChange={(e) => { setSelectedReportId(e.target.value); setImportMessage('') }} style={{ minWidth: 0 }}>
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
              <span style={{ color: 'var(--text-muted)', fontFamily: 'var(--font-mono)', fontSize: '0.72rem' }}>Job {selectedReport.short_job_id}</span>
            </div>
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
    <div className="dashboard registry-dashboard" style={{ maxWidth: 1480 }}>
      <section style={{ marginBottom: '1rem' }}>
        <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: '1rem', flexWrap: 'wrap' }}>
          <div>
            <div style={{ marginBottom: '0.5rem' }}><Badge tone="accent">REGISTRY V1 REVIEW ONLY</Badge></div>
            <h1 style={{ fontFamily: 'var(--font-display)', fontSize: '1.75rem', lineHeight: 1.1, margin: 0 }}>Lead Registry</h1>
            <p style={{ color: 'var(--text-muted)', fontFamily: 'var(--font-mono)', fontSize: '0.78rem', marginTop: '0.4rem' }}>
              Household identity workspace for source attribution, recommendations, and consent evidence.
            </p>
          </div>
          <form onSubmit={runSearch} style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap', justifyContent: 'flex-end' }}>
            <input className="input" value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Search name, phone, email, or source ID" style={{ minWidth: 300 }} />
            <button className="btn-secondary" type="submit" disabled={loading}>{loading ? 'Searching...' : 'Search'}</button>
            <button className="btn-secondary" type="button" onClick={loadCore}>Refresh</button>
          </form>
        </div>
        {error && <p style={{ color: 'var(--red)', marginTop: '0.75rem', fontFamily: 'var(--font-mono)', fontSize: '0.78rem' }}>{error}</p>}
      </section>

      <section style={{ marginBottom: '1rem' }}>
        <div style={{ display: 'flex', gap: '0.45rem', flexWrap: 'wrap' }}>
          {TABS.map((name) => (
            <button key={name} type="button" onClick={() => setTab(name)} className={tab === name ? 'btn-primary' : 'btn-secondary'} style={{ padding: '0.4rem 0.65rem' }}>
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
          <section className="section" style={{ marginBottom: '1rem' }}>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '1rem', marginBottom: '0.75rem' }}>
              <div className="section-title" style={{ marginBottom: 0 }}>Registry Attribution Flow</div>
              <Badge>{flow?.totals?.households || 0} households</Badge>
            </div>
            <ActiveFilterBanner filter={activeFilter} onClear={clearFilters} />
            <div className="registry-attribution-grid">
              <RegistryFlow data={flow} onFilter={applyFilters} activeFilter={activeFilter} />
              <div className="registry-source-coverage-panel">
                <div className="section-title" style={{ marginBottom: '0.75rem', paddingBottom: '0.5rem' }}>Source Coverage</div>
                <SourceCoverage rows={flow?.source_coverage || []} />
              </div>
            </div>
          </section>
          {importPanel}
          <section className="section">
            <div className="section-title">Recent Recommendations</div>
            <DataTable columns={[
              { key: 'recommendation_type', label: 'Type' },
              { key: 'risk_level', label: 'Risk', render: (row) => <RiskBadge value={row.risk_level} /> },
              { key: 'status', label: 'Status' },
              { key: 'confidence', label: 'Confidence' },
            ]} rows={recommendations.slice(0, 8)} onRowClick={loadHousehold} />
          </section>
        </>
      )}

      {tab === 'Households' && (
        <section className="section">
          <ActiveFilterBanner filter={activeFilter} onClear={clearFilters} />
          <div style={{ display: 'flex', justifyContent: 'space-between', gap: '1rem', flexWrap: 'wrap', alignItems: 'center', marginBottom: '0.75rem' }}>
            <div className="section-title" style={{ marginBottom: 0 }}>Households</div>
            <div style={{ display: 'flex', gap: '0.4rem', flexWrap: 'wrap' }}>
              <button className={filters.risk === 'high' ? 'btn-primary' : 'btn-secondary'} type="button" onClick={() => applyFilters({ risk: filters.risk === 'high' ? '' : 'high' }, filters.risk === 'high' ? null : { type: 'Risk', label: 'High' })}>High Risk</button>
              <button className={filters.has_conflict ? 'btn-primary' : 'btn-secondary'} type="button" onClick={() => applyFilters({ has_conflict: !filters.has_conflict }, filters.has_conflict ? null : { type: 'Signal', label: 'Conflicts' })}>Conflicts</button>
              <button className="btn-secondary" type="button" onClick={clearFilters}>Clear</button>
            </div>
          </div>
          <HouseholdTable rows={households} onOpen={loadHousehold} />
          {searchResults && (
            <div style={{ marginTop: '1rem', display: 'grid', gap: '0.75rem' }}>
              <div className="section-title">Search Matches</div>
              <HouseholdTable rows={searchResults.households || []} onOpen={loadHousehold} />
              <DataTable columns={[
                { key: 'display_name', label: 'People' },
                { key: 'role', label: 'Role' },
                { key: 'consent_status', label: 'Consent' },
              ]} rows={searchResults.people || []} onRowClick={loadHousehold} minWidth={520} />
            </div>
          )}
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
            { key: 'risk_level', label: 'Risk', render: (row) => <RiskBadge value={row.risk_level} /> },
            { key: 'status', label: 'Status' },
            { key: 'confidence', label: 'Confidence' },
          ]} rows={highRisk} onRowClick={loadHousehold} />
        </section>
      )}

      {tab === 'Connections' && (
        <section className="section">
          <div className="section-title">Connections</div>
          <DataTable columns={[
            { key: 'source', label: 'Source' },
            { key: 'configured', label: 'Configured', render: (row) => <Badge tone={row.configured ? 'green' : 'muted'}>{row.configured ? 'yes' : 'no'}</Badge> },
            { key: 'mode', label: 'Mode' },
            { key: 'secret', label: 'Secret' },
          ]} rows={connections} />
        </section>
      )}

      <HouseholdDrawer detail={detail} onClose={() => setDetail(null)} />
    </div>
  )
}
