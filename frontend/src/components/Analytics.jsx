import { useState, useEffect } from 'react'
import { useAuth } from '@clerk/clerk-react'
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer } from 'recharts'

function Analytics() {
  const [days, setDays] = useState(30)
  const [summary, setSummary] = useState(null)
  const [daily, setDaily] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  // Google Sheets state
  const [sheetUrl, setSheetUrl] = useState(() => localStorage.getItem('fc_accountability_sheet') || '')
  const [sheetData, setSheetData] = useState(null)
  const [sheetLoading, setSheetLoading] = useState(false)
  const [sheetError, setSheetError] = useState(null)
  const [lastFetched, setLastFetched] = useState(() => localStorage.getItem('fc_accountability_last_fetched') || null)
  const [showSettings, setShowSettings] = useState(false)

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

  const fetchData = async (d) => {
    setLoading(true)
    setError(null)
    try {
      const headers = await getHeaders()
      const [sumResp, dailyResp] = await Promise.all([
        fetch(`/api/analytics/summary?days=${d}`, { headers }),
        fetch(`/api/analytics/daily?days=${d}`, { headers }),
      ])

      if (!sumResp.ok) throw new Error(`Summary: HTTP ${sumResp.status}`)
      if (!dailyResp.ok) throw new Error(`Daily: HTTP ${dailyResp.status}`)

      const sumData = await sumResp.json()
      const dailyData = await dailyResp.json()

      setSummary(sumData)
      setDaily(dailyData)
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { fetchData(days) }, [days])

  // Load cached sheet data on mount
  useEffect(() => {
    const cached = localStorage.getItem('fc_accountability_data')
    if (cached) {
      try { setSheetData(JSON.parse(cached)) } catch { /* ignore */ }
    }
  }, [])

  const saveSheetUrl = () => {
    localStorage.setItem('fc_accountability_sheet', sheetUrl)
    setShowSettings(false)
  }

  const fetchSheetData = async () => {
    if (!sheetUrl.trim()) { setSheetError('Set a Sheet URL first'); return }

    // Extract sheet ID
    const match = sheetUrl.match(/\/spreadsheets\/d\/([a-zA-Z0-9_-]+)/)
    const id = match ? match[1] : sheetUrl.trim()

    setSheetLoading(true)
    setSheetError(null)

    try {
      const headers = await getHeaders()
      const resp = await fetch(`/api/public/sheets/data?sheet_id=${encodeURIComponent(id)}`, { headers })

      if (resp.status === 404 || resp.status === 501) {
        // Backend doesn't have sheets endpoint yet - try parsing from localStorage mock
        setSheetError('Google Sheets API not configured on backend. Connect in a future update.')
        setSheetLoading(false)
        return
      }
      if (!resp.ok) throw new Error('Could not fetch sheet data')

      const data = await resp.json()
      const parsed = parseAccountabilityData(data.headers || [], data.rows || [])
      setSheetData(parsed)
      const now = new Date().toISOString()
      setLastFetched(now)
      localStorage.setItem('fc_accountability_data', JSON.stringify(parsed))
      localStorage.setItem('fc_accountability_last_fetched', now)
    } catch (err) {
      setSheetError(err.message)
    } finally {
      setSheetLoading(false)
    }
  }

  // Parse accountability tracker data - flexible column detection
  const parseAccountabilityData = (headers, rows) => {
    const colMap = {}
    const aliases = {
      date: ['date', 'day', 'dt'],
      dials: ['dials', 'dial', 'calls', 'call'],
      shows: ['shows', 'show', 'appts', 'appointments', 'appointments kept', 'appt kept', 'kept'],
      closes: ['closes', 'close', 'deals', 'deal', 'sold', 'sales'],
      revenue: ['revenue', 'premium', 'income', 'amount', '$', 'premium submitted'],
      notes: ['notes', 'note', 'comments'],
    }

    headers.forEach((h, i) => {
      const lw = h.toLowerCase().trim()
      for (const [field, terms] of Object.entries(aliases)) {
        if (terms.some(t => lw === t || lw.includes(t))) {
          if (!colMap[field]) colMap[field] = i
        }
      }
    })

    const days = []
    for (const row of rows) {
      const entry = {
        date: colMap.date !== undefined ? String(row[colMap.date] || '') : '',
        dials: colMap.dials !== undefined ? parseInt(row[colMap.dials], 10) || 0 : 0,
        shows: colMap.shows !== undefined ? parseInt(row[colMap.shows], 10) || 0 : 0,
        closes: colMap.closes !== undefined ? parseInt(row[colMap.closes], 10) || 0 : 0,
        revenue: colMap.revenue !== undefined ? parseFloat(String(row[colMap.revenue] || '0').replace(/[$,]/g, '')) || 0 : 0,
        notes: colMap.notes !== undefined ? String(row[colMap.notes] || '') : '',
      }
      if (entry.date || entry.dials > 0 || entry.closes > 0) days.push(entry)
    }

    // Compute aggregates
    const now = new Date()
    const today = now.toISOString().split('T')[0]
    const weekStart = new Date(now)
    weekStart.setDate(now.getDate() - now.getDay())
    const monthStart = new Date(now.getFullYear(), now.getMonth(), 1)
    const yearStart = new Date(now.getFullYear(), 0, 1)

    const isInRange = (dateStr, start) => {
      try {
        const d = new Date(dateStr)
        return d >= start && d <= now
      } catch { return false }
    }

    const todayData = days.filter(d => d.date === today || d.date.includes(today))
    const weekData = days.filter(d => isInRange(d.date, weekStart))
    const monthData = days.filter(d => isInRange(d.date, monthStart))
    const yearData = days.filter(d => isInRange(d.date, yearStart))

    const sum = (arr, field) => arr.reduce((s, d) => s + (d[field] || 0), 0)

    const totalDials = sum(days, 'dials')
    const totalShows = sum(days, 'shows')
    const totalCloses = sum(days, 'closes')

    // Weekly trend (last 8 weeks)
    const weeklyTrend = []
    for (let w = 7; w >= 0; w--) {
      const wStart = new Date(now)
      wStart.setDate(now.getDate() - now.getDay() - (w * 7))
      const wEnd = new Date(wStart)
      wEnd.setDate(wStart.getDate() + 6)
      const wLabel = `${wStart.getMonth() + 1}/${wStart.getDate()}`
      const wData = days.filter(d => {
        try { const dd = new Date(d.date); return dd >= wStart && dd <= wEnd } catch { return false }
      })
      weeklyTrend.push({
        week: wLabel,
        dials: sum(wData, 'dials'),
        deals: sum(wData, 'closes'),
      })
    }

    return {
      metrics: {
        dialsToday: sum(todayData, 'dials'),
        dialsWeek: sum(weekData, 'dials'),
        dialsMonth: sum(monthData, 'dials'),
        dealsToday: sum(todayData, 'closes'),
        dealsWeek: sum(weekData, 'closes'),
        dealsMonth: sum(monthData, 'closes'),
        showRate: totalDials > 0 ? ((totalShows / totalDials) * 100).toFixed(1) : '0.0',
        closeRate: totalShows > 0 ? ((totalCloses / totalShows) * 100).toFixed(1) : '0.0',
        revenueMonth: sum(monthData, 'revenue'),
        revenueYTD: sum(yearData, 'revenue'),
      },
      weeklyTrend,
      totalRows: days.length,
    }
  }

  const formatCurrency = (val) => {
    if (val == null) return '$0'
    return '$' + Number(val).toLocaleString('en-US', { maximumFractionDigits: 0 })
  }

  const formatPct = (val) => {
    if (val == null) return '\u2014'
    return val.toFixed(1) + '%'
  }

  const hasSummaryData = summary && summary.data_days > 0
  const totals = hasSummaryData ? summary.totals : {}
  const rates = hasSummaryData ? (summary.rates || {}) : {}

  const pcTarget = 400000
  const paceTarget = (pcTarget / 365) * days
  const premiumIssued = totals.premium_issued || 0
  const pcPace = paceTarget > 0 ? Math.min((premiumIssued / paceTarget) * 100, 100) : 0

  return (
    <div className="dashboard">
      {/* Days Toggle */}
      <section className="section">
        <div className="section-header-row">
          <h2 className="section-title" style={{ marginBottom: 0, paddingBottom: 0, borderBottom: 'none' }}>
            Production Analytics
          </h2>
          <div className="days-toggle">
            {[7, 30, 90].map((d) => (
              <button
                key={d}
                className={`btn btn-sm ${days === d ? 'btn-toggle-active' : ''}`}
                onClick={() => setDays(d)}
              >
                {d}d
              </button>
            ))}
          </div>
        </div>
      </section>

      {error && (
        <div className="alert alert-error">
          <strong>Error:</strong> {error}
        </div>
      )}

      {loading ? (
        <section className="section">
          <p className="loading-text">Loading...</p>
        </section>
      ) : !hasSummaryData ? (
        <section className="section">
          <p className="no-results" style={{ textAlign: 'center' }}>No production data logged yet.</p>
        </section>
      ) : (
        <>
          {/* Summary Stats */}
          <section className="section">
            <h2 className="section-title">Summary &mdash; {days} Days</h2>
            <div className="stat-row">
              <div className="stat-box"><span className="stat-label">Dials</span><span className="stat-value">{totals.dials || 0}</span></div>
              <div className="stat-box"><span className="stat-label">Contacts</span><span className="stat-value">{totals.contacts || 0}</span></div>
              <div className="stat-box"><span className="stat-label">Appts Set</span><span className="stat-value">{totals.appointments_set || 0}</span></div>
              <div className="stat-box"><span className="stat-label">Appts Kept</span><span className="stat-value">{totals.appointments_kept || 0}</span></div>
              <div className="stat-box"><span className="stat-label">Closes</span><span className="stat-value">{totals.closes || 0}</span></div>
              <div className="stat-box"><span className="stat-label">Premium Submitted</span><span className="stat-value">{formatCurrency(totals.premium_submitted)}</span></div>
              <div className="stat-box"><span className="stat-label">Premium Issued</span><span className="stat-value">{formatCurrency(totals.premium_issued)}</span></div>
            </div>
          </section>

          {/* Conversion Rates */}
          <section className="section">
            <h2 className="section-title">Conversion Rates</h2>
            <div className="stat-row">
              <div className="stat-box"><span className="stat-label">Contact Rate</span><span className="stat-value">{formatPct(rates.contact_rate)}</span></div>
              <div className="stat-box"><span className="stat-label">Appt Rate</span><span className="stat-value">{formatPct(rates.appt_rate)}</span></div>
              <div className="stat-box"><span className="stat-label">Close Rate</span><span className="stat-value">{formatPct(rates.close_rate)}</span></div>
            </div>
          </section>

          {/* Presidents Club Progress */}
          <section className="section">
            <h2 className="section-title">Presidents Club Pace</h2>
            <p className="section-desc">Target: $400,000/year issued premium</p>
            <div className="progress-bar-container">
              <div className="progress-bar" style={{ width: `${pcPace}%` }} />
            </div>
            <p className="progress-label">
              {formatCurrency(premiumIssued)} / {formatCurrency(paceTarget)} &mdash; {pcPace.toFixed(1)}% of pace
            </p>
          </section>

          {/* Daily Breakdown */}
          <section className="section">
            <h2 className="section-title">Daily Breakdown</h2>
            {daily && daily.data && daily.data.length > 0 ? (
              <div className="table-scroll-wrapper">
              <table className="results-table">
                <thead>
                  <tr>
                    <th>Date</th><th>Dials</th><th>Contacts</th><th>Appt Set</th><th>Appt Kept</th><th>Closes</th><th>Premium</th>
                  </tr>
                </thead>
                <tbody>
                  {daily.data.map((row, idx) => (
                    <tr key={idx}>
                      <td>{row.date}</td><td>{row.dials}</td><td>{row.contacts}</td><td>{row.appointments_set}</td><td>{row.appointments_kept}</td><td>{row.closes}</td><td>{formatCurrency(row.premium_submitted)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              </div>
            ) : (
              <p className="no-results">No daily data available.</p>
            )}
          </section>
        </>
      )}

      {/* ═══ Accountability Tracker — Google Sheets ═══ */}
      <section className="section">
        <div className="section-header-row">
          <h2 className="section-title" style={{ marginBottom: 0, paddingBottom: 0, borderBottom: 'none' }}>
            Accountability Tracker
          </h2>
          <div style={{ display: 'flex', gap: '0.5rem' }}>
            {sheetData && (
              <button className="btn btn-sm" onClick={fetchSheetData} disabled={sheetLoading}>
                {sheetLoading ? 'Fetching...' : 'Refresh'}
              </button>
            )}
            <button className="btn btn-sm" onClick={() => setShowSettings(!showSettings)}>
              {showSettings ? 'Hide' : 'Settings'}
            </button>
          </div>
        </div>

        {lastFetched && (
          <p className="form-hint" style={{ margin: '0.5rem 0 0', fontSize: '0.65rem' }}>
            Last fetched: {new Date(lastFetched).toLocaleString()}
          </p>
        )}
      </section>

      {/* Settings panel */}
      {showSettings && (
        <section className="section">
          <h2 className="section-title" style={{ fontSize: '0.75rem' }}>Sheet Connection</h2>
          <p className="form-hint" style={{ margin: '0 0 0.5rem' }}>Paste the URL or ID of the accountability tracker spreadsheet</p>
          <div className="input-btn-row" style={{ marginBottom: '0.75rem' }}>
            <input
              className="form-input"
              style={{ flex: 1 }}
              placeholder="https://docs.google.com/spreadsheets/d/..."
              value={sheetUrl}
              onChange={e => setSheetUrl(e.target.value)}
            />
            <button className="btn btn-primary" onClick={saveSheetUrl}>Save</button>
          </div>
          <div style={{ display: 'flex', gap: '0.5rem' }}>
            <button className="btn" onClick={fetchSheetData} disabled={sheetLoading || !sheetUrl.trim()}>
              {sheetLoading ? 'Fetching...' : 'Fetch Latest Data'}
            </button>
          </div>
          {sheetError && <div className="alert alert-error" style={{ fontSize: '0.75rem' }}>{sheetError}</div>}
        </section>
      )}

      {/* Accountability metrics */}
      {sheetData ? (
        <>
          <section className="section">
            <h2 className="section-title">Activity Metrics</h2>
            <div className="stat-row">
              <div className="stat-box"><span className="stat-label">Dials Today</span><span className="stat-value">{sheetData.metrics.dialsToday}</span></div>
              <div className="stat-box"><span className="stat-label">Dials This Week</span><span className="stat-value">{sheetData.metrics.dialsWeek}</span></div>
              <div className="stat-box"><span className="stat-label">Dials This Month</span><span className="stat-value">{sheetData.metrics.dialsMonth}</span></div>
              <div className="stat-box"><span className="stat-label">Deals Today</span><span className="stat-value">{sheetData.metrics.dealsToday}</span></div>
              <div className="stat-box"><span className="stat-label">Deals This Week</span><span className="stat-value">{sheetData.metrics.dealsWeek}</span></div>
              <div className="stat-box"><span className="stat-label">Deals This Month</span><span className="stat-value">{sheetData.metrics.dealsMonth}</span></div>
            </div>
          </section>

          <section className="section">
            <h2 className="section-title">Performance</h2>
            <div className="stat-row">
              <div className="stat-box"><span className="stat-label">Show Rate</span><span className="stat-value">{sheetData.metrics.showRate}%</span></div>
              <div className="stat-box"><span className="stat-label">Close Rate</span><span className="stat-value">{sheetData.metrics.closeRate}%</span></div>
              <div className="stat-box"><span className="stat-label">Revenue This Month</span><span className="stat-value">{formatCurrency(sheetData.metrics.revenueMonth)}</span></div>
              <div className="stat-box"><span className="stat-label">Revenue YTD</span><span className="stat-value">{formatCurrency(sheetData.metrics.revenueYTD)}</span></div>
            </div>
          </section>

          {/* Weekly Trend Chart */}
          {sheetData.weeklyTrend && sheetData.weeklyTrend.length > 0 && (
            <section className="section">
              <h2 className="section-title">Weekly Trend &mdash; Dials vs Deals</h2>
              <div style={{ width: '100%', height: 260 }}>
                <ResponsiveContainer>
                  <LineChart data={sheetData.weeklyTrend} margin={{ top: 5, right: 20, left: 0, bottom: 5 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="oklch(20% 0.01 240)" />
                    <XAxis dataKey="week" tick={{ fontSize: 11, fill: 'oklch(55% 0.008 240)', fontFamily: 'JetBrains Mono' }} />
                    <YAxis tick={{ fontSize: 11, fill: 'oklch(55% 0.008 240)', fontFamily: 'JetBrains Mono' }} />
                    <Tooltip
                      contentStyle={{ background: 'oklch(12% 0.008 240)', border: '1px solid oklch(20% 0.01 240)', borderRadius: 3, fontFamily: 'JetBrains Mono', fontSize: 12 }}
                      labelStyle={{ color: 'oklch(92% 0.005 240)' }}
                    />
                    <Legend wrapperStyle={{ fontFamily: 'JetBrains Mono', fontSize: 11 }} />
                    <Line type="monotone" dataKey="dials" stroke="oklch(78% 0.15 85)" strokeWidth={2} dot={{ r: 3 }} name="Dials" />
                    <Line type="monotone" dataKey="deals" stroke="oklch(72% 0.18 145)" strokeWidth={2} dot={{ r: 3 }} name="Deals" />
                  </LineChart>
                </ResponsiveContainer>
              </div>
            </section>
          )}
        </>
      ) : (
        <section className="section">
          <div style={{ textAlign: 'center', padding: '1.5rem 1rem' }}>
            <div style={{ fontSize: '2rem', marginBottom: '0.5rem', color: 'var(--text-muted)' }}>G</div>
            <p style={{ fontFamily: 'var(--font-mono)', fontSize: '0.8rem', color: 'var(--text)', marginBottom: '0.25rem' }}>
              Connect Google Sheets
            </p>
            <p className="form-hint" style={{ margin: '0 auto 1rem', maxWidth: 400 }}>
              Link your accountability tracker spreadsheet to see dials, deals, show/close rates, and revenue metrics here.
            </p>
            <button className="btn btn-primary" onClick={() => setShowSettings(true)}>
              Connect Sheet
            </button>
          </div>
        </section>
      )}
    </div>
  )
}

export default Analytics
