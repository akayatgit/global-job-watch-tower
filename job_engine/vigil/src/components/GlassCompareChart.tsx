import type { ReactNode } from 'react'

export type GlassBarItem = {
  id: string
  label: string
  value: number
  /** Optional secondary line under the value (e.g. "+12") */
  meta?: string
}

type Props = {
  title: string
  subtitle?: string
  items: GlassBarItem[]
  /** Cap pillars shown (rest implied via Show all action) */
  maxItems?: number
  action?: ReactNode
  onSelect?: (item: GlassBarItem) => void
  actionPrefix?: string
  /** Format value above pillar — default plain number */
  formatValue?: (n: number) => string
  className?: string
  emptyText?: string
}

/**
 * Responsive glass-pillar comparison chart (reference: glowing crystal bars).
 * Width follows the panel — pillars flex; never force a wide fixed layout.
 */
export function GlassCompareChart({
  title,
  subtitle,
  items,
  maxItems = 8,
  action,
  onSelect,
  actionPrefix = 'glass',
  formatValue = (n) => String(n),
  className = '',
  emptyText = 'No data in this window yet',
}: Props) {
  const rows = items.slice(0, maxItems)
  const max = Math.max(...rows.map((r) => r.value), 1)
  const leaderId = rows.reduce(
    (best, r) => (r.value > (best?.value ?? -1) ? r : best),
    null as GlassBarItem | null,
  )?.id

  return (
    <section className={`glass-chart ${className}`.trim()}>
      <header className="glass-chart-head">
        <div className="glass-chart-titles">
          <h4 className="glass-chart-title">{title}</h4>
          <div className="glass-chart-rule" aria-hidden />
          {subtitle ? <p className="glass-chart-sub">{subtitle}</p> : null}
        </div>
        {action ? <div className="glass-chart-action">{action}</div> : null}
      </header>

      {rows.length === 0 ? (
        <div className="empty soft">{emptyText}</div>
      ) : (
        <div className="glass-chart-stage">
          <div
            className="glass-chart-pillars"
            style={{ ['--glass-n' as string]: String(rows.length) }}
          >
            {rows.map((item) => {
              const pct = Math.max(8, Math.round((item.value / max) * 100))
              const leader = item.id === leaderId
              const clickable = Boolean(onSelect)
              const body = (
                <>
                  <div className="glass-pillar-label">
                    <span className="glass-pillar-value">
                      {formatValue(item.value)}
                    </span>
                    {item.meta ? (
                      <span className="glass-pillar-meta">{item.meta}</span>
                    ) : null}
                    <span className="glass-pillar-name">{item.label}</span>
                  </div>
                  <div className="glass-pillar-shaft-wrap">
                    <div
                      className="glass-pillar-shaft"
                      style={{ height: `${pct}%` }}
                    >
                      <span className="glass-pillar-face" aria-hidden />
                      <span className="glass-pillar-edge" aria-hidden />
                      <span className="glass-pillar-glow" aria-hidden />
                    </div>
                  </div>
                </>
              )
              const cls = `glass-pillar ${leader ? 'leader' : ''} ${clickable ? 'clickable' : ''}`
              if (clickable) {
                return (
                  <button
                    key={item.id}
                    type="button"
                    className={cls}
                    data-gesture-action={`${actionPrefix}-${item.id}`}
                    onClick={() => onSelect?.(item)}
                    title={item.label}
                  >
                    {body}
                  </button>
                )
              }
              return (
                <div key={item.id} className={cls} title={item.label}>
                  {body}
                </div>
              )
            })}
          </div>
          <div className="glass-chart-floor" aria-hidden>
            <span className="glass-floor-line" />
            <span className="glass-floor-grid" />
          </div>
        </div>
      )}
    </section>
  )
}
