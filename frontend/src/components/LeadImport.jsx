import { useState, useRef, useCallback, useEffect } from 'react'
import * as XLSX from 'xlsx'

/* ── Constants ── */
const VENDOR_TIERS = {
  'HOFLeads': ['Diamond', 'Gold', 'Silver'],
  'Proven Leads': ['N/A'],
  'Aria Leads': ['Gold', 'Silver', 'N/A'],
  'MilMo': ['Gold', 'Silver', 'N/A'],
}
const NEEDS_LEAD_AGE = { 'HOFLeads': false, 'Proven Leads': true, 'Aria Leads': true, 'MilMo': true }
const LEAD_AGE_BUCKETS = ['7–12M', '13–24M', '25–36M', '37–48M', '49–60M', '60+M']
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
  'phone': 'phone', 'cell': 'phone', 'cell phone': 'phone', 'mobile': 'phone', 'mobile phone': 'phone',
  'email': 'email', 'e-mail': 'email',
  'address': 'address', 'street': 'address', 'street address': 'address',
  'city': 'city', 'state': 'state', 'st': 'state',
  'zip': 'zip_code', 'zip_code': 'zip_code', 'zipcode': 'zip_code', 'zip code': 'zip_code', 'postal': 'zip_code',
  'birth year': 'birth_year', 'birth_year': 'birth_year', 'birthyear': 'birth_year', 'dob': 'birth_year',
  'source': 'lead_source', 'lead source': 'lead_source', 'lead_source': 'lead_source', 'vendor': 'lead_source',
  'type': 'lead_type', 'lead type': 'lead_type', 'lead_type': 'lead_type',
  'lead age': 'lead_age_bucket', 'lender': 'lender', 'mortgage company': 'lender',
  'mail date': 'mail_date', 'mail_date': 'mail_date', 'maildate': 'mail_date',
  'notes': 'notes', 'note': 'notes', 'comments': 'notes',
}

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
  if (fn.includes('hof')) {
    out.vendor = 'HOFLeads'
    if (fn.includes('gold') || fn.includes('t2')) out.tier = 'Gold'
    else if (fn.includes('silver') || fn.includes('t3')) out.tier = 'Silver'
  } else if (fn.includes('proven')) { out.vendor = 'Proven Leads'; out.tier = 'N/A' }
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

const STEP_LABELS = {
  source: 'Source', file: 'Upload', sheets: 'Sheets',
  mapping: 'Map Columns', metadata: 'Lead Details',
  preview: 'Preview', importing: 'Importing', results: 'Results',
}

