import { Badge, DataTable, Empty, RiskBadge } from './RegistryBadges'

export default function HouseholdDrawer({ detail, onClose }) {
  if (!detail) return null
  return (
    <div style={{
      position: 'fixed',
      inset: 0,
      zIndex: 50,
      display: 'flex',
      justifyContent: 'flex-end',
      background: 'oklch(8% 0.01 250 / 0.62)',
    }}>
      <aside style={{
        width: 'min(760px, 100vw)',
        height: '100%',
        overflowY: 'auto',
        background: 'var(--bg)',
        borderLeft: '1px solid var(--border)',
        padding: '1.1rem',
        boxShadow: '-18px 0 48px oklch(0% 0 0 / 0.35)',
      }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', gap: '1rem', alignItems: 'flex-start', marginBottom: '1rem' }}>
          <div>
            <div style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap', marginBottom: '0.5rem' }}>
              <RiskBadge value={detail.risk_level} />
              <Badge>{detail.status || 'active'}</Badge>
              <Badge tone="accent">full contact detail</Badge>
            </div>
            <h2 style={{ fontFamily: 'var(--font-display)', fontSize: '1.45rem', lineHeight: 1.1, margin: 0 }}>{detail.display_name}</h2>
          </div>
          <button className="btn-secondary" type="button" onClick={onClose}>Close</button>
        </div>

        <div style={{ display: 'grid', gap: '1rem' }}>
          <section className="section">
            <div className="section-title">People</div>
            <DataTable columns={[
              { key: 'display_name', label: 'Person' },
              { key: 'role', label: 'Role' },
              { key: 'consent_status', label: 'Consent' },
              { key: 'dnc_status', label: 'DNC' },
            ]} rows={detail.people || []} minWidth={520} />
          </section>

          <section className="section">
            <div className="section-title">Contact Methods</div>
            <DataTable columns={[
              { key: 'kind', label: 'Type' },
              { key: 'normalized_value', label: 'Value' },
              { key: 'validity_status', label: 'Valid' },
              { key: 'consent_status', label: 'Consent' },
            ]} rows={detail.contact_methods || []} minWidth={560} />
          </section>

          <section className="section">
            <div className="section-title">Source Records</div>
            <DataTable columns={[
              { key: 'source', label: 'Source' },
              { key: 'external_type', label: 'Type' },
              { key: 'external_id', label: 'External ID' },
              { key: 'match_basis', label: 'Match' },
            ]} rows={detail.external_records || []} minWidth={620} />
          </section>

          <section className="section">
            <div className="section-title">Recommendations</div>
            <DataTable columns={[
              { key: 'recommendation_type', label: 'Recommendation' },
              { key: 'status', label: 'Status', render: (row) => <Badge tone="accent">{row.status}</Badge> },
              { key: 'risk_level', label: 'Risk', render: (row) => <RiskBadge value={row.risk_level} /> },
              { key: 'confidence', label: 'Confidence' },
            ]} rows={detail.recommendations || []} minWidth={620} />
          </section>

          <section className="section">
            <div className="section-title">Consent Evidence</div>
            {(detail.consent_events || []).length ? (
              <DataTable columns={[
                { key: 'event_type', label: 'Event' },
                { key: 'source', label: 'Source' },
                { key: 'evidence', label: 'Evidence' },
              ]} rows={detail.consent_events || []} minWidth={620} />
            ) : <Empty label="No consent evidence recorded for this household." />}
          </section>
        </div>
      </aside>
    </div>
  )
}
