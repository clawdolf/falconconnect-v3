import { useState, useRef, useCallback } from 'react'
import { useAuth } from '@clerk/clerk-react'
import * as XLSX from 'xlsx'

/* Constants */
const VENDOR_TIERS = {
  'HOFLeads': ['Diamond', 'Gold', 'Silver'],
  'Proven Leads': ['N/A'],
  'Aria Leads': ['Gold', 'Silver', 'N/A'],
  'MilMo': ['Gold', 'Silver', 'N/A'],
}
const LEAD_AGE_BUCKETS = ['7-12M', '13-24M', '25-36M', '37-48M', '49-60M', '60+M']
const LEAD_TYPES = ['Mortgage Protection', 'Final Expense', 'Annuity', 'IUL']
const LEAD_VENDORS = Object.keys(VENDOR_TIERS)

const LEAD_FIELDS = [
  { value: 'first_name', label: 'First Name' },
  { value: 'last_name', label: 'Last Name' },
  { value: 'phone', label: 'Phone' },
  { value: 'email', label: 'Email' },
  { value: 'address', label: 'Address' },
  { value: 'city', label: 'City' },
  { value: 'state', label: 'State' },
  { value: 'zip_code', label: 'ZIP Code' },
  { value: 'birth_year', label: 'Birth Year' },
  { value: 'lead_source', label: 'Lead Source' },
  { value: 'lead_type', label: 'Lead Type' },
  { value: 'lead_age_bucket', label: 'Lead Age Bucket' },
  { value: 'lender', label: 'Lender' },
  { value: 'mail_date', label: 'Mail Date' },
  { value: 'notes', label: 'Notes' },
]

const COLUMN_ALIASES = {
  'first name': 'first_name', 'firstname': 'first_name', 'fname': 'first_name',
  'last name': 'last_name', 'lastname': 'last_name', 'lname': 'last_name',
  'phone': 'phone', 'cell': 'phone', 'cell phone': 'phone', 'mobile': 'phone',
  'email': 'email', 'address': 'address', 'street': 'address',
  'city': 'city', 'state': 'state', 'st': 'state',
  'zip': 'zip_code', 'zip_code': 'zip_code', 'zipcode': 'zip_code', 'zip code': 'zip_code',
  'birth year': 'birth_year', 'birth_year': 'birth_year', 'dob': 'birth_year',
  'source': 'lead_source', 'lead source': 'lead_source', 'vendor': 'lead_source',
  'type': 'lead_type', 'lead type': 'lead_type',
  'lead age': 'lead_age_bucket', 'lender': 'lender',
  'mail date': 'mail_date', 'mail_date': 'mail_date',
  'notes': 'notes', 'note': 'notes', 'comments': 'notes',
}

/* Helpers */
function autoMapHeaders(hdrs) {
  const m = {}
  hdrs.forEach(h => {
    const lw = h.toLowerCase().trim()
    if (COLUMN_ALIASES[lw]) { m[h] = COLUMN_ALIASES[lw]; return }
    const match = LEAD_FIELDS.find(f => f.label.toLowerCase() === lw || f.value === lw)
    if (match) m[h] = match.value
  })
  return m
}

function autoDetectVendor(filename) {
  const fn = filename.toLowerCase()
  const out = { vendor: 'HOFLeads', tier: 'Diamond', leadType: 'Mortgage Protection' }
  if (fn.includes('hof')) { out.vendor = 'HOFLeads'; if (fn.includes('gold')) out.tier = 'Gold'; else if (fn.includes('silver')) out.tier = 'Silver' }
  else if (fn.includes('proven')) { out.vendor = 'Proven Leads'; out.tier = 'N/A' }
  else if (fn.includes('aria')) { out.vendor = 'Aria Leads'; out.tier = 'Gold' }
  else if (fn.includes('milmo')) { out.vendor = 'MilMo'; out.tier = 'Gold' }
  if (fn.includes('final expense') || fn.includes('_fe_')) out.leadType = 'Final Expense'
  else if (fn.includes('annuity')) out.leadType = 'Annuity'
  else if (fn.includes('iul')) out.leadType = 'IUL'
  return out
}

