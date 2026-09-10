import { FavoriteChipRow } from './FavoriteChipRow'
import { useVigilStore } from '../store/vigilStore'

export function SourceChips({ actionPrefix }: { actionPrefix: string }) {
  const selected = useVigilStore((s) => s.sourceFilter)
  const options = useVigilStore((s) => s.sourceOptions)
  const favorites = useVigilStore((s) => s.sourceFavorites)
  const setSourceFilter = useVigilStore((s) => s.setSourceFilter)
  const toggleSourceFavorite = useVigilStore((s) => s.toggleSourceFavorite)
  const chips = options.length
    ? options
    : [
        { id: '', label: 'All sources' },
        { id: 'reddit', label: 'Reddit' },
        { id: 'web', label: 'Web' },
        { id: 'instagram', label: 'Instagram' },
        { id: 'manual', label: 'Pasted' },
      ]
  return (
    <FavoriteChipRow
      options={chips}
      selected={selected}
      favorites={favorites}
      onSelect={setSourceFilter}
      onToggleFavorite={toggleSourceFavorite}
      actionPrefix={actionPrefix}
    />
  )
}

export function CategoryChips({ actionPrefix }: { actionPrefix: string }) {
  const selected = useVigilStore((s) => s.categoryFilter)
  const options = useVigilStore((s) => s.categoryOptions)
  const favorites = useVigilStore((s) => s.categoryFavorites)
  const setCategoryFilter = useVigilStore((s) => s.setCategoryFilter)
  const toggleCategoryFavorite = useVigilStore((s) => s.toggleCategoryFavorite)
  const chips = options.length ? options : [{ id: '', label: 'All categories' }]
  return (
    <FavoriteChipRow
      options={chips}
      selected={selected}
      favorites={favorites}
      onSelect={setCategoryFilter}
      onToggleFavorite={toggleCategoryFavorite}
      actionPrefix={actionPrefix}
    />
  )
}
