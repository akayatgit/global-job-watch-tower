import { useVigilStore, type SectorOption } from '../store/vigilStore'
import { FavoriteChipRow } from './FavoriteChipRow'

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
  actionPrefix?: string
  className?: string
}

/** Global sector filter chips — favourites first; Show more for the rest. */
export function SectorChips({ actionPrefix = 'sector', className = '' }: Props) {
  const sectorFilter = useVigilStore((s) => s.sectorFilter)
  const setSectorFilter = useVigilStore((s) => s.setSectorFilter)
  const options = useVigilStore((s) => s.sectorOptions)
  const favorites = useVigilStore((s) => s.sectorFavorites)
  const toggleSectorFavorite = useVigilStore((s) => s.toggleSectorFavorite)
  const chips = options.length ? options : FALLBACK

  return (
    <FavoriteChipRow
      className={className}
      actionPrefix={actionPrefix}
      options={chips.map((o) => ({
        id: o.id || '',
        label: o.label,
        title: o.industry || o.label,
      }))}
      selected={sectorFilter}
      favorites={favorites}
      onSelect={setSectorFilter}
      onToggleFavorite={toggleSectorFavorite}
    />
  )
}
