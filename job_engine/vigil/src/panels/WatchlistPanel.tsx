import { useEffect, useState } from 'react'
import { api } from '../lib/api'
import { PanelShell } from './PanelShell'
import { useVigilStore } from '../store/vigilStore'

export function WatchlistPanel() {
  const [days, setDays] = useState(7)
  const [data, setData] = useState<any>(null)
  const setStatus = useVigilStore((s) => s.setStatus)

  const reload = () => api.watchlist(days).then(setData).catch(() => {})

  useEffect(() => {
    reload()
  }, [days])

  return (
    <PanelShell id="watchlist">
      <div className="chip-row">
        {[7, 14, 30].map((d) => (
          <button
            key={d}
            type="button"
            className={`chip ${days === d ? 'active' : ''}`}
            data-gesture-action={`watch-${d}`}
            onClick={() => setDays(d)}
          >
            Last {d}d
          </button>
        ))}
      </div>
      {!data ? (
        <div className="empty">Loading watchlist…</div>
      ) : (data.watched || []).length === 0 ? (
        <div className="empty">No watched companies yet — pick from directory below</div>
      ) : (
        (data.watched || []).map((c: any) => (
          <div className="list-row" key={c.company_id}>
            <div>
              <div>{c.name}</div>
              <div className="meta">{c.recent} recent · prior {c.prior}</div>
            </div>
            <button
              type="button"
              className="chip active"
              data-gesture-action={`unwatch-${c.company_id}`}
              onClick={() =>
                api.toggleWatch(c.company_id).then(() => {
                  setStatus(`UNWATCHED ${c.name}`)
                  reload()
                })
              }
            >
              Watching
            </button>
          </div>
        ))
      )}
      <div className="muted" style={{ marginTop: 12 }}>Add from directory</div>
      {(data?.directory || []).slice(0, 10).map((c: any) => (
        <div className="list-row" key={`d-${c.company_id || c.id}`}>
          <div>{c.name}</div>
          <button
            type="button"
            className="chip"
            data-gesture-action={`watch-${c.company_id || c.id}`}
            onClick={() =>
              api.toggleWatch(c.company_id || c.id).then(() => {
                setStatus(`WATCHING ${c.name}`)
                reload()
              })
            }
          >
            {c.watched ? 'Unwatch' : 'Watch'}
          </button>
        </div>
      ))}
    </PanelShell>
  )
}