/* ── Main Component ── */
function LeadImport() {
  // Wizard state
  const [step, setStep] = useState('source')
  const [sourceType, setSourceType] = useState(null)
  const fileInputRef = useRef(null)
  const [dragActive, setDragActive] = useState(false)
  const [fileName, setFileName] = useState('')
  const [sheetUrl, setSheetUrl] = useState('')
  const [sheetLoading, setSheetLoading] = useState(false)
  const [headers, setHeaders] = useState([])
  const [parsedRows, setParsedRows] = useState([])
  const [columnMap, setColumnMap] = useState({})
  const [vendor, setVendor] = useState('HOFLeads')
  const [tier, setTier] = useState('Diamond')
  const [leadType, setLeadType] = useState('Mortgage Protection')
  const [leadAge, setLeadAge] = useState('')
  const [purchaseDate, setPurchaseDate] = useState('')
  const [progress, setProgress] = useState({ current: 0, total: 0 })
  const [result, setResult] = useState(null)
  const [error, setError] = useState(null)

  // Auth (Clerk optional)
  let getToken = null
  try { const { useAuth } = require('@clerk/clerk-react'); const auth = useAuth(); getToken = auth.getToken } catch { /* no-op */ }

  const getHeaders = async () => {
    const h = { 'Content-Type': 'application/json' }
    if (getToken) { try { const t = await getToken(); if (t) h['Authorization'] = 'Bearer ' + t } catch { /* no-op */ } }
    return h
  }

  const resetWizard = () => {
    setStep('source'); setSourceType(null); setFileName('')
    setHeaders([]); setParsedRows([]); setColumnMap({})
    setVendor('HOFLeads'); setTier('Diamond'); setLeadType('Mortgage Protection')
    setLeadAge(''); setPurchaseDate(''); setResult(null); setError(null)
    setSheetUrl(''); setSheetLoading(false)
  }

  const parseFile = async (file) => {
    setError(null)
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
      setHeaders(hdrs); setParsedRows(rows); setColumnMap(autoMapHeaders(hdrs))
      setFileName(file.name)
      const det = autoDetectVendor(file.name)
      setVendor(det.vendor); setTier(det.tier); setLeadType(det.leadType)
      setStep('mapping')
    } catch (err) { setError('Parse error: ' + err.message) }
  }

  const handleDrag = useCallback((e) => {
    e.preventDefault(); e.stopPropagation()
    setDragActive(e.type === 'dragenter' || e.type === 'dragover')
  }, [])

  const handleDrop = useCallback((e) => {
    e.preventDefault(); e.stopPropagation(); setDragActive(false)
    if (e.dataTransfer.files?.[0]) parseFile(e.dataTransfer.files[0])
  }, [])

  const fetchSheet = async () => {
    const m = sheetUrl.match(/\/spreadsheets\/d\/([a-zA-Z0-9_-]+)/); const id = m ? m[1] : sheetUrl.trim()
    if (!id) { setError('Enter a valid Sheets URL or ID'); return }
    setSheetLoading(true); setError(null)
    try {
      const hdrs = await getHeaders()
      const resp = await fetch('/api/public/sheets/data?sheet_id=' + encodeURIComponent(id), { headers: hdrs })
      if (resp.status === 404 || resp.status === 501) { setError('Google Sheets API not configured. Export as CSV and use file upload.'); return }
      if (!resp.ok) throw new Error('Could not fetch sheet data.')
      const data = await resp.json()
      setHeaders(data.headers || []); setParsedRows(data.rows || []); setColumnMap(autoMapHeaders(data.headers || []))
      setFileName('Google Sheet'); setStep('mapping')
    } catch (err) { setError(err.message) }
    finally { setSheetLoading(false) }
  }

  const mappingOk = ['first_name', 'last_name', 'phone'].every(f => Object.values(columnMap).includes(f))

  const doImport = async () => {
    const leads = buildLeads(parsedRows, headers, columnMap, vendor, tier, leadType, leadAge, purchaseDate)
    if (!leads.length) { setError('No valid leads. Ensure required fields are mapped.'); return }
    setStep('importing'); setError(null); setProgress({ current: 0, total: leads.length })
    const hdrs = await getHeaders(); const BS = 50; let created = 0, failed = 0; const errors = []
    for (let i = 0; i < leads.length; i += BS) {
      const batch = leads.slice(i, i + BS)
      try {
        const resp = await fetch('/api/public/leads/bulk', { method: 'POST', headers: hdrs, body: JSON.stringify({ leads: batch }) })
        if (resp.ok) { const d = await resp.json(); created += d.created || 0; failed += d.failed || 0; if (d.errors) errors.push(...d.errors) }
        else {
          for (const l of batch) {
            try { const r = await fetch('/api/public/leads/capture', { method: 'POST', headers: hdrs, body: JSON.stringify(l) }); if (r.ok) created++; else failed++ }
            catch { failed++ }
          }
        }
      } catch { failed += batch.length }
      setProgress({ current: Math.min(i + BS, leads.length), total: leads.length })
    }
    setResult({ created, failed, errors }); setStep('results')
  }

  const goBack = () => {
    if (step === 'mapping') setStep(sourceType || 'source')
    else if (step === 'metadata') setStep('mapping')
    else if (step === 'preview') setStep('metadata')
    else setStep('source')
  }

  const previewLeads = step === 'preview'
    ? buildLeads(parsedRows.slice(0, 5), headers, columnMap, vendor, tier, leadType, leadAge, purchaseDate)
    : []

  const stepFlow = ['mapping', 'metadata', 'preview', 'importing', 'results']
  const stepIdx = stepFlow.indexOf(step)

  const titleMap = {
    source: 'Import Leads', file: 'Upload File', sheets: 'Google Sheets',
    mapping: 'Map Columns', metadata: 'Lead Details',
    preview: 'Review & Confirm', importing: 'Importing...', results: 'Import Complete',
  }

  return (
    <div className="dashboard">
      <section className="section">
        {/* Header row */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', marginBottom: '0.25rem' }}>
          {step !== 'source' && step !== 'importing' && step !== 'results' && (
            <button className="btn btn-sm" onClick={goBack} style={{ padding: '0.2rem 0.6rem' }}>&larr;</button>
          )}
          <h2 className="section-title" style={{ margin: 0 }}>{titleMap[step]}</h2>
          {fileName && step !== 'source' && step !== 'results' && (
            <span style={{ fontFamily: 'var(--font-mono)', fontSize: '0.65rem', color: 'var(--text-muted)' }}>{fileName}</span>
          )}
          {step !== 'source' && step !== 'importing' && (
            <button className="btn btn-sm" onClick={resetWizard} style={{ marginLeft: 'auto', padding: '0.2rem 0.6rem' }}>Start Over</button>
          )}
        </div>

        {/* Step indicator */}
        {stepIdx >= 0 && (
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.375rem', marginBottom: '1.25rem', fontFamily: 'var(--font-mono)', fontSize: '0.6rem', color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.06em', flexWrap: 'wrap' }}>
            {stepFlow.map((s, i) => {
              const cur = s === step, done = i < stepIdx
              return (
                <span key={s} style={{ display: 'flex', alignItems: 'center', gap: '0.25rem' }}>
                  <span style={{ width: 16, height: 16, borderRadius: '50%', display: 'inline-flex', alignItems: 'center', justifyContent: 'center', fontSize: '0.55rem', fontWeight: 600, background: cur ? 'var(--accent)' : done ? 'var(--green)' : 'var(--bg)', color: cur || done ? 'oklch(15% 0.01 85)' : 'var(--text-muted)', border: '1px solid ' + (cur ? 'var(--accent)' : done ? 'var(--green)' : 'var(--border)') }}>
                    {done ? '✓' : i + 1}
                  </span>
                  <span style={{ color: cur ? 'var(--text)' : 'var(--text-muted)' }}>{STEP_LABELS[s] || s}</span>
                  {i < stepFlow.length - 1 && <span style={{ margin: '0 0.25rem', color: 'var(--border)' }}>&mdash;</span>}
                </span>
              )
            })}
          </div>
        )}

        {error && <div className="alert alert-error" style={{ marginBottom: '1rem', fontSize: '0.75rem' }}>{error}</div>}

        {/* SOURCE */}
        {step === 'source' && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '0.625rem', maxWidth: 480 }}>
            <button onClick={() => { setSourceType('file'); setStep('file') }} className="btn" style={{ display: 'flex', alignItems: 'center', gap: '1rem', padding: '1rem 1.25rem', textAlign: 'left', height: 'auto' }}>
              <div style={{ width: 40, height: 40, background: 'oklch(18% 0.04 85)', borderRadius: 3, display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--accent)', fontSize: '1.25rem', fontWeight: 700, flexShrink: 0 }}>↑</div>
              <div>
                <div style={{ fontFamily: 'var(--font-display)', fontSize: '0.85rem', fontWeight: 600, color: 'var(--text)' }}>Upload File</div>
                <div style={{ fontFamily: 'var(--font-mono)', fontSize: '0.7rem', color: 'var(--text-muted)' }}>CSV, Excel (.xlsx, .xls), TSV</div>
              </div>
            </button>
            <button onClick={() => { setSourceType('sheets'); setStep('sheets') }} className="btn" style={{ display: 'flex', alignItems: 'center', gap: '1rem', padding: '1rem 1.25rem', textAlign: 'left', height: 'auto' }}>
              <div style={{ width: 40, height: 40, background: 'oklch(18% 0.04 145)', borderRadius: 3, display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--green)', fontSize: '1.25rem', fontWeight: 700, flexShrink: 0 }}>G</div>
              <div>
                <div style={{ fontFamily: 'var(--font-display)', fontSize: '0.85rem', fontWeight: 600, color: 'var(--text)' }}>Google Sheets</div>
                <div style={{ fontFamily: 'var(--font-mono)', fontSize: '0.7rem', color: 'var(--text-muted)' }}>Import from a shared spreadsheet</div>
              </div>
            </button>
          </div>
        )}

        {/* FILE UPLOAD */}
        {step === 'file' && (
          <div onDragEnter={handleDrag} onDragLeave={handleDrag} onDragOver={handleDrag} onDrop={handleDrop}
            onClick={() => fileInputRef.current?.click()}
            style={{ border: '2px dashed ' + (dragActive ? 'var(--accent)' : 'var(--border)'), borderRadius: 3, padding: '4rem 2rem', textAlign: 'center', cursor: 'pointer', background: dragActive ? 'oklch(14% 0.015 85 / 0.1)' : 'var(--bg)', transition: 'all 0.15s', maxWidth: 560 }}>
            <input ref={fileInputRef} type="file" accept=".csv,.xlsx,.xls,.tsv" onChange={e => { if (e.target.files?.[0]) parseFile(e.target.files[0]); e.target.value = '' }} style={{ display: 'none' }} />
            <div style={{ fontSize: '2.5rem', marginBottom: '0.75rem', color: 'var(--text-muted)' }}>↑</div>
            <p style={{ fontFamily: 'var(--font-mono)', fontSize: '0.85rem', color: 'var(--text)', marginBottom: '0.375rem' }}>Drop file here or click to browse</p>
            <p className="form-hint">CSV, Excel (.xlsx, .xls), TSV</p>
          </div>
        )}

        {/* GOOGLE SHEETS */}
        {step === 'sheets' && (
          <div style={{ maxWidth: 560 }}>
            <p className="form-hint" style={{ marginBottom: '0.75rem' }}>Paste a Google Sheets URL or spreadsheet ID.</p>
            <div style={{ display: 'flex', gap: '0.5rem' }}>
              <input className="form-input" style={{ flex: 1 }} placeholder="https://docs.google.com/spreadsheets/d/..." value={sheetUrl} onChange={e => setSheetUrl(e.target.value)} onKeyDown={e => { if (e.key === 'Enter') fetchSheet() }} />
              <button className="btn btn-primary" onClick={fetchSheet} disabled={!sheetUrl.trim() || sheetLoading}>{sheetLoading ? 'Loading...' : 'Fetch'}</button>
            </div>
            <p className="form-hint" style={{ marginTop: '0.75rem' }}>If Google Sheets API is not configured, export as CSV and use file upload.</p>
          </div>
        )}

        {/* COLUMN MAPPING */}
        {step === 'mapping' && (
          <div>
            <p className="form-hint" style={{ marginBottom: '0.75rem' }}>{parsedRows.length} rows detected. Map columns to lead fields.</p>
            {!mappingOk && (
              <div style={{ background: 'oklch(18% 0.04 75)', border: '1px solid oklch(25% 0.05 75)', color: 'var(--amber)', padding: '0.5rem 0.75rem', fontFamily: 'var(--font-mono)', fontSize: '0.7rem', borderRadius: 2, marginBottom: '0.75rem' }}>
                Map at least First Name, Last Name, and Phone to continue.
              </div>
            )}
            <div style={{ maxHeight: 360, overflow: 'auto' }}>
              {headers.map(h => (
                <div key={h} style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', marginBottom: '0.375rem' }}>
                  <span style={{ fontFamily: 'var(--font-mono)', fontSize: '0.75rem', color: 'var(--text-muted)', width: '38%', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={h}>{h}</span>
                  <span style={{ color: 'var(--text-muted)', fontSize: '0.7rem' }}>→</span>
                  <select className="form-input" style={{ flex: 1, fontSize: '0.75rem', padding: '0.25rem 0.5rem' }} value={columnMap[h] || ''} onChange={e => setColumnMap(prev => ({ ...prev, [h]: e.target.value }))}>
                    <option value="">— skip —</option>
                    {LEAD_FIELDS.map(f => <option key={f.value} value={f.value}>{f.label}</option>)}
                  </select>
                  {columnMap[h] && <span className="badge badge-success" style={{ fontSize: '0.55rem' }}>mapped</span>}
                </div>
              ))}
            </div>
            <div style={{ display: 'flex', justifyContent: 'flex-end', marginTop: '1rem' }}>
              <button className="btn btn-primary" onClick={() => setStep('metadata')} disabled={!mappingOk}>Next →</button>
            </div>
          </div>
        )}

        {/* METADATA */}
        {step === 'metadata' && (
          <div>
            <p className="form-hint" style={{ marginBottom: '0.75rem' }}>Set batch-level metadata for all {parsedRows.length} leads.</p>
            <div className="form-grid">
              <div className="form-field">
                <label className="form-label">Lead Vendor</label>
                <select className="form-input" value={vendor} onChange={e => { setVendor(e.target.value); setTier((VENDOR_TIERS[e.target.value] || [])[0] || 'N/A') }}>
                  {LEAD_VENDORS.map(v => <option key={v} value={v}>{v}</option>)}
                </select>
              </div>
              <div className="form-field">
                <label className="form-label">Tier</label>
                <select className="form-input" value={tier} onChange={e => setTier(e.target.value)} disabled={vendor === 'Proven Leads'}>
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
                <label className="form-label">Purchase Date</label>
                <input className="form-input" type="date" value={purchaseDate} onChange={e => setPurchaseDate(e.target.value)} />
              </div>
            </div>
            {NEEDS_LEAD_AGE[vendor] && (
              <div className="form-field" style={{ marginTop: '0.75rem' }}>
                <label className="form-label">Lead Age Bucket</label>
                <select className="form-input" value={leadAge} onChange={e => setLeadAge(e.target.value)}>
                  <option value="">N/A</option>
                  {LEAD_AGE_BUCKETS.map(a => <option key={a} value={a}>{a}</option>)}
                </select>
              </div>
            )}
            <div style={{ display: 'flex', justifyContent: 'flex-end', marginTop: '1rem', gap: '0.5rem' }}>
              <button className="btn btn-primary" onClick={() => setStep('preview')}>Review →</button>
            </div>
          </div>
        )}

        {/* PREVIEW */}
        {step === 'preview' && (
          <div>
            <div style={{ background: 'var(--bg)', border: '1px solid var(--border)', borderRadius: 2, padding: '0.75rem 1rem', marginBottom: '1rem' }}>
              <div style={{ fontFamily: 'var(--font-mono)', fontSize: '0.7rem', color: 'var(--text-muted)', display: 'flex', flexWrap: 'wrap', gap: '1.25rem' }}>
                <span><strong style={{ color: 'var(--text)' }}>{parsedRows.length}</strong> leads to import</span>
                <span>Source: <strong style={{ color: 'var(--text)' }}>{fileName}</strong></span>
                <span>Vendor: <strong style={{ color: 'var(--text)' }}>{vendor} / {tier}</strong></span>
                <span>Type: <strong style={{ color: 'var(--text)' }}>{leadType}</strong></span>
                {purchaseDate && <span>Date: <strong style={{ color: 'var(--text)' }}>{purchaseDate}</strong></span>}
                {leadAge && <span>Age: <strong style={{ color: 'var(--text)' }}>{leadAge}</strong></span>}
              </div>
            </div>
            {previewLeads.length > 0 && (
              <div style={{ overflow: 'auto', maxHeight: 240, marginBottom: '1rem' }}>
                <table className="results-table">
                  <thead><tr><th>#</th><th>Name</th><th>Phone</th><th>Email</th><th>Source</th></tr></thead>
                  <tbody>
                    {previewLeads.map((l, i) => (
                      <tr key={i}><td>{i + 1}</td><td>{l.first_name} {l.last_name}</td><td>{l.phone}</td><td>{l.email || '—'}</td><td>{l.lead_source || '—'}</td></tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
            <p className="form-hint">Showing first {previewLeads.length} of {parsedRows.length} leads. Dual push: GHL + Notion.</p>
            <div style={{ display: 'flex', justifyContent: 'flex-end', marginTop: '1rem', gap: '0.5rem' }}>
              <button className="btn btn-primary" onClick={doImport}>Import {parsedRows.length} Leads</button>
            </div>
          </div>
        )}

        {/* IMPORTING */}
        {step === 'importing' && (
          <div style={{ textAlign: 'center', padding: '3rem 0' }}>
            <p style={{ fontFamily: 'var(--font-display)', fontSize: '0.9rem', fontWeight: 600, color: 'var(--text)', marginBottom: '1rem' }}>Importing leads...</p>
            <div className="progress-bar-container" style={{ marginBottom: '0.5rem' }}>
              <div className="progress-bar" style={{ width: (progress.total > 0 ? (progress.current / progress.total * 100) : 0) + '%' }} />
            </div>
            <p className="progress-label">{progress.current} / {progress.total}</p>
          </div>
        )}

        {/* RESULTS */}
        {step === 'results' && result && (
          <div>
            <div style={{ textAlign: 'center', padding: '1.5rem 0' }}>
              <div style={{ width: 48, height: 48, borderRadius: '50%', background: result.failed === 0 ? 'oklch(18% 0.04 145)' : 'oklch(18% 0.04 75)', display: 'flex', alignItems: 'center', justifyContent: 'center', margin: '0 auto 0.75rem', color: result.failed === 0 ? 'var(--green)' : 'var(--amber)', fontSize: '1.5rem' }}>{result.failed === 0 ? '✓' : '!'}</div>
              <h3 className="section-title" style={{ borderBottom: 'none', marginBottom: '0.25rem' }}>Import Complete</h3>
              <div style={{ fontFamily: 'var(--font-mono)', fontSize: '0.8rem', display: 'flex', justifyContent: 'center', gap: '1.5rem', marginTop: '0.5rem' }}>
                <span style={{ color: 'var(--green)' }}>{result.created} created</span>
                {result.failed > 0 && <span style={{ color: 'var(--red)' }}>{result.failed} failed</span>}
              </div>
            </div>
            {result.errors && result.errors.length > 0 && (
              <div style={{ maxHeight: 160, overflow: 'auto', marginBottom: '1rem' }}>
                {result.errors.slice(0, 15).map((e, i) => (
                  <div key={i} className="alert alert-error" style={{ marginTop: i > 0 ? '0.375rem' : 0, fontSize: '0.7rem', padding: '0.375rem 0.625rem' }}>
                    Row {e.index + 1}{e.lead_name ? ' (' + e.lead_name + ')' : ''}: {e.error}
                  </div>
                ))}
                {result.errors.length > 15 && <p className="form-hint">...and {result.errors.length - 15} more errors</p>}
              </div>
            )}
            <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '0.5rem', marginTop: '1rem' }}>
              <button className="btn btn-primary" onClick={resetWizard}>Import More</button>
            </div>
          </div>
        )}

      </section>
    </div>
  )
}

export default LeadImport
