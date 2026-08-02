import { useEffect, useState } from 'react'
import { CityChips } from '../components/CityChips'
import { api, chipLabel } from '../lib/api'
import { useVigilStore } from '../store/vigilStore'
import { PanelShell } from './PanelShell'

export function RoleHirePanel() {
  const insightFocus = useVigilStore((s) => s.insightFocus)
  const openCompanyJobs = useVigilStore((s) => s.openCompanyJobs)
  const cityFilter = useVigilStore((s) => s.cityFilter)
  const sectorFilter = useVigilStore((s) => s.sectorFilter)
  const setCityFilter = useVigilStore((s) => s.setCityFilter)
  const setCityOptions = useVigilStore((s) => s.setCityOptions)
  const role =
    insightFocus?.kind === 'role'
      ? insightFocus
      : null
  const [days, setDays] = useState(role?.days ?? 7)
  const [data, setData] = useState<any>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (role?.days != null) setDays(role.days)
  }, [role?.searchId, role?.days])

  useEffect(() => {
    if (!role) {
      setData(null)
      return
    }
    let alive = true
    api
      .roleCompanies(role.searchId, days, cityFilter, sectorFilter)
      .then((d) => {
        if (!alive) return
        setData(d)
        setError(null)
        if (d?.city_options?.length) setCityOptions(d.city_options)
      })
      .catch((e: Error) => {
        if (!alive) return
        setData(null)
        setError(e.message || 'Could not load companies')
      })
    return () => {
      alive = false
    }
  }, [role?.searchId, days, cityFilter, sectorFilter, setCityOptions])

  const companies = data?.companies || []
  const cities = data?.cities || []
  const maxN = data?.max || Math.max(...companies.map((c: any) => c.recent), 1)
  const maxCity = data?.max_city || Math.max(...cities.map((c: any) => c.n), 1)
  const windows = data?.window_options || [
    { days: 0, label: 'Last 24 hours' },
    { days: 1, label: 'Today' },
    { days: 2, label: 'Last 2 days' },
    { days: 4, label: 'Last 4 days' },
    { days: 7, label: 'Last 7 days' },
    { days: 14, label: 'Last 14 days' },
    { days: 30, label: 'Last 30 days' },
  ]

  return (
    <PanelShell id="role_hire">
      {!role ? (
        <div className="empty">Pick a role from Tower or Hiring Signals</div>
      ) : (
        <>
          <div className="role-hire-hero">
            <div className="muted">Companies hiring</div>
            <h3>{role.name}</h3>
            <div className="muted">{companies.length} companies · sorted max → min</div>
          </div>
          <CityChips actionPrefix="role-hire-city" />
          <div className="chip-row wrap">
            {windows.map((w: { days: number; label: string }) => (
              <button
                key={w.days}
                type="button"
                className={`chip ${days === w.days ? 'active' : ''}`}
                data-gesture-action={`role-hire-${w.days}`}
                onClick={() => setDays(w.days)}
              >
                {chipLabel(w.days, w.label)}
              </button>
            ))}
          </div>
          {cities.length > 0 && (
            <>
              <div className="muted" style={{ marginTop: 8 }}>Where this role is hiring</div>
              <div className="hire-bars">
                {cities.slice(0, 8).map((c: any) => (
                  <button
                    type="button"
                    className="hire-bar-row clickable"
                    key={c.city}
                    data-gesture-action={`role-city-${c.city}`}
                    onClick={() => setCityFilter(c.city)}
                  >
                    <div className="hire-bar-main">
                      <div className="hire-bar-name">{c.label}</div>
                      <div className="bar-track tall">
                        <div
                          className="bar-fill"
                          style={{ width: `${(c.n / maxCity) * 100}%` }}
                        />
                      </div>
                    </div>
                    <strong className="hire-bar-n">{c.n}</strong>
                  </button>
                ))}
              </div>
            </>
          )}
          {error ? (
            <div className="empty fail">{error}</div>
          ) : companies.length === 0 ? (
            <div className="empty">No companies hiring this role in this window</div>
          ) : (
            <div className="hire-bars">
              {companies.map((c: any) => (
                <button
                  type="button"
                  className="hire-bar-row clickable"
                  key={c.company_id}
                  data-gesture-action={`role-co-${c.company_id}`}
                  onClick={() =>
                    openCompanyJobs(c.company_id, c.name, days, {
                      searchId: role.searchId,
                      roleName: role.name,
                    })
                  }
                >
                  <div className="hire-bar-main">
                    <div className="hire-bar-name">{c.name}</div>
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
          )}
        </>
      )}
    </PanelShell>
  )
}
