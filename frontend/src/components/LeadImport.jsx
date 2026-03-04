import { useState } from 'react'
import { useAuth } from '@clerk/clerk-react'

function LeadImport() {
  const [formData, setFormData] = useState({
    first_name: '',
    last_name: '',
    phone: '',
    email: '',
    birth_year: '',
    mail_date: '',
    address: '',
    city: '',
    state: '',
    zip_code: '',
    lead_source: '',
    notes: '',
  })

  const [errors, setErrors] = useState({})
  const [result, setResult] = useState(null)
  const [loading, setLoading] = useState(false)
  const [apiError, setApiError] = useState(null)

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

    setLoading(true)
    setApiError(null)
    setResult(null)

    try {
      const headers = await getHeaders()
      const body = {
        first_name: formData.first_name.trim(),
        last_name: formData.last_name.trim(),
        phone: formData.phone.trim(),
      }

      if (formData.email.trim()) body.email = formData.email.trim()
      if (formData.birth_year) body.birth_year = parseInt(formData.birth_year, 10)
      if (formData.mail_date) body.mail_date = formData.mail_date
      if (formData.address.trim()) body.address = formData.address.trim()
      if (formData.city.trim()) body.city = formData.city.trim()
      if (formData.state.trim()) body.state = formData.state.trim()
      if (formData.zip_code.trim()) body.zip_code = formData.zip_code.trim()
      if (formData.lead_source.trim()) body.lead_source = formData.lead_source.trim()
      if (formData.notes.trim()) body.notes = formData.notes.trim()

      const resp = await fetch('/api/public/leads/capture', {
        method: 'POST',
        headers,
        body: JSON.stringify(body),
      })

      if (!resp.ok) {
        const errData = await resp.json().catch(() => null)
        throw new Error(errData?.detail || `HTTP ${resp.status}: ${resp.statusText}`)
      }

      const data = await resp.json()
      setResult(data)
    } catch (err) {
      setApiError(err.message)
    } finally {
      setLoading(false)
    }
  }

  const handleChange = (field, value) => {
    setFormData({ ...formData, [field]: value })
    if (errors[field]) {
      setErrors({ ...errors, [field]: null })
    }
  }

  const resetForm = () => {
    setFormData({
      first_name: '',
      last_name: '',
      phone: '',
      email: '',
      birth_year: '',
      mail_date: '',
      address: '',
      city: '',
      state: '',
      zip_code: '',
      lead_source: '',
      notes: '',
    })
    setErrors({})
    setResult(null)
    setApiError(null)
  }

  return (
    <div className="dashboard">
      <section className="section">
        <h2 className="section-title">Lead Import</h2>
        <p className="section-desc">
          Capture a new lead. Dual push: GHL + Notion.
        </p>

        <div className="form-grid">
          <div className="form-field">
            <label className="form-label">First Name *</label>
            <input
              className={`form-input ${errors.first_name ? 'form-input-error' : ''}`}
              type="text"
              value={formData.first_name}
              onChange={(e) => handleChange('first_name', e.target.value)}
              placeholder="John"
            />
            {errors.first_name && <span className="form-error">{errors.first_name}</span>}
          </div>
          <div className="form-field">
            <label className="form-label">Last Name *</label>
            <input
              className={`form-input ${errors.last_name ? 'form-input-error' : ''}`}
              type="text"
              value={formData.last_name}
              onChange={(e) => handleChange('last_name', e.target.value)}
              placeholder="Doe"
            />
            {errors.last_name && <span className="form-error">{errors.last_name}</span>}
          </div>
          <div className="form-field">
            <label className="form-label">Phone *</label>
            <input
              className={`form-input ${errors.phone ? 'form-input-error' : ''}`}
              type="text"
              value={formData.phone}
              onChange={(e) => handleChange('phone', e.target.value)}
              placeholder="480-555-1234"
            />
            {errors.phone && <span className="form-error">{errors.phone}</span>}
          </div>
          <div className="form-field">
            <label className="form-label">Email</label>
            <input
              className="form-input"
              type="email"
              value={formData.email}
              onChange={(e) => handleChange('email', e.target.value)}
              placeholder="john@example.com"
            />
          </div>
          <div className="form-field">
            <label className="form-label">Birth Year</label>
            <input
              className="form-input"
              type="number"
              min="1900"
              max="2026"
              value={formData.birth_year}
              onChange={(e) => handleChange('birth_year', e.target.value)}
              placeholder="1972"
            />
          </div>
          <div className="form-field">
            <label className="form-label">Mail Date</label>
            <input
              className="form-input"
              type="date"
              value={formData.mail_date}
              onChange={(e) => handleChange('mail_date', e.target.value)}
            />
          </div>
          <div className="form-field">
            <label className="form-label">Address</label>
            <input
              className="form-input"
              type="text"
              value={formData.address}
              onChange={(e) => handleChange('address', e.target.value)}
              placeholder="123 Main St"
            />
          </div>
          <div className="form-field">
            <label className="form-label">City</label>
            <input
              className="form-input"
              type="text"
              value={formData.city}
              onChange={(e) => handleChange('city', e.target.value)}
              placeholder="Scottsdale"
            />
          </div>
          <div className="form-field">
            <label className="form-label">State</label>
            <input
              className="form-input"
              type="text"
              maxLength={2}
              value={formData.state}
              onChange={(e) => handleChange('state', e.target.value)}
              placeholder="AZ"
            />
          </div>
          <div className="form-field">
            <label className="form-label">ZIP</label>
            <input
              className="form-input"
              type="text"
              maxLength={10}
              value={formData.zip_code}
              onChange={(e) => handleChange('zip_code', e.target.value)}
              placeholder="85251"
            />
          </div>
          <div className="form-field">
            <label className="form-label">Lead Source</label>
            <input
              className="form-input"
              type="text"
              value={formData.lead_source}
              onChange={(e) => handleChange('lead_source', e.target.value)}
              placeholder="mailer"
            />
          </div>
          <div className="form-field">
            <label className="form-label">Notes</label>
            <input
              className="form-input"
              type="text"
              value={formData.notes}
              onChange={(e) => handleChange('notes', e.target.value)}
              placeholder="Optional notes"
            />
          </div>
        </div>

        <p className="form-hint">Dual push: GHL + Notion</p>

        <div style={{ display: 'flex', gap: '0.5rem' }}>
          <button
            className="btn btn-primary"
            onClick={handleSubmit}
            disabled={loading}
          >
            {loading ? 'Capturing...' : 'Capture Lead'}
          </button>
          <button className="btn" onClick={resetForm}>
            Reset
          </button>
        </div>

        {apiError && (
          <div className="alert alert-error">
            <strong>Error:</strong> {apiError}
          </div>
        )}

        {result && (
          <div className="result-card">
            <h2 className="section-title">Lead Captured</h2>
            <div className="result-grid">
              <div className="result-row">
                <span className="result-label">GHL ID</span>
                <span className="result-value">{result.ghl_id}</span>
              </div>
              <div className="result-row">
                <span className="result-label">Notion ID</span>
                <span className="result-value">{result.notion_id}</span>
              </div>
              {result.age != null && (
                <div className="result-row">
                  <span className="result-label">Age</span>
                  <span className="result-value">{result.age}</span>
                </div>
              )}
              {result.lage_months != null && (
                <div className="result-row">
                  <span className="result-label">Lead Age</span>
                  <span className="result-value">{result.lage_months} months</span>
                </div>
              )}
              <div className="result-row">
                <span className="result-label">Status</span>
                <span className="result-value">
                  <span className="badge badge-success">{result.status}</span>
                </span>
              </div>
            </div>
          </div>
        )}
      </section>
    </div>
  )
}

export default LeadImport
