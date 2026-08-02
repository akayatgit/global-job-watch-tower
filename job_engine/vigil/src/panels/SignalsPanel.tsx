import { useEffect, useState } from 'react'
import { CityChips } from '../components/CityChips'
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

          <section className="insight-block insight-grow">
            <header className="insight-block-head">
              <span className="insight-mark" aria-hidden />
              <div>
                <h4>Growing roles</h4>
                <p>Open companies hiring for these rises</p>
              </div>
              <span className="insight-count">{growing.length}</span>
            </header>
            {growing.length === 0 ? (
              <div className="empty soft">No growing roles in this window</div>
            ) : (
              growing.map((r: any) => (
                <button
                  type="button"
                  className="list-row clickable insight-row"
                  key={r.search_id}
                  data-gesture-action={`sig-role-${r.search_id}`}
                  onClick={() => openRoleHire(r.search_id, r.name, days)}
                >
                  <div>
                    {r.name}
                    <div className="meta">{r.recent} recent</div>
                  </div>
                  <span className="delta-pill up">+{r.delta}</span>
                </button>
              ))
            )}
          </section>

          <section className="insight-block insight-fast">
            <header className="insight-block-head">
              <span className="insight-mark" aria-hidden />
              <div>
                <h4>Fastest companies</h4>
                <p>Open jobs at the hottest hirers</p>
              </div>
              <span className="insight-count">{fastest.length}</span>
            </header>
            {fastest.length === 0 ? (
              <div className="empty soft">No company pace yet in this window</div>
            ) : (
              fastest.map((c: any) => (
                <button
                  type="button"
                  className="list-row clickable insight-row"
                  key={c.company_id}
                  data-gesture-action={`sig-co-${c.company_id}`}
                  onClick={() => openCompanyJobs(c.company_id, c.name, days)}
                >
                  <div>
                    {c.name}
                    <div className="meta">{c.recent} recent</div>
                  </div>
                  <span className="delta-pill up">+{c.delta}</span>
                </button>
              ))
            )}
          </section>
        </>
      )}
    </PanelShell>
  )
}
