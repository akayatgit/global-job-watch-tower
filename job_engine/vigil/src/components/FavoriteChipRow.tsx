import { useMemo, useState } from 'react'

export type ChipOption = { id: string; label: string; title?: string }

type Props = {
  options: ChipOption[]
  selected: string
  favorites: string[]
  onSelect: (id: string) => void
  onToggleFavorite: (id: string) => void
  actionPrefix: string
  className?: string
  /** Optional leading label (e.g. "A" for compare) */
  lead?: string
  /** Hide the empty-id "All …" chip (compare pickers) */
  hideAll?: boolean
}

/**
 * Compact chip row: All + favorites by default; Show more reveals the rest.
 * ★ on each chip (except All) pins/unpins a favourite anytime.
 */
export function FavoriteChipRow({
  options,
  selected,
  favorites,
  onSelect,
  onToggleFavorite,
  actionPrefix,
  className = '',
  lead,
  hideAll = false,
}: Props) {
  const [expanded, setExpanded] = useState(false)

  const { visible, hiddenCount } = useMemo(() => {
    const favSet = new Set(favorites.filter(Boolean))
    const allOpt = hideAll ? undefined : options.find((o) => !o.id)
    const rest = options.filter((o) => o.id)
    const favOpts = rest.filter((o) => favSet.has(o.id))
    const otherOpts = rest.filter((o) => !favSet.has(o.id))
    const selectedOpt = rest.find((o) => o.id === selected)
    const collapsed: ChipOption[] = []
    if (allOpt) collapsed.push(allOpt)
    for (const o of favOpts) collapsed.push(o)
    if (selectedOpt && !favSet.has(selected) && selected) {
      collapsed.push(selectedOpt)
    }
    if (expanded) {
      return {
        visible: allOpt ? [allOpt, ...rest] : rest,
        hiddenCount: otherOpts.length,
      }
    }
    return { visible: collapsed, hiddenCount: otherOpts.length }
  }, [options, favorites, selected, expanded, hideAll])

  return (
    <div className={`chip-row wrap fav-chip-row ${className}`.trim()}>
      {lead ? <span className="chip-lead">{lead}</span> : null}
      {visible.map((opt) => {
        const id = opt.id || ''
        const active = selected === id
        const isFav = Boolean(id && favorites.includes(id))
        return (
          <div
            key={id || 'all'}
            className={`chip-unit ${active ? 'active' : ''} ${isFav ? 'is-fav' : ''}`}
          >
            <button
              type="button"
              className={`chip ${active ? 'active' : ''}`}
              data-gesture-action={`${actionPrefix}-${id || 'all'}`}
              onClick={() => onSelect(id)}
              title={opt.title || opt.label}
            >
              {opt.label}
            </button>
            {id ? (
              <button
                type="button"
                className={`chip-star ${isFav ? 'on' : ''}`}
                data-gesture-action={`${actionPrefix}-fav-${id}`}
                title={isFav ? 'Remove from favourites' : 'Add to favourites'}
                aria-label={isFav ? `Unfavourite ${opt.label}` : `Favourite ${opt.label}`}
                onClick={(e) => {
                  e.stopPropagation()
                  onToggleFavorite(id)
                }}
              >
                {isFav ? '★' : '☆'}
              </button>
            ) : null}
          </div>
        )
      })}
      {hiddenCount > 0 && (
        <button
          type="button"
          className="chip chip-more"
          data-gesture-action={`${actionPrefix}-more`}
          onClick={() => setExpanded((v) => !v)}
          title={expanded ? 'Hide extra chips' : `Show ${hiddenCount} more`}
        >
          {expanded ? 'Show less' : `Show more · ${hiddenCount}`}
        </button>
      )}
    </div>
  )
}
