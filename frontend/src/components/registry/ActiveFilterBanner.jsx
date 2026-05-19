import { Badge } from './RegistryBadges'

export default function ActiveFilterBanner({ filter, onClear }) {
  if (!filter) return null

  return (
    <div style={{
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'space-between',
      gap: '0.75rem',
      flexWrap: 'wrap',
      border: '1px solid var(--accent)',
      background: 'oklch(14% 0.018 85 / 0.32)',
      padding: '0.65rem 0.75rem',
      marginBottom: '0.85rem',
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', flexWrap: 'wrap' }}>
        <Badge tone="accent">Filtered by {filter.type}</Badge>
        <span style={{ color: 'var(--text)', fontFamily: 'var(--font-mono)', fontSize: '0.76rem' }}>{filter.label}</span>
      </div>
      <button className="btn-secondary" type="button" onClick={onClear} style={{ padding: '0.32rem 0.55rem' }}>
        Clear
      </button>
    </div>
  )
}