function buildLeads(rows, headers, columnMap, vendor, tier, leadType, leadAge, purchaseDate) {
  const leads = []
  for (const row of rows) {
    const lead = {}
    headers.forEach((h, i) => {
      const field = columnMap[h]
      if (field && row[i] !== undefined && row[i] !== null && String(row[i]).trim()) {
        lead[field] = String(row[i]).trim()
      }
    })
    if (!lead.first_name || !lead.last_name || !lead.phone) continue
    if (vendor && !lead.lead_source) lead.lead_source = vendor + (tier && tier !== 'N/A' ? ' / ' + tier : '')
    if (leadType && !lead.lead_type) lead.lead_type = leadType
    if (leadAge) lead.lead_age_bucket = leadAge
    if (purchaseDate && !lead.mail_date) lead.mail_date = purchaseDate
    if (lead.birth_year) { const yr = parseInt(lead.birth_year, 10); lead.birth_year = isNaN(yr) ? undefined : yr }
    leads.push(lead)
  }
  return leads
}

async function submitBulk(leads, getHeaders, onProgress) {
  const hdrs = await getHeaders()
  const BS = 50
  let created = 0, failed = 0
  const errors = []
  for (let i = 0; i < leads.length; i += BS) {
    const batch = leads.slice(i, i + BS)
    try {
      const resp = await fetch('/api/public/leads/bulk', { method: 'POST', headers: hdrs, body: JSON.stringify({ leads: batch }) })
      if (resp.ok) {
        const d = await resp.json(); created += d.created || 0; failed += d.failed || 0; if (d.errors) errors.push(...d.errors)
      } else {
        for (let j = 0; j < batch.length; j++) {
          try { const r = await fetch('/api/public/leads/capture', { method: 'POST', headers: hdrs, body: JSON.stringify(batch[j]) }); if (r.ok) created++; else failed++ } catch { failed++ }
          onProgress(i + j + 1)
        }
        continue
      }
    } catch { failed += batch.length }
    onProgress(Math.min(i + BS, leads.length))
  }
  return { created, failed, errors }
}

function ImportResult({ result, onReset }) {
  return (
    <div>
      <div style={{ textAlign: 'center', padding: '1.5rem 0' }}>
        <div style={{ width: 48, height: 48, borderRadius: '50%', background: result.failed === 0 ? 'oklch(18% 0.04 145)' : 'oklch(18% 0.04 75)', display: 'flex', alignItems: 'center', justifyContent: 'center', margin: '0 auto 0.75rem', color: result.failed === 0 ? 'var(--green)' : 'var(--amber)', fontSize: '1.5rem' }}>
          {result.failed === 0 ? '\u2713' : '!'}
        </div>
        <h3 className="section-title" style={{ borderBottom: 'none', marginBottom: '0.25rem' }}>Import Complete</h3>
        <p className="form-hint" style={{ margin: 0 }}>{result.created} created \u2014 {result.failed} failed</p>
      </div>
      {result.errors && result.errors.length > 0 && (
        <div style={{ maxHeight: 200, overflow: 'auto', marginBottom: '1rem' }}>
          {result.errors.slice(0, 20).map((e, i) => (
            <div key={i} className="alert alert-error" style={{ marginTop: i > 0 ? '0.5rem' : 0, fontSize: '0.7rem' }}>
              Row {e.index + 1}{e.lead_name ? ' (' + e.lead_name + ')' : ''}: {e.error}
            </div>
          ))}
        </div>
      )}
      <button className="btn btn-primary" onClick={onReset}>Import More</button>
    </div>
  )
}

