import { useEffect, useState } from 'react'
import { api } from '../lib/api'
import { PanelShell } from './PanelShell'
import { useVigilStore } from '../store/vigilStore'

export function SearchesPanel() {
  const [configs, setConfigs] = useState<any[]>([])
  const setStatus = useVigilStore((s) => s.setStatus)

  const reload = () => api.configs().then(setConfigs).catch(() => {})

  useEffect(() => {
    reload()
    const id = window.setInterval(reload, 10000)
    return () => clearInterval(id)
  }, [])

  return (
    <PanelShell id="searches">
      <div className="muted" style={{ marginBottom: 8 }}>
        {configs.length} roles · dwell Run / Pause chips
      </div>
      {configs.length === 0 ? (
        <div className="empty">No searches yet — use legacy shell /legacy/configs to create</div>
      ) : (
        configs.map((c) => (
          <div className="list-row" key={c.id}>
            <div>
              <div>{c.name}</div>
              <div className="meta">
                {c.keywords} · {c.enabled ? <span className="ok">On</span> : <span className="warn">Paused</span>}
              </div>
            </div>
            <div className="chip-row" style={{ margin: 0 }}>
              <button
                type="button"
                className="chip"
                data-gesture-action={`toggle-cfg-${c.id}`}
                onClick={() =>
                  api.toggleConfig(c.id).then(() => {
                    setStatus(`${c.enabled ? 'PAUSED' : 'ENABLED'} ${c.name}`)
                    reload()
                  })
                }
              >
                {c.enabled ? 'Pause' : 'Enable'}
              </button>
              <button
                type="button"
                className="chip active"
                data-gesture-action={`run-cfg-${c.id}`}
                onClick={() =>
                  api.runConfig(c.id).then(() => {
                    setStatus(`DISPATCHED ${c.name}`)
                  }).catch(() => setStatus(`BUSY — ${c.name}`))
                }
              >
                Run
              </button>
            </div>
          </div>
        ))
      )}
    </PanelShell>
  )
}
