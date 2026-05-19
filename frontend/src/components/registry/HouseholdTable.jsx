import { Badge, DataTable, RiskBadge } from './RegistryBadges'

export default function HouseholdTable({ rows, onOpen }) {
  return (
    <DataTable
      rows={rows}
      onRowClick={onOpen}
      minWidth={940}
      columns={[
        { key: 'display_name', label: 'Household' },
        { key: 'risk_level', label: 'Risk', render: (row) => <RiskBadge value={row.risk_level} /> },
        {
          key: 'rollups',
          label: 'Rollups',
          render: (row) => (
            <div style={{ display: 'flex', gap: '0.35rem', flexWrap: 'wrap' }}>
              <Badge>{row.people_count || 0} people</Badge>
              <Badge>{row.contact_method_count || 0} contacts</Badge>
              <Badge>{row.source_count || 0} sources</Badge>
              <Badge tone={row.recommendation_count ? 'accent' : 'muted'}>{row.recommendation_count || 0} recs</Badge>
            </div>
          ),
        },
        {
          key: 'contact',
          label: 'Masked Contact',
          render: (row) => (
            <div style={{ display: 'grid', gap: '0.18rem' }}>
              <span>{row.primary_phone || '-'}</span>
              <span style={{ color: 'var(--text-muted)' }}>{row.primary_email || '-'}</span>
            </div>
          ),
        },
        {
          key: 'sources',
          label: 'Sources',
          render: (row) => (
            <div style={{ display: 'flex', gap: '0.3rem', flexWrap: 'wrap' }}>
              {(row.sources || []).slice(0, 4).map((source) => <Badge key={source}>{source}</Badge>)}
            </div>
          ),
        },
        {
          key: 'risk_flags',
          label: 'Signals',
          render: (row) => (
            <div style={{ display: 'flex', gap: '0.3rem', flexWrap: 'wrap' }}>
              {row.high_risk_recommendation_count > 0 && <Badge tone="red">{row.high_risk_recommendation_count} high</Badge>}
              {row.hard_stop_count > 0 && <Badge tone="red">hard stop</Badge>}
              {row.dnc_event_count > 0 && <Badge tone="amber">dnc</Badge>}
              {!row.high_risk_recommendation_count && !row.hard_stop_count && !row.dnc_event_count && <Badge>clear</Badge>}
            </div>
          ),
        },
        { key: 'latest_source_label', label: 'Latest Source' },
      ]}
    />
  )
}
