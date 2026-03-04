import { useState } from 'react'
import { useAuth } from '@clerk/clerk-react'

function DryRunReport() {
  const [results, setResults] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)

  // Try to use Clerk auth if available, otherwise make unauthenticated requests
  let getToken = null
  try {
    const auth = useAuth()
    getToken = auth.getToken
  } catch {
    // Clerk not configured — that's fine, backend allows unauthenticated in dev mode
  }

  const runDryRun = async () => {
    setLoading(true)
    setError(null)
    setResults(null)

    try {
      const headers = { 'Content-Type': 'application/json' }

      if (getToken) {
        try {
          const token = await getToken()
          if (token) {
            headers['Authorization'] = `Bearer ${token}`
          }
        } catch {
          // Token fetch failed — try without auth
        }
      }

      const resp = await fetch('/api/sync/notion-to-ghl/dry-run', {
        method: 'POST',
        headers,
      })

      if (!resp.ok) {
        throw new Error(`HTTP ${resp.status}: ${resp.statusText}`)
      }

      const data = await resp.json()
      setResults(data)
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  return (
    <section className="section">
      <h2 className="section-title">Notion → GHL Sync (Dry Run)</h2>
      <p className="section-desc">
        Preview which appointments would be pushed to GHL. No data is modified.
      </p>

      <button
        className="btn btn-primary"
        onClick={runDryRun}
        disabled={loading}
      >
        {loading ? 'Running...' : 'Run Dry Run'}
      </button>

      {error && (
        <div className="alert alert-error">
          <strong>Error:</strong> {error}
        </div>
      )}

      {results && (
        <div style={{ marginTop: '1rem' }}>
          <div className="results-meta">
            <span>Mode: <strong>{results.mode}</strong></span>
            <span>After date: <strong>{results.sync_after_date}</strong></span>
            <span>Found: <strong>{results.appointments_found}</strong> appointments</span>
          </div>

          {results.results.length > 0 ? (
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
                {results.results.map((r, idx) => (
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
          ) : (
            <p className="no-results">No appointments found matching criteria.</p>
          )}
        </div>
      )}
    </section>
  )
}

export default DryRunReport
