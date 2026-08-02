import { useEffect, useState } from 'react'
import { CityChips } from '../components/CityChips'
import { GlassCompareChart } from '../components/GlassCompareChart'
import { SectorChips } from '../components/SectorChips'
import { api, chipLabel, WINDOW_FALLBACK } from '../lib/api'
import { useVigilStore } from '../store/vigilStore'
import { PanelShell } from './PanelShell'

export function SignalsPanel() {
  const [days, setDays] = useState(7)
  const [data, setData] = useState<any>(null)
  const sectorFilter = useVigilStore((s) => s.sectorFilter)
  const cityFilter = useVigilStore((s) => s.cityFilter)
  const setSectorOptions = useVigilStore((s) => s.setSectorOptions)
  const setCityOptions = useVigilStore((s) => s.setCityOptions)
  const openRoleHire = useVigilStore((s) => s.openRoleHire)
  const openCompanyJobs = useVigilStore((s) => s.openCompanyJobs)

  useEffect(() => {
    let alive = true
    api
      .signals(days, sectorFilter, cityFilter)
      .then((d) => {
        if (!alive) return
        setData(d)
        if (d?.sector_options?.length) setSectorOptions(d.sector_options)
        if (d?.city_options?.length) setCityOptions(d.city_options)
      })
      .catch(() => {})
    return () => {
      alive = false
    }
  }, [days, sectorFilter, cityFilter, setSectorOptions, setCityOptions])

  const s = data?.signals
  const windows = data?.window_options || WINDOW_FALLBACK
  const growing = (s?.growing_roles || []).slice(0, 8)
  const fastest = (s?.fastest_companies || []).slice(0, 8)

  return (
    <PanelShell id="signals">
      <SectorChips actionPrefix="signals-sector" />
      <CityChips actionPrefix="signals-city" />
      <div className="chip-row wrap">
        {windows.map((w: { days: number; label: string }) => (
          <button
            key={w.days}
            type="button"
            className={`chip ${days === w.days ? 'active' : ''}`}
            data-gesture-action={`signals-${w.days}`}
            onClick={() => setDays(w.days)}
          >
            {chipLabel(w.days, w.label)}
          </button>
        ))}
      </div>
      {!s ? (
        <div className="empty">Reading hiring signals…</div>
      ) : (
        <>
          <div className="signal-hero">
            <div className="stat-grid">
              <div className="stat-card signal-stat">
                <div className="n">{s.recent_total}</div>
                <div className="l">Recent</div>
              </div>
              <div className="stat-card">
                <div className="n">{s.prior_total}</div>
                <div className="l">Prior</div>
              </div>
            </div>
            <p className="signal-headline">{s.headline}</p>
          </div>

          <GlassCompareChart
            title="Growing roles"
            subtitle="Open companies hiring for these rises"
            actionPrefix="sig-role"
            maxItems={8}
            emptyText="No growing roles in this window"
            items={growing.map((r: any) => ({
              id: String(r.search_id),
              label: r.name,
              value: r.recent,
              meta: r.delta > 0 ? `+${r.delta}` : String(r.delta),
            }))}
            onSelect={(item) => openRoleHire(Number(item.id), item.label, days)}
          />

          <GlassCompareChart
            title="Fastest companies"
            subtitle="Open jobs at the hottest hirers"
            actionPrefix="sig-co"
            maxItems={8}
            emptyText="No company pace yet in this window"
            items={fastest.map((c: any) => ({
              id: String(c.company_id),
              label: c.name,
              value: c.recent,
              meta: c.delta > 0 ? `+${c.delta}` : String(c.delta),
            }))}
            onSelect={(item) =>
              openCompanyJobs(Number(item.id), item.label, days)
            }
          />
        </>
      )}
    </PanelShell>
  )
}
