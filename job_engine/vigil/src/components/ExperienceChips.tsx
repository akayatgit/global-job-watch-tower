import { useVigilStore, type ExperienceOption } from '../store/vigilStore'
import { FavoriteChipRow } from './FavoriteChipRow'

const FALLBACK: ExperienceOption[] = [
  { id: '', label: 'All experience' },
  { id: 'fresher', label: 'Fresher' },
  { id: '1-2', label: '1–2' },
  { id: '3-5', label: '3–5' },
  { id: '6-8', label: '6–8' },
  { id: '9-12', label: '9–12' },
  { id: '13plus', label: '13+' },
]

type Props = {
  actionPrefix?: string
  className?: string
}

/** Global experience filter chips — favourites first; Show more for the rest. */
export function ExperienceChips({
  actionPrefix = 'experience',
  className = '',
}: Props) {
  const experienceFilter = useVigilStore((s) => s.experienceFilter)
  const setExperienceFilter = useVigilStore((s) => s.setExperienceFilter)
  const options = useVigilStore((s) => s.experienceOptions)
  const favorites = useVigilStore((s) => s.experienceFavorites)
  const toggleExperienceFavorite = useVigilStore((s) => s.toggleExperienceFavorite)
  const chips = options.length ? options : FALLBACK

  return (
    <FavoriteChipRow
      className={className}
      actionPrefix={actionPrefix}
      options={chips.map((o) => ({
        id: o.id || '',
        label: o.label,
        title: o.label,
      }))}
      selected={experienceFilter}
      favorites={favorites}
      onSelect={setExperienceFilter}
      onToggleFavorite={toggleExperienceFavorite}
    />
  )
}