function MappingUI({ headers, columnMap, setColumnMap }) {
  return (
    <div style={{ marginBottom: '1rem' }}>
      <h3 className="section-title" style={{ fontSize: '0.75rem' }}>Column Mapping</h3>
      <div style={{ maxHeight: 220, overflow: 'auto' }}>
        {headers.map(h => (
          <div key={h} style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', marginBottom: '0.375rem' }}>
            <span style={{ fontFamily: 'var(--font-mono)', fontSize: '0.75rem', color: 'var(--text-muted)', width: '35%', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={h}>{h}</span>
            <span style={{ color: 'var(--text-muted)', fontSize: '0.7rem' }}>&rarr;</span>
            <select className="form-input" style={{ flex: 1, fontSize: '0.75rem', padding: '0.25rem 0.5rem' }}
              value={columnMap[h] || ''} onChange={e => setColumnMap(prev => ({ ...prev, [h]: e.target.value }))}>
              <option value="">&mdash; skip &mdash;</option>
              {LEAD_FIELDS.map(f => <option key={f.value} value={f.value}>{f.label}</option>)}
            </select>
          </div>
        ))}
      </div>
    </div>
  )
}

function BatchSettings({ vendor, setVendor, tier, setTier, leadType, setLeadType, leadAge, setLeadAge, purchaseDate, setPurchaseDate }) {
  return (
    <div style={{ marginBottom: '1rem' }}>
      <h3 className="section-title" style={{ fontSize: '0.75rem' }}>Batch Settings</h3>
      <div className="form-grid">
        <div className="form-field">
          <label className="form-label">Vendor</label>
          <select className="form-input" value={vendor} onChange={e => { setVendor(e.target.value); setTier((VENDOR_TIERS[e.target.value] || [])[0] || 'N/A') }}>
            {LEAD_VENDORS.map(v => <option key={v} value={v}>{v}</option>)}
          </select>
        </div>
        <div className="form-field">
          <label className="form-label">Tier</label>
          <select className="form-input" value={tier} onChange={e => setTier(e.target.value)}>
            {(VENDOR_TIERS[vendor] || []).map(t => <option key={t} value={t}>{t}</option>)}
          </select>
        </div>
        <div className="form-field">
          <label className="form-label">Lead Type</label>
          <select className="form-input" value={leadType} onChange={e => setLeadType(e.target.value)}>
            {LEAD_TYPES.map(t => <option key={t} value={t}>{t}</option>)}
          </select>
        </div>
        <div className="form-field">
          <label className="form-label">Lead Age Bucket</label>
          <select className="form-input" value={leadAge} onChange={e => setLeadAge(e.target.value)}>
            <option value="">N/A</option>
            {LEAD_AGE_BUCKETS.map(a => <option key={a} value={a}>{a}</option>)}
          </select>
        </div>
        <div className="form-field">
          <label className="form-label">Purchase Date</label>
          <input className="form-input" type="date" value={purchaseDate} onChange={e => setPurchaseDate(e.target.value)} />
        </div>
      </div>
    </div>
  )
}

function PreviewTable({ headers, columnMap, rows }) {
  const mapped = headers.filter(h => columnMap[h])
  if (mapped.length === 0 || rows.length === 0) return null
  return (
    <div style={{ marginBottom: '1rem' }}>
      <h3 className="section-title" style={{ fontSize: '0.75rem' }}>Preview (first {rows.length} rows)</h3>
      <div style={{ overflow: 'auto', maxHeight: 200 }}>
        <table className="results-table">
          <thead><tr>{mapped.map(h => <th key={h}>{columnMap[h]}</th>)}</tr></thead>
          <tbody>{rows.map((row, ri) => <tr key={ri}>{mapped.map((h, ci) => <td key={ci}>{row[headers.indexOf(h)] || ''}</td>)}</tr>)}</tbody>
        </table>
      </div>
    </div>
  )
}

function ProgressBar({ current, total }) {
  return (
    <div>
      <div className="progress-bar-container"><div className="progress-bar" style={{ width: (total > 0 ? (current / total * 100) : 0) + '%' }} /></div>
      <p className="progress-label">{current} / {total} leads processed</p>
    </div>
  )
}

/* ---- Tab: Upload File ---- */
function UploadFileTab({ getHeaders }) {
  const fileInputRef = useRef(null)
  const [dragActive, setDragActive] = useState(false)
  const [parsedData, setParsedData] = useState(null)
  const [headers, setHeaders] = useState([])
  const [columnMap, setColumnMap] = useState({})
  const [vendor, setVendor] = useState('HOFLeads')
  const [tier, setTier] = useState('Diamond')
  const [leadType, setLeadType] = useState('Mortgage Protection')
  const [leadAge, setLeadAge] = useState('')
  const [purchaseDate, setPurchaseDate] = useState('')
  const [importing, setImporting] = useState(false)
  const [progress, setProgress] = useState({ current: 0, total: 0 })
  const [result, setResult] = useState(null)
  const [error, setError] = useState(null)

  const parseFile = useCallback(async (file) => {
    setError(null); setResult(null)
    const ext = file.name.split('.').pop().toLowerCase()
    if (!['csv', 'xlsx', 'xls', 'tsv'].includes(ext)) { setError('Unsupported file type.'); return }
    try {
      const data = await file.arrayBuffer()
      const wb = XLSX.read(data, { type: 'array' })
      const sheet = wb.Sheets[wb.SheetNames[0]]
      const json = XLSX.utils.sheet_to_json(sheet, { header: 1 })
      if (json.length < 2) { setError('File appears empty.'); return }
      const hdrs = json[0].map(h => String(h || '').trim())
      const rows = json.slice(1).filter(r => r.some(c => c !== null && c !== undefined && c !== ''))
      setHeaders(hdrs); setParsedData(rows); setColumnMap(autoMapHeaders(hdrs))
      const det = autoDetectVendor(file.name)
      setVendor(det.vendor); setTier(det.tier); setLeadType(det.leadType)
    } catch (err) { setError('Parse error: ' + err.message) }
  }, [])

  const handleDrag = useCallback((e) => { e.preventDefault(); e.stopPropagation(); setDragActive(e.type === 'dragenter' || e.type === 'dragover') }, [])
  const handleDrop = useCallback((e) => { e.preventDefault(); e.stopPropagation(); setDragActive(false); if (e.dataTransfer.files?.[0]) parseFile(e.dataTransfer.files[0]) }, [parseFile])
  const resetAll = () => { setParsedData(null); setHeaders([]); setColumnMap({}); setResult(null); setError(null) }

  const mappingOk = ['first_name', 'last_name', 'phone'].every(f => Object.values(columnMap).includes(f))

  const doImport = async () => {
    const leads = buildLeads(parsedData, headers, columnMap, vendor, tier, leadType, leadAge, purchaseDate)
    if (!leads.length) { setError('No valid leads. Map first_name, last_name, and phone.'); return }
    setImporting(true); setError(null); setProgress({ current: 0, total: leads.length })
    try { setResult(await submitBulk(leads, getHeaders, c => setProgress({ current: c, total: leads.length }))) }
    catch (err) { setError('Import failed: ' + err.message) }
    finally { setImporting(false) }
  }

  if (result) return <ImportResult result={result} onReset={resetAll} />

  if (!parsedData) return (
    <div>
      <div onDragEnter={handleDrag} onDragLeave={handleDrag} onDragOver={handleDrag} onDrop={handleDrop} onClick={() => fileInputRef.current?.click()}
        style={{ border: '2px dashed ' + (dragActive ? 'var(--accent)' : 'var(--border)'), borderRadius: 3, padding: '2.5rem 1.5rem', textAlign: 'center', cursor: 'pointer', background: dragActive ? 'oklch(14% 0.015 85 / 0.1)' : 'var(--bg)', transition: 'all 0.15s' }}>
        <input ref={fileInputRef} type="file" accept=".csv,.xlsx,.xls,.tsv" onChange={e => { if (e.target.files?.[0]) parseFile(e.target.files[0]) }} style={{ display: 'none' }} />
        <div style={{ fontSize: '1.75rem', marginBottom: '0.5rem', color: 'var(--text-muted)' }}>&uarr;</div>
        <p style={{ fontFamily: 'var(--font-mono)', fontSize: '0.8rem', color: 'var(--text)' }}>Drop files here or click to browse</p>
        <p className="form-hint" style={{ margin: '0.25rem 0 0' }}>CSV, Excel (.xlsx, .xls), TSV</p>
      </div>
      {error && <div className="alert alert-error"><strong>Error:</strong> {error}</div>}
    </div>
  )

  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '1rem' }}>
        <p className="form-hint" style={{ margin: 0 }}>{parsedData.length} rows parsed</p>
        <button className="btn btn-sm" onClick={resetAll}>Clear</button>
      </div>
      {!mappingOk && <p style={{ fontFamily: 'var(--font-mono)', fontSize: '0.7rem', color: 'var(--amber)', marginBottom: '0.75rem' }}>Map first_name, last_name, and phone to continue</p>}
      <MappingUI headers={headers} columnMap={columnMap} setColumnMap={setColumnMap} />
      <BatchSettings vendor={vendor} setVendor={setVendor} tier={tier} setTier={setTier} leadType={leadType} setLeadType={setLeadType} leadAge={leadAge} setLeadAge={setLeadAge} purchaseDate={purchaseDate} setPurchaseDate={setPurchaseDate} />
      <PreviewTable headers={headers} columnMap={columnMap} rows={parsedData.slice(0, 5)} />
      {error && <div className="alert alert-error"><strong>Error:</strong> {error}</div>}
      {importing ? <ProgressBar current={progress.current} total={progress.total} /> : <button className="btn btn-primary" onClick={doImport} disabled={!mappingOk} style={{ width: '100%' }}>Import {parsedData.length} Leads</button>}
    </div>
  )
}

