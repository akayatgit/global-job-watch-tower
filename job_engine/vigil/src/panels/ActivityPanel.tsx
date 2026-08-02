import { useEffect, useMemo, useState } from 'react'
import { SectorChips } from '../components/SectorChips'
import { api, relTime } from '../lib/api'
import { PanelShell } from './PanelShell'
import { useVigilStore } from '../store/vigilStore'

export function ActivityPanel() {
  const [runs, setRuns] = useState<any[]>([])
  const [sectorIds, setSectorIds] = useState<Set<number> | null>(null)
  const sectorFilter = useVigilStore((s) => s.sectorFilter)
  const setStatus = useVigilStore((s) => s.setStatus)

  useEffect(() => {
    let alive = true
    if (!sectorFilter) {
      setSectorIds(null)
      return
    }
    api
      .configs(sectorFilter)
      .then((cfgs) => {
        if (!alive) return
        setSectorIds(new Set(cfgs.map((c) => c.id as number)))
      })
      .catch(() => {
        if (alive) setSectorIds(new Set())
      })
    return () => {
      alive = false
    }
  }, [sectorFilter])

  const reload = () => api.runs(40).then(setRuns).catch(() => {})

  useEffect(() => {
    reload()
    const id = window.setInterval(reload, 5000)
    return () => clearInterval(id)
  }, [])

  const shown = useMemo(() => {
    if (!sectorIds) return runs
    return runs.filter((r) => sectorIds.has(r.search_config_id))
  }, [runs, sectorIds])

  return (
    <PanelShell id="activity">
      <SectorChips actionPrefix="activity-sector" />
      <div className="muted" style={{ marginBottom: 8 }}>
        Showing {shown.length}
        {sectorFilter ? ` · sector filtered` : ''} · newest first
      </div>
      {shown.length === 0 ? (
        <div className="empty">
          {sectorFilter ? 'No activity in this sector yet' : 'No activity yet'}
        </div>
      ) : (
        shown.map((r) => (
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
