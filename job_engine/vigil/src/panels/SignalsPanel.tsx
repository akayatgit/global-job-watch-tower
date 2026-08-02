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
  const windows = data?.window_options || FALLBACK_WINDOWS

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
          <div className="stat-grid">
            <div className="stat-card"><div className="n">{s.recent_total}</div><div className="l">Recent</div></div>
            <div className="stat-card"><div className="n">{s.prior_total}</div><div className="l">Prior</div></div>
          </div>
          <p className="muted">{s.headline}</p>
          <div className="muted" style={{ marginTop: 8 }}>Growing roles — open companies</div>
          {(s.growing_roles || []).slice(0, 8).map((r: any) => (
            <button
              type="button"
              className="list-row clickable"
              key={r.search_id}
              data-gesture-action={`sig-role-${r.search_id}`}
              onClick={() => openRoleHire(r.search_id, r.name, days)}
            >
              <div>{r.name}<div className="meta">{r.recent} recent</div></div>
              <span className="ok">+{r.delta}</span>
            </button>
          ))}
          <div className="muted" style={{ marginTop: 8 }}>Fastest companies — open jobs</div>
          {(s.fastest_companies || []).slice(0, 8).map((c: any) => (
            <button
              type="button"
              className="list-row clickable"
              key={c.company_id}
              data-gesture-action={`sig-co-${c.company_id}`}
              onClick={() => openCompanyJobs(c.company_id, c.name, days)}
            >
              <div>{c.name}<div className="meta">{c.recent} recent</div></div>
              <span className="ok">+{c.delta}</span>
            </button>
          ))}
        </>
      )}
    </PanelShell>
  )
}
