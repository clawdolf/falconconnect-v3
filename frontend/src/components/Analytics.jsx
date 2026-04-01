import { useState, useEffect, useMemo } from 'react'
import { useAuthSafe as useAuth } from '../hooks/useClerkSafe'
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer } from 'recharts'

const CANONICAL_FIELDS = [
  { key: 'date', label: 'Date', required: true, hint: 'Date column (one row per working day)' },
  { key: 'dials', label: 'Dials', required: true, hint: 'Outbound dials/calls' },
  { key: 'pickups', label: 'Pickups', required: false, hint: 'Contacts reached' },
  { key: 'appointments', label: 'Appointments', required: false, hint: 'Appts booked or kept' },
  { key: 'presentations', label: 'Presentations', required: false, hint: 'One-call + standard combined' },
  { key: 'closes', label: 'Closes', required: true, hint: 'Deals closed' },
  { key: 'applications', label: 'Applications', required: false, hint: 'Applications submitted' },
  { key: 'ap', label: 'AP (Annual Premium)', required: false, hint: 'Annual Premium submitted ($)' },
  { key: 'notes', label: 'Notes', required: false, hint: 'Daily notes (optional)' },
]

const MAPPING_KEY = 'fc_accountability_mapping'
const SHEET_URL_KEY = 'fc_accountability_sheet'
const SHEET_DATA_KEY = 'fc_accountability_data'
const SHEET_FETCHED_KEY = 'fc_accountability_last_fetched'

const fmtCurr = (v) => v == null || isNaN(v) ? '$0' : '$' + Number(v).toLocaleString('en-US', { maximumFractionDigits: 0 })
const fmtPct = (v) => v == null || isNaN(v) ? '\u2014' : Number(v).toFixed(1) + '%'
const parseD = (s) => { if (!s) return null; const d = new Date(String(s).trim()); return isNaN(d.getTime()) ? null : d }
const sameDay = (a, b) => a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate()
const sumF = (arr, f) => arr.reduce((s, d) => s + (d[f] || 0), 0)
const wDays = (arr) => arr.filter(d => d.dials > 0).length
const pdAvg = (total, arr) => { const w = wDays(arr); return w > 0 ? Math.round(total / w) : 0 }

function ColumnMapperWizard({ headers, onComplete, onCancel }) {
  const [mapping, setMapping] = useState({})
  useEffect(() => {
    if (!headers || !headers.length) return
    const auto = {}
    const aliases = {
      date: ['date', 'day', 'dt'], dials: ['dials', 'dial', 'calls', 'call', 'total dials'],
      pickups: ['pickups', 'pickup', 'contacts', 'contact', 'reached'],
      appointments: ['appointments', 'appointment', 'appts', 'appt', 'kept', 'shows', 'show'],
      presentations: ['presentations', 'presentation', 'present', 'pres'],
      closes: ['closes', 'close', 'deals', 'deal', 'sold', 'sales'],
      applications: ['applications', 'application', 'apps'],
      ap: ['ap', 'annual premium', 'premium', 'premium submitted', 'revenue', 'income', 'amount'],
      notes: ['notes', 'note', 'comments'],
    }
    const used = new Set()
    for (const [field, terms] of Object.entries(aliases)) {
      for (let i = 0; i < headers.length; i++) {
        if (used.has(i)) continue
        const lw = headers[i].toLowerCase().trim()
        if (terms.some(t => lw === t || lw.includes(t))) { auto[field] = headers[i]; used.add(i); break }
      }
    }
    setMapping(auto)
  }, [headers])
  const handleSave = () => {
    if (!mapping.date || !mapping.dials) { alert('Date and Dials columns are required.'); return }
    localStorage.setItem(MAPPING_KEY, JSON.stringify(mapping))
    onComplete(mapping)
  }
  const ss = { flex: 1, minWidth: 180, padding: '0.4rem 0.5rem', background: 'var(--bg)', border: '1px solid var(--border)', borderRadius: 2, fontFamily: 'var(--font-mono)', fontSize: '0.72rem', color: 'var(--text)', cursor: 'pointer' }
  return (
    <section className="section">
      <h2 className="section-title">Map Your Columns</h2>
      <p className="form-hint" style={{ margin: '0 0 1rem' }}>Match each metric to a column header. Auto-detected where possible.</p>
      <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
        {CANONICAL_FIELDS.map(f => (
          <div key={f.key} style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', flexWrap: 'wrap' }}>
            <label style={{ fontFamily: 'var(--font-mono)', fontSize: '0.72rem', fontWeight: 600, color: 'var(--text)', minWidth: 140, letterSpacing: '0.04em' }}>
              {f.label}{f.required && <span style={{ color: 'var(--red)', marginLeft: 4 }}>*</span>}
            </label>
            <select value={mapping[f.key] || ''} onChange={e => setMapping(m => ({ ...m, [f.key]: e.target.value }))} style={ss}>
              <option value="">Not in my sheet</option>
              {headers.map((h, i) => <option key={i} value={h}>{h}</option>)}
            </select>
            <span style={{ fontFamily: 'var(--font-mono)', fontSize: '0.56rem', color: 'var(--text-muted)' }}>{f.hint}</span>
          </div>
        ))}
      </div>
      <div style={{ display: 'flex', gap: '0.5rem', marginTop: '1.25rem' }}>
        <button className="btn btn-primary" onClick={handleSave}>Save Mapping</button>
        {onCancel && <button className="btn" onClick={onCancel}>Cancel</button>}
      </div>
    </section>
  )
}

