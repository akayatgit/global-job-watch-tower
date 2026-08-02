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

/** Wrap label at ~11 chars; prefer break on space. */
export function wrapGlassLabel(label: string, maxChars = 11): string[] {
  const text = label.trim().replace(/\s+/g, ' ')
  if (!text) return ['']
  if (text.length <= maxChars) return [text]

  const lines: string[] = []
  let rest = text
  while (rest.length > maxChars) {
    const chunk = rest.slice(0, maxChars + 1)
    let breakAt = chunk.lastIndexOf(' ')
    if (breakAt < 3) breakAt = maxChars
    lines.push(rest.slice(0, breakAt).trim())
    rest = rest.slice(breakAt).trim()
  }
  if (rest) lines.push(rest)
  return lines.slice(0, 3)
}

/**
 * Responsive glass-pillar comparison chart (reference: glowing crystal bars).
 * Labels sit on each bar tip; width follows the panel.
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
              const pct = Math.max(10, Math.round((item.value / max) * 100))
              const leader = item.id === leaderId
              const clickable = Boolean(onSelect)
              const nameLines = wrapGlassLabel(item.label, 11)
              const body = (
                <div
                  className="glass-pillar-rise"
                  style={{ height: `${pct}%` }}
                >
                  <div className="glass-pillar-label">
                    <span className="glass-pillar-value">
                      {formatValue(item.value)}
                    </span>
                    {item.meta ? (
                      <span className="glass-pillar-meta">{item.meta}</span>
                    ) : null}
                    <span className="glass-pillar-name">
                      {nameLines.map((line, i) => (
                        <span key={`${item.id}-ln-${i}`} className="glass-pillar-name-line">
                          {line}
                        </span>
                      ))}
                    </span>
                  </div>
                  <div className="glass-pillar-shaft">
                    <span className="glass-pillar-sheen" aria-hidden />
                    <span className="glass-pillar-rim left" aria-hidden />
                    <span className="glass-pillar-rim right" aria-hidden />
                    <span className="glass-pillar-core" aria-hidden />
                    <span className="glass-pillar-cap" aria-hidden />
                  </div>
                  <div className="glass-pillar-reflect" aria-hidden>
                    <span className="glass-reflect-shaft" />
                    <span className="glass-reflect-streak" />
                  </div>
                </div>
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
          <div className="glass-chart-floor" aria-hidden />
        </div>
      )}
    </section>
  )
}
