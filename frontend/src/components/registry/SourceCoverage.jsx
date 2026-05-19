import { Badge, Empty } from './RegistryBadges'

function pctText(value) {
  const numeric = Number(value || 0)
  return `${numeric.toFixed(numeric % 1 === 0 ? 0 : 1)}%`
}

export default function SourceCoverage({ rows = [] }) {
  if (!rows.length) return <Empty label="No source coverage yet." />

  return (
    <div style={{ display: 'grid', gap: '0.65rem' }}>
      {rows.map((row) => (
        <div key={row.source} style={{ display: 'grid', gap: '0.35rem' }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '0.75rem' }}>
            <span style={{ color: 'var(--text)', fontFamily: 'var(--font-mono)', fontSize: '0.74rem' }}>{row.label}</span>
            <Badge tone={row.missing ? 'amber' : 'green'}>{pctText(row.match_pct)}</Badge>
          </div>
          <div style={{ height: 8, background: 'oklch(13% 0.01 240)', border: '1px solid var(--border-subtle)', borderRadius: 2, overflow: 'hidden' }}>
            <div style={{ width: `${Math.max(0, Math.min(100, Number(row.match_pct || 0)))}%`, height: '100%', background: 'var(--accent)' }} />
          </div>
          <div style={{ display: 'flex', gap: '0.35rem', flexWrap: 'wrap' }}>
            <Badge tone="green">Matched {row.matched || 0}</Badge>
            <Badge tone={row.missing ? 'amber' : 'muted'}>Missing {row.missing || 0}</Badge>
            <Badge>Total {row.total || 0}</Badge>
          </div>
        </div>
      ))}
    </div>
  )
}
