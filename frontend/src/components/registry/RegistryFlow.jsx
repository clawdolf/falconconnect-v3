import { Empty } from './RegistryBadges'

const columnOrder = ['source', 'risk', 'bucket', 'state']
const columnLabels = {
  source: 'Source',
  risk: 'Risk',
  bucket: 'Recommendation',
  state: 'Review state',
}

function nodeColor(node) {
  if (node.column === 'risk') {
    if (node.label === 'High') return 'var(--red)'
    if (node.label === 'Medium') return 'var(--amber)'
    if (node.label === 'Low') return 'var(--green)'
  }
  if (node.column === 'source') return 'var(--accent)'
  if (node.column === 'state') return node.label.toLowerCase().includes('locked') ? 'var(--red)' : 'var(--green)'
  return 'oklch(78% 0.08 86)'
}

export default function RegistryFlow({ data, onFilter }) {
  const nodes = data?.nodes || []
  const links = data?.links || []
  if (!nodes.length) return <Empty label="No attribution flow yet. Import a Lead Hygiene report to populate the graph." />

  const width = 980
  const height = 360
  const margin = { top: 46, right: 36, bottom: 28, left: 36 }
  const columns = new Map(columnOrder.map((col) => [col, []]))
  nodes.forEach((node) => {
    if (!columns.has(node.column)) columns.set(node.column, [])
    columns.get(node.column).push(node)
  })
  columns.forEach((items) => items.sort((a, b) => b.count - a.count || a.label.localeCompare(b.label)))

  const positioned = new Map()
  columnOrder.forEach((col, colIndex) => {
    const items = columns.get(col) || []
    const x = margin.left + colIndex * ((width - margin.left - margin.right) / Math.max(1, columnOrder.length - 1))
    const gap = 14
    const itemHeight = Math.min(58, Math.max(34, (height - margin.top - margin.bottom - gap * Math.max(0, items.length - 1)) / Math.max(1, items.length)))
    const totalHeight = items.length * itemHeight + Math.max(0, items.length - 1) * gap
    const startY = margin.top + Math.max(0, (height - margin.top - margin.bottom - totalHeight) / 2)
    items.forEach((node, index) => {
      positioned.set(node.id, { ...node, x, y: startY + index * (itemHeight + gap), w: 152, h: itemHeight })
    })
  })

  const maxLink = Math.max(...links.map((link) => link.value), 1)

  function handleNodeClick(node) {
    if (node.column === 'source') onFilter?.({ source: node.id.split(':')[1] })
    if (node.column === 'risk') onFilter?.({ risk: node.label.toLowerCase() })
    if (node.column === 'bucket') onFilter?.({ bucket: node.label.toLowerCase().replaceAll(' ', '-') })
  }

  return (
    <div style={{ overflowX: 'auto' }}>
      <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label="Registry attribution flow" style={{ width: '100%', minWidth: 820, height: 'auto', display: 'block' }}>
        <defs>
          <filter id="registry-flow-glow" x="-20%" y="-20%" width="140%" height="140%">
            <feGaussianBlur stdDeviation="2.5" result="blur" />
            <feMerge>
              <feMergeNode in="blur" />
              <feMergeNode in="SourceGraphic" />
            </feMerge>
          </filter>
        </defs>
        {columnOrder.map((col, index) => {
          const x = margin.left + index * ((width - margin.left - margin.right) / Math.max(1, columnOrder.length - 1))
          return (
            <text key={col} x={x} y={24} fill="var(--text-muted)" fontFamily="var(--font-mono)" fontSize="11" letterSpacing="0.8">
              {columnLabels[col]}
            </text>
          )
        })}
        {links.map((link) => {
          const source = positioned.get(link.source)
          const target = positioned.get(link.target)
          if (!source || !target) return null
          const x1 = source.x + source.w
          const y1 = source.y + source.h / 2
          const x2 = target.x
          const y2 = target.y + target.h / 2
          const thickness = 3 + (link.value / maxLink) * 18
          return (
            <path
              key={`${link.source}-${link.target}`}
              d={`M ${x1} ${y1} C ${x1 + 70} ${y1}, ${x2 - 70} ${y2}, ${x2} ${y2}`}
              fill="none"
              stroke="oklch(78% 0.07 86 / 0.45)"
              strokeWidth={thickness}
              strokeLinecap="round"
            />
          )
        })}
        {[...positioned.values()].map((node) => (
          <g key={node.id} onClick={() => handleNodeClick(node)} style={{ cursor: ['source', 'risk', 'bucket'].includes(node.column) ? 'pointer' : 'default' }}>
            <rect x={node.x} y={node.y} width={node.w} height={node.h} rx="4" fill="oklch(18% 0.02 250)" stroke={nodeColor(node)} strokeWidth="1.2" filter="url(#registry-flow-glow)" />
            <rect x={node.x} y={node.y} width="4" height={node.h} fill={nodeColor(node)} />
            <text x={node.x + 13} y={node.y + 20} fill="var(--text)" fontFamily="var(--font-mono)" fontSize="12">{node.label}</text>
            <text x={node.x + 13} y={node.y + node.h - 10} fill="var(--text-muted)" fontFamily="var(--font-mono)" fontSize="10">{node.count.toLocaleString()} records</text>
          </g>
        ))}
      </svg>
    </div>
  )
}
