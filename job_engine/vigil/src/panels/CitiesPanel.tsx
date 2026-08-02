import { useEffect, useState } from 'react'
import { CityChips } from '../components/CityChips'
import { GlassCompareChart } from '../components/GlassCompareChart'
import { SectorChips } from '../components/SectorChips'
import { api, chipLabel, WINDOW_FALLBACK } from '../lib/api'
import { useVigilStore } from '../store/vigilStore'
import { PanelShell } from './PanelShell'

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

  const windows = data?.window_options || WINDOW_FALLBACK
  const cities = data?.cities || []

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
          <div className="signal-hero">
            <div className="stat-grid">
              <div className="stat-card signal-stat">
                <div className="n">{data.recent_total}</div>
                <div className="l">Recent</div>
              </div>
              <div className="stat-card">
                <div className="n">{data.prior_total}</div>
                <div className="l">Prior</div>
              </div>
            </div>
            <p className="signal-headline">{data.headline}</p>
          </div>

          <GlassCompareChart
            title="Hiring by city"
            subtitle="Tap a city to filter Jobs"
            actionPrefix="cities-rank"
            maxItems={8}
            items={cities.slice(0, 8).map((c: any) => ({
              id: String(c.city),
              label: c.label,
              value: c.recent,
              meta: c.delta > 0 ? `+${c.delta}` : c.delta < 0 ? String(c.delta) : undefined,
            }))}
            onSelect={(item) => {
              setCityFilter(item.id)
              openPanel('jobs')
            }}
          />

          <section className="glass-compare-shell">
            <header className="glass-chart-head">
              <div className="glass-chart-titles">
                <h4 className="glass-chart-title">Compare two cities</h4>
                <div className="glass-chart-rule" aria-hidden />
                <p className="glass-chart-sub">
                  Pick A and B — favourites first, Show more for the rest
                </p>
              </div>
            </header>
            <CityChips
              lead="A"
              hideAll
              actionPrefix="cities-a"
              selected={pickA}
              onSelect={setPickA}
            />
            <CityChips
              lead="B"
              hideAll
              actionPrefix="cities-b"
              selected={pickB}
              onSelect={setPickB}
            />
            {compare?.error ? (
              <div className="empty soft">{compare.error}</div>
            ) : compare?.a && compare?.b ? (
              <>
                <GlassCompareChart
                  title="Head to head"
                  subtitle={
                    compare.leader
                      ? `${compare.leader} leads by ${compare.gap} openings`
                      : 'Same pace in this window'
                  }
                  actionPrefix="cities-h2h"
                  maxItems={2}
                  items={[
                    {
                      id: compare.a.city,
                      label: compare.a.label,
                      value: compare.a.recent,
                      meta:
                        compare.a.delta > 0
                          ? `+${compare.a.delta}`
                          : String(compare.a.delta ?? 0),
                    },
                    {
                      id: compare.b.city,
                      label: compare.b.label,
                      value: compare.b.recent,
                      meta:
                        compare.b.delta > 0
                          ? `+${compare.b.delta}`
                          : String(compare.b.delta ?? 0),
                    },
                  ]}
                  onSelect={(item) => {
                    setCityFilter(item.id)
                    openPanel('jobs')
                  }}
                />
                <div className="glass-compare-duo">
                  <GlassCompareChart
                    title={`Top roles · ${compare.a.label}`}
                    subtitle="Tap to open companies"
                    actionPrefix={`cities-role-${compare.a.city}`}
                    maxItems={5}
                    items={(compare.a.top_roles || []).map((r: any) => ({
                      id: String(r.search_id),
                      label: r.name,
                      value: r.n,
                    }))}
                    onSelect={(item) => {
                      setCityFilter(compare.a.city)
                      openRoleHire(Number(item.id), item.label, days)
                    }}
                  />
                  <GlassCompareChart
                    title={`Top roles · ${compare.b.label}`}
                    subtitle="Tap to open companies"
                    actionPrefix={`cities-role-${compare.b.city}`}
                    maxItems={5}
                    items={(compare.b.top_roles || []).map((r: any) => ({
                      id: String(r.search_id),
                      label: r.name,
                      value: r.n,
                    }))}
                    onSelect={(item) => {
                      setCityFilter(compare.b.city)
                      openRoleHire(Number(item.id), item.label, days)
                    }}
                  />
                </div>
                <div className="glass-compare-duo">
                  <GlassCompareChart
                    title={`Top companies · ${compare.a.label}`}
                    subtitle="Tap for jobs"
                    actionPrefix={`cities-co-${compare.a.city}`}
                    maxItems={5}
                    items={(compare.a.top_companies || []).map((c: any) => ({
                      id: String(c.company_id),
                      label: c.name,
                      value: c.n,
                    }))}
                    onSelect={(item) => {
                      setCityFilter(compare.a.city)
                      openCompanyJobs(Number(item.id), item.label, days)
                    }}
                  />
                  <GlassCompareChart
                    title={`Top companies · ${compare.b.label}`}
                    subtitle="Tap for jobs"
                    actionPrefix={`cities-co-${compare.b.city}`}
                    maxItems={5}
                    items={(compare.b.top_companies || []).map((c: any) => ({
                      id: String(c.company_id),
                      label: c.name,
                      value: c.n,
                    }))}
                    onSelect={(item) => {
                      setCityFilter(compare.b.city)
                      openCompanyJobs(Number(item.id), item.label, days)
                    }}
                  />
                </div>
              </>
            ) : (
              <div className="empty soft">Pick two different cities</div>
            )}
          </section>
        </>
      )}
    </PanelShell>
  )
}
