import { useEffect, useState } from 'react'
import { api, relTime } from '../lib/api'
import { PanelShell } from './PanelShell'

export function HealthPanel() {
  const [data, setData] = useState<any>(null)

  useEffect(() => {
    let alive = true
    const load = () => api.health().then((d) => alive && setData(d)).catch(() => {})
    load()
    const id = window.setInterval(load, 3000)
    return () => {
      alive = false
      clearInterval(id)
    }
  }, [])

  const v = data?.vitals

  return (
    <PanelShell id="health">
      {!v ? (
        <div className="empty">Reading tower health…</div>
      ) : (
        <>
          <div className="stat-grid">
            <div className="stat-card"><div className="n">{v.heat_c != null ? `${Math.round(v.heat_c)}°` : '—'}</div><div className="l">Heat</div></div>
            <div className="stat-card"><div className="n">{Math.round(v.mem_pct)}%</div><div className="l">Memory</div></div>
            <div className="stat-card"><div className="n">{v.searches_today}</div><div className="l">Today</div></div>
            <div className="stat-card"><div className="n">{v.searches_24h}</div><div className="l">24h</div></div>
            <div className="stat-card"><div className="n">{v.ollama_today}</div><div className="l">Ollama day</div></div>
            <div className="stat-card"><div className="n">{v.ollama_24h}</div><div className="l">Ollama 24h</div></div>
          </div>
          <div className="list-row">
            <div>Next search</div>
            <div className="meta">{v.next_search_name || '—'} · {v.next_search_secs ?? '—'}s</div>
          </div>
          <div className="list-row">
            <div>Last browser</div>
            <div className="meta" title={v.last_browser_at}>{relTime(v.last_browser_at)}</div>
          </div>
          <div className="list-row">
            <div>Capacity</div>
            <div className="meta">{v.ollama_capacity_estimate ?? '—'}</div>
          </div>
          <div className="muted" style={{ marginTop: 10 }}>Recent pulses</div>
          {(data.recent_events || []).slice(0, 12).map((e: any) => (
            <div className="list-row" key={e.id}>
              <div>
                <div>{e.kind}</div>
                <div className="meta">{e.message}</div>
              </div>
              <div className="meta" title={e.created_at}>{relTime(e.created_at)}</div>
            </div>
          ))}
        </>
      )}
    </PanelShell>
  )
}
