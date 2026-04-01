import { useState, useEffect } from 'react'
import { useAuthSafe as useAuth } from '../hooks/useClerkSafe'

function SyncManagement() {
  const [syncStatus, setSyncStatus] = useState(null)
  const [statusLoading, setStatusLoading] = useState(true)
  const [statusError, setStatusError] = useState(null)

  const [dryRunResults, setDryRunResults] = useState(null)
  const [dryRunLoading, setDryRunLoading] = useState(false)
  const [dryRunError, setDryRunError] = useState(null)

  const [liveResults, setLiveResults] = useState(null)
  const [liveLoading, setLiveLoading] = useState(false)
  const [liveError, setLiveError] = useState(null)

  let getToken = null
  try {
    const auth = useAuth()
    getToken = auth.getToken
  } catch {
    // Clerk not configured
  }

  const getHeaders = async () => {
    const headers = { 'Content-Type': 'application/json' }
    if (getToken) {
      try {
        const token = await getToken()
        if (token) headers['Authorization'] = `Bearer ${token}`
      } catch { /* no-op */ }
    }
    return headers
  }

  const fetchStatus = async () => {
    setStatusLoading(true)
    setStatusError(null)
    try {
      const headers = await getHeaders()
      const resp = await fetch('/api/sync/status', { headers })
      if (!resp.ok) throw new Error(`HTTP ${resp.status}: ${resp.statusText}`)
      const data = await resp.json()
      setSyncStatus(data)
    } catch (err) {
      setStatusError(err.message)
    } finally {
      setStatusLoading(false)
    }
  }

  useEffect(() => { fetchStatus() }, [])

  const runDryRun = async () => {
    setDryRunLoading(true)
    setDryRunError(null)
    setDryRunResults(null)
    try {
      const headers = await getHeaders()
      const resp = await fetch('/api/sync/notion-to-ghl/dry-run', {
        method: 'POST',
        headers,
      })
      if (!resp.ok) throw new Error(`HTTP ${resp.status}: ${resp.statusText}`)
      const data = await resp.json()
      setDryRunResults(data)
    } catch (err) {
      setDryRunError(err.message)
    } finally {
      setDryRunLoading(false)
    }
  }

  const runLiveSync = async () => {
    if (!window.confirm('This will WRITE to GHL. Appointments will be created/updated. Continue?')) return
    setLiveLoading(true)
    setLiveError(null)
    setLiveResults(null)
    try {
      const headers = await getHeaders()
      const resp = await fetch('/api/sync/notion-to-ghl/live', {
        method: 'POST',
        headers,
      })
      if (!resp.ok) throw new Error(`HTTP ${resp.status}: ${resp.statusText}`)
      const data = await resp.json()
      setLiveResults(data)
    } catch (err) {
      setLiveError(err.message)
    } finally {
      setLiveLoading(false)
    }
  }

  const modeClass = syncStatus
    ? syncStatus.dry_run ? 'badge-warn' : (syncStatus.sync_enabled ? 'badge-success' : 'badge-error')
    : 'badge-info'

  const modeLabel = syncStatus
    ? syncStatus.dry_run ? 'DRY RUN' : (syncStatus.sync_enabled ? 'LIVE' : 'DISABLED')
    : '...'

  return (
    <div className="dashboard">
      {/* Sync Status */}
      <section className="section">
        <div className="section-header-row" style={{ marginBottom: '1rem' }}>
          <h2 className="section-title" style={{ marginBottom: 0, paddingBottom: 0, borderBottom: 'none' }}>
            Sync Status
          </h2>
          <span className={`badge ${modeClass}`}>{modeLabel}</span>
        </div>

        {statusError && (
          <div className="alert alert-error">
            <strong>Error:</strong> {statusError}
          </div>
        )}

        {statusLoading ? (
          <p className="loading-text">Loading...</p>
        ) : syncStatus ? (
          <div className="status-grid">
            <div className="status-cell">
              <div className="status-label">Sync Enabled</div>
              <div className={`status-value ${syncStatus.sync_enabled ? 'c-green' : 'c-red'}`}>
                <span className={`status-dot ${syncStatus.sync_enabled ? 'healthy' : 'error'}`} />
                {syncStatus.sync_enabled ? 'Yes' : 'No'}
              </div>
            </div>
            <div className="status-cell">
              <div className="status-label">Mode</div>
              <div className={`status-value ${syncStatus.dry_run ? 'c-amber' : 'c-green'}`}>
                {syncStatus.dry_run ? 'Dry Run' : 'Live'}
              </div>
            </div>
            <div className="status-cell">
              <div className="status-label">Sync After</div>
              <div className="status-value">{syncStatus.sync_after_date || '—'}</div>
            </div>
            <div className="status-cell">
              <div className="status-label">Poll Interval</div>
              <div className="status-value">{syncStatus.poll_interval_seconds}s</div>
            </div>
            <div className="status-cell">
              <div className="status-label">Clerk</div>
              <div className={`status-value ${syncStatus.clerk_configured ? 'c-green' : 'c-amber'}`}>
                {syncStatus.clerk_configured ? 'Configured' : 'Not configured'}
              </div>
            </div>
            <div className="status-cell">
              <div className="status-label">Timestamp</div>
              <div className="status-value">
                {syncStatus.timestamp ? new Date(syncStatus.timestamp).toLocaleString() : '—'}
              </div>
            </div>
          </div>
        ) : null}
      </section>

      {/* Dry Run */}
      <section className="section">
        <h2 className="section-title">Notion → GHL Sync (Dry Run)</h2>
        <p className="section-desc">
          Preview which appointments would be pushed to GHL. No data is modified.
        </p>

        <button
          className="btn btn-primary"
          onClick={runDryRun}
          disabled={dryRunLoading}
        >
          {dryRunLoading ? 'Running...' : 'Run Dry Run'}
        </button>

        {dryRunError && (
          <div className="alert alert-error">
            <strong>Error:</strong> {dryRunError}
          </div>
        )}

        {dryRunResults && (
          <div style={{ marginTop: '1rem' }}>
            <div className="results-meta">
              <span>Mode: <strong>{dryRunResults.mode}</strong></span>
              <span>After date: <strong>{dryRunResults.sync_after_date}</strong></span>
              <span>Found: <strong>{dryRunResults.appointments_found}</strong> appointments</span>
            </div>

            {dryRunResults.results && dryRunResults.results.length > 0 ? (
              <div className="table-scroll-wrapper">
              <table className="results-table">
                <thead>
                  <tr>
                    <th>Name</th>
                    <th>Phone</th>
                    <th>Appointment Date</th>
                    <th>Action</th>
                  </tr>
                </thead>
                <tbody>
                  {dryRunResults.results.map((r, idx) => (
                    <tr key={idx}>
                      <td>{r.name}</td>
                      <td>{r.phone}</td>
                      <td>{r.appointment_date}</td>
                      <td>
                        <span className={`badge ${r.dry_run ? 'badge-info' : 'badge-success'}`}>
                          {r.action}
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              </div>
            ) : (
              <p className="no-results">No appointments found matching criteria.</p>
            )}
          </div>
        )}
      </section>

      {/* Live Sync — Bug 10 fix */}
      <section className="section">
        <h2 className="section-title">Notion → GHL Sync (Live)</h2>
        <p className="section-desc">
          Push appointments to GHL for real. This creates/updates actual calendar events.
        </p>

        <button
          className="btn btn-primary"
          style={{ backgroundColor: '#dc2626' }}
          onClick={runLiveSync}
          disabled={liveLoading}
        >
          {liveLoading ? 'Syncing...' : 'Run Live Sync'}
        </button>

        {liveError && (
          <div className="alert alert-error">
            <strong>Error:</strong> {liveError}
          </div>
        )}

        {liveResults && (
          <div style={{ marginTop: '1rem' }}>
            <div className="results-meta">
              <span>Mode: <strong><span className="badge badge-error">LIVE</span></strong></span>
              <span>After date: <strong>{liveResults.sync_after_date}</strong></span>
              <span>Processed: <strong>{liveResults.appointments_found}</strong> appointments</span>
            </div>

            {liveResults.results && liveResults.results.length > 0 ? (
              <div className="table-scroll-wrapper">
              <table className="results-table">
                <thead>
                  <tr>
                    <th>Name</th>
                    <th>Phone</th>
                    <th>Appointment Date</th>
                    <th>Action</th>
                  </tr>
                </thead>
                <tbody>
                  {liveResults.results.map((r, idx) => (
                    <tr key={idx}>
                      <td>{r.name}</td>
                      <td>{r.phone}</td>
                      <td>{r.appointment_date}</td>
                      <td>
                        <span className={`badge ${r.action === 'created' ? 'badge-success' : r.action === 'failed' ? 'badge-error' : 'badge-warn'}`}>
                          {r.action}
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              </div>
            ) : (
              <p className="no-results">No appointments found matching criteria.</p>
            )}
          </div>
        )}
      </section>
    </div>
  )
}

export default SyncManagement
