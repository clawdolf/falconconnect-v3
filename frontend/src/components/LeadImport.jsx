import { useState, useRef, useCallback } from 'react'
import * as XLSX from 'xlsx'
import {
  VENDOR_TIERS, NEEDS_LEAD_AGE, VENDOR_AGE_BUCKETS, LEAD_TYPES, LEAD_VENDORS,
  LEAD_FIELDS, STEP_LABELS, autoMapHeaders, autoDetectVendor, buildLeads,
} from '../utils/leadImportUtils'
import QuickAddLead from './QuickAddLead'

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
  const [dryRun, setDryRun] = useState(false)

  // Auth (Clerk)
  let getToken = null
  try { const { useAuth } = require('@clerk/clerk-react'); const auth = useAuth(); getToken = auth.getToken } catch { /* no-op */ }

  const getHeaders = async () => {
    const h = { 'Content-Type': 'application/json' }
    if (getToken) {
      try {
        const t = await getToken()
        if (t) h['Authorization'] = 'Bearer ' + t
      } catch { /* no-op */ }
    }
    return h
  }

  // BUG 2 FIX: Get Google OAuth token from Clerk for Sheets API
  const getGoogleToken = async () => {
    if (!getToken) return null
    try {
      const t = await getToken({ template: 'google' })
      return t || null
    } catch {
      return null
    }
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

  // BUG 1 + 2 FIX: Use correct route (/api/sheets/data) and send X-Google-Token header
  const fetchSheet = async () => {
    const m = sheetUrl.match(/\/spreadsheets\/d\/([a-zA-Z0-9_-]+)/); const id = m ? m[1] : sheetUrl.trim()
    if (!id) { setError('Enter a valid Sheets URL or ID'); return }
    setSheetLoading(true); setError(null)
    try {
      const hdrs = await getHeaders()
      // BUG 2: Get Google OAuth token and send as X-Google-Token header
      const googleToken = await getGoogleToken()
      if (googleToken) {
        hdrs['X-Google-Token'] = googleToken
      }
      // BUG 1 FIX: Use /api/sheets/data (matching backend mount point)
      const resp = await fetch('/api/sheets/data?sheet_id=' + encodeURIComponent(id), { headers: hdrs })
      if (resp.status === 400 && !googleToken) {
        setError('Google Sheets requires signing in with Google. Sign out and sign in with your Google account, or export as CSV and use file upload.')
        return
      }
      if (resp.status === 404 || resp.status === 501) {
        setError('Google Sheets API not configured. Export as CSV and use file upload.')
        return
      }
      if (!resp.ok) {
        const body = await resp.json().catch(() => ({}))
        throw new Error(body.detail || 'Could not fetch sheet data.')
      }
      const data = await resp.json()
      setHeaders(data.headers || []); setParsedRows(data.rows || []); setColumnMap(autoMapHeaders(data.headers || []))
      setFileName(data.sheet_title || 'Google Sheet'); setStep('mapping')
    } catch (err) { setError(err.message) }
    finally { setSheetLoading(false) }
  }

  const mappingOk = ['first_name', 'last_name', 'phone'].every(f => Object.values(columnMap).includes(f))

  // BUG 11 FIX: Use authenticated endpoint /api/leads/bulk instead of /api/public/leads/bulk
  const doImport = async () => {
    const { leads, droppedCount } = buildLeads(parsedRows, headers, columnMap, vendor, tier, leadType, leadAge, purchaseDate)
    if (!leads.length) { setError('No valid leads. Ensure required fields are mapped.'); return }
    setStep('importing'); setError(null); setProgress({ current: 0, total: leads.length })
    const hdrs = await getHeaders()
    const BS = 50
    let created = 0, updated = 0, failed = 0
    const errors = []
    const ghlWarnings = []

    for (let i = 0; i < leads.length; i += BS) {
      const batch = leads.slice(i, i + BS)
      try {
        // BUG 11 FIX: Authenticated endpoint
        const resp = await fetch('/api/leads/bulk', {
          method: 'POST',
          headers: hdrs,
          body: JSON.stringify({ leads: batch, dry_run: dryRun })
        })
        if (resp.ok) {
          const d = await resp.json()
          created += d.created || 0
          updated += d.updated || 0
          failed += d.failed || 0
          if (d.errors) errors.push(...d.errors)
          if (d.ghl_warnings) ghlWarnings.push(...d.ghl_warnings)
        } else {
          // If bulk fails, try individual
          for (const l of batch) {
            try {
              const r = await fetch('/api/leads/capture', {
                method: 'POST',
                headers: hdrs,
                body: JSON.stringify(l)
              })
              if (r.ok) created++
              else failed++
            } catch { failed++ }
          }
        }
      } catch { failed += batch.length }
      setProgress({ current: Math.min(i + BS, leads.length), total: leads.length })
      // Small delay between batches to avoid rate limiting
      if (i + BS < leads.length) await new Promise(r => setTimeout(r, 100))
    }
    setResult({ created, updated, failed, errors, ghlWarnings, droppedCount }); setStep('results')
  }

  const retryFailed = async () => {
    if (!result?.errors?.length) return
    // Rebuild only the failed leads from parsedRows by index
    const failedIndices = new Set(result.errors.map(e => e.index))
    const { leads: failedLeads } = buildLeads(
      parsedRows.filter((_, i) => failedIndices.has(i)),
      headers, columnMap, vendor, tier, leadType, leadAge, purchaseDate
    )
    if (!failedLeads.length) { setError('No retryable leads.'); return }
    setStep('importing'); setError(null); setProgress({ current: 0, total: failedLeads.length })
    const hdrs = await getHeaders()
    let created = 0, failed = 0; const errors = []; const ghlWarnings = []
    try {
      const resp = await fetch('/api/leads/bulk', {
        method: 'POST', headers: hdrs,
        body: JSON.stringify({ leads: failedLeads, dry_run: dryRun })
      })
      if (resp.ok) {
        const d = await resp.json()
        created = d.created || 0; failed = d.failed || 0
        if (d.errors) errors.push(...d.errors)
        if (d.ghl_warnings) ghlWarnings.push(...d.ghl_warnings)
      } else { failed = failedLeads.length }
    } catch { failed = failedLeads.length }
    setProgress({ current: failedLeads.length, total: failedLeads.length })
    setResult(prev => ({
      ...prev,
      created: (prev?.created || 0) + created,
      failed,
      errors,
      ghlWarnings: [...(prev?.ghlWarnings || []), ...ghlWarnings],
    }))
    setStep('results')
  }

  const goBack = () => {
    if (step === 'mapping') setStep(sourceType || 'source')
    else if (step === 'metadata') setStep('mapping')
    else if (step === 'preview') setStep('metadata')
    else setStep('source')
  }

  const previewData = step === 'preview'
    ? buildLeads(parsedRows.slice(0, 5), headers, columnMap, vendor, tier, leadType, leadAge, purchaseDate)
    : { leads: [], droppedCount: 0 }
  const previewLeads = previewData.leads

  // Full count for the preview summary
  const fullBuildData = step === 'preview'
    ? buildLeads(parsedRows, headers, columnMap, vendor, tier, leadType, leadAge, purchaseDate)
    : { leads: [], droppedCount: 0 }

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
        {/* Dry Run Toggle */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', marginBottom: '1rem', padding: '0.625rem 0.875rem', background: dryRun ? 'oklch(18% 0.06 85 / 0.6)' : 'var(--surface)', border: '1px solid ' + (dryRun ? 'var(--accent)' : 'var(--border)'), borderRadius: 3 }}>
          <button
            onClick={() => setDryRun(d => !d)}
            style={{
              display: 'flex', alignItems: 'center', gap: '0.5rem',
              background: dryRun ? 'var(--accent)' : 'var(--bg)',
              color: dryRun ? 'oklch(15% 0.01 85)' : 'var(--text-muted)',
              border: '1px solid ' + (dryRun ? 'var(--accent)' : 'var(--border)'),
              borderRadius: 3, padding: '0.3rem 0.75rem',
              fontFamily: 'var(--font-display)', fontSize: '0.75rem', fontWeight: 700,
              letterSpacing: '0.06em', textTransform: 'uppercase', cursor: 'pointer',
              transition: 'all 0.15s'
            }}
          >
            <span style={{ width: 10, height: 10, borderRadius: '50%', background: dryRun ? 'oklch(15% 0.01 85)' : 'var(--border)', display: 'inline-block', transition: 'all 0.15s' }} />
            {dryRun ? 'DRY RUN ON' : 'DRY RUN OFF'}
          </button>
          <span style={{ fontFamily: 'var(--font-mono)', fontSize: '0.7rem', color: dryRun ? 'var(--accent)' : 'var(--text-muted)' }}>
            {dryRun ? 'Wizard and menus work — no data will be sent to GHL or Notion' : 'Live mode — imports will write to GHL and Notion'}
          </span>
        </div>

        {/* Header row */}
        <div className="section-header-row" style={{ marginBottom: '0.25rem' }}>
          {step !== 'source' && step !== 'importing' && step !== 'results' && (
            <button className="btn btn-sm" onClick={goBack} style={{ padding: '0.2rem 0.6rem' }}>&larr;</button>
          )}
          <h2 className="section-title" style={{ margin: 0 }}>{titleMap[step]}</h2>
          {fileName && step !== 'source' && step !== 'results' && (
            <span className="wizard-filename">{fileName}</span>
          )}
          <div style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
            <QuickAddLead />
            {step !== 'source' && step !== 'importing' && (
              <button className="btn btn-sm" onClick={resetWizard} style={{ padding: '0.2rem 0.6rem' }}>Start Over</button>
            )}
          </div>
        </div>

        {/* Step indicator */}
        {stepIdx >= 0 && (
          <div className="wizard-step-indicator">
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
            <div className="input-btn-row">
              <input className="form-input" style={{ flex: 1 }} placeholder="https://docs.google.com/spreadsheets/d/..." value={sheetUrl} onChange={e => setSheetUrl(e.target.value)} onKeyDown={e => { if (e.key === 'Enter') fetchSheet() }} />
              <button className="btn btn-primary" onClick={fetchSheet} disabled={!sheetUrl.trim() || sheetLoading}>{sheetLoading ? 'Loading...' : 'Fetch'}</button>
            </div>
            <p className="form-hint" style={{ marginTop: '0.75rem' }}>Requires Google sign-in with Sheets access. Otherwise, export as CSV and use file upload.</p>
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
                <div key={h} className="column-map-row">
                  <span className="column-map-label" title={h}>{h}</span>
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
                <label className="form-label">Lead Age Bucket <span style={{ fontWeight: 400, color: 'var(--text-muted)', fontSize: '0.65rem' }}>(applied only to rows without their own value)</span></label>
                <select className="form-input" value={leadAge} onChange={e => setLeadAge(e.target.value)}>
                  <option value="">N/A</option>
                  {(VENDOR_AGE_BUCKETS[vendor] || []).map(a => <option key={a} value={a}>{a}</option>)}
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
            <div className="preview-summary">
              <div className="preview-summary-grid">
                <span><strong style={{ color: 'var(--text)' }}>{fullBuildData.leads.length}</strong> leads to import</span>
                {fullBuildData.droppedCount > 0 && (
                  <span style={{ color: 'var(--amber)' }}><strong>{fullBuildData.droppedCount}</strong> rows dropped (missing name/phone)</span>
                )}
                <span>Source: <strong style={{ color: 'var(--text)' }}>{fileName}</strong></span>
                <span>Vendor: <strong style={{ color: 'var(--text)' }}>{vendor} / {tier}</strong></span>
                <span>Type: <strong style={{ color: 'var(--text)' }}>{leadType}</strong></span>
                {purchaseDate && <span>Date: <strong style={{ color: 'var(--text)' }}>{purchaseDate}</strong></span>}
                {leadAge && <span>Age: <strong style={{ color: 'var(--text)' }}>{leadAge}</strong></span>}
              </div>
            </div>
            {previewLeads.length > 0 && (
              <div className="table-scroll-wrapper" style={{ maxHeight: 240, marginBottom: '1rem' }}>
                <table className="results-table">
                  <thead><tr><th>#</th><th>Name</th><th>Phone</th><th>Email</th><th>Source</th><th>Type</th></tr></thead>
                  <tbody>
                    {previewLeads.map((l, i) => (
                      <tr key={i}><td>{i + 1}</td><td>{l.first_name} {l.last_name}</td><td>{l.phone}</td><td>{l.email || '—'}</td><td>{l.lead_source || '—'}</td><td>{l.lead_type || '—'}</td></tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
            <p className="form-hint">Showing first {previewLeads.length} of {fullBuildData.leads.length} leads. Write order: Notion first, then GHL.</p>
            <div style={{ display: 'flex', justifyContent: 'flex-end', marginTop: '1rem', gap: '0.5rem' }}>
              <button className="btn btn-primary" onClick={doImport}>
                {dryRun ? `Dry Run ${fullBuildData.leads.length} Leads` : `Import ${fullBuildData.leads.length} Leads`}
              </button>
            </div>
          </div>
        )}

        {/* IMPORTING */}
        {step === 'importing' && (
          <div style={{ textAlign: 'center', padding: '3rem 0' }}>
            <p style={{ fontFamily: 'var(--font-display)', fontSize: '0.9rem', fontWeight: 600, color: 'var(--text)', marginBottom: '1rem' }}>
              {dryRun ? 'Validating leads...' : 'Importing leads...'}
            </p>
            <div className="progress-bar-container" style={{ marginBottom: '0.5rem' }}>
              <div className="progress-bar" style={{ width: (progress.total > 0 ? (progress.current / progress.total * 100) : 0) + '%' }} />
            </div>
            <p className="progress-label">{progress.current} / {progress.total}</p>
          </div>
        )}

        {/* RESULTS — Enhanced completion screen */}
        {step === 'results' && result && (
          <div>
            <div style={{ textAlign: 'center', padding: '1.5rem 0' }}>
              <div style={{ width: 48, height: 48, borderRadius: '50%', background: result.failed === 0 ? 'oklch(18% 0.04 145)' : 'oklch(18% 0.04 75)', display: 'flex', alignItems: 'center', justifyContent: 'center', margin: '0 auto 0.75rem', color: result.failed === 0 ? 'var(--green)' : 'var(--amber)', fontSize: '1.5rem' }}>{result.failed === 0 ? '✓' : '!'}</div>
              <h3 className="section-title" style={{ borderBottom: 'none', marginBottom: '0.25rem' }}>{dryRun ? 'Dry Run Complete' : 'Import Complete'}</h3>
              {dryRun && <div style={{ display: 'inline-block', fontFamily: 'var(--font-mono)', fontSize: '0.65rem', fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.06em', color: 'oklch(15% 0.01 85)', background: 'var(--accent)', borderRadius: 3, padding: '0.15rem 0.5rem', marginBottom: '0.5rem' }}>DRY RUN — No data was written</div>}
              <div style={{ fontFamily: 'var(--font-mono)', fontSize: '0.8rem', display: 'flex', justifyContent: 'center', gap: '1.5rem', marginTop: '0.5rem', flexWrap: 'wrap' }}>
                <span style={{ color: 'var(--green)' }}>{result.created} created</span>
                {(result.updated || 0) > 0 && <span style={{ color: 'var(--accent)' }}>{result.updated} updated</span>}
                {result.failed > 0 && <span style={{ color: 'var(--red)' }}>{result.failed} failed</span>}
                {(result.ghlWarnings?.length || 0) > 0 && <span style={{ color: 'var(--amber)' }}>{result.ghlWarnings.length} GHL warnings</span>}
                {(result.droppedCount || 0) > 0 && <span style={{ color: 'var(--text-muted)' }}>{result.droppedCount} rows dropped (missing required fields)</span>}
              </div>
            </div>

            {/* Failed rows */}
            {result.errors && result.errors.length > 0 && (
              <div style={{ marginBottom: '1rem' }}>
                <h4 style={{ fontFamily: 'var(--font-display)', fontSize: '0.75rem', fontWeight: 600, color: 'var(--red)', marginBottom: '0.5rem' }}>Failed Rows</h4>
                <div style={{ maxHeight: 160, overflow: 'auto' }}>
                  {result.errors.slice(0, 20).map((e, i) => (
                    <div key={i} className="alert alert-error" style={{ marginTop: i > 0 ? '0.375rem' : 0, fontSize: '0.7rem', padding: '0.375rem 0.625rem' }}>
                      Row {e.index + 1}{e.lead_name ? ' (' + e.lead_name + ')' : ''}: {e.error}
                    </div>
                  ))}
                  {result.errors.length > 20 && <p className="form-hint">...and {result.errors.length - 20} more errors</p>}
                </div>
              </div>
            )}

            {/* GHL warnings */}
            {result.ghlWarnings && result.ghlWarnings.length > 0 && (
              <div style={{ marginBottom: '1rem' }}>
                <h4 style={{ fontFamily: 'var(--font-display)', fontSize: '0.75rem', fontWeight: 600, color: 'var(--amber)', marginBottom: '0.5rem' }}>GHL Warnings (leads saved to Notion but not GHL)</h4>
                <div style={{ maxHeight: 120, overflow: 'auto' }}>
                  {result.ghlWarnings.slice(0, 10).map((w, i) => (
                    <div key={i} style={{ background: 'oklch(18% 0.04 75)', border: '1px solid oklch(25% 0.05 75)', color: 'var(--amber)', padding: '0.375rem 0.625rem', fontFamily: 'var(--font-mono)', fontSize: '0.7rem', borderRadius: 2, marginTop: i > 0 ? '0.375rem' : 0 }}>
                      {w.lead_name}: {w.error}
                    </div>
                  ))}
                  {result.ghlWarnings.length > 10 && <p className="form-hint">...and {result.ghlWarnings.length - 10} more warnings</p>}
                </div>
              </div>
            )}

            <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '0.5rem', marginTop: '1rem' }}>
              {result.failed > 0 && result.errors?.length > 0 && (
                <button className="btn" onClick={retryFailed}>Retry {result.failed} Failed</button>
              )}
              <button className="btn btn-primary" onClick={resetWizard}>Import More</button>
            </div>
          </div>
        )}

      </section>
    </div>
  )
}

export default LeadImport