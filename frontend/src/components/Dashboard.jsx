import { useState, useEffect } from 'react'
import CalendarLinks from './CalendarLinks'
import DryRunReport from './DryRunReport'
import QuickAddLead from './QuickAddLead'

function Dashboard() {
  const [health, setHealth] = useState(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    fetch('/health')
      .then(r => r.json())
      .then(data => {
        setHealth(data)
        setLoading(false)
      })
      .catch(() => setLoading(false))
  }, [])

  const statusColor = (val) => {
    if (val === 'healthy') return 'c-green'
    if (val === 'degraded') return 'c-amber'
    return 'c-red'
  }

  const statusDot = (val) => {
    if (val === 'healthy') return 'healthy'
    if (val === 'degraded') return 'warning'
    return 'error'
  }

  return (
    <div className="dashboard">
      {/* Service Health */}
      <section className="section">
        <h2 className="section-title" style={{ display: 'flex', alignItems: 'center', gap: '0.6rem' }}>
          Service Status
          <QuickAddLead />
        </h2>
        {loading ? (
          <p className="loading-text">Loading...</p>
        ) : health ? (
          <div className="status-grid">
            <div className="status-cell">
              <div className="status-label">Status</div>
              <div className={`status-value ${statusColor(health.status)}`}>
                <span className={`status-dot ${statusDot(health.status)}`} />
                {health.status}
              </div>
            </div>
            <div className="status-cell">
              <div className="status-label">Version</div>
              <div className="status-value">{health.version}</div>
            </div>
            <div className="status-cell">
              <div className="status-label">Sync</div>
              <div className={`status-value ${health.sync_enabled ? 'c-green' : 'c-red'}`}>
                {health.sync_enabled ? (health.sync_dry_run ? 'Dry Run' : 'Live') : 'Disabled'}
              </div>
            </div>
          </div>
        ) : (
          <p className="loading-text c-red">Unable to reach service</p>
        )}
      </section>

      {/* Calendar Links */}
      <CalendarLinks />

      {/* Dry Run */}
      <DryRunReport />
    </div>
  )
}

export default Dashboard
