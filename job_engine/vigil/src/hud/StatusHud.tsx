import { useEffect, useState } from 'react'
import { api, WINDOW_FALLBACK, chipLabel } from '../lib/api'
import { useVigilStore } from '../store/vigilStore'
import { IconBrowser, IconTrain, IconVigil } from './ModuleIcons'
import { stepCampusFocus } from '../scene/campusNav'

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
  const sceneMode = useVigilStore((s) => s.sceneMode)
  const setSceneMode = useVigilStore((s) => s.setSceneMode)
  const cityFocus = useVigilStore((s) => s.cityFocus)
  const setCityFocus = useVigilStore((s) => s.setCityFocus)
  const cityWindowDays = useVigilStore((s) => s.cityWindowDays)
  const setCityWindowDays = useVigilStore((s) => s.setCityWindowDays)
  const sceneSpin = useVigilStore((s) => s.sceneSpin)
  const toggleSceneSpin = useVigilStore((s) => s.toggleSceneSpin)
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
            <div className="scene-mode-switch" role="group" aria-label="World view">
              <button
                type="button"
                className={`hud-icon-btn ${sceneMode === 'core' ? 'on' : ''}`}
                title="Core — particle singularity (scroll to enter)"
                aria-label="Core singularity"
                aria-pressed={sceneMode === 'core'}
                onClick={() => setSceneMode('core')}
              >
                <svg viewBox="0 0 24 24" width="16" height="16" aria-hidden>
                  <circle cx="12" cy="12" r="3" fill="currentColor" />
                  <circle cx="12" cy="12" r="7" fill="none" stroke="currentColor" strokeWidth="1.4" opacity="0.55" />
                </svg>
              </button>
              <button
                type="button"
                className={`hud-icon-btn ${sceneMode === 'graph' ? 'on' : ''}`}
                title="Graph — Obsidian world-model nodes"
                aria-label="Obsidian graph"
                aria-pressed={sceneMode === 'graph'}
                onClick={() => setSceneMode('graph')}
              >
                <svg viewBox="0 0 24 24" width="16" height="16" aria-hidden>
                  <circle cx="6" cy="8" r="2" fill="currentColor" />
                  <circle cx="18" cy="7" r="2" fill="currentColor" />
                  <circle cx="12" cy="17" r="2" fill="currentColor" />
                  <path d="M7.5 9.2L10.5 15.2M16.5 8.5L13.2 15.2M8 8h8" fill="none" stroke="currentColor" strokeWidth="1.4" />
                </svg>
              </button>
              <button
                type="button"
                className={`hud-icon-btn ${sceneMode === 'city' ? 'on' : ''}`}
                title="City — globe, then enter a metro"
                aria-label="City globe"
                aria-pressed={sceneMode === 'city'}
                onClick={() => setSceneMode('city')}
              >
                <svg viewBox="0 0 24 24" width="16" height="16" aria-hidden>
                  <circle cx="12" cy="12" r="8" fill="none" stroke="currentColor" strokeWidth="1.5" />
                  <path d="M4 12h16M12 4a14 14 0 0 1 0 16M12 4a14 14 0 0 0 0 16" fill="none" stroke="currentColor" strokeWidth="1.2" opacity="0.7" />
                </svg>
              </button>
              {sceneMode === 'city' && cityFocus ? (
                <>
                  <button
                    type="button"
                    className="hud-icon-btn city-rank-btn"
                    title="Focus next higher openings"
                    aria-label="Next higher openings"
                    onClick={() => stepCampusFocus('higher')}
                  >
                    <svg viewBox="0 0 24 24" width="15" height="15" aria-hidden>
                      <path
                        d="M12 6l6 8H6l6-8z"
                        fill="currentColor"
                      />
                      <path
                        d="M7 18h10"
                        fill="none"
                        stroke="currentColor"
                        strokeWidth="1.6"
                        strokeLinecap="round"
                      />
                    </svg>
                  </button>
                  <button
                    type="button"
                    className="hud-icon-btn city-rank-btn"
                    title="Focus next lower openings"
                    aria-label="Next lower openings"
                    onClick={() => stepCampusFocus('lower')}
                  >
                    <svg viewBox="0 0 24 24" width="15" height="15" aria-hidden>
                      <path
                        d="M7 6h10"
                        fill="none"
                        stroke="currentColor"
                        strokeWidth="1.6"
                        strokeLinecap="round"
                      />
                      <path
                        d="M12 18l6-8H6l6 8z"
                        fill="currentColor"
                      />
                    </svg>
                  </button>
                  <button
                    type="button"
                    className="hud-icon-btn city-exit-btn"
                    title={
                      cityFocus === '__jobs__'
                        ? 'Leave city view — back to globe'
                        : 'Leave campus — back to globe'
                    }
                    aria-label="Leave campus"
                    onClick={() => {
                      setCityFocus(null)
                      useVigilStore.getState().clearCameraFocus()
                      useVigilStore.getState().resetView()
                      useVigilStore.getState().setStatus('CITY · GLOBE')
                    }}
                  >
                    <svg viewBox="0 0 24 24" width="16" height="16" aria-hidden>
                      <path
                        d="M9 6H5.5A1.5 1.5 0 0 0 4 7.5v9A1.5 1.5 0 0 0 5.5 18H9"
                        fill="none"
                        stroke="currentColor"
                        strokeWidth="1.6"
                        strokeLinecap="round"
                      />
                      <path
                        d="M10 12h10M16 7l5 5-5 5"
                        fill="none"
                        stroke="currentColor"
                        strokeWidth="1.6"
                        strokeLinecap="round"
                        strokeLinejoin="round"
                      />
                    </svg>
                  </button>
                </>
              ) : null}
              <button
                type="button"
                className={`hud-icon-btn ${sceneSpin ? 'on' : ''}`}
                title={sceneSpin ? 'Spin on — click or Space to freeze' : 'Spin off — click or Space to resume'}
                aria-label={sceneSpin ? 'Freeze spin' : 'Resume spin'}
                aria-pressed={sceneSpin}
                onClick={() => toggleSceneSpin()}
              >
                <svg viewBox="0 0 24 24" width="16" height="16" aria-hidden>
                  {sceneSpin ? (
                    <path
                      d="M12 4a8 8 0 1 1-5.7 2.3M12 4v4M12 4l2.5 2"
                      fill="none"
                      stroke="currentColor"
                      strokeWidth="1.6"
                      strokeLinecap="round"
                    />
                  ) : (
                    <>
                      <rect x="7" y="6" width="3" height="12" rx="0.5" fill="currentColor" />
                      <rect x="14" y="6" width="3" height="12" rx="0.5" fill="currentColor" />
                    </>
                  )}
                </svg>
              </button>
            </div>
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

      {sceneMode === 'city' ? (
        <div
          className={`city-window-bar interactive ${cityFocus ? 'in-campus' : 'on-globe'}`}
          role="group"
          aria-label="Hiring window for city view"
        >
          {!cityFocus ? (
            <span className="city-window-hint" title="Applies when you enter a metro">
              Hiring window
            </span>
          ) : null}
          {WINDOW_FALLBACK.map((w) => (
            <button
              key={w.days}
              type="button"
              className={`chip city-window-chip ${cityWindowDays === w.days ? 'active' : ''}`}
              title={w.label}
              aria-pressed={cityWindowDays === w.days}
              onClick={() => setCityWindowDays(w.days)}
            >
              {chipLabel(w.days, w.label)}
            </button>
          ))}
        </div>
      ) : null}

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
