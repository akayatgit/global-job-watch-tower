import { useEffect, useState } from 'react'
import { api, relTime } from '../lib/api'
import { PanelShell } from './PanelShell'
import { useVigilStore } from '../store/vigilStore'

export function ActivityPanel() {
  const [runs, setRuns] = useState<any[]>([])
  const setStatus = useVigilStore((s) => s.setStatus)

  const reload = () => api.runs(40).then(setRuns).catch(() => {})

  useEffect(() => {
    reload()
    const id = window.setInterval(reload, 5000)
    return () => clearInterval(id)
  }, [])

  return (
    <PanelShell id="activity">
      <div className="muted" style={{ marginBottom: 8 }}>Showing {runs.length} · newest first</div>
      {runs.length === 0 ? (
        <div className="empty">No activity yet</div>
      ) : (
        runs.map((r) => (
          <div className="list-row" key={r.id}>
            <div>
              <div>Search #{r.search_config_id} · {r.status}</div>
              <div className="meta" title={r.started_at || r.scheduled_for}>
                {relTime(r.started_at || r.scheduled_for)} · {r.run_type}
              </div>
            </div>
            {['queued', 'dispatched', 'running'].includes(r.status) ? (
              <button
                type="button"
                className="chip"
                data-gesture-action={`cancel-${r.id}`}
                onClick={() =>
                  api.cancelRun(r.id).then(() => {
                    setStatus(`CANCEL ${r.id}`)
                    reload()
                  })
                }
              >
                Cancel
              </button>
            ) : (
              <span className="meta">{r.jobs_found ?? ''}</span>
            )}
          </div>
        ))
      )}
    </PanelShell>
  )
}
