import { useEffect, useState } from 'react'
import { api } from '../lib/api'
import { useVigilStore } from '../store/vigilStore'
import { IconBrowser, IconTrain, IconVigil } from './ModuleIcons'

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
  const trainingActive = useVigilStore((s) => s.trainingActive)
  const startTraining = useVigilStore((s) => s.startTraining)
  const sessions = useVigilStore((s) => s.calibration.sessionsCompleted)
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
          </div>

          <div className="vigil-controls">
            <button
              type="button"
              className={`hud-icon-btn browser-vis-btn ${v?.headless ? 'hidden-mode' : 'visible-mode'}`}
              data-gesture-action="toggle-browser"
              aria-label={v?.headless ? 'Browser hidden' : 'Browser visible'}
              title={
                v?.headless
                  ? 'Browser hidden — click to show Chrome for next search'
                  : 'Browser visible — click to hide for next search'
              }
              onClick={async () => {
                try {
                  const r = await api.toggleHeadless()
                  setVitals({ ...(vitals || {}), headless: r.headless })
                  useVigilStore.getState().setStatus(
                    r.headless
                      ? 'BROWSER HIDDEN — NEXT SEARCH'
                      : 'BROWSER VISIBLE — NEXT SEARCH',
                  )
                } catch {
                  useVigilStore.getState().setStatus('BROWSER TOGGLE FAILED')
                }
              }}
            >
              <IconBrowser hidden={Boolean(v?.headless)} />
            </button>
            <button
              type="button"
              className={`hud-icon-btn train-btn ${trainingActive ? 'active' : ''}`}
              data-gesture-action="start-training"
              disabled={trainingActive}
              aria-label={sessions > 0 ? `Training · ${sessions} sessions` : 'Training'}
              title={
                sessions > 0
                  ? `Guided hand training · ${sessions} sessions done`
                  : 'Guided hand training + calibration'
              }
              onClick={() => startTraining()}
            >
              <IconTrain />
              {sessions > 0 ? <span className="hud-icon-badge">{sessions}</span> : null}
            </button>
            <button
              type="button"
              className={`hud-icon-btn vigil-mode-btn ${vigilMode ? 'on' : 'off'}`}
              data-gesture-action="toggle-vigil-mode"
              aria-pressed={vigilMode}
              aria-label={vigilMode ? 'Vigil mode on' : 'Vigil mode off'}
              title={
                vigilMode
                  ? 'Hand control on — click for mouse & keyboard'
                  : 'Mouse & keyboard — click for hand control'
              }
              onClick={() => setVigilMode(!vigilMode)}
            >
              <IconVigil on={vigilMode} />
            </button>
          </div>
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
    </div>
  )
}
