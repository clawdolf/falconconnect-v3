import { useState, useEffect, useRef } from 'react'

const STATE_MAP = {
  'Alabama': 'AL', 'Alaska': 'AK', 'Arizona': 'AZ', 'Arkansas': 'AR', 'California': 'CA',
  'Colorado': 'CO', 'Connecticut': 'CT', 'Delaware': 'DE', 'Florida': 'FL', 'Georgia': 'GA',
  'Hawaii': 'HI', 'Idaho': 'ID', 'Illinois': 'IL', 'Indiana': 'IN', 'Iowa': 'IA',
  'Kansas': 'KS', 'Kentucky': 'KY', 'Louisiana': 'LA', 'Maine': 'ME', 'Maryland': 'MD',
  'Massachusetts': 'MA', 'Michigan': 'MI', 'Minnesota': 'MN', 'Mississippi': 'MS', 'Missouri': 'MO',
  'Montana': 'MT', 'Nebraska': 'NE', 'Nevada': 'NV', 'New Hampshire': 'NH', 'New Jersey': 'NJ',
  'New Mexico': 'NM', 'New York': 'NY', 'North Carolina': 'NC', 'North Dakota': 'ND', 'Ohio': 'OH',
  'Oklahoma': 'OK', 'Oregon': 'OR', 'Pennsylvania': 'PA', 'Rhode Island': 'RI', 'South Carolina': 'SC',
  'South Dakota': 'SD', 'Tennessee': 'TN', 'Texas': 'TX', 'Utah': 'UT', 'Vermont': 'VT',
  'Virginia': 'VA', 'Washington': 'WA', 'West Virginia': 'WV', 'Wisconsin': 'WI', 'Wyoming': 'WY',
  'District of Columbia': 'DC',
}
const STATE_NAMES = Object.keys(STATE_MAP)