function Analytics() {
  const [sheetUrl, setSheetUrl] = useState(() => localStorage.getItem(SHEET_URL_KEY) || '')
  const [sheetLoading, setSheetLoading] = useState(false)
  const [sheetError, setSheetError] = useState(null)
  const [lastFetched, setLastFetched] = useState(() => localStorage.getItem(SHEET_FETCHED_KEY) || null)
  const [showSettings, setShowSettings] = useState(false)
  const [rawHeaders, setRawHeaders] = useState(null)
  const [rawRows, setRawRows] = useState(null)
  const [sheetTitle, setSheetTitle] = useState(null)
  const [mapping, setMapping] = useState(() => { try { return JSON.parse(localStorage.getItem(MAPPING_KEY)) } catch { return null } })
  const [showWizard, setShowWizard] = useState(false)
  const [period, setPeriod] = useState('month')
  const [parsedData, setParsedData] = useState(() => { try { return JSON.parse(localStorage.getItem(SHEET_DATA_KEY)) } catch { return null } })
  let getToken = null
  try { const auth = useAuth(); getToken = auth.getToken } catch {}
  const extractId = (url) => { if (!url) return null; const m = url.match(/\/spreadsheets\/d\/([a-zA-Z0-9_-]+)/); return m ? m[1] : url.trim() }

  const parseWithMapping = (headers, rows, cm) => {
    const hIdx = {}; headers.forEach((h, i) => { hIdx[h] = i })
    const days = []
    for (const row of rows) {
      const g = (f) => { const c = cm[f]; if (!c) return null; const i = hIdx[c]; return i !== undefined ? row[i] : null }
      const ds = String(g('date') || '').trim()
      const dials = parseInt(g('dials'), 10) || 0, pickups = parseInt(g('pickups'), 10) || 0
      const appointments = parseInt(g('appointments'), 10) || 0, presentations = parseInt(g('presentations'), 10) || 0
      const closes = parseInt(g('closes'), 10) || 0, applications = parseInt(g('applications'), 10) || 0
      const ap = parseFloat(String(g('ap') || '0').replace(/[$,]/g, '')) || 0
      const notes = String(g('notes') || '')
      if (ds || dials > 0 || closes > 0 || presentations > 0)
        days.push({ date: ds, dials, pickups, appointments, presentations, closes, applications, ap, notes })
    }
    return { days, hasPickups: !!cm.pickups, hasAppts: !!cm.appointments, hasPres: !!cm.presentations, hasApps: !!cm.applications, hasAP: !!cm.ap }
  }

  const fetchSheetData = async () => {
    const id = extractId(sheetUrl)
    if (!id) { setSheetError('Enter a valid Google Sheet URL or ID.'); return }
    setSheetLoading(true); setSheetError(null)
    try {
      let gTok = null
      if (getToken) { try { gTok = await getToken({ template: 'google' }) } catch {} }
      if (!gTok) { setSheetError('Connect your Google account to access your tracker. Sign in with Google through Clerk to grant sheet access.'); setSheetLoading(false); return }
      const cTok = await getToken()
      const resp = await fetch('/api/sheets/data?sheet_id=' + encodeURIComponent(id), { headers: { 'Authorization': 'Bearer ' + cTok, 'X-Google-Token': gTok } })
      if (resp.status === 403) { const b = await resp.json().catch(() => ({})); setSheetError(b.detail || 'Sheet not accessible.'); setSheetLoading(false); return }
      if (!resp.ok) throw new Error('Could not fetch sheet data (HTTP ' + resp.status + ')')
      const data = await resp.json()
      setRawHeaders(data.headers || []); setRawRows(data.rows || []); setSheetTitle(data.sheet_title || id)
      const now = new Date().toISOString(); setLastFetched(now); localStorage.setItem(SHEET_FETCHED_KEY, now)
      if (!mapping) { setShowWizard(true) }
      else { const p = parseWithMapping(data.headers || [], data.rows || [], mapping); setParsedData(p); localStorage.setItem(SHEET_DATA_KEY, JSON.stringify(p)) }
    } catch (err) { setSheetError(err.message) } finally { setSheetLoading(false) }
  }

  const handleMappingDone = (nm) => { setMapping(nm); setShowWizard(false); if (rawHeaders && rawRows) { const p = parseWithMapping(rawHeaders, rawRows, nm); setParsedData(p); localStorage.setItem(SHEET_DATA_KEY, JSON.stringify(p)) } }
  const resetMapping = () => { localStorage.removeItem(MAPPING_KEY); setMapping(null); setParsedData(null); localStorage.removeItem(SHEET_DATA_KEY); if (rawHeaders) setShowWizard(true) }

  const M = useMemo(() => {
    if (!parsedData || !parsedData.days || !parsedData.days.length) return null
    const { days, hasPickups, hasAppts, hasPres, hasApps, hasAP } = parsedData
    const now = new Date(), today = new Date(now.getFullYear(), now.getMonth(), now.getDate())
    const wkS = new Date(today); wkS.setDate(today.getDate() - today.getDay())
    const moS = new Date(now.getFullYear(), now.getMonth(), 1), yrS = new Date(now.getFullYear(), 0, 1)
    const inR = (start) => days.filter(d => { const dd = parseD(d.date); return dd && dd >= start && dd <= now })
    const tArr = days.filter(d => { const dd = parseD(d.date); return dd && sameDay(dd, today) })
    const wArr = inR(wkS), mArr = inR(moS), yArr = inR(yrS)
    const pd = ({ today: tArr, week: wArr, month: mArr, ytd: yArr }[period] || mArr)
    const mk = (arr) => { const o = {}; ['dials','pickups','appointments','presentations','closes','applications','ap'].forEach(f => o[f] = sumF(arr, f)); return o }
    const tS = mk(tArr), wS = mk(wArr), mS = mk(mArr), yS = mk(yArr), pS = mk(pd)
    const mA = (f) => pdAvg(mS[f], mArr)
    const rates = {
      pickup: hasPickups && pS.dials > 0 ? (pS.pickups / pS.dials) * 100 : null,
      show: hasPres ? (hasAppts && pS.appointments > 0 ? (pS.presentations / pS.appointments) * 100 : (hasPickups && pS.pickups > 0 ? (pS.presentations / pS.pickups) * 100 : null)) : null,
      close: hasPres && pS.presentations > 0 ? (pS.closes / pS.presentations) * 100 : null,
      app: hasApps && pS.closes > 0 ? (pS.applications / pS.closes) * 100 : null,
    }
    const trend = []
    for (let w = 7; w >= 0; w--) { const ws = new Date(today); ws.setDate(today.getDate() - today.getDay() - w*7); const we = new Date(ws); we.setDate(ws.getDate()+6); const wd = days.filter(d => { const dd = parseD(d.date); return dd && dd >= ws && dd <= we }); trend.push({ week: (ws.getMonth()+1)+'/'+ws.getDate(), dials: sumF(wd,'dials'), presentations: sumF(wd,'presentations'), closes: sumF(wd,'closes') }) }
    const pcT = 400000; let pcP, pcD, pcL
    if (period === 'ytd') { pcP = yS.ap; pcD = pcT; pcL = 'YTD' }
    else { const dp = period === 'today' ? 1 : period === 'week' ? 7 : 30; pcD = (pcT/365)*dp; pcP = pS.ap; pcL = period === 'today' ? '1-Day' : period === 'week' ? '7-Day' : '30-Day' }
    const pcPct = pcD > 0 ? Math.min((pcP/pcD)*100, 100) : 0
    return { tS, wS, mS, yS, pS, rates, trend, mA, hasPickups, hasAppts, hasPres, hasApps, hasAP, pc: { p: pcP, d: pcD, pct: pcPct, l: pcL }, totalRows: days.length }
  }, [parsedData, period])

  const pLabel = { today: 'Today', week: 'This Week', month: 'This Month', ytd: 'YTD' }[period]
  const hasData = !!M
  const sub = { fontFamily: 'var(--font-mono)', fontSize: '0.56rem', color: 'var(--text-muted)' }
  return (
    <div className="dashboard">
      <section className="section">
        <div className="section-header-row">
          <h2 className="section-title" style={{ marginBottom: 0, paddingBottom: 0, borderBottom: 'none' }}>
            Analytics
            {sheetTitle && <span style={{ fontFamily: 'var(--font-mono)', fontSize: '0.62rem', fontWeight: 400, color: 'var(--text-muted)', marginLeft: '0.75rem' }}>{sheetTitle}</span>}
          </h2>
          <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center' }}>
            {hasData && (
              <>
                <div className="days-toggle">
                  {[{k:'today',l:'Today'},{k:'week',l:'7d'},{k:'month',l:'30d'},{k:'ytd',l:'YTD'}].map(t =>
                    <button key={t.k} className={'btn btn-sm ' + (period === t.k ? 'btn-toggle-active' : '')} onClick={() => setPeriod(t.k)}>{t.l}</button>
                  )}
                </div>
                <button className="btn btn-sm" onClick={fetchSheetData} disabled={sheetLoading}>{sheetLoading ? 'Syncing...' : 'Refresh'}</button>
              </>
            )}
            <button className="btn btn-sm" onClick={() => setShowSettings(!showSettings)}>{showSettings ? 'Hide' : 'Settings'}</button>
          </div>
        </div>
        {lastFetched && <p className="form-hint" style={{ margin: '0.4rem 0 0', fontSize: '0.56rem' }}>Last synced: {new Date(lastFetched).toLocaleString()}</p>}
      </section>

      {showSettings && (
        <section className="section">
          <h2 className="section-title" style={{ fontSize: '0.75rem' }}>Sheet Connection</h2>
          <p className="form-hint" style={{ margin: '0 0 0.5rem' }}>Paste the URL or ID of your accountability tracker.</p>
          <div className="input-btn-row" style={{ marginBottom: '0.75rem' }}>
            <input className="form-input" style={{ flex: 1 }} placeholder="https://docs.google.com/spreadsheets/d/..." value={sheetUrl} onChange={e => setSheetUrl(e.target.value)} />
            <button className="btn btn-primary" onClick={() => { localStorage.setItem(SHEET_URL_KEY, sheetUrl); setShowSettings(false) }}>Save</button>
          </div>
          <div style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap' }}>
            <button className="btn" onClick={fetchSheetData} disabled={sheetLoading || !sheetUrl.trim()}>{sheetLoading ? 'Fetching...' : 'Fetch Latest Data'}</button>
            {mapping && <button className="btn" onClick={resetMapping} style={{ color: 'var(--amber)' }}>Reset Column Mapping</button>}
          </div>
          <p className="form-hint" style={{ margin: '0.75rem 0 0', fontSize: '0.56rem', color: 'var(--text-muted)' }}>Requires Google sign-in via Clerk.</p>
          {sheetError && <div className="alert alert-error" style={{ fontSize: '0.72rem', marginTop: '0.5rem' }}>{sheetError}</div>}
        </section>
      )}

      {sheetError && !showSettings && <div className="alert alert-error"><strong>Error:</strong> {sheetError}</div>}
      {showWizard && rawHeaders && <ColumnMapperWizard headers={rawHeaders} onComplete={handleMappingDone} onCancel={() => setShowWizard(false)} />}

      {!hasData && !showWizard && (
        <section className="section">
          <div style={{ textAlign: 'center', padding: '2rem 1rem' }}>
            <p style={{ fontFamily: 'var(--font-display)', fontSize: '1.1rem', fontWeight: 600, color: 'var(--text)', marginBottom: '0.5rem' }}>Connect Your Tracker</p>
            <p className="form-hint" style={{ margin: '0 auto 0.5rem', maxWidth: 440 }}>Link your Google Sheets accountability tracker to see full funnel analytics.</p>
            <p className="form-hint" style={{ margin: '0 auto 1.25rem', maxWidth: 440, fontSize: '0.6rem' }}>Sign in with Google through Clerk, then paste your sheet URL in Settings.</p>
            <button className="btn btn-primary" onClick={() => setShowSettings(true)}>Connect Sheet</button>
          </div>
        </section>
      )}

      {hasData && M && (
        <>
          <section className="section">
            <h2 className="section-title">Primary Metrics</h2>
            <div className="stat-row">
              <div className="stat-box"><span className="stat-label">Closes Today</span><span className="stat-value" style={{color:'var(--green)'}}>{M.tS.closes}</span></div>
              <div className="stat-box"><span className="stat-label">Closes This Week</span><span className="stat-value" style={{color:'var(--green)'}}>{M.wS.closes}</span></div>
              <div className="stat-box"><span className="stat-label">Closes This Month</span><span className="stat-value" style={{color:'var(--green)'}}>{M.mS.closes}</span><span style={sub}>{M.mA('closes')}/day avg</span></div>
            </div>
            {M.hasApps && (
              <div className="stat-row" style={{marginTop:0}}>
                <div className="stat-box"><span className="stat-label">Apps Today</span><span className="stat-value">{M.tS.applications}</span></div>
                <div className="stat-box"><span className="stat-label">Apps This Week</span><span className="stat-value">{M.wS.applications}</span></div>
                <div className="stat-box"><span className="stat-label">Apps This Month</span><span className="stat-value">{M.mS.applications}</span><span style={sub}>{M.mA('applications')}/day avg</span></div>
              </div>
            )}
            {M.hasPres && (
              <div className="stat-row" style={{marginTop:0}}>
                <div className="stat-box"><span className="stat-label">Pres. Today</span><span className="stat-value">{M.tS.presentations}</span></div>
                <div className="stat-box"><span className="stat-label">Pres. This Week</span><span className="stat-value">{M.wS.presentations}</span></div>
                <div className="stat-box"><span className="stat-label">Pres. This Month</span><span className="stat-value">{M.mS.presentations}</span><span style={sub}>{M.mA('presentations')}/day avg</span></div>
              </div>
            )}
          </section>

          <section className="section">
            <h2 className="section-title">Activity</h2>
            <div className="stat-row">
              <div className="stat-box"><span className="stat-label">Dials Today</span><span className="stat-value">{M.tS.dials}</span></div>
              <div className="stat-box"><span className="stat-label">Dials This Week</span><span className="stat-value">{M.wS.dials}</span></div>
              <div className="stat-box"><span className="stat-label">Dials This Month</span><span className="stat-value">{M.mS.dials}</span><span style={sub}>{M.mA('dials')}/day avg</span></div>
              <div className="stat-box"><span className="stat-label">Dials YTD</span><span className="stat-value">{M.yS.dials.toLocaleString()}</span></div>
            </div>
            {M.hasPickups && (
              <div className="stat-row" style={{marginTop:0}}>
                <div className="stat-box"><span className="stat-label">Pickups Today</span><span className="stat-value">{M.tS.pickups}</span></div>
                <div className="stat-box"><span className="stat-label">Pickups This Week</span><span className="stat-value">{M.wS.pickups}</span></div>
                <div className="stat-box"><span className="stat-label">Pickups This Month</span><span className="stat-value">{M.mS.pickups}</span><span style={sub}>{M.mA('pickups')}/day avg</span></div>
              </div>
            )}
            {M.hasAppts && (
              <div className="stat-row" style={{marginTop:0}}>
                <div className="stat-box"><span className="stat-label">Appts Today</span><span className="stat-value">{M.tS.appointments}</span></div>
                <div className="stat-box"><span className="stat-label">Appts This Week</span><span className="stat-value">{M.wS.appointments}</span></div>
                <div className="stat-box"><span className="stat-label">Appts This Month</span><span className="stat-value">{M.mS.appointments}</span><span style={sub}>{M.mA('appointments')}/day avg</span></div>
              </div>
            )}
            {M.hasAP && (
              <div className="stat-row" style={{marginTop:0}}>
                <div className="stat-box"><span className="stat-label">AP This Month</span><span className="stat-value">{fmtCurr(M.mS.ap)}</span></div>
                <div className="stat-box"><span className="stat-label">AP YTD</span><span className="stat-value">{fmtCurr(M.yS.ap)}</span></div>
              </div>
            )}
          </section>

          <section className="section">
            <h2 className="section-title">Conversion Rates &mdash; {pLabel}</h2>
            <div className="stat-row">
              {M.hasPickups && <div className="stat-box"><span className="stat-label">Pickup Rate</span><span className="stat-value">{fmtPct(M.rates.pickup)}</span>{M.rates.pickup != null && <span style={sub}>{M.pS.pickups} / {M.pS.dials}</span>}</div>}
              {M.hasPres && <div className="stat-box"><span className="stat-label">Show Rate</span><span className="stat-value">{fmtPct(M.rates.show)}</span>{M.rates.show != null && <span style={sub}>{M.pS.presentations} / {M.hasAppts ? M.pS.appointments : M.pS.pickups}</span>}</div>}
              {M.hasPres && <div className="stat-box"><span className="stat-label">Close Rate</span><span className="stat-value">{fmtPct(M.rates.close)}</span>{M.rates.close != null && <span style={sub}>{M.pS.closes} / {M.pS.presentations}</span>}</div>}
              {M.hasApps && <div className="stat-box"><span className="stat-label">App Rate</span><span className="stat-value">{fmtPct(M.rates.app)}</span>{M.rates.app != null && <span style={sub}>{M.pS.applications} / {M.pS.closes}</span>}</div>}
              {!M.hasPres && <div className="stat-box"><span className="stat-label">Close Rate (vs Dials)</span><span className="stat-value">{M.pS.dials > 0 ? fmtPct((M.pS.closes/M.pS.dials)*100) : '\u2014'}</span></div>}
            </div>
          </section>

          {M.trend && M.trend.length > 0 && (
            <section className="section">
              <h2 className="section-title">Weekly Trend</h2>
              <div style={{ width: '100%', height: 260 }}>
                <ResponsiveContainer>
                  <LineChart data={M.trend} margin={{ top: 5, right: 20, left: 0, bottom: 5 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="oklch(20% 0.01 240)" />
                    <XAxis dataKey="week" tick={{ fontSize: 11, fill: 'oklch(55% 0.008 240)', fontFamily: 'JetBrains Mono' }} />
                    <YAxis tick={{ fontSize: 11, fill: 'oklch(55% 0.008 240)', fontFamily: 'JetBrains Mono' }} />
                    <Tooltip contentStyle={{ background: 'oklch(12% 0.008 240)', border: '1px solid oklch(20% 0.01 240)', borderRadius: 3, fontFamily: 'JetBrains Mono', fontSize: 12 }} labelStyle={{ color: 'oklch(92% 0.005 240)' }} />
                    <Legend wrapperStyle={{ fontFamily: 'JetBrains Mono', fontSize: 11 }} />
                    <Line type="monotone" dataKey="dials" stroke="oklch(78% 0.15 85)" strokeWidth={2} dot={{ r: 3 }} name="Dials" />
                    <Line type="monotone" dataKey="presentations" stroke="oklch(72% 0.15 200)" strokeWidth={2} dot={{ r: 3 }} name="Presentations" />
                    <Line type="monotone" dataKey="closes" stroke="oklch(72% 0.18 145)" strokeWidth={2} dot={{ r: 3 }} name="Closes" />
                  </LineChart>
                </ResponsiveContainer>
              </div>
            </section>
          )}

          {M.hasAP && (
            <section className="section">
              <h2 className="section-title">Presidents Club Pace &mdash; {M.pc.l}</h2>
              <p className="section-desc" style={{ fontFamily: 'var(--font-mono)', fontSize: '0.65rem', color: 'var(--text-muted)', marginBottom: '0.5rem' }}>
                Submitted AP (proxy for Presidents Club pace) &mdash; Target: $400,000/year
              </p>
              <div className="progress-bar-container">
                <div className="progress-bar" style={{ width: M.pc.pct + '%' }} />
              </div>
              <p className="progress-label">
                {fmtCurr(M.pc.p)} / {fmtCurr(M.pc.d)} &mdash; {M.pc.pct.toFixed(1)}% of {M.pc.l} pace
              </p>
            </section>
          )}

          <section className="section">
            <p className="form-hint" style={{ textAlign: 'center', fontSize: '0.56rem' }}>
              {M.totalRows} rows loaded from sheet &mdash; Rates computed for {pLabel.toLowerCase()} window
            </p>
          </section>
        </>
      )}
    </div>
  )
}

export default Analytics