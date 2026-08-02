import { useVigilStore, type CityOption } from '../store/vigilStore'
import { FavoriteChipRow } from './FavoriteChipRow'

const FALLBACK: CityOption[] = [
  { id: '', label: 'All cities' },
  { id: 'bengaluru', label: 'Bengaluru' },
  { id: 'hyderabad', label: 'Hyderabad' },
  { id: 'chennai', label: 'Chennai' },
  { id: 'kerala', label: 'Kerala' },
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
  /** Optional leading label for compare rows */
  lead?: string
  /** Override selected / onSelect for compare pickers */
  selected?: string
  onSelect?: (id: string) => void
  hideAll?: boolean
}

/** Global city filter chips — favourites first; Show more for the rest. */
export function CityChips({
  actionPrefix = 'city',
  className = '',
  lead,
  selected,
  onSelect,
  hideAll = false,
}: Props) {
  const cityFilter = useVigilStore((s) => s.cityFilter)
  const setCityFilter = useVigilStore((s) => s.setCityFilter)
  const options = useVigilStore((s) => s.cityOptions)
  const favorites = useVigilStore((s) => s.cityFavorites)
  const toggleCityFavorite = useVigilStore((s) => s.toggleCityFavorite)
  const chips = options.length ? options : FALLBACK

  return (
    <FavoriteChipRow
      className={className}
      lead={lead}
      actionPrefix={actionPrefix}
      options={chips.map((o) => ({
        id: o.id || '',
        label: o.label,
        title: o.label,
      }))}
      selected={selected ?? cityFilter}
      favorites={favorites}
      onSelect={onSelect ?? setCityFilter}
      onToggleFavorite={toggleCityFavorite}
      hideAll={hideAll}
    />
  )
}
