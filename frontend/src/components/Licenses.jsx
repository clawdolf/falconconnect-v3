import { useState, useEffect } from 'react'

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

function Licenses() {
  const [licenses, setLicenses] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [showAddForm, setShowAddForm] = useState(false)
  const [editingId, setEditingId] = useState(null)
  const [deleteConfirm, setDeleteConfirm] = useState(null)
  const [submitting, setSubmitting] = useState(false)

  const blankForm = { state: '', license_number: '' }
  const [formData, setFormData] = useState(blankForm)
  const [editData, setEditData] = useState({})

  // Auth (Clerk optional)
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
        state_abbreviation: STATE_MAP[formData.state] || '',
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
        state_abbreviation: STATE_MAP[editData.state] || editData.state_abbreviation || '',
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
                      <td>{lic.state_abbreviation} <span style={{ color: 'var(--text-muted)', fontSize: '0.7rem' }}>{lic.state}</span></td>
                      <td>{lic.license_number || '—'}</td>
                      <td><span className={`badge ${statusBadge(lic.status)}`}>{lic.status}</span></td>
                      <td>
                        {lic.verify_url ? (
                          <a href={lic.verify_url} target="_blank" rel="noopener noreferrer" className="c-accent" style={{ fontFamily: 'var(--font-mono)', fontSize: '0.75rem' }}>Verify</a>
                        ) : <span className="c-muted">—</span>}
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
                    <select className="form-input" value={editData.state || ''} onChange={e => setEditData({ ...editData, state: e.target.value, state_abbreviation: STATE_MAP[e.target.value] || '' })}>
                      <option value="">Select state...</option>
                      {STATE_NAMES.map(s => <option key={s} value={s}>{s} ({STATE_MAP[s]})</option>)}
                    </select>
                  </div>
                  <div className="form-field">
                    <label className="form-label">Abbreviation</label>
                    <input className="form-input" type="text" value={editData.state ? STATE_MAP[editData.state] || '' : ''} readOnly style={{ opacity: 0.6, cursor: 'default' }} />
                  </div>
                  <div className="form-field">
                    <label className="form-label">License #</label>
                    <input className="form-input" type="text" placeholder="Optional" value={editData.license_number || ''} onChange={e => setEditData({ ...editData, license_number: e.target.value })} />
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
                    <select className="form-input" value={formData.state} onChange={e => setFormData({ ...formData, state: e.target.value })}>
                      <option value="">Select state...</option>
                      {STATE_NAMES.map(s => <option key={s} value={s}>{s} ({STATE_MAP[s]})</option>)}
                    </select>
                  </div>
                  <div className="form-field">
                    <label className="form-label">Abbreviation</label>
                    <input className="form-input" type="text" value={formData.state ? STATE_MAP[formData.state] || '' : ''} readOnly style={{ opacity: 0.6, cursor: 'default' }} />
                  </div>
                  <div className="form-field">
                    <label className="form-label">License #</label>
                    <input className="form-input" type="text" placeholder="Optional" value={formData.license_number} onChange={e => setFormData({ ...formData, license_number: e.target.value })} />
                  </div>
                </div>
                <div style={{ marginTop: '0.75rem', display: 'flex', gap: '0.5rem' }}>
                  <button className="btn btn-primary" onClick={handleAdd} disabled={submitting}>{submitting ? 'Adding...' : 'Submit'}</button>
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
