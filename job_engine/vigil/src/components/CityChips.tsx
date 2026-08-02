import { useVigilStore, type CityOption } from '../store/vigilStore'

const FALLBACK: CityOption[] = [
  { id: '', label: 'All cities' },
  { id: 'bengaluru', label: 'Bengaluru' },
  { id: 'hyderabad', label: 'Hyderabad' },
  { id: 'chennai', label: 'Chennai' },
  { id: 'pune', label: 'Pune' },
  { id: 'mumbai', label: 'Mumbai' },
  { id: 'delhi', label: 'Delhi' },
  { id: 'gurugram', label: 'Gurugram' },
  { id: 'noida', label: 'Noida' },
  { id: 'ahmedabad', label: 'Ahmedabad' },
  { id: 'kolkata', label: 'Kolkata' },
  { id: 'remote', label: 'Remote' },
  { id: 'india', label: 'India-wide' },
  { id: 'other', label: 'Other' },
]

type Props = {
  actionPrefix?: string
  className?: string
}

/** Global city filter chips — shared across Tower, Jobs, Signals, etc. */
export function CityChips({ actionPrefix = 'city', className = '' }: Props) {
  const cityFilter = useVigilStore((s) => s.cityFilter)
  const setCityFilter = useVigilStore((s) => s.setCityFilter)
  const options = useVigilStore((s) => s.cityOptions)
  const chips = options.length ? options : FALLBACK

  return (
    <div className={`chip-row wrap ${className}`.trim()}>
      {chips.map((opt) => {
        const id = opt.id || ''
        const active = cityFilter === id
        return (
          <button
            key={id || 'all'}
            type="button"
            className={`chip ${active ? 'active' : ''}`}
            data-gesture-action={`${actionPrefix}-${id || 'all'}`}
            onClick={() => setCityFilter(id)}
            title={opt.label}
          >
            {opt.label}
          </button>
        )
      })}
    </div>
  )
}