/* ---- Tab: Google Sheets ---- */
function GoogleSheetsTab({ getHeaders }) {
  const [sheetUrl, setSheetUrl] = useState('')
  const [step, setStep] = useState('url')
  const [headers, setHeaders] = useState([])
  const [allRows, setAllRows] = useState([])
  const [columnMap, setColumnMap] = useState({})
  const [vendor, setVendor] = useState('HOFLeads')
  const [tier, setTier] = useState('Diamond')
  const [leadType, setLeadType] = useState('Mortgage Protection')
  const [leadAge, setLeadAge] = useState('')
  const [purchaseDate, setPurchaseDate] = useState('')
  const [progress, setProgress] = useState({ current: 0, total: 0 })
  const [result, setResult] = useState(null)
  const [error, setError] = useState(null)
  const [loading, setLoading] = useState(false)

  const extractId = (input) => { const m = input.match(/\/spreadsheets\/d\/([a-zA-Z0-9_-]+)/); return m ? m[1] : input.trim() }

  const fetchSheet = async () => {
    const id = extractId(sheetUrl)
    if (!id) { setError('Enter a valid Sheets URL or ID'); return }
    setLoading(true); setError(null)
    try {
      const hdrs = await getHeaders()
      const resp = await fetch('/api/public/sheets/data?sheet_id=' + encodeURIComponent(id), { headers: hdrs })
      if (resp.status === 404 || resp.status === 501) { setStep('noapi'); return }
      if (!resp.ok) throw new Error('Could not fetch sheet.')
      const data = await resp.json()
      setHeaders(data.headers || []); setAllRows(data.rows || [])
      setColumnMap(autoMapHeaders(data.headers || []))
      setStep('mapping')
    } catch (err) { setStep('noapi'); setError(err.message) }
    finally { setLoading(false) }
  }

  const doImport = async () => {
    const leads = buildLeads(allRows, headers, columnMap, vendor, tier, leadType, leadAge, purchaseDate)
    if (!leads.length) { setError('No valid leads found.'); return }
    setStep('importing'); setError(null); setProgress({ current: 0, total: leads.length })
    try { setResult(await submitBulk(leads, getHeaders, c => setProgress({ current: c, total: leads.length }))); setStep('done') }
    catch (err) { setError(err.message); setStep('mapping') }
  }

  const mappingOk = ['first_name', 'last_name', 'phone'].every(f => Object.values(columnMap).includes(f))

  if (step === 'done' && result) return <ImportResult result={result} onReset={() => { setStep('url'); setResult(null); setSheetUrl('') }} />
  if (step === 'importing') return <ProgressBar current={progress.current} total={progress.total} />
  if (step === 'noapi') return (
    <div style={{ textAlign: 'center', padding: '2rem 1rem' }}>
      <div style={{ fontSize: '2rem', marginBottom: '0.75rem', color: 'var(--text-muted)' }}>G</div>
      <h3 className="section-title" style={{ borderBottom: 'none' }}>Google Sheets</h3>
      <p className="form-hint" style={{ maxWidth: 400, margin: '0 auto' }}>Google Sheets API not configured on backend yet. Export as CSV and use the Upload File tab.</p>
      <button className="btn" onClick={() => { setStep('url'); setError(null) }} style={{ marginTop: '1rem' }}>Back</button>
    </div>
  )
  if (loading) return <div style={{ textAlign: 'center', padding: '2rem' }}><p className="loading-text">Fetching sheet data...</p></div>

  if (step === 'mapping') return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '1rem' }}>
        <p className="form-hint" style={{ margin: 0 }}>{allRows.length} rows from Google Sheets</p>
        <button className="btn btn-sm" onClick={() => setStep('url')}>Change</button>
      </div>
      {!mappingOk && <p style={{ fontFamily: 'var(--font-mono)', fontSize: '0.7rem', color: 'var(--amber)', marginBottom: '0.75rem' }}>Map first_name, last_name, and phone</p>}
      <MappingUI headers={headers} columnMap={columnMap} setColumnMap={setColumnMap} />
      <BatchSettings vendor={vendor} setVendor={setVendor} tier={tier} setTier={setTier} leadType={leadType} setLeadType={setLeadType} leadAge={leadAge} setLeadAge={setLeadAge} purchaseDate={purchaseDate} setPurchaseDate={setPurchaseDate} />
      <PreviewTable headers={headers} columnMap={columnMap} rows={allRows.slice(0, 5)} />
      {error && <div className="alert alert-error">{error}</div>}
      <button className="btn btn-primary" onClick={doImport} disabled={!mappingOk} style={{ width: '100%' }}>Import {allRows.length} Leads</button>
    </div>
  )

  return (
    <div>
      <p className="form-hint">Paste a Google Sheets URL or spreadsheet ID</p>
      <div style={{ display: 'flex', gap: '0.5rem', marginBottom: '0.75rem' }}>
        <input className="form-input" style={{ flex: 1 }} placeholder="https://docs.google.com/spreadsheets/d/..." value={sheetUrl} onChange={e => setSheetUrl(e.target.value)} onKeyDown={e => { if (e.key === 'Enter') fetchSheet() }} />
        <button className="btn btn-primary" onClick={fetchSheet} disabled={!sheetUrl.trim()}>Fetch</button>
      </div>
      {error && <div className="alert alert-error">{error}</div>}
    </div>
  )
}

