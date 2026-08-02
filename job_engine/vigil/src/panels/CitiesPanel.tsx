import { useEffect, useState } from 'react'
import { CityChips } from '../components/CityChips'
import { SectorChips } from '../components/SectorChips'
import { api, chipLabel } from '../lib/api'
import { useVigilStore } from '../store/vigilStore'
import { PanelShell } from './PanelShell'

const FALLBACK_WINDOWS = [
  { days: 0, label: 'Last 24 hours' },
  { days: 1, label: 'Today' },
  { days: 2, label: 'Last 2 days' },
  { days: 4, label: 'Last 4 days' },
  { days: 7, label: 'Last 7 days' },
  { days: 14, label: 'Last 14 days' },
  { days: 30, label: 'Last 30 days' },
]

export function CitiesPanel() {
  const [days, setDays] = useState(7)
  const [data, setData] = useState<any>(null)
  const [compare, setCompare] = useState<any>(null)
  const [pickA, setPickA] = useState('bengaluru')
  const [pickB, setPickB] = useState('hyderabad')
  const sectorFilter = useVigilStore((s) => s.sectorFilter)
  const setCityFilter = useVigilStore((s) => s.setCityFilter)
  const setCityOptions = useVigilStore((s) => s.setCityOptions)
  const openPanel = useVigilStore((s) => s.openPanel)
  const openRoleHire = useVigilStore((s) => s.openRoleHire)
  const openCompanyJobs = useVigilStore((s) => s.openCompanyJobs)

  useEffect(() => {
    let alive = true
    api
      .citySignals(days, sectorFilter)
      .then((d) => {
        if (!alive) return
        setData(d)
        if (d?.city_options?.length) setCityOptions(d.city_options)
      })
      .catch(() => {})
    return () => {
      alive = false
    }
  }, [days, sectorFilter, setCityOptions])

  useEffect(() => {
    if (!pickA || !pickB || pickA === pickB) {
      setCompare(null)
      return
    }
    let alive = true
    api
      .cityCompare(pickA, pickB, days, sectorFilter)
      .then((d) => alive && setCompare(d))
      .catch(() => {})
    return () => {
      alive = false
    }
  }, [pickA, pickB, days, sectorFilter])

  const windows = data?.window_options || FALLBACK_WINDOWS
  const cities = data?.cities || []
  const maxN = data?.max || Math.max(...cities.map((c: any) => c.recent), 1)
  const cityOpts = (data?.city_options || []).filter((o: any) => o.id)

  const openCityJobs = (cityId: string) => {
    setCityFilter(cityId)
    openPanel('jobs')
  }

  return (
    <PanelShell id="cities">
      <SectorChips actionPrefix="cities-sector" />
      <div className="chip-row wrap">
        {windows.map((w: { days: number; label: string }) => (
          <button
            key={w.days}
            type="button"
            className={`chip ${days === w.days ? 'active' : ''}`}
            data-gesture-action={`cities-days-${w.days}`}
            onClick={() => setDays(w.days)}
          >
            {chipLabel(w.days, w.label)}
          </button>
        ))}
      </div>

      {!data ? (
        <div className="empty">Reading city hiring signals…</div>
      ) : (
        <>
          <div className="stat-grid">
            <div className="stat-card">
              <div className="n">{data.recent_total}</div>
              <div className="l">Recent</div>
            </div>
            <div className="stat-card">
              <div className="n">{data.prior_total}</div>
              <div className="l">Prior</div>
            </div>
          </div>
          <p className="muted">{data.headline}</p>

          <div className="muted" style={{ marginTop: 10 }}>Hiring by city — tap to filter Jobs</div>
          <div className="hire-bars">
            {cities.map((c: any) => (
              <button
                type="button"
                className="hire-bar-row clickable"
                key={c.city}
                data-gesture-action={`cities-rank-${c.city}`}
                onClick={() => openCityJobs(c.city)}
              >
                <div className="hire-bar-main">
                  <div className="hire-bar-name">
                    {c.label}
                    <span className="meta">
                      {' '}
                      · {c.delta > 0 ? `+${c.delta}` : c.delta}
                    </span>
                  </div>
                  <div className="bar-track tall">
                    <div
                      className="bar-fill"
                      style={{ width: `${(c.recent / maxN) * 100}%` }}
                    />
                  </div>
                </div>
                <strong className="hire-bar-n">{c.recent}</strong>
              </button>
            ))}
          </div>

          <div className="section-head" style={{ marginTop: 14 }}>
            <span className="muted">Compare two cities</span>
          </div>
          <div className="chip-row wrap">
            <span className="meta" style={{ alignSelf: 'center' }}>A</span>
            {cityOpts.map((o: { id: string; label: string }) => (
              <button
                key={`a-${o.id}`}
                type="button"
                className={`chip ${pickA === o.id ? 'active' : ''}`}
                data-gesture-action={`cities-a-${o.id}`}
                onClick={() => setPickA(o.id)}
              >
                {o.label}
              </button>
            ))}
          </div>
          <div className="chip-row wrap">
            <span className="meta" style={{ alignSelf: 'center' }}>B</span>
            {cityOpts.map((o: { id: string; label: string }) => (
              <button
                key={`b-${o.id}`}
                type="button"
                className={`chip ${pickB === o.id ? 'active' : ''}`}
                data-gesture-action={`cities-b-${o.id}`}
                onClick={() => setPickB(o.id)}
              >
                {o.label}
              </button>
            ))}
          </div>

          {compare?.error ? (
            <div className="empty">{compare.error}</div>
          ) : compare?.a && compare?.b ? (
            <div className="stat-grid" style={{ marginTop: 8 }}>
              {[compare.a, compare.b].map((side: any) => (
                <div className="stat-card" key={side.city} style={{ textAlign: 'left' }}>
                  <div className="l">{side.label}</div>
                  <div className="n">{side.recent}</div>
                  <div className="meta">
                    prior {side.prior} ·{' '}
                    {side.delta > 0 ? `+${side.delta}` : side.delta}
                    {side.delta_pct != null
                      ? ` (${side.delta_pct > 0 ? '+' : ''}${Math.round(side.delta_pct)}%)`
                      : ''}
                  </div>
                  <div className="muted" style={{ marginTop: 6 }}>Top roles</div>
                  {(side.top_roles || []).map((r: any) => (
                    <button
                      key={r.search_id}
                      type="button"
                      className="inline-link"
                      style={{ display: 'block', marginTop: 2 }}
                      data-gesture-action={`cities-role-${side.city}-${r.search_id}`}
                      onClick={() => {
                        setCityFilter(side.city)
                        openRoleHire(r.search_id, r.name, days)
                      }}
                    >
                      {r.name} ({r.n})
                    </button>
                  ))}
                  <div className="muted" style={{ marginTop: 6 }}>Top companies</div>
                  {(side.top_companies || []).map((c: any) => (
                    <button
                      key={c.company_id}
                      type="button"
                      className="inline-link"
                      style={{ display: 'block', marginTop: 2 }}
                      data-gesture-action={`cities-co-${side.city}-${c.company_id}`}
                      onClick={() => {
                        setCityFilter(side.city)
                        openCompanyJobs(c.company_id, c.name, days)
                      }}
                    >
                      {c.name} ({c.n})
                    </button>
                  ))}
                </div>
              ))}
            </div>
          ) : (
            <div className="empty">Pick two different cities</div>
          )}
          {compare?.leader ? (
            <p className="muted" style={{ marginTop: 8 }}>
              {compare.leader} leads by {compare.gap} openings
            </p>
          ) : null}

          <div className="muted" style={{ marginTop: 12 }}>Global city filter</div>
          <CityChips actionPrefix="cities-global" />
        </>
      )}
    </PanelShell>
  )
}