/* ── State autocomplete input ── */
function StateInput({ value, onChange, onSelect }) {
  const [query, setQuery] = useState(value || '')
  const [suggestions, setSuggestions] = useState([])
  const [open, setOpen] = useState(false)
  const [highlighted, setHighlighted] = useState(0)
  const wrapRef = useRef(null)

  // Sync external value reset
  useEffect(() => { if (!value) { setQuery(''); setSuggestions([]) } }, [value])

  const handleChange = (e) => {
    const q = e.target.value
    setQuery(q)
    if (q.length < 1) { setSuggestions([]); setOpen(false); onChange('', ''); return }
    const lq = q.toLowerCase()
    const matches = STATE_NAMES.filter(s =>
      s.toLowerCase().startsWith(lq) || STATE_MAP[s].toLowerCase().startsWith(lq)
    ).slice(0, 8)
    setSuggestions(matches)
    setOpen(matches.length > 0)
    setHighlighted(0)
    // If user typed exact abbrev match, auto-resolve
    const exactAbbr = STATE_NAMES.find(s => STATE_MAP[s].toLowerCase() === lq)
    if (exactAbbr) { onChange(exactAbbr, STATE_MAP[exactAbbr]); return }
    onChange('', '')
  }

  const pick = (state) => {
    setQuery(state)
    setSuggestions([])
    setOpen(false)
    onSelect(state, STATE_MAP[state])
    onChange(state, STATE_MAP[state])
  }

  const handleKeyDown = (e) => {
    if (!open) return
    if (e.key === 'ArrowDown') { e.preventDefault(); setHighlighted(h => Math.min(h + 1, suggestions.length - 1)) }
    else if (e.key === 'ArrowUp') { e.preventDefault(); setHighlighted(h => Math.max(h - 1, 0)) }
    else if (e.key === 'Enter') { e.preventDefault(); if (suggestions[highlighted]) pick(suggestions[highlighted]) }
    else if (e.key === 'Escape') { setOpen(false) }
  }

  // Close on outside click
  useEffect(() => {
    const handler = (e) => { if (wrapRef.current && !wrapRef.current.contains(e.target)) setOpen(false) }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [])

  return (
    <div ref={wrapRef} style={{ position: 'relative' }}>
      <input
        className="form-input"
        type="text"
        placeholder="Start typing a state..."
        value={query}
        onChange={handleChange}
        onKeyDown={handleKeyDown}
        onFocus={() => { if (suggestions.length > 0) setOpen(true) }}
        autoComplete="off"
      />
      {open && (
        <div style={{
          position: 'absolute', top: '100%', left: 0, right: 0, zIndex: 50,
          background: 'var(--surface)', border: '1px solid var(--border)',
          borderRadius: 2, boxShadow: '0 4px 12px rgba(0,0,0,0.3)',
          maxHeight: 240, overflowY: 'auto',
        }}>
          {suggestions.map((s, i) => (
            <div
              key={s}
              onMouseDown={() => pick(s)}
              style={{
                padding: '0.5rem 0.75rem',
                cursor: 'pointer',
                fontFamily: 'var(--font-mono)',
                fontSize: '0.8rem',
                display: 'flex',
                justifyContent: 'space-between',
                alignItems: 'center',
                background: i === highlighted ? 'var(--bg)' : 'transparent',
                color: 'var(--text)',
              }}
              onMouseEnter={() => setHighlighted(i)}
            >
              <span>{s}</span>
              <span style={{ color: 'var(--accent)', fontWeight: 600, fontSize: '0.75rem' }}>{STATE_MAP[s]}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

/* ── Main Component ── */
function Licenses() {
  const [licenses, setLicenses] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [showAddForm, setShowAddForm] = useState(false)
  const [editingId, setEditingId] = useState(null)
  const [deleteConfirm, setDeleteConfirm] = useState(null)
  const [submitting, setSubmitting] = useState(false)

  const blankForm = { state: '', state_abbreviation: '', license_number: '' }
  const [formData, setFormData] = useState(blankForm)
  const [editData, setEditData] = useState({})

  let getToken = null
  try { const { useAuth } = require('@clerk/clerk-react'); const auth = useAuth(); getToken = auth.getToken } catch { /* no-op */ }

  const getHeaders = async () => {
    const headers = { 'Content-Type': 'application/json' }
    if (getToken) { try { const t = await getToken(); if (t) headers['Authorization'] = `Bearer ${t}` } catch { /* no-op */ } }
    return headers
  }

  const fetchLicenses = async () => {
    setLoading(true); setError(null)
    try {
      const headers = await getHeaders()
      const resp = await fetch('/api/licenses', { headers })
      if (!resp.ok) throw new Error(`HTTP ${resp.status}: ${resp.statusText}`)
      setLicenses(await resp.json())
    } catch (err) { setError(err.message) }
    finally { setLoading(false) }
  }

  useEffect(() => { fetchLicenses() }, [])

  const handleAdd = async () => {
    if (!formData.state) { setError('Select a state.'); return }
    setSubmitting(true); setError(null)
    try {
      const headers = await getHeaders()
      const body = {
        state: formData.state,
        state_abbreviation: formData.state_abbreviation,
        license_number: formData.license_number || null,
        license_type: 'insurance_producer',
      }
      const resp = await fetch('/api/licenses', { method: 'POST', headers, body: JSON.stringify(body) })
      if (!resp.ok) throw new Error(`HTTP ${resp.status}: ${resp.statusText}`)
      setShowAddForm(false); setFormData(blankForm); await fetchLicenses()
    } catch (err) { setError(err.message) }
    finally { setSubmitting(false) }
  }

  const handleEdit = async (id) => {
    setSubmitting(true); setError(null)
    try {
      const headers = await getHeaders()
      const body = {
        state: editData.state,
        state_abbreviation: editData.state_abbreviation || STATE_MAP[editData.state] || '',
        license_number: editData.license_number || null,
      }
      const resp = await fetch(`/api/licenses/${id}`, { method: 'PUT', headers, body: JSON.stringify(body) })
      if (!resp.ok) throw new Error(`HTTP ${resp.status}: ${resp.statusText}`)
      setEditingId(null); setEditData({}); await fetchLicenses()
    } catch (err) { setError(err.message) }
    finally { setSubmitting(false) }
  }

  const handleDelete = async (id) => {
    if (deleteConfirm !== id) { setDeleteConfirm(id); return }
    setSubmitting(true); setError(null)
    try {
      const headers = await getHeaders()
      const resp = await fetch(`/api/licenses/${id}`, { method: 'DELETE', headers })
      if (!resp.ok) throw new Error(`HTTP ${resp.status}: ${resp.statusText}`)
      setDeleteConfirm(null); await fetchLicenses()
    } catch (err) { setError(err.message) }
    finally { setSubmitting(false) }
  }

  const startEdit = (lic) => {
    setEditingId(lic.id)
    setEditData({ state: lic.state, state_abbreviation: lic.state_abbreviation, license_number: lic.license_number || '' })
    setDeleteConfirm(null); setShowAddForm(false)
  }

  const statusBadge = (s) => s === 'active' ? 'badge-success' : s === 'expired' ? 'badge-error' : 'badge-warn'

  return (
    <div className="dashboard">
      <section className="section">
        <h2 className="section-title">Licenses</h2>
        <p className="section-desc">Active insurance licenses with verification links.</p>

        {error && <div className="alert alert-error"><strong>Error:</strong> {error}</div>}

        {loading ? (
          <p className="loading-text">Loading...</p>
        ) : (
          <>
            {licenses.length > 0 ? (
              <table className="results-table">
                <thead>
                  <tr>
                    <th>State</th>
                    <th>License #</th>
                    <th>Status</th>
                    <th>Verify</th>
                    <th>Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {licenses.map((lic) => (
                    <tr key={lic.id}>
                      <td>
                        <span style={{ fontWeight: 600 }}>{lic.state_abbreviation}</span>
                        <span style={{ color: 'var(--text-muted)', fontSize: '0.7rem', marginLeft: '0.4rem' }}>{lic.state}</span>
                      </td>
                      <td>{lic.license_number || '—'}</td>
                      <td><span className={`badge ${statusBadge(lic.status)}`}>{lic.status}</span></td>
                      <td>
                        {lic.verify_url
                          ? <a href={lic.verify_url} target="_blank" rel="noopener noreferrer" className="c-accent" style={{ fontFamily: 'var(--font-mono)', fontSize: '0.75rem' }}>Verify</a>
                          : <span className="c-muted">—</span>}
                      </td>
                      <td>
                        <button className="btn btn-sm" onClick={() => startEdit(lic)} disabled={submitting}>Edit</button>
                        {' '}
                        <button className={`btn btn-sm ${deleteConfirm === lic.id ? 'c-red' : ''}`} onClick={() => handleDelete(lic.id)} disabled={submitting}>
                          {deleteConfirm === lic.id ? 'Confirm?' : 'Delete'}
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : (
              <p className="no-results">No licenses found.</p>
            )}

            {/* Edit form */}
            {editingId && (
              <div className="section" style={{ marginTop: '1rem' }}>
                <h2 className="section-title">Edit License</h2>
                <div className="form-grid">
                  <div className="form-field">
                    <label className="form-label">State</label>
                    <StateInput
                      value={editData.state}
                      onChange={(state, abbr) => setEditData(d => ({ ...d, state, state_abbreviation: abbr }))}
                      onSelect={(state, abbr) => setEditData(d => ({ ...d, state, state_abbreviation: abbr }))}
                    />
                  </div>
                  <div className="form-field">
                    <label className="form-label">Abbreviation</label>
                    <input className="form-input" type="text" value={editData.state_abbreviation || ''} readOnly style={{ opacity: 0.6, cursor: 'default' }} />
                  </div>
                  <div className="form-field">
                    <label className="form-label">License #</label>
                    <input className="form-input" type="text" placeholder="Optional" value={editData.license_number || ''} onChange={e => setEditData(d => ({ ...d, license_number: e.target.value }))} />
                  </div>
                </div>
                <div style={{ marginTop: '0.75rem', display: 'flex', gap: '0.5rem' }}>
                  <button className="btn btn-primary" onClick={() => handleEdit(editingId)} disabled={submitting}>{submitting ? 'Saving...' : 'Save'}</button>
                  <button className="btn" onClick={() => { setEditingId(null); setEditData({}) }}>Cancel</button>
                </div>
              </div>
            )}

            {/* Add button */}
            {!showAddForm && !editingId && (
              <button className="btn btn-primary" style={{ marginTop: '0.75rem' }} onClick={() => setShowAddForm(true)}>
                Add License
              </button>
            )}

            {/* Add form */}
            {showAddForm && (
              <div className="section" style={{ marginTop: '1rem' }}>
                <h2 className="section-title">Add License</h2>
                <div className="form-grid">
                  <div className="form-field">
                    <label className="form-label">State</label>
                    <StateInput
                      value={formData.state}
                      onChange={(state, abbr) => setFormData(d => ({ ...d, state, state_abbreviation: abbr }))}
                      onSelect={(state, abbr) => setFormData(d => ({ ...d, state, state_abbreviation: abbr }))}
                    />
                  </div>
                  <div className="form-field">
                    <label className="form-label">Abbreviation</label>
                    <input className="form-input" type="text" value={formData.state_abbreviation || ''} readOnly style={{ opacity: 0.6, cursor: 'default' }} />
                  </div>
                  <div className="form-field">
                    <label className="form-label">License #</label>
                    <input className="form-input" type="text" placeholder="Optional" value={formData.license_number} onChange={e => setFormData(d => ({ ...d, license_number: e.target.value }))} />
                  </div>
                </div>
                <div style={{ marginTop: '0.75rem', display: 'flex', gap: '0.5rem' }}>
                  <button className="btn btn-primary" onClick={handleAdd} disabled={submitting || !formData.state}>{submitting ? 'Adding...' : 'Submit'}</button>
                  <button className="btn" onClick={() => { setShowAddForm(false); setFormData(blankForm); setError(null) }}>Cancel</button>
                </div>
              </div>
            )}
          </>
        )}
      </section>
    </div>
  )
}

export default Licenses