/* ---- Tab: Manual Entry ---- */
function ManualEntryTab({ getHeaders }) {
  const [formData, setFormData] = useState({
    first_name: '', last_name: '', phone: '', email: '', birth_year: '', mail_date: '',
    address: '', city: '', state: '', zip_code: '', lead_source: '', notes: '',
  })
  const [errors, setErrors] = useState({})
  const [result, setResult] = useState(null)
  const [loading, setLoading] = useState(false)
  const [apiError, setApiError] = useState(null)

  const validate = () => {
    const errs = {}
    if (!formData.first_name.trim()) errs.first_name = 'Required'
    if (!formData.last_name.trim()) errs.last_name = 'Required'
    if (!formData.phone.trim()) errs.phone = 'Required'
    setErrors(errs)
    return Object.keys(errs).length === 0
  }

  const handleSubmit = async () => {
    if (!validate()) return
    setLoading(true); setApiError(null); setResult(null)
    try {
      const headers = await getHeaders()
      const body = { first_name: formData.first_name.trim(), last_name: formData.last_name.trim(), phone: formData.phone.trim() }
      if (formData.email.trim()) body.email = formData.email.trim()
      if (formData.birth_year) body.birth_year = parseInt(formData.birth_year, 10)
      if (formData.mail_date) body.mail_date = formData.mail_date
      if (formData.address.trim()) body.address = formData.address.trim()
      if (formData.city.trim()) body.city = formData.city.trim()
      if (formData.state.trim()) body.state = formData.state.trim()
      if (formData.zip_code.trim()) body.zip_code = formData.zip_code.trim()
      if (formData.lead_source.trim()) body.lead_source = formData.lead_source.trim()
      if (formData.notes.trim()) body.notes = formData.notes.trim()
      const resp = await fetch('/api/public/leads/capture', { method: 'POST', headers, body: JSON.stringify(body) })
      if (!resp.ok) { const ed = await resp.json().catch(() => null); throw new Error(ed?.detail || 'HTTP ' + resp.status) }
      setResult(await resp.json())
    } catch (err) { setApiError(err.message) }
    finally { setLoading(false) }
  }

  const handleChange = (field, value) => { setFormData(prev => ({ ...prev, [field]: value })); if (errors[field]) setErrors(prev => ({ ...prev, [field]: null })) }

  const resetForm = () => {
    setFormData({ first_name: '', last_name: '', phone: '', email: '', birth_year: '', mail_date: '', address: '', city: '', state: '', zip_code: '', lead_source: '', notes: '' })
    setErrors({}); setResult(null); setApiError(null)
  }

  return (
    <div>
      <div className="form-grid">
        {[
          { key: 'first_name', label: 'First Name *', type: 'text', placeholder: 'John', required: true },
          { key: 'last_name', label: 'Last Name *', type: 'text', placeholder: 'Doe', required: true },
          { key: 'phone', label: 'Phone *', type: 'text', placeholder: '480-555-1234', required: true },
          { key: 'email', label: 'Email', type: 'email', placeholder: 'john@example.com' },
          { key: 'birth_year', label: 'Birth Year', type: 'number', placeholder: '1972' },
          { key: 'mail_date', label: 'Mail Date', type: 'date' },
          { key: 'address', label: 'Address', type: 'text', placeholder: '123 Main St' },
          { key: 'city', label: 'City', type: 'text', placeholder: 'Scottsdale' },
          { key: 'state', label: 'State', type: 'text', placeholder: 'AZ' },
          { key: 'zip_code', label: 'ZIP', type: 'text', placeholder: '85251' },
          { key: 'lead_source', label: 'Lead Source', type: 'text', placeholder: 'mailer' },
          { key: 'notes', label: 'Notes', type: 'text', placeholder: 'Optional notes' },
        ].map(f => (
          <div className="form-field" key={f.key}>
            <label className="form-label">{f.label}</label>
            <input className={'form-input' + (errors[f.key] ? ' form-input-error' : '')} type={f.type} value={formData[f.key]} onChange={e => handleChange(f.key, e.target.value)} placeholder={f.placeholder || ''} />
            {errors[f.key] && <span className="form-error">{errors[f.key]}</span>}
          </div>
        ))}
      </div>
      <p className="form-hint">Dual push: GHL + Notion</p>
      <div style={{ display: 'flex', gap: '0.5rem' }}>
        <button className="btn btn-primary" onClick={handleSubmit} disabled={loading}>{loading ? 'Capturing...' : 'Capture Lead'}</button>
        <button className="btn" onClick={resetForm}>Reset</button>
      </div>
      {apiError && <div className="alert alert-error"><strong>Error:</strong> {apiError}</div>}
      {result && (
        <div className="result-card">
          <h2 className="section-title">Lead Captured</h2>
          <div className="result-grid">
            <div className="result-row"><span className="result-label">GHL ID</span><span className="result-value">{result.ghl_id}</span></div>
            <div className="result-row"><span className="result-label">Notion ID</span><span className="result-value">{result.notion_id}</span></div>
            {result.age != null && <div className="result-row"><span className="result-label">Age</span><span className="result-value">{result.age}</span></div>}
            <div className="result-row"><span className="result-label">Status</span><span className="result-value"><span className="badge badge-success">{result.status}</span></span></div>
          </div>
        </div>
      )}
    </div>
  )
}

