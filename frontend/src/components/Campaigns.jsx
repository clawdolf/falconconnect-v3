import React, { useState, useEffect, useCallback } from 'react'
import { useAuth } from '@clerk/clerk-react'

const fmtCurr = (v) => v == null || isNaN(v) ? '$0' : '$' + Number(v).toLocaleString('en-US', { maximumFractionDigits: 0 })
const fmtCpl = (v) => v == null || isNaN(v) ? '$0.00' : '$' + Number(v).toFixed(2)

const STATUS_COLORS = {
  active: { bg: 'rgba(34,197,94,0.15)', color: '#22c55e', label: 'ACTIVE' },
  draft: { bg: 'rgba(234,179,8,0.15)', color: '#eab308', label: 'DRAFT' },
  paused: { bg: 'rgba(156,163,175,0.15)', color: '#9ca3af', label: 'PAUSED' },
  completed: { bg: 'rgba(59,130,246,0.15)', color: '#3b82f6', label: 'COMPLETED' },
}

function StatusBadge({ status }) {
  const s = STATUS_COLORS[status] || STATUS_COLORS.draft
  return (
    <span style={{
      fontFamily: 'var(--font-mono)', fontSize: '0.58rem', fontWeight: 600,
      letterSpacing: '0.08em', padding: '0.15rem 0.45rem', borderRadius: 3,
      background: s.bg, color: s.color,
    }}>
      {s.label}
    </span>
  )
}

function AngleBadge({ angle }) {
  const colors = {
    fear: { bg: 'rgba(239,68,68,0.15)', color: '#ef4444' },
    math: { bg: 'rgba(59,130,246,0.15)', color: '#3b82f6' },
    social_proof: { bg: 'rgba(168,85,247,0.15)', color: '#a855f7' },
    urgency: { bg: 'rgba(234,179,8,0.15)', color: '#eab308' },
  }
  const c = colors[angle] || colors.fear
  return (
    <span style={{
      fontFamily: 'var(--font-mono)', fontSize: '0.52rem', fontWeight: 600,
      letterSpacing: '0.06em', padding: '0.1rem 0.35rem', borderRadius: 2,
      background: c.bg, color: c.color,
    }}>
      {(angle || '').toUpperCase().replace('_', ' ')}
    </span>
  )
}

