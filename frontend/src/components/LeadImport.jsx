import { useState } from 'react'
import { useAuth } from '@clerk/clerk-react'
import LeadImportWizardModal from './LeadImportWizardModal'

function LeadImport() {
  const [showWizard, setShowWizard] = useState(false)
  const [lastImport, setLastImport] = useState(null)

  // Manual entry state
  const [formData, setFormData] = useState({
    first_name: '', last_name: '', phone: '', email: '', birth_year: '', mail_date: '',
    address: '', city: '', state: '', zip_code: '', lead_source: '', notes: '',
  })
  const [errors, setErrors] = useState({})
  const [result, setResult] = useState(null)
  const [loading, setLoading] = useState(false)
  const [apiError, setApiError] = useState(null)

  let getToken = null
  try { const auth = useAuth(); getToken = auth.getToken } catch { /* Clerk not configured */ }

  const getHeaders = async () => {
    const headers = { 'Content-Type': 'application/json' }
    if (getToken) { try { const t = await getToken(); if (t) headers['Authorization'] = 'Bearer ' + t } catch { /* no-op */ } }
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

  const handleChange = (field, value) => {
    setFormData(prev => ({ ...prev, [field]: value }))
    if (errors[field]) setErrors(prev => ({ ...prev, [field]: null }))
  }

  const resetForm = () => {
    setFormData({ first_name: '', last_name: '', phone: '', email: '', birth_year: '', mail_date: '', address: '', city: '', state: '', zip_code: '', lead_source: '', notes: '' })
    setErrors({}); setResult(null); setApiError(null)
  }

  const FIELDS = [
    { key: 'first_name', label: 'First Name *', type: 'text', placeholder: 'John' },
    { key: 'last_name', label: 'Last Name *', type: 'text', placeholder: 'Doe' },
    { key: 'phone', label: 'Phone *', type: 'text', placeholder: '480-555-1234' },
    { key: 'email', label: 'Email', type: 'email', placeholder: 'john@example.com' },
    { key: 'birth_year', label: 'Birth Year', type: 'number', placeholder: '1972' },
    { key: 'mail_date', label: 'Mail Date', type: 'date' },
    { key: 'address', label: 'Address', type: 'text', placeholder: '123 Main St' },
    { key: 'city', label: 'City', type: 'text', placeholder: 'Scottsdale' },
    { key: 'state', label: 'State', type: 'text', placeholder: 'AZ' },
    { key: 'zip_code', label: 'ZIP', type: 'text', placeholder: '85251' },
    { key: 'lead_source', label: 'Lead Source', type: 'text', placeholder: 'mailer' },
    { key: 'notes', label: 'Notes', type: 'text', placeholder: 'Optional notes' },
  ]

  return (
    <div className="dashboard">
      {/* Bulk Import CTA */}
      <section className="section">
        <h2 className="section-title">Bulk Import</h2>
        <p className="section-desc">
          Import leads from CSV, Excel, or Google Sheets. Column mapping, vendor/tier tagging, and preview before import.
        </p>
        <button className="btn btn-primary" onClick={() => setShowWizard(true)}>
          Import Leads
        </button>
        {lastImport && (
          <p className="form-hint" style={{ marginTop: '0.5rem' }}>
            Last import: {lastImport} leads created
          </p>
        )}
      </section>

      {/* Manual Entry */}
      <section className="section">
        <h2 className="section-title">Manual Entry</h2>
        <p className="section-desc">Capture a single lead. Dual push: GHL + Notion.</p>

        <div className="form-grid">
          {FIELDS.map(f => (
            <div className="form-field" key={f.key}>
              <label className="form-label">{f.label}</label>
              <input
                className={'form-input' + (errors[f.key] ? ' form-input-error' : '')}
                type={f.type}
                value={formData[f.key]}
                onChange={e => handleChange(f.key, e.target.value)}
                placeholder={f.placeholder || ''}
              />
              {errors[f.key] && <span className="form-error">{errors[f.key]}</span>}
            </div>
          ))}
        </div>

        <div style={{ display: 'flex', gap: '0.5rem' }}>
          <button className="btn btn-primary" onClick={handleSubmit} disabled={loading}>
            {loading ? 'Capturing...' : 'Capture Lead'}
          </button>
          <button className="btn" onClick={resetForm}>Reset</button>
        </div>

        {apiError && (
          <div className="alert alert-error"><strong>Error:</strong> {apiError}</div>
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

      {/* Wizard Modal */}
      <LeadImportWizardModal
        isOpen={showWizard}
        onClose={() => setShowWizard(false)}
        onComplete={(count) => setLastImport(count)}
        getHeaders={getHeaders}
      />
    </div>
  )
}

export default LeadImport
