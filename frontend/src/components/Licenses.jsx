import { useState, useEffect } from 'react'
import { useAuth } from '@clerk/clerk-react'

function Licenses() {
  const [licenses, setLicenses] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [showAddForm, setShowAddForm] = useState(false)
  const [editingId, setEditingId] = useState(null)
  const [deleteConfirm, setDeleteConfirm] = useState(null)
  const [submitting, setSubmitting] = useState(false)

  const [formData, setFormData] = useState({
    state: '',
    state_abbreviation: '',
    license_number: '',
    license_type: 'insurance_producer',
    expiry_date: '',
  })

  const [editData, setEditData] = useState({})

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

  const fetchLicenses = async () => {
    setLoading(true)
    setError(null)
    try {
      const headers = await getHeaders()
      const resp = await fetch('/api/licenses', { headers })
      if (!resp.ok) throw new Error(`HTTP ${resp.status}: ${resp.statusText}`)
      const data = await resp.json()
      setLicenses(data)
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { fetchLicenses() }, [])

  const resetForm = () => {
    setFormData({
      state: '',
      state_abbreviation: '',
      license_number: '',
      license_type: 'insurance_producer',
      expiry_date: '',
    })
  }

  const handleAdd = async () => {
    setSubmitting(true)
    setError(null)
    try {
      const headers = await getHeaders()
      const body = {
        state: formData.state,
        state_abbreviation: formData.state_abbreviation.toUpperCase(),
        license_number: formData.license_number,
        license_type: formData.license_type,
      }
      if (formData.expiry_date) body.expiry_date = formData.expiry_date

      const resp = await fetch('/api/licenses', {
        method: 'POST',
        headers,
        body: JSON.stringify(body),
      })
      if (!resp.ok) throw new Error(`HTTP ${resp.status}: ${resp.statusText}`)
      setShowAddForm(false)
      resetForm()
      await fetchLicenses()
    } catch (err) {
      setError(err.message)
    } finally {
      setSubmitting(false)
    }
  }

  const handleEdit = async (id) => {
    setSubmitting(true)
    setError(null)
    try {
      const headers = await getHeaders()
      const body = { ...editData }
      if (body.state_abbreviation) body.state_abbreviation = body.state_abbreviation.toUpperCase()

      const resp = await fetch(`/api/licenses/${id}`, {
        method: 'PUT',
        headers,
        body: JSON.stringify(body),
      })
      if (!resp.ok) throw new Error(`HTTP ${resp.status}: ${resp.statusText}`)
      setEditingId(null)
      setEditData({})
      await fetchLicenses()
    } catch (err) {
      setError(err.message)
    } finally {
      setSubmitting(false)
    }
  }

  const handleDelete = async (id) => {
    if (deleteConfirm !== id) {
      setDeleteConfirm(id)
      return
    }
    setSubmitting(true)
    setError(null)
    try {
      const headers = await getHeaders()
      const resp = await fetch(`/api/licenses/${id}`, {
        method: 'DELETE',
        headers,
      })
      if (!resp.ok) throw new Error(`HTTP ${resp.status}: ${resp.statusText}`)
      setDeleteConfirm(null)
      await fetchLicenses()
    } catch (err) {
      setError(err.message)
    } finally {
      setSubmitting(false)
    }
  }

  const startEdit = (lic) => {
    setEditingId(lic.id)
    setEditData({
      state: lic.state,
      state_abbreviation: lic.state_abbreviation,
      license_number: lic.license_number || '',
      license_type: lic.license_type,
    })
    setDeleteConfirm(null)
  }

  const statusBadge = (s) => {
    if (s === 'active') return 'badge-success'
    if (s === 'expired') return 'badge-error'
    return 'badge-warn'
  }

  return (
    <div className="dashboard">
      <section className="section">
        <h2 className="section-title">Licenses</h2>
        <p className="section-desc">
          Active insurance licenses with verification links.
        </p>

        {error && (
          <div className="alert alert-error">
            <strong>Error:</strong> {error}
          </div>
        )}

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
                    <th>Type</th>
                    <th>Status</th>
                    <th>Verify</th>
                    <th>Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {licenses.map((lic) => (
                    <tr key={lic.id}>
                      <td>{lic.state_abbreviation}</td>
                      <td>{lic.license_number || '—'}</td>
                      <td>{lic.license_type}</td>
                      <td>
                        <span className={`badge ${statusBadge(lic.status)}`}>
                          {lic.status}
                        </span>
                      </td>
                      <td>
                        {lic.verify_url ? (
                          <a
                            href={lic.verify_url}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="c-accent"
                            style={{ fontFamily: 'var(--font-mono)', fontSize: '0.75rem' }}
                          >
                            Verify
                          </a>
                        ) : (
                          <span className="c-muted">—</span>
                        )}
                      </td>
                      <td>
                        <button
                          className="btn btn-sm"
                          onClick={() => startEdit(lic)}
                          disabled={submitting}
                        >
                          Edit
                        </button>
                        {' '}
                        <button
                          className={`btn btn-sm ${deleteConfirm === lic.id ? 'c-red' : ''}`}
                          onClick={() => handleDelete(lic.id)}
                          disabled={submitting}
                        >
                          {deleteConfirm === lic.id ? 'Confirm delete?' : 'Delete'}
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : (
              <p className="no-results">No licenses found.</p>
            )}

            {/* Edit form — inline below table */}
            {editingId && (
              <div className="section" style={{ marginTop: '1rem' }}>
                <h2 className="section-title">Edit License</h2>
                <div className="form-grid">
                  <div className="form-field">
                    <label className="form-label">State</label>
                    <input
                      className="form-input"
                      type="text"
                      value={editData.state || ''}
                      onChange={(e) => setEditData({ ...editData, state: e.target.value })}
                    />
                  </div>
                  <div className="form-field">
                    <label className="form-label">Abbreviation</label>
                    <input
                      className="form-input"
                      type="text"
                      maxLength={2}
                      value={editData.state_abbreviation || ''}
                      onChange={(e) => setEditData({ ...editData, state_abbreviation: e.target.value })}
                    />
                  </div>
                  <div className="form-field">
                    <label className="form-label">License #</label>
                    <input
                      className="form-input"
                      type="text"
                      value={editData.license_number || ''}
                      onChange={(e) => setEditData({ ...editData, license_number: e.target.value })}
                    />
                  </div>
                  <div className="form-field">
                    <label className="form-label">Type</label>
                    <input
                      className="form-input"
                      type="text"
                      value={editData.license_type || ''}
                      onChange={(e) => setEditData({ ...editData, license_type: e.target.value })}
                    />
                  </div>
                </div>
                <div style={{ marginTop: '0.75rem', display: 'flex', gap: '0.5rem' }}>
                  <button
                    className="btn btn-primary"
                    onClick={() => handleEdit(editingId)}
                    disabled={submitting}
                  >
                    {submitting ? 'Saving...' : 'Save'}
                  </button>
                  <button
                    className="btn"
                    onClick={() => { setEditingId(null); setEditData({}) }}
                  >
                    Cancel
                  </button>
                </div>
              </div>
            )}

            {/* Add form toggle */}
            {!showAddForm && !editingId && (
              <button
                className="btn btn-primary"
                onClick={() => setShowAddForm(true)}
              >
                Add License
              </button>
            )}

            {/* Add form — inline below table */}
            {showAddForm && (
              <div className="section" style={{ marginTop: '1rem' }}>
                <h2 className="section-title">Add License</h2>
                <div className="form-grid">
                  <div className="form-field">
                    <label className="form-label">State</label>
                    <input
                      className="form-input"
                      type="text"
                      placeholder="Arizona"
                      value={formData.state}
                      onChange={(e) => setFormData({ ...formData, state: e.target.value })}
                    />
                  </div>
                  <div className="form-field">
                    <label className="form-label">Abbreviation</label>
                    <input
                      className="form-input"
                      type="text"
                      maxLength={2}
                      placeholder="AZ"
                      value={formData.state_abbreviation}
                      onChange={(e) => setFormData({ ...formData, state_abbreviation: e.target.value })}
                    />
                  </div>
                  <div className="form-field">
                    <label className="form-label">License #</label>
                    <input
                      className="form-input"
                      type="text"
                      placeholder="12345678"
                      value={formData.license_number}
                      onChange={(e) => setFormData({ ...formData, license_number: e.target.value })}
                    />
                  </div>
                  <div className="form-field">
                    <label className="form-label">Type</label>
                    <input
                      className="form-input"
                      type="text"
                      value={formData.license_type}
                      onChange={(e) => setFormData({ ...formData, license_type: e.target.value })}
                    />
                  </div>
                  <div className="form-field">
                    <label className="form-label">Expiry Date</label>
                    <input
                      className="form-input"
                      type="date"
                      value={formData.expiry_date}
                      onChange={(e) => setFormData({ ...formData, expiry_date: e.target.value })}
                    />
                  </div>
                </div>
                <div style={{ marginTop: '0.75rem', display: 'flex', gap: '0.5rem' }}>
                  <button
                    className="btn btn-primary"
                    onClick={handleAdd}
                    disabled={submitting}
                  >
                    {submitting ? 'Adding...' : 'Submit'}
                  </button>
                  <button
                    className="btn"
                    onClick={() => { setShowAddForm(false); resetForm() }}
                  >
                    Cancel
                  </button>
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
