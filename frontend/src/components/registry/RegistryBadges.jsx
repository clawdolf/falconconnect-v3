export function fmt(value) {
  if (value === null || value === undefined || value === '') return '-'
  return String(value)
}

export function Badge({ children, tone = 'muted' }) {
  const colors = {
    muted: 'var(--text-muted)',
    green: 'var(--green)',
    amber: 'var(--amber)',
    red: 'var(--red)',
    accent: 'var(--accent)',
  }
  return (
    <span style={{
      display: 'inline-flex',
      alignItems: 'center',
      border: `1px solid ${colors[tone] || colors.muted}`,
      color: colors[tone] || colors.muted,
      borderRadius: 2,
      padding: '0.1rem 0.45rem',
      fontFamily: 'var(--font-mono)',
      fontSize: '0.58rem',
      textTransform: 'uppercase',
      letterSpacing: '0.04em',
      whiteSpace: 'nowrap',
    }}>
      {children}
    </span>
  )
}

export function RiskBadge({ value }) {
  const risk = value || 'unknown'
  const tone = risk === 'high' ? 'red' : risk === 'medium' ? 'amber' : risk === 'low' ? 'green' : 'muted'
  return <Badge tone={tone}>{risk}</Badge>
}

export function Empty({ label = 'No records yet.' }) {
  return <p style={{ color: 'var(--text-muted)', fontFamily: 'var(--font-mono)', fontSize: '0.78rem', margin: 0 }}>{label}</p>
}

export function Stat({ label, value }) {
  return (
    <div className="stat-box" style={{ minHeight: 92 }}>
      <div className="stat-label">{label}</div>
      <div className="stat-value">{value ?? 0}</div>
    </div>
  )
}

export function DataTable({ columns, rows, onRowClick, minWidth = 720 }) {
  if (!rows?.length) return <Empty />
  return (
    <div style={{ overflowX: 'auto', borderTop: '1px solid var(--border-subtle)' }}>
      <table style={{ width: '100%', borderCollapse: 'collapse', minWidth }}>
        <thead>
          <tr>
            {columns.map((col) => (
              <th key={col.key} style={{
                textAlign: 'left',
                padding: '0.55rem 0.35rem',
                borderBottom: '1px solid var(--border-subtle)',
                color: 'var(--text-muted)',
                fontFamily: 'var(--font-mono)',
                fontSize: '0.62rem',
                textTransform: 'uppercase',
                letterSpacing: '0.06em',
              }}>{col.label}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr
              key={`${row.id}-${row.external_id || row.display_name || row.recommendation_type || row.event_type}`}
              onClick={() => onRowClick?.(row)}
              style={{ cursor: onRowClick ? 'pointer' : 'default' }}
            >
              {columns.map((col) => (
                <td key={col.key} style={{
                  padding: '0.55rem 0.35rem',
                  borderBottom: '1px solid var(--border-subtle)',
                  color: 'var(--text)',
                  fontFamily: 'var(--font-mono)',
                  fontSize: '0.74rem',
                  verticalAlign: 'top',
                }}>
                  {col.render ? col.render(row) : fmt(row[col.key])}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
