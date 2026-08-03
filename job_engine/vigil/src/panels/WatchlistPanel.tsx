import { useEffect, useState } from 'react'
import { CityChips } from '../components/CityChips'
import { ExperienceChips } from '../components/ExperienceChips'
import { GlassCompareChart } from '../components/GlassCompareChart'
import { SectorChips } from '../components/SectorChips'
import { api, chipLabel, WINDOW_FALLBACK } from '../lib/api'
import { PanelShell } from './PanelShell'
import { useVigilStore } from '../store/vigilStore'

export function WatchlistPanel() {
  const [days, setDays] = useState(7)
  const [data, setData] = useState<any>(null)
  const sectorFilter = useVigilStore((s) => s.sectorFilter)
  const cityFilter = useVigilStore((s) => s.cityFilter)
  const experienceFilter = useVigilStore((s) => s.experienceFilter)
  const setSectorOptions = useVigilStore((s) => s.setSectorOptions)
  const setCityOptions = useVigilStore((s) => s.setCityOptions)
  const setExperienceOptions = useVigilStore((s) => s.setExperienceOptions)
  const setStatus = useVigilStore((s) => s.setStatus)
  const openCompanyJobs = useVigilStore((s) => s.openCompanyJobs)

  const reload = () =>
    api
      .watchlist(days, '', sectorFilter, cityFilter, experienceFilter)
      .then((d) => {
        setData(d)
        if (d?.sector_options?.length) setSectorOptions(d.sector_options)
        if (d?.city_options?.length) setCityOptions(d.city_options)
        if (d?.experience_options?.length) setExperienceOptions(d.experience_options)
      })
      .catch(() => {})

  useEffect(() => {
    reload()
  }, [days, sectorFilter, cityFilter, experienceFilter])

  const windows = data?.window_options || WINDOW_FALLBACK

  return (
    <PanelShell id="watchlist">
      <SectorChips actionPrefix="watch-sector" />
      <CityChips actionPrefix="watch-city" />
      <ExperienceChips actionPrefix="watch-experience" />
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
        <>
          <GlassCompareChart
            title="Watched companies"
            subtitle="Open jobs — pace in this window"
            actionPrefix="watch-open"
            maxItems={8}
            emptyText="No watched companies yet — pick from directory below"
            items={(data.watched || []).slice(0, 8).map((c: any) => ({
              id: String(c.company_id),
              label: c.name,
              value: c.recent,
              meta: `prior ${c.prior}`,
            }))}
            onSelect={(item) =>
              openCompanyJobs(Number(item.id), item.label, days)
            }
          />
          {(data.watched || []).length > 0 && (
            <div className="chip-row wrap" style={{ marginTop: 4 }}>
              {(data.watched || []).slice(0, 8).map((c: any) => (
                <button
                  key={`uw-${c.company_id}`}
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
                  {c.name} · Watching
                </button>
              ))}
            </div>
          )}
        </>
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
