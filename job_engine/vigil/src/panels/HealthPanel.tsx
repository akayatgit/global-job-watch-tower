import { useEffect, useState } from 'react'
import { api, relTime } from '../lib/api'
import { PanelShell } from './PanelShell'
import { useVigilStore } from '../store/vigilStore'

export function HealthPanel() {
  const [data, setData] = useState<any>(null)
  const [scanning, setScanning] = useState(false)
  const setStatus = useVigilStore((s) => s.setStatus)

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
  const promptMode = (v?.tower_mode || 'prompts') === 'prompts'

  return (
    <PanelShell id="health">
      {!v ? (
        <div className="empty">Reading tower health…</div>
      ) : (
        <>
          {promptMode ? (
            <div className="chip-row wrap">
              <button
                type="button"
                className={`chip ${scanning ? 'active' : ''}`}
                data-gesture-action="health-scan"
                disabled={scanning}
                onClick={() => {
                  setScanning(true)
                  api
                    .promptScan()
                    .then(() => setStatus('SCAN QUEUED'))
                    .catch(() => setStatus('SCAN BUSY'))
                    .finally(() => setScanning(false))
                }}
              >
                {scanning ? 'Scanning…' : 'Scan now'}
              </button>
            </div>
          ) : null}
          <div className="stat-grid">
            <div className="stat-card"><div className="n">{v.heat_c != null ? `${Math.round(v.heat_c)}°` : '—'}</div><div className="l">Heat</div></div>
            <div className="stat-card"><div className="n">{Math.round(v.mem_pct)}%</div><div className="l">Memory</div></div>
            <div className="stat-card"><div className="n">{v.searches_today}</div><div className="l">{promptMode ? 'Caught today' : 'Today'}</div></div>
            <div className="stat-card"><div className="n">{v.searches_24h}</div><div className="l">24h</div></div>
            <div className="stat-card"><div className="n">{v.pending_score ?? 0}</div><div className="l">To score</div></div>
            <div className="stat-card"><div className="n">{v.ollama_live ? 'ON' : 'OFF'}</div><div className="l">Hermes</div></div>
          </div>
          <div className="list-row">
            <div>Next scan</div>
            <div className="meta">{v.next_search_name || '—'} · {v.next_search_label || '—'}</div>
          </div>
          <div className="list-row">
            <div>Last catch</div>
            <div className="meta" title={v.last_collected_at}>{relTime(v.last_collected_at)}</div>
          </div>
          <div className="list-row">
            <div>Last browser</div>
            <div className="meta" title={v.last_browser_at}>{relTime(v.last_browser_at)}</div>
          </div>
          {v.stalled ? (
            <div className="list-row">
              <div>Stall</div>
              <div className="meta">{v.stall_detail || v.alert_label}</div>
            </div>
          ) : null}
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
