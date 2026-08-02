import { useEffect, useState } from 'react'
import { api, chipLabel } from '../lib/api'
import { PanelShell } from './PanelShell'
import { useVigilStore } from '../store/vigilStore'

const FALLBACK_WINDOWS = [
  { days: 0, label: 'Last 24 hours' },
  { days: 1, label: 'Today' },
  { days: 2, label: 'Last 2 days' },
  { days: 4, label: 'Last 4 days' },
  { days: 7, label: 'Last 7 days' },
  { days: 14, label: 'Last 14 days' },
  { days: 30, label: 'Last 30 days' },
]

export function WatchlistPanel() {
  const [days, setDays] = useState(7)
  const [data, setData] = useState<any>(null)
  const setStatus = useVigilStore((s) => s.setStatus)
  const openCompanyJobs = useVigilStore((s) => s.openCompanyJobs)

  const reload = () => api.watchlist(days).then(setData).catch(() => {})

  useEffect(() => {
    reload()
  }, [days])

  const windows = data?.window_options || FALLBACK_WINDOWS

  return (
    <PanelShell id="watchlist">
      <div className="chip-row wrap">
        {windows.map((w: { days: number; label: string }) => (
          <button
            key={w.days}
            type="button"
            className={`chip ${days === w.days ? 'active' : ''}`}
            data-gesture-action={`watch-${w.days}`}
            onClick={() => setDays(w.days)}
          >
            {chipLabel(w.days, w.label)}
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
            <button
              type="button"
              className="list-row-main clickable"
              data-gesture-action={`watch-open-${c.company_id}`}
              onClick={() => openCompanyJobs(c.company_id, c.name, days)}
            >
              <div>{c.name}</div>
              <div className="meta">{c.recent} recent · prior {c.prior} · open jobs →</div>
            </button>
            <button
              type="button"
              className="chip active"
              data-gesture-action={`unwatch-${c.company_id}`}
              onClick={(e) => {
                e.stopPropagation()
                api.toggleWatch(c.company_id).then(() => {
                  setStatus(`UNWATCHED ${c.name}`)
                  reload()
                })
              }}
            >
              Watching
            </button>
          </div>
        ))
      )}
      <div className="muted" style={{ marginTop: 12 }}>Add from directory</div>
      {(data?.directory || []).slice(0, 10).map((c: any) => {
        const id = c.company_id || c.id
        return (
          <div className="list-row" key={`d-${id}`}>
            <button
              type="button"
              className="list-row-main clickable"
              data-gesture-action={`dir-open-${id}`}
              onClick={() => openCompanyJobs(id, c.name, days)}
            >
              <div>{c.name}</div>
              <div className="meta">open jobs →</div>
            </button>
            <button
              type="button"
              className="chip"
              data-gesture-action={`watch-${id}`}
              onClick={(e) => {
                e.stopPropagation()
                api.toggleWatch(id).then(() => {
                  setStatus(`${c.watched ? 'UNWATCHED' : 'WATCHING'} ${c.name}`)
                  reload()
                })
              }}
            >
              {c.watched ? 'Unwatch' : 'Watch'}
            </button>
          </div>
        )
      })}
    </PanelShell>
  )
}
