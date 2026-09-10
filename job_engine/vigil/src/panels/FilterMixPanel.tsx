import { useEffect, useState } from 'react'
import { GlassCompareChart } from '../components/GlassCompareChart'
import { api } from '../lib/api'
import { PanelShell } from './PanelShell'

export function FilterMixPanel() {
  const [days, setDays] = useState(7)
  const [data, setData] = useState<any>(null)

  useEffect(() => {
    let alive = true
    const load = () =>
      api.promptMix(days).then((d) => alive && setData(d)).catch(() => {})
    load()
    const id = window.setInterval(load, 8000)
    return () => {
      alive = false
      clearInterval(id)
    }
  }, [days])

  const windows = data?.window_options || [
    { days: 0, label: 'Last 24 hours' },
    { days: 1, label: 'Today' },
    { days: 7, label: 'Last 7 days' },
    { days: 30, label: 'Last 30 days' },
  ]

  return (
    <PanelShell id="filter_mix">
      <div className="chip-row wrap">
        {windows.map((w: { days: number; label: string }) => (
          <button
            key={w.days}
            type="button"
            className={`chip ${days === w.days ? 'active' : ''}`}
            data-gesture-action={`mix-${w.days}`}
            onClick={() => setDays(w.days)}
          >
            {w.days === 0 ? '24h' : w.days === 1 ? 'Today' : `${w.days}d`}
          </button>
        ))}
      </div>
      {!data ? (
        <div className="empty">Comparing Hermes vs recipe scores…</div>
      ) : (
        <>
          <div className="stat-grid">
            <div className="stat-card ai-tone">
              <div className="n">{data.ai_mean ?? '—'}</div>
              <div className="l">Hermes mean</div>
            </div>
            <div className="stat-card kw-tone">
              <div className="n">{data.heuristic_mean ?? '—'}</div>
              <div className="l">Recipe mean</div>
            </div>
            <div className="stat-card">
              <div className="n">{data.blended_mean ?? '—'}</div>
              <div className="l">Blend mean</div>
            </div>
            <div className="stat-card">
              <div className="n">{data.outliers}</div>
              <div className="l">Outliers</div>
            </div>
          </div>
          <GlassCompareChart
            title="How we score"
            subtitle="Recipe is the structure check · Hermes grades detail + flow"
            actionPrefix="mix-bar"
            maxItems={3}
            items={(data.items || []).map((c: any) => ({
              id: c.id,
              label: c.label,
              value: c.value,
            }))}
          />
          <div className="muted" style={{ marginTop: 8 }}>
            {data.ai_n} Hermes reads · {data.heuristic_n} recipe scores
          </div>
        </>
      )}
    </PanelShell>
  )
}
