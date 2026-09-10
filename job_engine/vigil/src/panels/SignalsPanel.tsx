import { useEffect, useState } from 'react'
import { CategoryChips, SourceChips } from '../components/SourceChips'
import { GlassCompareChart } from '../components/GlassCompareChart'
import { api, chipLabel, WINDOW_FALLBACK } from '../lib/api'
import { useVigilStore } from '../store/vigilStore'
import { PanelShell } from './PanelShell'

export function SignalsPanel() {
  const [days, setDays] = useState(7)
  const [data, setData] = useState<any>(null)
  const setSourceOptions = useVigilStore((s) => s.setSourceOptions)
  const setCategoryOptions = useVigilStore((s) => s.setCategoryOptions)
  const setCategoryFilter = useVigilStore((s) => s.setCategoryFilter)
  const setSourceFilter = useVigilStore((s) => s.setSourceFilter)
  const openPanel = useVigilStore((s) => s.openPanel)

  useEffect(() => {
    let alive = true
    api
      .promptSignals(days)
      .then((d) => {
        if (!alive) return
        setData(d)
        if (d?.source_options?.length) setSourceOptions(d.source_options)
        if (d?.category_options?.length) setCategoryOptions(d.category_options)
      })
      .catch(() => {})
    return () => {
      alive = false
    }
  }, [days, setSourceOptions, setCategoryOptions])

  const s = data?.signals
  const windows = data?.window_options || WINDOW_FALLBACK
  const growing = (s?.growing_categories || []).slice(0, 8)
  const fastest = (s?.fastest_sources || []).slice(0, 8)

  return (
    <PanelShell id="signals">
      <SourceChips actionPrefix="signals-source" />
      <CategoryChips actionPrefix="signals-category" />
      <div className="chip-row wrap">
        {windows.map((w: { days: number; label: string }) => (
          <button
            key={w.days}
            type="button"
            className={`chip ${days === w.days ? 'active' : ''}`}
            data-gesture-action={`signals-${w.days}`}
            onClick={() => setDays(w.days)}
          >
            {chipLabel(w.days, w.label)}
          </button>
        ))}
      </div>
      {!s ? (
        <div className="empty">Reading score signals…</div>
      ) : (
        <>
          <div className="signal-hero">
            <div className="stat-grid">
              <div className="stat-card signal-stat">
                <div className="n">{s.recent_total}</div>
                <div className="l">Caught</div>
              </div>
              <div className="stat-card">
                <div className="n">{s.scored}</div>
                <div className="l">Scored</div>
              </div>
              <div className="stat-card">
                <div className="n">{s.mean_score ?? '—'}</div>
                <div className="l">Mean</div>
              </div>
              <div className="stat-card">
                <div className="n">{s.outliers}</div>
                <div className="l">Outliers</div>
              </div>
            </div>
          </div>
          <GlassCompareChart
            title="Score bands"
            subtitle="Hermes blend in this window"
            actionPrefix="signals-band"
            maxItems={4}
            items={(s.score_bands || []).map((b: any) => ({
              id: b.id,
              label: b.label,
              value: b.n,
            }))}
          />
          <GlassCompareChart
            title="Growing categories"
            subtitle="Vs previous window — tap to filter"
            actionPrefix="signals-cat"
            maxItems={8}
            items={growing.map((r: any) => ({
              id: r.id,
              label: r.label,
              value: r.n,
              meta: r.delta > 0 ? `+${r.delta}` : String(r.delta),
            }))}
            onSelect={(item) => {
              setCategoryFilter(item.id)
              openPanel('jobs')
            }}
          />
          <GlassCompareChart
            title="Fastest sources"
            subtitle="Vs previous window"
            actionPrefix="signals-src"
            maxItems={8}
            items={fastest.map((r: any) => ({
              id: r.id,
              label: r.label,
              value: r.n,
              meta: r.delta > 0 ? `+${r.delta}` : String(r.delta),
            }))}
            onSelect={(item) => {
              setSourceFilter(item.id)
              openPanel('jobs')
            }}
          />
        </>
      )}
    </PanelShell>
  )
}
