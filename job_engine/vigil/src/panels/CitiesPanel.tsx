import { useEffect, useState } from 'react'
import { GlassCompareChart } from '../components/GlassCompareChart'
import { api, chipLabel, WINDOW_FALLBACK } from '../lib/api'
import { useVigilStore } from '../store/vigilStore'
import { PanelShell } from './PanelShell'

export function CitiesPanel() {
  const [days, setDays] = useState(7)
  const [data, setData] = useState<any>(null)
  const setCategoryFilter = useVigilStore((s) => s.setCategoryFilter)
  const setCategoryOptions = useVigilStore((s) => s.setCategoryOptions)
  const openPanel = useVigilStore((s) => s.openPanel)

  useEffect(() => {
    let alive = true
    api
      .promptCategories(days)
      .then((d) => {
        if (!alive) return
        setData(d)
        if (d?.categories?.length) {
          setCategoryOptions([
            { id: '', label: 'All categories' },
            ...d.categories.map((c: any) => ({ id: c.id, label: c.label })),
          ])
        }
      })
      .catch(() => {})
    return () => {
      alive = false
    }
  }, [days, setCategoryOptions])

  const windows = data?.window_options || WINDOW_FALLBACK
  const cats = data?.categories || []

  return (
    <PanelShell id="cities">
      <div className="chip-row wrap">
        {windows.map((w: { days: number; label: string }) => (
          <button
            key={w.days}
            type="button"
            className={`chip ${days === w.days ? 'active' : ''}`}
            data-gesture-action={`cats-${w.days}`}
            onClick={() => setDays(w.days)}
          >
            {chipLabel(w.days, w.label)}
          </button>
        ))}
      </div>
      {!data ? (
        <div className="empty">Reading categories…</div>
      ) : (
        <>
          <div className="stat-grid">
            <div className="stat-card signal-stat">
              <div className="n">{data.total}</div>
              <div className="l">Prompts</div>
            </div>
            <div className="stat-card">
              <div className="n">{cats.length}</div>
              <div className="l">Categories</div>
            </div>
          </div>
          <GlassCompareChart
            title="Category mix"
            subtitle="Tap a bar to open Prompts"
            actionPrefix="cats-bar"
            maxItems={12}
            items={cats.map((c: any) => ({
              id: c.id,
              label: c.label,
              value: c.n,
            }))}
            onSelect={(item) => {
              setCategoryFilter(item.id)
              openPanel('jobs')
            }}
          />
        </>
      )}
    </PanelShell>
  )
}
