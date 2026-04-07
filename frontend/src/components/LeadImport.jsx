import { useState, useRef, useCallback, useMemo } from 'react'
import { flushSync } from 'react-dom'
import { useAuthSafe as useAuth } from '../hooks/useClerkSafe'
import * as XLSX from 'xlsx'
import {
  VENDOR_TIERS, NEEDS_LEAD_AGE, VENDOR_AGE_BUCKETS, LEAD_TYPES, LEAD_VENDORS,
  LEAD_FIELDS, STEP_LABELS, autoMapHeaders, autoDetectVendor, buildLeads,
  isMappingValid, getMissingRequired, getDuplicateMappings,
} from '../utils/leadImportUtils'
import QuickAddLead from './QuickAddLead'

function LeadImport() {
  const [step, setStep] = useState('source')
  const [sourceType, setSourceType] = useState(null)
  const fileInputRef = useRef(null)
  const [dragActive, setDragActive] = useState(false)
  const [sheetUrl, setSheetUrl] = useState('')
  const [sheetLoading, setSheetLoading] = useState(false)
  const [fileQueue, setFileQueue] = useState([])
  const [columnMap, setColumnMap] = useState({})
  const [initialAutoMap, setInitialAutoMap] = useState({})
  const [applyMappingToAll, setApplyMappingToAll] = useState(true)
  const [mappingWarning, setMappingWarning] = useState('')
  const [headers, setHeaders] = useState([])
  const [sampleRow, setSampleRow] = useState([])
  const [progress, setProgress] = useState({ current: 0, total: 0, fileIndex: 0, fileName: '' })
  const [error, setError] = useState(null)
  const [dryRun, setDryRun] = useState(false)
  const [testMode, setTestMode] = useState(false)
  const [grandResult, setGrandResult] = useState(null)
  const [previewTab, setPreviewTab] = useState(0)
  const [perFileMaps, setPerFileMaps] = useState({})
  const [mappingFileIdx, setMappingFileIdx] = useState(0)
  const [adjustAge, setAdjustAge] = useState(false)
  const [enableRvm, setEnableRvm] = useState(true)

  const { getToken } = useAuth()

  const getAuthHeaders = async () => {
    const h = { 'Content-Type': 'application/json' }
    if (getToken) { try { const t = await getToken(); if (t) h['Authorization'] = 'Bearer ' + t } catch {} }
    return h
  }
  const getGoogleToken = async () => {
    if (!getToken) return null
    try { const t = await getToken({ template: 'google' }); return t || null } catch { return null }
  }

  const resetWizard = () => {
    setStep('source'); setSourceType(null); setFileQueue([]); setHeaders([]); setSampleRow([])
    setColumnMap({}); setInitialAutoMap({}); setApplyMappingToAll(true); setMappingWarning('')
    setError(null); setGrandResult(null); setSheetUrl(''); setSheetLoading(false); setPreviewTab(0)
    setProgress({ current: 0, total: 0, fileIndex: 0, fileName: '' })
    setPerFileMaps({}); setMappingFileIdx(0); setAdjustAge(false); setEnableRvm(true)
  }

  const parseOneFile = async (file) => {
    const ext = file.name.split('.').pop().toLowerCase()
    if (!['csv', 'xlsx', 'xls', 'tsv'].includes(ext)) throw new Error('Unsupported: .' + ext)
    const data = await file.arrayBuffer()
    const wb = XLSX.read(data, { type: 'array', cellDates: true })
    // Prefer known data sheet names over default first sheet.
    // Cheryl files have 'qryExportOrder' (data) + 'Call_Sheet' (transposed print layout).
    const PREFERRED_SHEETS = ['qryexportorder', 'data', 'leads', 'sheet1']
    const sheetName = wb.SheetNames.find(n => PREFERRED_SHEETS.includes(n.toLowerCase())) || wb.SheetNames[0]
    const sheet = wb.Sheets[sheetName]
    // Use raw:true to get Date objects for date cells, then stringify with 4-digit years.
    // raw:false with dateNF produces 2-digit years (e.g. "4/9/24") which break getCherylTier().
    let json = XLSX.utils.sheet_to_json(sheet, { header: 1, raw: true })
    json = json.map(row => row.map(cell => {
      if (cell instanceof Date) {
        return `${cell.getMonth() + 1}/${cell.getDate()}/${cell.getFullYear()}`
      }
      return cell === null || cell === undefined ? '' : cell
    }))
    if (json.length < 2) throw new Error('"' + file.name + '" appears empty.')

    // Auto-detect transposed layout (fields as rows, leads as columns).
    // Cheryl and some other vendors export this way. Detect by checking if
    // the first row contains only numeric or blank values while col 0 of row 1
    // looks like a field name (e.g. "FIRST NAME", "LAST NAME").
    const firstRowAllNumericOrBlank = json[0].every(v => v === '' || v === null || v === undefined || /^\d+$/.test(String(v).trim()))
    const secondRowFirstCellIsLabel = json.length > 1 && /^[A-Z ]{3,}$/.test(String(json[1][0] || '').trim())
    if (firstRowAllNumericOrBlank && secondRowFirstCellIsLabel) {
      // Transpose: rows become columns, columns become rows
      const maxCols = Math.max(...json.map(r => r.length))
      const transposed = Array.from({ length: maxCols }, (_, ci) =>
        json.map(row => (row[ci] !== undefined && row[ci] !== null) ? String(row[ci]).trim() : '')
      )
      json = transposed
    }

    const hdrs = json[0].map(h => String(h || '').trim())
    const rows = json.slice(1).filter(r => r.some(c => c !== null && c !== undefined && c !== ''))
    return { headers: hdrs, parsedRows: rows, sampleRow: rows[0] || [] }
  }

  const handleFiles = async (files) => {
    setError(null)
    const fileList = Array.from(files).filter(f => ['csv','xlsx','xls','tsv'].includes(f.name.split('.').pop().toLowerCase()))
    if (!fileList.length) { setError('No supported files selected.'); return }
    try {
      const newQueue = []
      for (const file of fileList) {
        const { headers: hdrs, parsedRows: rows, sampleRow: sample } = await parseOneFile(file)
        const det = autoDetectVendor(file.name)
        const defaultLeadAge = det.leadAge || (NEEDS_LEAD_AGE[det.vendor] ? (VENDOR_AGE_BUCKETS[det.vendor] || [])[0] || '' : '')
        newQueue.push({ file, name: file.name, vendor: det.vendor, tier: det.tier, leadType: det.leadType, leadAge: defaultLeadAge, purchaseDate: '', status: 'pending', result: null, headers: hdrs, parsedRows: rows, sampleRow: sample })
      }
      setFileQueue(newQueue)
      if (newQueue.length > 0) {
        setHeaders(newQueue[0].headers); setSampleRow(newQueue[0].sampleRow)
        const autoMap = autoMapHeaders(newQueue[0].headers)
        setColumnMap(autoMap); setInitialAutoMap({ ...autoMap })
      }
      setStep('fileConfig')
    } catch (err) { setError('Parse error: ' + err.message) }
  }

  const handleDrag = useCallback((e) => { e.preventDefault(); e.stopPropagation(); setDragActive(e.type === 'dragenter' || e.type === 'dragover') }, [])
  const handleDrop = useCallback((e) => { e.preventDefault(); e.stopPropagation(); setDragActive(false); if (e.dataTransfer.files?.length) handleFiles(e.dataTransfer.files) }, [])

  const fetchSheet = async () => {
    const m = sheetUrl.match(/\/spreadsheets\/d\/([a-zA-Z0-9_-]+)/); const id = m ? m[1] : sheetUrl.trim()
    if (!id) { setError('Enter a valid Sheets URL or ID'); return }
    setSheetLoading(true); setError(null)
    try {
      const hdrs = await getAuthHeaders()
      const googleToken = await getGoogleToken()
      if (googleToken) hdrs['X-Google-Token'] = googleToken
      const resp = await fetch('/api/sheets/data?sheet_id=' + encodeURIComponent(id), { headers: hdrs })
      if (resp.status === 400 && !googleToken) { setError('Google Sheets requires signing in with Google.'); return }
      if (resp.status === 404 || resp.status === 501) { setError('Google Sheets API not configured. Export as CSV.'); return }
      if (!resp.ok) { const body = await resp.json().catch(() => ({})); throw new Error(body.detail || 'Could not fetch sheet data.') }
      const data = await resp.json()
      const sheetHdrs = data.headers || []; const sheetRows = data.rows || []
      const autoMap = autoMapHeaders(sheetHdrs)
      setFileQueue([{ file: null, name: data.sheet_title || 'Google Sheet', vendor: 'HOFLeads', tier: 'Diamond', leadType: 'Mortgage Protection', leadAge: '', purchaseDate: '', status: 'pending', result: null, headers: sheetHdrs, parsedRows: sheetRows, sampleRow: sheetRows[0] || [] }])
      setHeaders(sheetHdrs); setSampleRow(sheetRows[0] || []); setColumnMap(autoMap); setInitialAutoMap({ ...autoMap }); setStep('fileConfig')
    } catch (err) { setError(err.message) } finally { setSheetLoading(false) }
  }

  const updateFileQueueItem = (index, updates) => setFileQueue(prev => prev.map((item, i) => i === index ? { ...item, ...updates } : item))
  const removeFromQueue = (index) => {
    setFileQueue(prev => {
      const next = prev.filter((_, i) => i !== index)
      if (index === 0 && next.length > 0) {
        setHeaders(next[0].headers); setSampleRow(next[0].sampleRow)
        const autoMap = autoMapHeaders(next[0].headers); setColumnMap(autoMap); setInitialAutoMap({ ...autoMap })
      }
      return next
    })
  }

  const mappingOk = isMappingValid(columnMap)
  const duplicateMappings = useMemo(() => getDuplicateMappings(columnMap), [columnMap])
  const sortedHeaders = useMemo(() => [...headers].sort((a, b) => (columnMap[b] ? 1 : 0) - (columnMap[a] ? 1 : 0)), [headers, columnMap])
  const headerIndexMap = useMemo(() => { const m = {}; headers.forEach((h, i) => { m[h] = i }); return m }, [headers])

  // Helper: check if two header arrays are identical
  const headersMatch = (a, b) => a.length === b.length && a.every((h, i) => h === b[i])

  // For per-file mapping: find groups of files with unique headers
  const uniqueHeaderGroups = useMemo(() => {
    if (fileQueue.length <= 1) return []
    const groups = [] // [{fileIndices: [0,2], headers: [...]}]
    fileQueue.forEach((fq, idx) => {
      const existing = groups.find(g => headersMatch(g.headers, fq.headers))
      if (existing) { existing.fileIndices.push(idx) }
      else { groups.push({ fileIndices: [idx], headers: fq.headers }) }
    })
    return groups
  }, [fileQueue])

  // How many unique header sets need separate mapping?
  const uniqueHeaderCount = uniqueHeaderGroups.length

  // Get the effective column map for a given file index
  const getMapForFile = (fi) => {
    if (applyMappingToAll) return columnMap
    return perFileMaps[fi] || columnMap
  }

  // Load headers for a specific file into the mapping UI
  const loadFileForMapping = (fi) => {
    const fq = fileQueue[fi]
    if (!fq) return
    setHeaders(fq.headers)
    setSampleRow(fq.sampleRow)
    const existingMap = perFileMaps[fi]
    if (existingMap) {
      setColumnMap(existingMap)
    } else {
      const autoMap = autoMapHeaders(fq.headers)
      setColumnMap(autoMap)
    }
    setInitialAutoMap(autoMapHeaders(fq.headers))
  }

  const doImport = async () => {
    setStep('importing'); setError(null)
    let totalLeads = 0
    for (let fi = 0; fi < fileQueue.length; fi++) { const fq = fileQueue[fi]; const map = getMapForFile(fi); totalLeads += buildLeads(fq.parsedRows, fq.headers, map, fq.vendor, fq.tier, fq.leadType, fq.leadAge, fq.purchaseDate, adjustAge).leads.length }
    setProgress({ current: 0, total: totalLeads, fileIndex: 0, fileName: fileQueue[0]?.name || '' })
    const authHdrs = await getAuthHeaders()
    const BS = 10  // small batches = live progress bar updates
    let grandCreated = 0, grandFailed = 0, grandDropped = 0, processedLeads = 0
    const grandErrors = [], grandGhlWarnings = []
    for (let fi = 0; fi < fileQueue.length; fi++) {
      const fq = fileQueue[fi]
      const fileMap = getMapForFile(fi)
      updateFileQueueItem(fi, { status: 'importing' })
      setProgress(prev => ({ ...prev, fileIndex: fi, fileName: fq.name }))
      const { leads, droppedCount, droppedRows } = buildLeads(fq.parsedRows, fq.headers, fileMap, fq.vendor, fq.tier, fq.leadType, fq.leadAge, fq.purchaseDate, adjustAge)
      grandDropped += droppedCount
      if (!leads.length) { updateFileQueueItem(fi, { status: 'done', result: { created: 0, failed: 0, ghlWarnings: [], droppedCount, droppedRows } }); continue }
      let fileCreated = 0, fileFailed = 0; const fileGhlWarnings = [], fileErrors = []
      for (let i = 0; i < leads.length; i += BS) {
        const batch = leads.slice(i, i + BS)
        try {
          const resp = await fetch('/api/leads/bulk', { method: 'POST', headers: authHdrs, body: JSON.stringify({ leads: batch, dry_run: dryRun, test_mode: testMode, enable_rvm: enableRvm }) })
          if (resp.ok) {
            const d = await resp.json(); fileCreated += (d.created || 0) + (d.updated || 0); fileFailed += d.failed || 0
            if (d.errors) fileErrors.push(...d.errors); if (d.ghl_warnings) fileGhlWarnings.push(...d.ghl_warnings)
          } else {
            // Do NOT fall back to /api/leads/capture — that path writes to Notion only (no Close, breaks cadence).
            // Treat a non-OK bulk response as a hard failure for the whole batch.
            const errBody = await resp.json().catch(() => ({}))
            const errMsg = errBody.detail || `Bulk import failed (HTTP ${resp.status})`
            for (let k = 0; k < batch.length; k++) {
              fileErrors.push({ index: i + k, error: errMsg, lead_name: `${batch[k].first_name} ${batch[k].last_name}` })
            }
            fileFailed += batch.length
          }
        } catch { fileFailed += batch.length }
        processedLeads += batch.length
        flushSync(() => {
          setProgress(prev => ({ ...prev, current: Math.min(processedLeads, totalLeads) }))
        })
      }
      updateFileQueueItem(fi, { status: fileFailed > 0 && fileCreated === 0 ? 'error' : 'done', result: { created: fileCreated, failed: fileFailed, ghlWarnings: fileGhlWarnings, errors: fileErrors, droppedCount, droppedRows } })
      grandCreated += fileCreated; grandFailed += fileFailed; grandErrors.push(...fileErrors); grandGhlWarnings.push(...fileGhlWarnings)
      // no delay between files
    }
    setGrandResult({ created: grandCreated, failed: grandFailed, errors: grandErrors, ghlWarnings: grandGhlWarnings, droppedCount: grandDropped })
    setStep('results')
  }

  const goBack = () => {
    if (step === 'fileConfig') setStep(sourceType || 'source')
    else if (step === 'mapping') {
      if (!applyMappingToAll && mappingFileIdx > 0) {
        // Go back to previous file group in per-file mapping
        const prevIdx = mappingFileIdx - 1
        setMappingFileIdx(prevIdx)
        loadFileForMapping(uniqueHeaderGroups[prevIdx].fileIndices[0])
      } else {
        setMappingFileIdx(0)
        setStep('fileConfig')
      }
    }
    else if (step === 'preview') setStep('mapping')
    else setStep('source')
  }
  const handleMappingNext = () => {
    if (!mappingOk) { setMappingWarning('Required: First Name (or Full Name), Last Name, and Phone must be mapped.'); return }
    setMappingWarning('')

    // Per-file mapping mode: cycle through unique header groups
    if (!applyMappingToAll && fileQueue.length > 1 && uniqueHeaderCount > 1) {
      // Save current mapping for all files sharing this header set
      const currentGroup = uniqueHeaderGroups[mappingFileIdx]
      if (currentGroup) {
        const updated = { ...perFileMaps }
        currentGroup.fileIndices.forEach(fi => { updated[fi] = { ...columnMap } })
        setPerFileMaps(updated)
      }

      // Move to next unique header group
      const nextIdx = mappingFileIdx + 1
      if (nextIdx < uniqueHeaderCount) {
        setMappingFileIdx(nextIdx)
        const nextGroup = uniqueHeaderGroups[nextIdx]
        const nextFileIdx = nextGroup.fileIndices[0]
        loadFileForMapping(nextFileIdx)
        return
      }
    }

    // If apply-to-all is false but all files have same headers, store the single map for all
    if (!applyMappingToAll && fileQueue.length > 1 && uniqueHeaderCount <= 1) {
      const updated = {}
      fileQueue.forEach((_, fi) => { updated[fi] = { ...columnMap } })
      setPerFileMaps(updated)
    }

    setStep('preview')
  }

  const previewDataByFile = useMemo(() => {
    if (step !== 'preview') return []
    return fileQueue.map((fq, fi) => {
      const map = getMapForFile(fi)
      const preview = buildLeads(fq.parsedRows.slice(0, 5), fq.headers, map, fq.vendor, fq.tier, fq.leadType, fq.leadAge, fq.purchaseDate, adjustAge)
      const full = buildLeads(fq.parsedRows, fq.headers, map, fq.vendor, fq.tier, fq.leadType, fq.leadAge, fq.purchaseDate, adjustAge)
      return { name: fq.name, previewLeads: preview.leads, totalLeads: full.leads.length, droppedCount: full.droppedCount, vendor: fq.vendor, tier: fq.tier, leadType: fq.leadType, leadAge: fq.leadAge }
    })
  }, [step, fileQueue, columnMap, perFileMaps, applyMappingToAll, adjustAge])
  const totalLeadsAcrossFiles = useMemo(() => previewDataByFile.reduce((s, f) => s + f.totalLeads, 0), [previewDataByFile])
  const totalDroppedAcrossFiles = useMemo(() => previewDataByFile.reduce((s, f) => s + f.droppedCount, 0), [previewDataByFile])

  const stepFlow = ['fileConfig', 'mapping', 'preview', 'importing', 'results']
  const stepIdx = stepFlow.indexOf(step)
  const titleMap = { source: 'Import Leads', file: 'Upload Files', sheets: 'Google Sheets', fileConfig: 'File Configuration', mapping: 'Map Columns', preview: 'Review & Confirm', importing: 'Importing...', results: 'Import Complete' }

  return (
    <div className="dashboard">
      <section className="section">
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', marginBottom: '1rem', padding: '0.625rem 0.875rem', background: dryRun ? 'oklch(18% 0.06 85 / 0.6)' : 'var(--surface)', border: '1px solid ' + (dryRun ? 'var(--accent)' : 'var(--border)'), borderRadius: 3 }}>
          <button onClick={() => setDryRun(d => !d)} style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', background: dryRun ? 'var(--accent)' : 'var(--bg)', color: dryRun ? 'oklch(15% 0.01 85)' : 'var(--text-muted)', border: '1px solid ' + (dryRun ? 'var(--accent)' : 'var(--border)'), borderRadius: 3, padding: '0.3rem 0.75rem', fontFamily: 'var(--font-display)', fontSize: '0.75rem', fontWeight: 700, letterSpacing: '0.06em', textTransform: 'uppercase', cursor: 'pointer' }}>
            <span style={{ width: 10, height: 10, borderRadius: '50%', background: dryRun ? 'oklch(15% 0.01 85)' : 'var(--border)', display: 'inline-block' }} />
            {dryRun ? 'DRY RUN ON' : 'DRY RUN OFF'}
          </button>
          <span style={{ fontFamily: 'var(--font-mono)', fontSize: '0.7rem', color: dryRun ? 'var(--accent)' : 'var(--text-muted)' }}>{dryRun ? 'No data will be sent to Close.com' : 'Live mode'}</span>
        </div>
        {!dryRun && (
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', marginBottom: '1rem', padding: '0.625rem 0.875rem', background: testMode ? 'oklch(18% 0.04 200 / 0.6)' : 'var(--surface)', border: '1px solid ' + (testMode ? 'oklch(65% 0.15 200)' : 'var(--border)'), borderRadius: 3 }}>
            <button onClick={() => setTestMode(t => !t)} style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', background: testMode ? 'oklch(65% 0.15 200)' : 'var(--bg)', color: testMode ? 'oklch(15% 0.01 200)' : 'var(--text-muted)', border: '1px solid ' + (testMode ? 'oklch(65% 0.15 200)' : 'var(--border)'), borderRadius: 3, padding: '0.3rem 0.75rem', fontFamily: 'var(--font-display)', fontSize: '0.75rem', fontWeight: 700, letterSpacing: '0.06em', textTransform: 'uppercase', cursor: 'pointer' }}>
              <span style={{ width: 10, height: 10, borderRadius: '50%', background: testMode ? 'oklch(15% 0.01 200)' : 'var(--border)', display: 'inline-block' }} />
              {testMode ? 'TEST MODE ON' : 'TEST MODE OFF'}
            </button>
            <span style={{ fontFamily: 'var(--font-mono)', fontSize: '0.7rem', color: testMode ? 'oklch(65% 0.15 200)' : 'var(--text-muted)' }}>{testMode ? 'Writes with Tier=TEST tag' : 'Production'}</span>
          </div>
        )}
        <div className="section-header-row" style={{ marginBottom: '0.25rem' }}>
          {step !== 'source' && step !== 'importing' && step !== 'results' && <button className="btn btn-sm" onClick={goBack} style={{ padding: '0.2rem 0.6rem' }}>&larr;</button>}
          <h2 className="section-title" style={{ margin: 0 }}>{titleMap[step]}</h2>
          {fileQueue.length > 0 && step !== 'source' && step !== 'results' && <span className="wizard-filename">{fileQueue.length === 1 ? fileQueue[0].name : fileQueue.length + ' files'}</span>}
          <div style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
            <QuickAddLead />
            {step !== 'source' && step !== 'importing' && <button className="btn btn-sm" onClick={resetWizard} style={{ padding: '0.2rem 0.6rem' }}>Start Over</button>}
          </div>
        </div>
        {stepIdx >= 0 && (
          <div className="wizard-step-indicator">
            {stepFlow.map((s, i) => {
              const cur = s === step, done = i < stepIdx
              return (<span key={s} style={{ display: 'flex', alignItems: 'center', gap: '0.25rem' }}>
                <span style={{ width: 16, height: 16, borderRadius: '50%', display: 'inline-flex', alignItems: 'center', justifyContent: 'center', fontSize: '0.55rem', fontWeight: 600, background: cur ? 'var(--accent)' : done ? 'var(--green)' : 'var(--bg)', color: cur || done ? 'oklch(15% 0.01 85)' : 'var(--text-muted)', border: '1px solid ' + (cur ? 'var(--accent)' : done ? 'var(--green)' : 'var(--border)') }}>{done ? '\u2713' : i + 1}</span>
                <span style={{ color: cur ? 'var(--text)' : 'var(--text-muted)' }}>{STEP_LABELS[s] || s}</span>
                {i < stepFlow.length - 1 && <span style={{ margin: '0 0.25rem', color: 'var(--border)' }}>&mdash;</span>}
              </span>)
            })}
          </div>
        )}
        {error && <div className="alert alert-error" style={{ marginBottom: '1rem', fontSize: '0.75rem' }}>{error}</div>}

        {step === 'source' && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '0.625rem', maxWidth: 480 }}>
            <button onClick={() => { setSourceType('file'); setStep('file') }} className="btn" style={{ display: 'flex', alignItems: 'center', gap: '1rem', padding: '1rem 1.25rem', textAlign: 'left', height: 'auto' }}>
              <div style={{ width: 40, height: 40, background: 'oklch(18% 0.04 85)', borderRadius: 3, display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--accent)', fontSize: '1.25rem', fontWeight: 700, flexShrink: 0 }}>{'\u2191'}</div>
              <div><div style={{ fontFamily: 'var(--font-display)', fontSize: '0.85rem', fontWeight: 600, color: 'var(--text)' }}>Upload Files</div><div style={{ fontFamily: 'var(--font-mono)', fontSize: '0.7rem', color: 'var(--text-muted)' }}>CSV, Excel {'\u2014'} multiple files supported</div></div>
            </button>
            <button onClick={() => { setSourceType('sheets'); setStep('sheets') }} className="btn" style={{ display: 'flex', alignItems: 'center', gap: '1rem', padding: '1rem 1.25rem', textAlign: 'left', height: 'auto' }}>
              <div style={{ width: 40, height: 40, background: 'oklch(18% 0.04 145)', borderRadius: 3, display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--green)', fontSize: '1.25rem', fontWeight: 700, flexShrink: 0 }}>G</div>
              <div><div style={{ fontFamily: 'var(--font-display)', fontSize: '0.85rem', fontWeight: 600, color: 'var(--text)' }}>Google Sheets</div><div style={{ fontFamily: 'var(--font-mono)', fontSize: '0.7rem', color: 'var(--text-muted)' }}>Import from a shared spreadsheet</div></div>
            </button>
          </div>
        )}

        {step === 'file' && (
          <div onDragEnter={handleDrag} onDragLeave={handleDrag} onDragOver={handleDrag} onDrop={handleDrop} onClick={() => fileInputRef.current?.click()}
            style={{ border: '2px dashed ' + (dragActive ? 'var(--accent)' : 'var(--border)'), borderRadius: 3, padding: '4rem 2rem', textAlign: 'center', cursor: 'pointer', background: dragActive ? 'oklch(14% 0.015 85 / 0.1)' : 'var(--bg)', maxWidth: 560 }}>
            <input ref={fileInputRef} type="file" accept=".csv,.xlsx,.xls,.tsv" multiple onChange={e => { if (e.target.files?.length) handleFiles(e.target.files); e.target.value = '' }} style={{ display: 'none' }} />
            <div style={{ fontSize: '2.5rem', marginBottom: '0.75rem', color: 'var(--text-muted)' }}>{'\u2191'}</div>
            <p style={{ fontFamily: 'var(--font-mono)', fontSize: '0.85rem', color: 'var(--text)', marginBottom: '0.375rem' }}>Drop files here or click to browse</p>
            <p className="form-hint">CSV, Excel (.xlsx, .xls), TSV {'\u2014'} select multiple files</p>
          </div>
        )}

        {step === 'sheets' && (
          <div style={{ maxWidth: 560 }}>
            <p className="form-hint" style={{ marginBottom: '0.75rem' }}>Paste a Google Sheets URL or spreadsheet ID.</p>
            <div className="input-btn-row">
              <input className="form-input" style={{ flex: 1 }} placeholder="https://docs.google.com/spreadsheets/d/..." value={sheetUrl} onChange={e => setSheetUrl(e.target.value)} onKeyDown={e => { if (e.key === 'Enter') fetchSheet() }} />
              <button className="btn btn-primary" onClick={fetchSheet} disabled={!sheetUrl.trim() || sheetLoading}>{sheetLoading ? 'Loading...' : 'Fetch'}</button>
            </div>
          </div>
        )}

        {step === 'fileConfig' && (
          <div>
            <p className="form-hint" style={{ marginBottom: '0.75rem' }}>{fileQueue.length} file{fileQueue.length > 1 ? 's' : ''} loaded. Configure vendor details for each.</p>
            <div style={{ maxHeight: 440, overflow: 'auto' }}>
              <table className="results-table" style={{ fontSize: '0.75rem' }}>
                <thead><tr><th>File</th><th>Rows</th><th>Vendor</th><th>Tier</th><th>Lead Type</th>{fileQueue.some(fq => NEEDS_LEAD_AGE[fq.vendor]) && <th>Age</th>}<th>Purchase Date</th>{fileQueue.length > 1 && <th></th>}</tr></thead>
                <tbody>{fileQueue.map((fq, idx) => (
                  <tr key={idx}>
                    <td style={{ fontFamily: 'var(--font-mono)', fontSize: '0.7rem', maxWidth: 200, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={fq.name}>{fq.name.replace(/\.[^.]+$/, '')}</td>
                    <td>{fq.parsedRows.length}</td>
                    <td><select className="form-input" style={{ fontSize: '0.7rem', padding: '0.2rem 0.4rem' }} value={fq.vendor} onChange={e => { const v = e.target.value; updateFileQueueItem(idx, { vendor: v, tier: (VENDOR_TIERS[v] || [])[0] || 'N/A', leadAge: NEEDS_LEAD_AGE[v] ? (VENDOR_AGE_BUCKETS[v] || [])[0] || '' : '' }) }}>{LEAD_VENDORS.map(v => <option key={v} value={v}>{v}</option>)}</select></td>
                    <td>{fq.vendor === 'Cheryl'
                      ? <span style={{ fontFamily: 'var(--font-mono)', fontSize: '0.65rem', color: 'var(--text-muted)', padding: '0.2rem 0.4rem', display: 'inline-block' }} title="Cheryl tier is auto-assigned per lead from the Date Lead Rcvd column">Auto (by date)</span>
                      : <select className="form-input" style={{ fontSize: '0.7rem', padding: '0.2rem 0.4rem' }} value={fq.tier} onChange={e => updateFileQueueItem(idx, { tier: e.target.value })} disabled={fq.vendor === 'Anne Proven Leads'}>{(VENDOR_TIERS[fq.vendor] || []).map(t => <option key={t} value={t}>{t}</option>)}</select>
                    }</td>
                    <td><select className="form-input" style={{ fontSize: '0.7rem', padding: '0.2rem 0.4rem' }} value={fq.leadType} onChange={e => updateFileQueueItem(idx, { leadType: e.target.value })}>{LEAD_TYPES.map(t => <option key={t} value={t}>{t}</option>)}</select></td>
                    {fileQueue.some(f => NEEDS_LEAD_AGE[f.vendor]) && (<td>{NEEDS_LEAD_AGE[fq.vendor] ? (<select className="form-input" style={{ fontSize: '0.7rem', padding: '0.2rem 0.4rem' }} value={fq.leadAge} onChange={e => updateFileQueueItem(idx, { leadAge: e.target.value })}><option value="">N/A</option>{(VENDOR_AGE_BUCKETS[fq.vendor] || []).map(a => <option key={a} value={a}>{a}</option>)}</select>) : <span style={{ color: 'var(--text-muted)' }}>{'\u2014'}</span>}</td>)}
                    <td><input className="form-input" type="date" style={{ fontSize: '0.7rem', padding: '0.2rem 0.4rem' }} value={fq.purchaseDate} onChange={e => updateFileQueueItem(idx, { purchaseDate: e.target.value })} /></td>
                    {fileQueue.length > 1 && <td><button className="btn btn-sm" onClick={() => removeFromQueue(idx)} style={{ padding: '0.15rem 0.4rem', fontSize: '0.65rem', color: 'var(--red)' }}>{'\u2715'}</button></td>}
                  </tr>
                ))}</tbody>
              </table>
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginTop: '0.75rem' }}>
              <input
                type="checkbox"
                id="adjustAge"
                checked={adjustAge}
                onChange={e => setAdjustAge(e.target.checked)}
              />
              <label htmlFor="adjustAge" style={{ fontFamily: 'var(--font-mono)', fontSize: '0.75rem', color: 'var(--text)', cursor: 'pointer' }}>
                Adjust age from lead age bucket
              </label>
              <span
                title="If a lead has an age recorded but no date of birth, estimates their current age using the lead age bucket and purchase date. Example: age 62 on a 13-24M old lead bought 6 months ago → estimated current age 64. Rounds down — people prefer being told they're younger."
                style={{ display: 'inline-flex', alignItems: 'center', justifyContent: 'center', width: 16, height: 16, borderRadius: '50%', background: 'var(--bg)', border: '1px solid var(--border)', color: 'var(--text-muted)', fontSize: '0.65rem', fontWeight: 700, cursor: 'help' }}
              >
                ?
              </span>
            </div>
            <div style={{ display: 'flex', justifyContent: 'flex-end', marginTop: '1rem' }}>
              <button className="btn btn-primary" onClick={() => setStep('mapping')} disabled={fileQueue.length === 0}>Next {'\u2192'}</button>
            </div>
          </div>
        )}

        {step === 'mapping' && (
          <div>
            {!applyMappingToAll && fileQueue.length > 1 && uniqueHeaderCount > 1 ? (
              <p className="form-hint" style={{ marginBottom: '0.75rem' }}>
                Mapping file group {mappingFileIdx + 1} of {uniqueHeaderCount}: <strong>{fileQueue[uniqueHeaderGroups[mappingFileIdx]?.fileIndices[0]]?.name}</strong>
                {uniqueHeaderGroups[mappingFileIdx]?.fileIndices.length > 1 && (
                  <span style={{ color: 'var(--text-muted)' }}> (+{uniqueHeaderGroups[mappingFileIdx].fileIndices.length - 1} file{uniqueHeaderGroups[mappingFileIdx].fileIndices.length > 2 ? 's' : ''} with same headers)</span>
                )}
              </p>
            ) : (
              <p className="form-hint" style={{ marginBottom: '0.75rem' }}>Mapping columns from: <strong>{fileQueue[0]?.name}</strong> ({fileQueue[0]?.parsedRows.length} rows)</p>
            )}
            {fileQueue.length > 1 && (
              <label style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginBottom: '0.75rem', fontFamily: 'var(--font-mono)', fontSize: '0.7rem', color: 'var(--text-muted)' }}>
                <input type="checkbox" checked={applyMappingToAll} onChange={e => {
                  setApplyMappingToAll(e.target.checked)
                  if (e.target.checked) {
                    // Switching back to apply-all: reset to first file's headers
                    setMappingFileIdx(0); setPerFileMaps({})
                    if (fileQueue.length > 0) { setHeaders(fileQueue[0].headers); setSampleRow(fileQueue[0].sampleRow); const autoMap = autoMapHeaders(fileQueue[0].headers); setColumnMap(autoMap); setInitialAutoMap({ ...autoMap }) }
                  } else {
                    // Switching to per-file: start at first unique header group
                    setMappingFileIdx(0); setPerFileMaps({})
                    if (uniqueHeaderCount > 1) { loadFileForMapping(uniqueHeaderGroups[0].fileIndices[0]) }
                  }
                }} />
                Apply this mapping to all {fileQueue.length} files
              </label>
            )}
            {mappingWarning && (
              <div style={{ background: 'oklch(18% 0.06 25)', border: '1px solid oklch(35% 0.15 25)', color: 'var(--red)', padding: '0.5rem 0.75rem', fontFamily: 'var(--font-mono)', fontSize: '0.7rem', borderRadius: 2, marginBottom: '0.75rem' }}>{mappingWarning}</div>
            )}
            {duplicateMappings.length > 0 && (
              <div style={{ background: 'oklch(18% 0.06 25)', border: '1px solid oklch(35% 0.15 25)', color: 'var(--red)', padding: '0.5rem 0.75rem', fontFamily: 'var(--font-mono)', fontSize: '0.7rem', borderRadius: 2, marginBottom: '0.75rem' }}>
                Conflict: multiple columns mapped to the same field — {duplicateMappings.map(f => LEAD_FIELDS.find(lf => lf.value === f)?.label || f).join(', ')}. Change one to "skip" or a different field.
              </div>
            )}
            {!mappingOk && !mappingWarning && duplicateMappings.length === 0 && (
              <div style={{ background: 'oklch(18% 0.04 75)', border: '1px solid oklch(25% 0.05 75)', color: 'var(--amber)', padding: '0.5rem 0.75rem', fontFamily: 'var(--font-mono)', fontSize: '0.7rem', borderRadius: 2, marginBottom: '0.75rem' }}>
                Map at least First Name (or Full Name), Last Name, and Phone to continue.
              </div>
            )}
            <div style={{ maxHeight: 360, overflow: 'auto' }}>
              {sortedHeaders.map(h => {
                const colIdx = headerIndexMap[h]
                const sampleVal = sampleRow[colIdx]
                const isAutoMapped = initialAutoMap[h] && initialAutoMap[h] === columnMap[h]
                const isDupe = columnMap[h] && duplicateMappings.includes(columnMap[h])
                return (
                  <div key={h} className="column-map-row" style={{ background: isDupe ? 'oklch(25% 0.08 25 / 0.4)' : isAutoMapped ? 'oklch(25% 0.05 145 / 0.3)' : 'transparent' }}>
                    <span className="column-map-label" title={h}>{h}</span>
                    <span style={{ fontFamily: 'var(--font-mono)', fontSize: '0.7rem', color: 'var(--text-muted)', maxWidth: 120, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', display: 'inline-block' }} title={sampleVal != null ? String(sampleVal) : ''}>{sampleVal != null ? String(sampleVal) : ''}</span>
                    <span style={{ color: 'var(--text-muted)', fontSize: '0.7rem' }}>{'\u2192'}</span>
                    <select className="form-input" style={{ flex: 1, fontSize: '0.75rem', padding: '0.25rem 0.5rem', ...(isDupe ? { borderColor: 'var(--red)', boxShadow: '0 0 0 1px var(--red)' } : {}) }} value={columnMap[h] || ''} onChange={e => setColumnMap(prev => ({ ...prev, [h]: e.target.value }))}>
                      <option value="">{'\u2014'} skip {'\u2014'}</option>
                      {LEAD_FIELDS.map(f => <option key={f.value} value={f.value}>{f.label}</option>)}
                    </select>
                    {columnMap[h] && !isDupe && <span className="badge badge-success" style={{ fontSize: '0.55rem' }}>mapped</span>}
                    {isDupe && <span className="badge" style={{ fontSize: '0.55rem', background: 'var(--red)', color: '#fff' }}>conflict</span>}
                  </div>
                )
              })}
            </div>
            <div style={{ display: 'flex', justifyContent: 'flex-end', marginTop: '1rem' }}>
              <button className="btn btn-primary" onClick={handleMappingNext} disabled={!mappingOk}>
                {!applyMappingToAll && uniqueHeaderCount > 1 && mappingFileIdx < uniqueHeaderCount - 1 ? 'Next file \u2192' : 'Next \u2192'}
              </button>
            </div>
          </div>
        )}

        {step === 'preview' && (
          <div>
            <div className="preview-summary">
              <div className="preview-summary-grid">
                <span><strong style={{ color: 'var(--text)' }}>{totalLeadsAcrossFiles}</strong> leads to import across <strong>{fileQueue.length}</strong> file{fileQueue.length > 1 ? 's' : ''}</span>
                {totalDroppedAcrossFiles > 0 && <span style={{ color: 'var(--amber)' }}><strong>{totalDroppedAcrossFiles}</strong> rows dropped (missing name/phone)</span>}
              </div>
            </div>
            {fileQueue.length > 1 && (
              <div style={{ display: 'flex', gap: '0.25rem', marginBottom: '0.75rem', flexWrap: 'wrap' }}>
                {previewDataByFile.map((pf, i) => (
                  <button key={i} className="btn btn-sm" onClick={() => setPreviewTab(i)} style={{ padding: '0.2rem 0.6rem', fontSize: '0.65rem', background: previewTab === i ? 'var(--accent)' : 'var(--bg)', color: previewTab === i ? 'oklch(15% 0.01 85)' : 'var(--text-muted)', border: '1px solid ' + (previewTab === i ? 'var(--accent)' : 'var(--border)') }}>
                    {pf.name} ({pf.totalLeads})
                  </button>
                ))}
              </div>
            )}
            {previewDataByFile[previewTab] && (
              <div>
                <div style={{ fontFamily: 'var(--font-mono)', fontSize: '0.7rem', color: 'var(--text-muted)', marginBottom: '0.5rem' }}>
                  {previewDataByFile[previewTab].name} — {previewDataByFile[previewTab].vendor} / {previewDataByFile[previewTab].tier} — {previewDataByFile[previewTab].leadType}
                </div>
                {previewDataByFile[previewTab].previewLeads.length > 0 && (
                  <div className="table-scroll-wrapper" style={{ maxHeight: 240, marginBottom: '1rem' }}>
                    <table className="results-table">
                      <thead><tr><th>#</th><th>Name</th><th>Phone</th><th>Source</th><th>Tier</th><th>Lead Age</th></tr></thead>
                      <tbody>
                        {previewDataByFile[previewTab].previewLeads.map((l, i) => (
                          <tr key={i}><td>{i + 1}</td><td>{l.first_name} {l.last_name}</td><td>{l.phone}</td><td>{l.lead_source || '\u2014'}</td><td>{l.tier || '\u2014'}</td><td>{l.lead_age_bucket || previewDataByFile[previewTab].leadAge || '\u2014'}</td></tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
                <p className="form-hint">Showing first {previewDataByFile[previewTab].previewLeads.length} of {previewDataByFile[previewTab].totalLeads} leads.</p>
              </div>
            )}
            <div style={{ display: 'flex', justifyContent: 'flex-end', alignItems: 'center', marginTop: '1rem', gap: '0.75rem' }}>
              {!dryRun && (
                <label style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', cursor: 'pointer', fontFamily: 'var(--font-mono)', fontSize: '0.75rem', color: enableRvm ? 'var(--text)' : 'var(--text-muted)' }}>
                  <input
                    type="checkbox"
                    checked={enableRvm}
                    onChange={e => setEnableRvm(e.target.checked)}
                    style={{ accentColor: 'var(--accent)', width: 15, height: 15, cursor: 'pointer' }}
                  />
                  Enable RVM
                </label>
              )}
              <button className="btn btn-primary" onClick={doImport}>
                {dryRun ? 'Dry Run' : 'Import'} {totalLeadsAcrossFiles} Leads
              </button>
            </div>
          </div>
        )}

        {step === 'importing' && (
          <div style={{ textAlign: 'center', padding: '3rem 0' }}>
            <p style={{ fontFamily: 'var(--font-display)', fontSize: '0.9rem', fontWeight: 600, color: 'var(--text)', marginBottom: '0.5rem' }}>
              {dryRun ? 'Validating leads...' : 'Importing leads...'}
            </p>
            <p style={{ fontFamily: 'var(--font-mono)', fontSize: '0.7rem', color: 'var(--text-muted)', marginBottom: '1rem' }}>
              File {progress.fileIndex + 1}/{fileQueue.length}: {progress.fileName}
            </p>
            <div className="progress-bar-container" style={{ marginBottom: '0.5rem', position: 'relative' }}>
              <div className="progress-bar" style={{ width: (progress.total > 0 ? (progress.current / progress.total * 100) : 0) + '%', transition: 'width 0.25s ease' }} />
            </div>
            <p className="progress-label">
              {progress.current} / {progress.total} leads
              {progress.total > 0 && <span style={{ marginLeft: '0.75rem', color: 'var(--accent)', fontWeight: 700 }}>{Math.round(progress.current / progress.total * 100)}%</span>}
            </p>
            {fileQueue.filter(f => f.status === 'done').length > 0 && (
              <div style={{ marginTop: '1rem', textAlign: 'left' }}>
                {fileQueue.map((fq, i) => fq.status === 'done' && fq.result ? (
                  <div key={i} style={{ fontFamily: 'var(--font-mono)', fontSize: '0.7rem', color: 'var(--text-muted)', padding: '0.25rem 0' }}>
                    {'\u2713'} {fq.name}: {fq.result.created} created{fq.result.failed > 0 ? ', ' + fq.result.failed + ' failed' : ''}
                  </div>
                ) : null)}
              </div>
            )}
          </div>
        )}

        {step === 'results' && grandResult && (
          <div>
            <div style={{ textAlign: 'center', padding: '1.5rem 0' }}>
              <div style={{ width: 48, height: 48, borderRadius: '50%', background: grandResult.failed === 0 ? 'oklch(18% 0.04 145)' : 'oklch(18% 0.04 75)', display: 'flex', alignItems: 'center', justifyContent: 'center', margin: '0 auto 0.75rem', color: grandResult.failed === 0 ? 'var(--green)' : 'var(--amber)', fontSize: '1.5rem' }}>{grandResult.failed === 0 ? '\u2713' : '!'}</div>
              <h3 className="section-title" style={{ borderBottom: 'none', marginBottom: '0.25rem' }}>{dryRun ? 'Dry Run Complete' : 'Import Complete'}</h3>
              {dryRun && <div style={{ display: 'inline-block', fontFamily: 'var(--font-mono)', fontSize: '0.65rem', fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.06em', color: 'oklch(15% 0.01 85)', background: 'var(--accent)', borderRadius: 3, padding: '0.15rem 0.5rem', marginBottom: '0.5rem' }}>DRY RUN</div>}
              <div style={{ fontFamily: 'var(--font-mono)', fontSize: '0.8rem', display: 'flex', justifyContent: 'center', gap: '1.5rem', marginTop: '0.5rem', flexWrap: 'wrap' }}>
                <span style={{ color: 'var(--green)' }}>{grandResult.created} created</span>
                {grandResult.failed > 0 && <span style={{ color: 'var(--red)' }}>{grandResult.failed} failed</span>}
                {(grandResult.ghlWarnings?.length || 0) > 0 && <span style={{ color: 'var(--amber)' }}>{grandResult.ghlWarnings.length} warnings</span>}
                {(grandResult.droppedCount || 0) > 0 && <span style={{ color: 'var(--text-muted)' }}>{grandResult.droppedCount} rows dropped</span>}
              </div>
            </div>

            {fileQueue.length > 1 && (
              <div style={{ marginBottom: '1rem' }}>
                <h4 style={{ fontFamily: 'var(--font-display)', fontSize: '0.75rem', fontWeight: 600, color: 'var(--text)', marginBottom: '0.5rem' }}>Per-File Breakdown</h4>
                <table className="results-table" style={{ fontSize: '0.7rem' }}>
                  <thead><tr><th>File</th><th>Created</th><th>Failed</th><th>Dropped</th><th>Warnings</th></tr></thead>
                  <tbody>
                    {fileQueue.map((fq, i) => fq.result && (
                      <tr key={i}>
                        <td style={{ fontFamily: 'var(--font-mono)', maxWidth: 160, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{fq.name}</td>
                        <td style={{ color: 'var(--green)' }}>{fq.result.created}</td>
                        <td style={{ color: fq.result.failed > 0 ? 'var(--red)' : 'var(--text-muted)' }}>{fq.result.failed}</td>
                        <td style={{ color: fq.result.droppedCount > 0 ? 'var(--amber)' : 'var(--text-muted)' }}>{fq.result.droppedCount || 0}</td>
                        <td style={{ color: (fq.result.ghlWarnings?.length || 0) > 0 ? 'var(--amber)' : 'var(--text-muted)' }}>{fq.result.ghlWarnings?.length || 0}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}

            {(() => {
              const allDropped = fileQueue.flatMap(fq => (fq.result?.droppedRows || []).map(d => ({ ...d, file: fq.name.replace(/\.[^.]+$/, '') })))
              if (!allDropped.length) return null
              const allKeys = [...new Set(allDropped.flatMap(d => Object.keys(d.raw)))]
              const downloadCsv = () => {
                const cols = ['file', 'reason', ...allKeys]
                const rows = allDropped.map(d => cols.map(c => c === 'file' ? d.file : c === 'reason' ? d.reason : (d.raw[c] || '')).map(v => '"' + String(v).replace(/"/g, '""') + '"').join(','))
                const csv = [cols.join(','), ...rows].join('\n')
                const a = document.createElement('a'); a.href = URL.createObjectURL(new Blob([csv], { type: 'text/csv' })); a.download = 'dropped_leads.csv'; a.click()
              }
              return (
                <div style={{ marginBottom: '1rem' }}>
                  <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '0.5rem' }}>
                    <h4 style={{ fontFamily: 'var(--font-display)', fontSize: '0.75rem', fontWeight: 600, color: 'var(--amber)', margin: 0 }}>
                      Dropped Rows ({allDropped.length}) — Missing required fields
                    </h4>
                    <button className="btn btn-sm" onClick={downloadCsv} style={{ fontSize: '0.65rem', padding: '0.2rem 0.6rem', color: 'var(--amber)', borderColor: 'var(--amber)' }}>
                      ↓ Download CSV
                    </button>
                  </div>
                  <div style={{ overflowX: 'auto', maxHeight: 220, border: '1px solid oklch(25% 0.05 75)', borderRadius: 3 }}>
                    <table style={{ width: '100%', borderCollapse: 'collapse', fontFamily: 'var(--font-mono)', fontSize: '0.65rem', whiteSpace: 'nowrap' }}>
                      <thead>
                        <tr style={{ background: 'oklch(18% 0.04 75)' }}>
                          <th style={{ padding: '0.3rem 0.5rem', textAlign: 'left', color: 'var(--amber)', borderBottom: '1px solid oklch(25% 0.05 75)', position: 'sticky', top: 0, background: 'oklch(18% 0.04 75)' }}>File</th>
                          <th style={{ padding: '0.3rem 0.5rem', textAlign: 'left', color: 'var(--amber)', borderBottom: '1px solid oklch(25% 0.05 75)', position: 'sticky', top: 0, background: 'oklch(18% 0.04 75)' }}>Reason</th>
                          {allKeys.map(k => <th key={k} style={{ padding: '0.3rem 0.5rem', textAlign: 'left', color: 'var(--text-muted)', borderBottom: '1px solid oklch(25% 0.05 75)', position: 'sticky', top: 0, background: 'oklch(18% 0.04 75)' }}>{k}</th>)}
                        </tr>
                      </thead>
                      <tbody>
                        {allDropped.map((d, i) => (
                          <tr key={i} style={{ background: i % 2 === 0 ? 'oklch(14% 0.03 75 / 0.4)' : 'transparent' }}>
                            <td style={{ padding: '0.3rem 0.5rem', color: 'var(--text-muted)', maxWidth: 160, overflow: 'hidden', textOverflow: 'ellipsis' }}>{d.file}</td>
                            <td style={{ padding: '0.3rem 0.5rem', color: 'var(--amber)' }}>{d.reason}</td>
                            {allKeys.map(k => <td key={k} style={{ padding: '0.3rem 0.5rem', color: 'var(--text)' }}>{d.raw[k] || ''}</td>)}
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              )
            })()}

            {grandResult.errors && grandResult.errors.length > 0 && (
              <div style={{ marginBottom: '1rem' }}>
                <h4 style={{ fontFamily: 'var(--font-display)', fontSize: '0.75rem', fontWeight: 600, color: 'var(--red)', marginBottom: '0.5rem' }}>Failed Rows</h4>
                <div style={{ maxHeight: 160, overflow: 'auto' }}>
                  {grandResult.errors.slice(0, 20).map((e, i) => (
                    <div key={i} className="alert alert-error" style={{ marginTop: i > 0 ? '0.375rem' : 0, fontSize: '0.7rem', padding: '0.375rem 0.625rem' }}>
                      Row {e.index + 1}{e.lead_name ? ' (' + e.lead_name + ')' : ''}: {e.error}
                    </div>
                  ))}
                  {grandResult.errors.length > 20 && <p className="form-hint">...and {grandResult.errors.length - 20} more</p>}
                </div>
              </div>
            )}

            {grandResult.ghlWarnings && grandResult.ghlWarnings.length > 0 && (
              <div style={{ marginBottom: '1rem' }}>
                <h4 style={{ fontFamily: 'var(--font-display)', fontSize: '0.75rem', fontWeight: 600, color: 'var(--amber)', marginBottom: '0.5rem' }}>Import Warnings</h4>
                <div style={{ maxHeight: 120, overflow: 'auto' }}>
                  {grandResult.ghlWarnings.slice(0, 10).map((w, i) => (
                    <div key={i} style={{ background: 'oklch(18% 0.04 75)', border: '1px solid oklch(25% 0.05 75)', color: 'var(--amber)', padding: '0.375rem 0.625rem', fontFamily: 'var(--font-mono)', fontSize: '0.7rem', borderRadius: 2, marginTop: i > 0 ? '0.375rem' : 0 }}>
                      {w.lead_name}: {w.error}
                    </div>
                  ))}
                  {grandResult.ghlWarnings.length > 10 && <p className="form-hint">...and {grandResult.ghlWarnings.length - 10} more</p>}
                </div>
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