function CampaignDetail({ campaignId, authFetch, optimizeResult }) {
  const [detail, setDetail] = useState(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let cancelled = false
    async function load() {
      setLoading(true)
      try {
        const data = await authFetch('/api/campaigns/' + campaignId)
        if (!cancelled) setDetail(data)
      } catch (err) { /* silently fail */ }
      finally { if (!cancelled) setLoading(false) }
    }
    load()
    return () => { cancelled = true }
  }, [campaignId, authFetch])

  const thS = {
    fontFamily: 'var(--font-mono)', fontSize: '0.54rem', fontWeight: 600, color: 'var(--text-muted)',
    letterSpacing: '0.06em', textTransform: 'uppercase', padding: '0.4rem 0.5rem',
    textAlign: 'left', borderBottom: '1px solid var(--border)',
  }
  const tdS = {
    fontFamily: 'var(--font-mono)', fontSize: '0.64rem', color: 'var(--text)',
    padding: '0.4rem 0.5rem', borderBottom: '1px solid var(--border)',
  }

  if (loading) {
    return (
      <div style={{ padding: '1rem 1.5rem', background: 'var(--bg)', borderTop: '1px solid var(--border)' }}>
        <span style={{ fontFamily: 'var(--font-mono)', fontSize: '0.68rem', color: 'var(--text-muted)' }}>Loading variants...</span>
      </div>
    )
  }

  if (!detail || !detail.variants || detail.variants.length === 0) {
    return (
      <div style={{ padding: '1rem 1.5rem', background: 'var(--bg)', borderTop: '1px solid var(--border)' }}>
        <span style={{ fontFamily: 'var(--font-mono)', fontSize: '0.68rem', color: 'var(--text-muted)' }}>No variants found for this campaign.</span>
      </div>
    )
  }

  const getRowBg = (v) => {
    if (v.status === 'killed' || v.status === 'paused') return 'rgba(156,163,175,0.08)'
    if (v.leads > 0 && (v.spend / Math.max(v.leads, 1)) <= 40) return 'rgba(34,197,94,0.08)'
    if (v.leads > 0 && (v.spend / Math.max(v.leads, 1)) > 80) return 'rgba(239,68,68,0.08)'
    return 'transparent'
  }

  return (
    <div style={{ background: 'var(--bg)', borderTop: '1px solid var(--border)', padding: '0.75rem' }}>
      <div style={{ overflowX: 'auto' }}>
        <table style={{ width: '100%', borderCollapse: 'collapse' }}>
          <thead>
            <tr>
              <th style={thS}>Variant</th>
              <th style={thS}>Angle</th>
              <th style={thS}>Headline</th>
              <th style={thS}>Impr</th>
              <th style={thS}>Clicks</th>
              <th style={thS}>Leads</th>
              <th style={thS}>Booked</th>
              <th style={thS}>Spend</th>
              <th style={thS}>CPL</th>
              <th style={thS}>Status</th>
            </tr>
          </thead>
          <tbody>
            {detail.variants.map(v => {
              const effectiveCpl = v.leads > 0 ? v.spend / v.leads : 0
              return (
                <tr key={v.id} style={{ background: getRowBg(v) }}>
                  <td style={{ ...tdS, fontWeight: 600, maxWidth: 140, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{v.variant_name}</td>
                  <td style={tdS}><AngleBadge angle={v.angle} /></td>
                  <td style={{ ...tdS, maxWidth: 220, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{v.headline}</td>
                  <td style={tdS}>{v.impressions.toLocaleString()}</td>
                  <td style={tdS}>{v.clicks.toLocaleString()}</td>
                  <td style={tdS}>{v.leads}</td>
                  <td style={tdS}>{v.booked_appointments}</td>
                  <td style={tdS}>{fmtCurr(v.spend)}</td>
                  <td style={{
                    ...tdS,
                    color: effectiveCpl > 80 ? '#ef4444' : effectiveCpl > 0 && effectiveCpl <= 40 ? '#22c55e' : 'var(--text)',
                    fontWeight: effectiveCpl > 80 || (effectiveCpl > 0 && effectiveCpl <= 40) ? 600 : 400,
                  }}>
                    {fmtCpl(effectiveCpl)}
                  </td>
                  <td style={tdS}><StatusBadge status={v.status} /></td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>

      {optimizeResult && (
        <div style={{ marginTop: '0.75rem', padding: '0.75rem', background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 4 }}>
          <h4 style={{ fontFamily: 'var(--font-mono)', fontSize: '0.68rem', fontWeight: 600, color: 'var(--text)', margin: '0 0 0.5rem', letterSpacing: '0.04em' }}>
            Optimization Results
          </h4>
          <p style={{ fontFamily: 'var(--font-mono)', fontSize: '0.62rem', color: 'var(--text-muted)', margin: '0 0 0.5rem' }}>
            {optimizeResult.summary}
          </p>
          {optimizeResult.winners && optimizeResult.winners.length > 0 && (
            <div style={{ marginBottom: '0.5rem' }}>
              <span style={{ fontFamily: 'var(--font-mono)', fontSize: '0.58rem', fontWeight: 600, color: '#22c55e', letterSpacing: '0.04em' }}>WINNERS</span>
              {optimizeResult.winners.map(w => (
                <div key={w.id} style={{ fontFamily: 'var(--font-mono)', fontSize: '0.6rem', color: 'var(--text)', padding: '0.2rem 0', borderBottom: '1px solid var(--border)' }}>
                  {w.variant_name} — CPL {fmtCpl(w.cpl)} — {w.recommendation}
                </div>
              ))}
            </div>
          )}
          {optimizeResult.losers && optimizeResult.losers.length > 0 && (
            <div style={{ marginBottom: '0.5rem' }}>
              <span style={{ fontFamily: 'var(--font-mono)', fontSize: '0.58rem', fontWeight: 600, color: '#ef4444', letterSpacing: '0.04em' }}>FLAGGED FOR KILL</span>
              {optimizeResult.losers.map(l => (
                <div key={l.id} style={{ fontFamily: 'var(--font-mono)', fontSize: '0.6rem', color: 'var(--text)', padding: '0.2rem 0', borderBottom: '1px solid var(--border)' }}>
                  {l.variant_name} — CPL {fmtCpl(l.cpl)} — {l.recommendation}
                </div>
              ))}
            </div>
          )}
          {optimizeResult.needs_data && optimizeResult.needs_data.length > 0 && (
            <div>
              <span style={{ fontFamily: 'var(--font-mono)', fontSize: '0.58rem', fontWeight: 600, color: '#eab308', letterSpacing: '0.04em' }}>NEEDS MORE DATA</span>
              {optimizeResult.needs_data.map(n => (
                <div key={n.id} style={{ fontFamily: 'var(--font-mono)', fontSize: '0.6rem', color: 'var(--text-muted)', padding: '0.2rem 0', borderBottom: '1px solid var(--border)' }}>
                  {n.variant_name} — {n.reason}
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

function Campaigns() {
  const { getToken } = useAuth()
  const [campaigns, setCampaigns] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [metaConnected, setMetaConnected] = useState(null)
  const [expandedId, setExpandedId] = useState(null)
  const [showNewForm, setShowNewForm] = useState(false)
  const [optimizeResults, setOptimizeResults] = useState({})
  const [actionLoading, setActionLoading] = useState({})
  const [newName, setNewName] = useState('')
  const [newProduct, setNewProduct] = useState('Mortgage Protection')
  const [newStates, setNewStates] = useState('Arizona')
  const [newBudget, setNewBudget] = useState('50')
  const [newAgeMin, setNewAgeMin] = useState('25')
  const [newAgeMax, setNewAgeMax] = useState('65')
  const [newHomeowner, setNewHomeowner] = useState('yes')
  const [generatedVariants, setGeneratedVariants] = useState(null)
  const [generating, setGenerating] = useState(false)
  const [saving, setSaving] = useState(false)

  const authFetch = useCallback(async (url, opts = {}) => {
    const token = await getToken()
    const res = await fetch(url, {
      ...opts,
      headers: { 'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json', ...opts.headers },
    })
    if (!res.ok) {
      const b = await res.json().catch(() => ({}))
      throw new Error(b.detail || 'HTTP ' + res.status)
    }
    return res.json()
  }, [getToken])

  const fetchCampaigns = useCallback(async () => {
    setLoading(true); setError(null)
    try { const data = await authFetch('/api/campaigns'); setCampaigns(data.campaigns || []) }
    catch (err) { setError(err.message) }
    finally { setLoading(false) }
  }, [authFetch])

  const fetchMetaStatus = useCallback(async () => {
    try { const data = await authFetch('/api/campaigns/meta/status'); setMetaConnected(data.connected) }
    catch (e) { setMetaConnected(false) }
  }, [authFetch])

  useEffect(() => { fetchCampaigns(); fetchMetaStatus() }, [fetchCampaigns, fetchMetaStatus])

  const totalSpend = campaigns.reduce((s, c) => s + (c.total_spend || 0), 0)
  const totalLeads = campaigns.reduce((s, c) => s + (c.total_leads || 0), 0)
  const totalBooked = campaigns.reduce((s, c) => s + (c.total_booked || 0), 0)
  const avgCpl = totalLeads > 0 ? totalSpend / totalLeads : 0
  const activeCampaigns = campaigns.filter(c => c.status === 'active').length

  const handlePause = async (id) => {
    setActionLoading(prev => ({ ...prev, ['pause_' + id]: true }))
    try { await authFetch('/api/campaigns/' + id + '/pause', { method: 'PUT' }); await fetchCampaigns() }
    catch (err) { setError(err.message) }
    finally { setActionLoading(prev => ({ ...prev, ['pause_' + id]: false })) }
  }
  const handleResume = async (id) => {
    setActionLoading(prev => ({ ...prev, ['resume_' + id]: true }))
    try { await authFetch('/api/campaigns/' + id + '/resume', { method: 'PUT' }); await fetchCampaigns() }
    catch (err) { setError(err.message) }
    finally { setActionLoading(prev => ({ ...prev, ['resume_' + id]: false })) }
  }
  const handleOptimize = async (id) => {
    setActionLoading(prev => ({ ...prev, ['opt_' + id]: true }))
    try {
      const data = await authFetch('/api/campaigns/optimize', { method: 'POST', body: JSON.stringify({ campaign_id: id }) })
      setOptimizeResults(prev => ({ ...prev, [id]: data })); setExpandedId(id)
    } catch (err) { setError(err.message) }
    finally { setActionLoading(prev => ({ ...prev, ['opt_' + id]: false })) }
  }
  const handleGenerateVariants = async () => {
    setGenerating(true)
    try {
      const data = await authFetch('/api/campaigns/generate-variants', { method: 'POST', body: JSON.stringify({ product: newProduct, target_states: newStates }) })
      setGeneratedVariants(data.variants || [])
    } catch (err) { setError(err.message) }
    finally { setGenerating(false) }
  }
  const handleSaveCampaign = async (status) => {
    if (!newName.trim()) { setError('Campaign name is required.'); return }
    setSaving(true)
    try {
      await authFetch('/api/campaigns', { method: 'POST', body: JSON.stringify({
        name: newName, status, budget_daily: parseFloat(newBudget) || 0, budget_total: (parseFloat(newBudget) || 0) * 30,
        strategy: { product: newProduct, target_states: newStates, age_min: newAgeMin, age_max: newAgeMax, homeowner: newHomeowner },
        target_audience: { states: newStates, age_min: newAgeMin, age_max: newAgeMax, homeowner: newHomeowner },
        variants: generatedVariants || [],
      }) })
      setShowNewForm(false); setNewName(''); setGeneratedVariants(null); await fetchCampaigns()
    } catch (err) { setError(err.message) }
    finally { setSaving(false) }
  }

  const inputS = { width: '100%', padding: '0.5rem 0.6rem', background: 'var(--bg)', border: '1px solid var(--border)', borderRadius: 2, fontFamily: 'var(--font-mono)', fontSize: '0.72rem', color: 'var(--text)' }
  const labelS = { fontFamily: 'var(--font-mono)', fontSize: '0.6rem', color: 'var(--text-muted)', letterSpacing: '0.06em', textTransform: 'uppercase', marginBottom: '0.25rem', display: 'block' }
  const selectS = { ...inputS, cursor: 'pointer' }
  const thS = { fontFamily: 'var(--font-mono)', fontSize: '0.58rem', fontWeight: 600, color: 'var(--text-muted)', letterSpacing: '0.06em', textTransform: 'uppercase', padding: '0.5rem 0.6rem', textAlign: 'left', borderBottom: '1px solid var(--border)' }
  const tdS = { fontFamily: 'var(--font-mono)', fontSize: '0.68rem', color: 'var(--text)', padding: '0.5rem 0.6rem', borderBottom: '1px solid var(--border)' }
  const cardS = { background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 4, padding: '0.75rem 1rem' }
  const smBtnS = { display: 'inline-flex', alignItems: 'center', gap: '0.2rem', padding: '0.2rem 0.5rem', background: 'none', border: '1px solid var(--border)', borderRadius: 3, fontFamily: 'var(--font-mono)', fontSize: '0.56rem', color: 'var(--text-muted)', cursor: 'pointer', letterSpacing: '0.04em', touchAction: 'manipulation' }

  return (
    <div className="dashboard">
      <section className="section">
        <div className="section-header-row">
          <h2 className="section-title" style={{ marginBottom: 0, paddingBottom: 0, borderBottom: 'none' }}>Campaigns</h2>
          <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center' }}>
            <button className="btn btn-sm" onClick={fetchCampaigns} disabled={loading}>{loading ? 'Loading...' : 'Refresh'}</button>
            <button className="btn btn-sm btn-primary" onClick={() => setShowNewForm(!showNewForm)}>{showNewForm ? 'Cancel' : '+ New Campaign'}</button>
          </div>
        </div>
      </section>

      {metaConnected === false && (
        <div style={{ background: 'rgba(234,179,8,0.1)', border: '1px solid rgba(234,179,8,0.3)', borderRadius: 4, padding: '0.65rem 1rem', marginBottom: '0.75rem', fontFamily: 'var(--font-mono)', fontSize: '0.68rem', color: '#eab308' }}>
          Meta Ads not connected — add credentials in Settings to launch live campaigns.
        </div>
      )}

      {error && (
        <div className="alert alert-error" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <span>{error}</span>
          <button onClick={() => setError(null)} style={{ background: 'none', border: 'none', color: 'inherit', cursor: 'pointer', fontFamily: 'var(--font-mono)', fontSize: '0.72rem' }}>x</button>
        </div>
      )}

      <section className="section">
        <h2 className="section-title">Overview</h2>
        <div className="stat-row">
          <div className="stat-box"><span className="stat-label">Total Spend</span><span className="stat-value">{fmtCurr(totalSpend)}</span></div>
          <div className="stat-box"><span className="stat-label">Total Leads</span><span className="stat-value" style={{ color: 'var(--green)' }}>{totalLeads}</span></div>
          <div className="stat-box"><span className="stat-label">Avg CPL</span><span className="stat-value">{fmtCpl(avgCpl)}</span></div>
          <div className="stat-box"><span className="stat-label">Booked Appts</span><span className="stat-value" style={{ color: 'var(--green)' }}>{totalBooked}</span></div>
          <div className="stat-box"><span className="stat-label">Active Campaigns</span><span className="stat-value">{activeCampaigns}</span></div>
        </div>
      </section>

      {showNewForm && (
        <section className="section">
          <h2 className="section-title">New Campaign</h2>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
            <div><label style={labelS}>Campaign Name</label><input style={inputS} placeholder="e.g. AZ Mortgage Protection — March 2026" value={newName} onChange={e => setNewName(e.target.value)} /></div>
            <div style={{ display: 'flex', gap: '0.75rem', flexWrap: 'wrap' }}>
              <div style={{ flex: 1, minWidth: 180 }}><label style={labelS}>Product</label><select style={selectS} value={newProduct} onChange={e => setNewProduct(e.target.value)}><option>Mortgage Protection</option><option>Life Insurance</option><option>Final Expense</option></select></div>
              <div style={{ flex: 1, minWidth: 180 }}><label style={labelS}>Target States</label><input style={inputS} placeholder="Arizona, Texas, Florida" value={newStates} onChange={e => setNewStates(e.target.value)} /></div>
              <div style={{ flex: 0.5, minWidth: 100 }}><label style={labelS}>Budget / Day ($)</label><input style={inputS} type="number" value={newBudget} onChange={e => setNewBudget(e.target.value)} /></div>
            </div>
            <div style={{ display: 'flex', gap: '0.75rem', flexWrap: 'wrap' }}>
              <div style={{ flex: 0.5, minWidth: 80 }}><label style={labelS}>Age Min</label><input style={inputS} type="number" value={newAgeMin} onChange={e => setNewAgeMin(e.target.value)} /></div>
              <div style={{ flex: 0.5, minWidth: 80 }}><label style={labelS}>Age Max</label><input style={inputS} type="number" value={newAgeMax} onChange={e => setNewAgeMax(e.target.value)} /></div>
              <div style={{ flex: 0.5, minWidth: 100 }}><label style={labelS}>Homeowner</label><select style={selectS} value={newHomeowner} onChange={e => setNewHomeowner(e.target.value)}><option value="yes">Yes</option><option value="no">No</option><option value="any">Any</option></select></div>
            </div>
            <div style={{ display: 'flex', gap: '0.5rem', marginTop: '0.25rem' }}>
              <button className="btn btn-primary" onClick={handleGenerateVariants} disabled={generating}>{generating ? 'Generating...' : 'Generate Variants'}</button>
            </div>

            {generatedVariants && generatedVariants.length > 0 && (
              <div style={{ marginTop: '0.5rem' }}>
                <h3 style={{ fontFamily: 'var(--font-mono)', fontSize: '0.72rem', fontWeight: 600, color: 'var(--text)', marginBottom: '0.5rem', letterSpacing: '0.04em' }}>Generated Variants ({generatedVariants.length})</h3>
                <div style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
                  {generatedVariants.map((v, i) => (
                    <div key={i} style={cardS}>
                      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.35rem' }}>
                        <span style={{ fontFamily: 'var(--font-mono)', fontSize: '0.65rem', fontWeight: 600, color: 'var(--text)' }}>{v.variant_name}</span>
                        <AngleBadge angle={v.angle} />
                      </div>
                      <input style={{ ...inputS, fontWeight: 600, marginBottom: '0.35rem' }} value={v.headline} onChange={e => { const u = [...generatedVariants]; u[i] = { ...u[i], headline: e.target.value }; setGeneratedVariants(u) }} />
                      <textarea style={{ ...inputS, minHeight: 60, resize: 'vertical' }} value={v.body_copy} onChange={e => { const u = [...generatedVariants]; u[i] = { ...u[i], body_copy: e.target.value }; setGeneratedVariants(u) }} />
                      <input style={{ ...inputS, marginTop: '0.35rem', maxWidth: 250 }} value={v.cta_text} onChange={e => { const u = [...generatedVariants]; u[i] = { ...u[i], cta_text: e.target.value }; setGeneratedVariants(u) }} placeholder="CTA text" />
                    </div>
                  ))}
                </div>
                <div style={{ display: 'flex', gap: '0.5rem', marginTop: '0.75rem' }}>
                  <button className="btn" onClick={() => handleSaveCampaign('draft')} disabled={saving}>{saving ? 'Saving...' : 'Save as Draft'}</button>
                  <button className="btn btn-primary" style={{ opacity: metaConnected ? 1 : 0.5 }} onClick={() => handleSaveCampaign('active')} disabled={saving || !metaConnected} title={!metaConnected ? 'Connect Meta Ads first' : ''}>{saving ? 'Launching...' : 'Launch Campaign'}</button>
                </div>
              </div>
            )}
          </div>
        </section>
      )}

      {!loading && campaigns.length === 0 && !showNewForm && (
        <section className="section">
          <div style={{ textAlign: 'center', padding: '2rem 1rem' }}>
            <p style={{ fontFamily: 'var(--font-display)', fontSize: '1.1rem', fontWeight: 600, color: 'var(--text)', marginBottom: '0.5rem' }}>No Campaigns Yet</p>
            <p className="form-hint" style={{ margin: '0 auto 1.25rem', maxWidth: 440 }}>Create your first campaign to start generating leads with optimized ad copy.</p>
            <button className="btn btn-primary" onClick={() => setShowNewForm(true)}>+ Create Campaign</button>
          </div>
        </section>
      )}

      {campaigns.length > 0 && (
        <section className="section">
          <h2 className="section-title">All Campaigns</h2>
          <div style={{ overflowX: 'auto' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse' }}>
              <thead>
                <tr>
                  <th style={thS}>Name</th>
                  <th style={thS}>Status</th>
                  <th style={thS}>Budget/Day</th>
                  <th style={thS}>Spend</th>
                  <th style={thS}>Leads</th>
                  <th style={thS}>CPL</th>
                  <th style={thS}>Booked</th>
                  <th style={thS}>Actions</th>
                </tr>
              </thead>
              <tbody>
                {campaigns.map(c => (
                  <React.Fragment key={c.id}>
                    <tr style={{ cursor: 'pointer' }} onClick={() => setExpandedId(expandedId === c.id ? null : c.id)}>
                      <td style={tdS}>
                        <span style={{ fontWeight: 600 }}>{c.name}</span>
                        <span style={{ fontFamily: 'var(--font-mono)', fontSize: '0.54rem', color: 'var(--text-muted)', marginLeft: '0.5rem' }}>{c.variant_count} variants</span>
                      </td>
                      <td style={tdS}><StatusBadge status={c.status} /></td>
                      <td style={tdS}>{fmtCurr(c.budget_daily)}</td>
                      <td style={tdS}>{fmtCurr(c.total_spend)}</td>
                      <td style={tdS}>{c.total_leads}</td>
                      <td style={{ ...tdS, color: c.avg_cpl > 80 ? '#ef4444' : c.avg_cpl > 0 && c.avg_cpl <= 40 ? '#22c55e' : 'var(--text)' }}>{fmtCpl(c.avg_cpl)}</td>
                      <td style={tdS}>{c.total_booked}</td>
                      <td style={tdS} onClick={e => e.stopPropagation()}>
                        <div style={{ display: 'flex', gap: '0.3rem' }}>
                          {c.status === 'active' && <button style={smBtnS} onClick={() => handlePause(c.id)} disabled={actionLoading['pause_' + c.id]}>{actionLoading['pause_' + c.id] ? '...' : 'Pause'}</button>}
                          {c.status === 'paused' && <button style={smBtnS} onClick={() => handleResume(c.id)} disabled={actionLoading['resume_' + c.id]}>{actionLoading['resume_' + c.id] ? '...' : 'Resume'}</button>}
                          <button style={smBtnS} onClick={() => handleOptimize(c.id)} disabled={actionLoading['opt_' + c.id]}>{actionLoading['opt_' + c.id] ? '...' : 'Optimize'}</button>
                        </div>
                      </td>
                    </tr>
                    {expandedId === c.id && (
                      <tr><td colSpan={8} style={{ padding: 0 }}><CampaignDetail campaignId={c.id} authFetch={authFetch} optimizeResult={optimizeResults[c.id]} /></td></tr>
                    )}
                  </React.Fragment>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}
    </div>
  )
}

export default Campaigns
