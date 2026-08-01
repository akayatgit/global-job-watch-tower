import { useEffect, useState } from 'react'
import { api } from '../lib/api'
import { useVigilStore } from '../store/vigilStore'

function chipTone(level?: string) {
  if (level === 'red' || level === 'blocked') return 'fail'
  if (level === 'orange' || level === 'planb' || level === 'warn') return 'warn'
  return 'ok'
}

export function StatusHud() {
  const statusLine = useVigilStore((s) => s.statusLine)
  const vitals = useVigilStore((s) => s.vitals)
  const setVitals = useVigilStore((s) => s.setVitals)
  const wsConnected = useVigilStore((s) => s.wsConnected)
  const latencyMs = useVigilStore((s) => s.latencyMs)
  const vigilMode = useVigilStore((s) => s.vigilMode)
  const setVigilMode = useVigilStore((s) => s.setVigilMode)
  const [tick, setTick] = useState(0)

  useEffect(() => {
    let alive = true
    const pull = async () => {
      try {
        const s = await api.status()
        if (alive) setVitals(s.vitals)
      } catch {
        /* ignore */
      }
    }
    pull()
    const id = window.setInterval(pull, 3000)
    const t = window.setInterval(() => setTick((n) => n + 1), 1000)
    return () => {
      alive = false
      clearInterval(id)
      clearInterval(t)
    }
  }, [setVitals])

  const v = vitals
  const secs = v?.countdown_secs
  void tick

  return (
    <div className="vigil-hud">
      <div className="status-bar">
        <div className="brand-block">
          <h1>VIGIL</h1>
          <p>{statusLine}</p>
        </div>
        <div className="status-right interactive">
          <div className="vitals-strip">
            <div className={`vital-chip ${chipTone(v?.alert_level)}`} title="Tower alert">
              <span className="k">Link</span>
              <span className="v">{wsConnected ? 'ON' : '…'}</span>
            </div>
            {vigilMode && (
              <div className="vital-chip" title="Gesture bus latency">
                <span className="k">Lag</span>
                <span className="v">{latencyMs}ms</span>
              </div>
            )}
            <div className={`vital-chip ${v?.heat_c >= 85 ? 'fail' : v?.heat_c >= 75 ? 'warn' : 'ok'}`} title="PC heat">
              <span className="k">Heat</span>
              <span className="v">{v?.heat_c != null ? `${Math.round(v.heat_c)}°` : '—'}</span>
            </div>
            <div className="vital-chip" title="Memory">
              <span className="k">Mem</span>
              <span className="v">{v?.mem_pct != null ? `${Math.round(v.mem_pct)}%` : '—'}</span>
            </div>
            <div className="vital-chip" title="Searches today">
              <span className="k">Today</span>
              <span className="v">{v?.searches_today ?? '—'}</span>
            </div>
            <div className="vital-chip" title="Ollama">
              <span className="k">AI</span>
              <span className="v">{v?.ollama_live ? 'ON' : 'OFF'}</span>
            </div>
            <button
              className="vital-chip"
              data-gesture-action="toggle-browser"
              title="Browser visibility"
              onClick={() => api.toggleHeadless().then((r) => useVigilStore.getState().setStatus(
                r.headless ? 'BROWSER HIDDEN — NEXT SEARCH' : 'BROWSER VISIBLE — NEXT SEARCH',
              ))}
              type="button"
            >
              <span className="k">Browser</span>
              <span className="v">{v?.headless ? 'HID' : 'VIS'}</span>
            </button>
          </div>

          <label
            className={`vigil-mode-switch ${vigilMode ? 'on' : 'off'}`}
            title={vigilMode ? 'Hand control on — click to use mouse & keyboard' : 'Mouse & keyboard — click to enable hand control'}
          >
            <span className="switch-label">VIGIL Mode</span>
            <input
              type="checkbox"
              checked={vigilMode}
              onChange={(e) => setVigilMode(e.target.checked)}
            />
            <span className="switch-track" aria-hidden>
              <span className="switch-knob" />
            </span>
            <span className="switch-state">{vigilMode ? 'ON' : 'OFF'}</span>
          </label>
        </div>
      </div>

      {v?.alert_level === 'blocked' || v?.block ? (
        <div className="alert-strip interactive">
          <span>LinkedIn wall detected — check live feed</span>
          <button
            className="chip"
            data-gesture-action="dismiss-alert"
            onClick={() => api.dismissAlert()}
            type="button"
          >
            Dismiss
          </button>
        </div>
      ) : v?.filter_mode_policy === 'keyword' || v?.alert_level === 'planb' ? (
        <div className="alert-strip planb">Plan B keyword filter — heat/GPU recovery</div>
      ) : null}

      <div className="countdown-big">
        <div className="title">{v?.countdown_title || v?.phase_label || 'NEXT SEARCH'}</div>
        <div className="secs">
          {v?.countdown_mode === 'searching'
            ? `${v?.countdown_role || 'Searching'}… ${secs ?? ''}`
            : secs != null
              ? `${secs}`
              : '—'}
        </div>
      </div>

      <div className="orbit-hint">
        {vigilMode
          ? 'VIGIL Mode ON · point · dwell · pinch · two-hand zoom · switch OFF for mouse'
          : 'Desktop mode · click modules below · drag panel headers · type in fields · switch VIGIL Mode ON for hands'}
      </div>
    </div>
  )
}
