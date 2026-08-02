import { useVigilStore, type SectorOption } from '../store/vigilStore'

const FALLBACK: SectorOption[] = [
  { id: '', label: 'All sectors' },
  { id: 'tech_ai', label: 'Tech · AI' },
  { id: 'tech_digital', label: 'Tech · Digital' },
  { id: 'manufacturing_advanced', label: 'Manufacturing' },
  { id: 'healthcare', label: 'Healthcare' },
  { id: 'green_economy', label: 'Green economy' },
  { id: 'logistics', label: 'Logistics' },
  { id: 'tourism', label: 'Tourism' },
]

type Props = {
  /** Prefix for gesture action ids */
  actionPrefix?: string
  className?: string
}

/** Global sector filter chips — shared across Tower, Jobs, Signals, etc. */
export function SectorChips({ actionPrefix = 'sector', className = '' }: Props) {
  const sectorFilter = useVigilStore((s) => s.sectorFilter)
  const setSectorFilter = useVigilStore((s) => s.setSectorFilter)
  const options = useVigilStore((s) => s.sectorOptions)
  const chips = options.length ? options : FALLBACK

  return (
    <div className={`chip-row wrap ${className}`.trim()}>
      {chips.map((opt) => {
        const id = opt.id || ''
        const active = sectorFilter === id
        return (
          <button
            key={id || 'all'}
            type="button"
            className={`chip ${active ? 'active' : ''}`}
            data-gesture-action={`${actionPrefix}-${id || 'all'}`}
            onClick={() => setSectorFilter(id)}
            title={opt.industry || opt.label}
          >
            {opt.label}
          </button>
        )
      })}
    </div>
  )
}
