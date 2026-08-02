import { useEffect, useState } from 'react'
import { api } from '../lib/api'
import { PanelShell } from './PanelShell'

const FALLBACK_WINDOWS = [
  { key: '1h', chip: '1h', label: 'Last 1 hour' },
  { key: '5h', chip: '5h', label: 'Last 5 hours' },
  { key: '12h', chip: '12h', label: 'Last 12 hours' },
  { key: '24h', chip: '24h', label: 'Last 24 hours' },
  { key: '1d', chip: '1 day', label: 'Today' },
  { key: '2d', chip: '2d', label: 'Last 2 days' },
  { key: '5d', chip: '5d', label: 'Last 5 days' },
  { key: '1w', chip: '1 week', label: 'Last 7 days' },
  { key: 'last_week', chip: 'Last week', label: 'Previous calendar week' },
  { key: 'this_month', chip: 'This month', label: 'This calendar month' },
  { key: 'last_month', chip: 'Last month', label: 'Previous calendar month' },
]

export function FilterMixPanel() {
  const [windowKey, setWindowKey] = useState('24h')
  const [data, setData] = useState<any>(null)

  useEffect(() => {
    let alive = true
    const load = () =>
      api.filterCompare(windowKey).then((d) => alive && setData(d)).catch(() => {})
    load()
    const id = window.setInterval(load, 8000)
    return () => {
      alive = false
      clearInterval(id)
    }
  }, [windowKey])

  const windows = data?.window_options || FALLBACK_WINDOWS
  const ai = data?.ai ?? 0
  const kw = data?.keyword ?? 0
  const total = data?.total ?? 0
  const maxBar = Math.max(data?.max_bar ?? 1, 1)
  const series = data?.series || []
  const seriesMax = Math.max(data?.series_max ?? 1, 1)

  return (
    <PanelShell id="filter_mix">
      <div className="chip-row wrap">
        {windows.map((w: { key: string; chip: string; label: string }) => (
          <button
            key={w.key}
            type="button"
            className={`chip ${windowKey === w.key ? 'active' : ''}`}
            data-gesture-action={`filter-mix-${w.key}`}
            title={w.label}
            onClick={() => setWindowKey(w.key)}
          >
            {w.chip}
          </button>
        ))}
      </div>

      {!data ? (
        <div className="empty">Comparing AI vs keyword filters…</div>
      ) : (
        <>
          <div className="stat-grid">
            <div className="stat-card ai-tone">
              <div className="n">{ai}</div>
              <div className="l">AI · Ollama</div>
            </div>
            <div className="stat-card kw-tone">
              <div className="n">{kw}</div>
              <div className="l">Keyword · Plan B</div>
            </div>
            <div className="stat-card">
              <div className="n">{total}</div>
              <div className="l">Total filters</div>
            </div>
            <div className="stat-card">
              <div className="n">{total ? `${data.ai_pct}%` : '—'}</div>
              <div className="l">AI share</div>
            </div>
          </div>

          <p className="muted">{data.headline}</p>
          <div className="muted" style={{ marginTop: 4 }}>
            {data.label} · {data.start ? new Date(data.start).toLocaleString() : '—'}
            {' → '}
            {data.end ? new Date(data.end).toLocaleString() : '—'}
          </div>

          <div className="section-head" style={{ marginTop: 12 }}>
            <span className="muted">Head-to-head</span>
            <span className="meta">{total} runs</span>
          </div>
          <div className="bar-row">
            <div>
              <div>AI · Ollama</div>
              <div className="bar-track">
                <div
                  className="bar-fill ai-fill"
                  style={{ width: `${(ai / maxBar) * 100}%` }}
                />
              </div>
            </div>
            <strong>{ai}</strong>
          </div>
          <div className="bar-row">
            <div>
              <div>Keyword · Plan B</div>
              <div className="bar-track">
                <div
                  className="bar-fill kw-fill"
                  style={{ width: `${(kw / maxBar) * 100}%` }}
                />
              </div>
            </div>
            <strong>{kw}</strong>
          </div>

          <div className="section-head" style={{ marginTop: 12 }}>
            <span className="muted">
              Over time · {data.bucket === 'hour' ? 'hourly' : 'daily'}
            </span>
            <span className="meta">{series.length} buckets</span>
          </div>
          {series.length === 0 ? (
            <div className="empty">No filter pulses in this window yet.</div>
          ) : (
            <div className="mix-series">
              {series.slice(-24).map((s: any) => (
                <div className="mix-bucket" key={s.at} title={s.at}>
                  <div className="mix-cols">
                    <div
                      className="mix-col ai-fill"
                      style={{ height: `${Math.max(4, (s.ai / seriesMax) * 100)}%` }}
                    />
                    <div
                      className="mix-col kw-fill"
                      style={{ height: `${Math.max(4, (s.keyword / seriesMax) * 100)}%` }}
                    />
                  </div>
                  <div className="mix-lbl">{s.label}</div>
                  <div className="mix-nums">{s.ai}/{s.keyword}</div>
                </div>
              ))}
            </div>
          )}
          <div className="muted" style={{ marginTop: 8 }}>
            Legend: amber = AI · crimson = Keyword Plan B · ratio AI/Keyword under each bar
          </div>
        </>
      )}
    </PanelShell>
  )
}
