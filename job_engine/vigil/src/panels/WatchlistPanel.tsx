import { useEffect, useState } from 'react'
import { CityChips } from '../components/CityChips'
import { SectorChips } from '../components/SectorChips'
import { api, chipLabel, WINDOW_FALLBACK } from '../lib/api'
import { PanelShell } from './PanelShell'
import { useVigilStore } from '../store/vigilStore'

export function WatchlistPanel() {
  const [days, setDays] = useState(7)
  const [data, setData] = useState<any>(null)
  const sectorFilter = useVigilStore((s) => s.sectorFilter)
  const cityFilter = useVigilStore((s) => s.cityFilter)
  const setSectorOptions = useVigilStore((s) => s.setSectorOptions)
  const setCityOptions = useVigilStore((s) => s.setCityOptions)
  const setStatus = useVigilStore((s) => s.setStatus)
  const openCompanyJobs = useVigilStore((s) => s.openCompanyJobs)

  const reload = () =>
    api
      .watchlist(days, '', sectorFilter, cityFilter)
      .then((d) => {
        setData(d)
        if (d?.sector_options?.length) setSectorOptions(d.sector_options)
        if (d?.city_options?.length) setCityOptions(d.city_options)
      })
      .catch(() => {})

  useEffect(() => {
    reload()
  }, [days, sectorFilter, cityFilter])

  const windows = data?.window_options || WINDOW_FALLBACK

  return (
    <PanelShell id="watchlist">
      <SectorChips actionPrefix="watch-sector" />
      <CityChips actionPrefix="watch-city" />
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
      ) : (
        <section className="insight-block insight-fast">
          <header className="insight-block-head">
            <span className="insight-mark" aria-hidden />
            <div>
              <h4>Watched companies</h4>
              <p>Open jobs — pace in this window</p>
            </div>
            <span className="insight-count">{(data.watched || []).length}</span>
          </header>
          {(data.watched || []).length === 0 ? (
            <div className="empty soft">No watched companies yet — pick from directory below</div>
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
        </section>
      )}
      <section className="insight-block insight-cities">
        <header className="insight-block-head">
          <span className="insight-mark" aria-hidden />
          <div>
            <h4>Add from directory</h4>
            <p>Watch a company to track hiring pace</p>
          </div>
        </header>
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
      </section>
    </PanelShell>
  )
}