/* ================ Main Component ================ */
function LeadImport() {
  const [activeTab, setActiveTab] = useState('upload')

  let getToken = null
  try { const auth = useAuth(); getToken = auth.getToken } catch { /* Clerk not configured */ }

  const getHeaders = async () => {
    const headers = { 'Content-Type': 'application/json' }
    if (getToken) { try { const t = await getToken(); if (t) headers['Authorization'] = 'Bearer ' + t } catch { /* no-op */ } }
    return headers
  }

  const TABS = [
    { key: 'upload', label: 'Upload File' },
    { key: 'sheets', label: 'Google Sheets' },
    { key: 'manual', label: 'Manual Entry' },
  ]

  return (
    <div className="dashboard">
      <section className="section">
        <h2 className="section-title">Lead Import</h2>
        <p className="section-desc">Bulk import leads from CSV/Excel files, Google Sheets, or enter manually. Dual push: GHL + Notion.</p>

        {/* Tab bar */}
        <div className="days-toggle" style={{ marginBottom: '1.25rem' }}>
          {TABS.map(t => (
            <button key={t.key} className={'btn btn-sm' + (activeTab === t.key ? ' btn-toggle-active' : '')} onClick={() => setActiveTab(t.key)}>
              {t.label}
            </button>
          ))}
        </div>

        {/* Tab content */}
        {activeTab === 'upload' && <UploadFileTab getHeaders={getHeaders} />}
        {activeTab === 'sheets' && <GoogleSheetsTab getHeaders={getHeaders} />}
        {activeTab === 'manual' && <ManualEntryTab getHeaders={getHeaders} />}
      </section>
    </div>
  )
}

export default LeadImport