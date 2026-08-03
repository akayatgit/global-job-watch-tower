import { useEffect, useState } from 'react'
import { CityChips } from '../components/CityChips'
import { ExperienceChips } from '../components/ExperienceChips'
import { GlassCompareChart } from '../components/GlassCompareChart'
import { api, chipLabel, WINDOW_FALLBACK } from '../lib/api'
import { useVigilStore } from '../store/vigilStore'
import { PanelShell } from './PanelShell'

export function RoleHirePanel() {
  const insightFocus = useVigilStore((s) => s.insightFocus)
  const openCompanyJobs = useVigilStore((s) => s.openCompanyJobs)
  const cityFilter = useVigilStore((s) => s.cityFilter)
  const sectorFilter = useVigilStore((s) => s.sectorFilter)
  const experienceFilter = useVigilStore((s) => s.experienceFilter)
  const setCityFilter = useVigilStore((s) => s.setCityFilter)
  const setCityOptions = useVigilStore((s) => s.setCityOptions)
  const setExperienceOptions = useVigilStore((s) => s.setExperienceOptions)
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
      .roleCompanies(
        role.searchId,
        days,
        cityFilter,
        sectorFilter,
        experienceFilter,
      )
      .then((d) => {
        if (!alive) return
        setData(d)
        setError(null)
        if (d?.city_options?.length) setCityOptions(d.city_options)
        if (d?.experience_options?.length) setExperienceOptions(d.experience_options)
      })
      .catch((e: Error) => {
        if (!alive) return
        setData(null)
        setError(e.message || 'Could not load companies')
      })
    return () => {
      alive = false
    }
  }, [
    role?.searchId,
    days,
    cityFilter,
    sectorFilter,
    experienceFilter,
    setCityOptions,
    setExperienceOptions,
  ])

  const companies = data?.companies || []
  const cities = data?.cities || []
  const windows = data?.window_options || WINDOW_FALLBACK

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
          <ExperienceChips actionPrefix="role-hire-experience" />
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
            <GlassCompareChart
              title="Where this role is hiring"
              subtitle="Tap a city to filter companies below"
              actionPrefix="role-city"
              maxItems={8}
              items={cities.slice(0, 8).map((c: any) => ({
                id: String(c.city),
                label: c.label,
                value: c.n,
              }))}
              onSelect={(item) => setCityFilter(item.id)}
            />
          )}
          {error ? (
            <div className="empty fail">{error}</div>
          ) : (
            <GlassCompareChart
              title="Companies hiring"
              subtitle="Sorted max → min — tap for jobs"
              actionPrefix="role-co"
              maxItems={10}
              emptyText="No companies hiring this role in this window"
              items={companies.slice(0, 10).map((c: any) => ({
                id: String(c.company_id),
                label: c.name,
                value: c.recent,
              }))}
              onSelect={(item) =>
                openCompanyJobs(Number(item.id), item.label, days, {
                  searchId: role.searchId,
                  roleName: role.name,
                })
              }
            />
          )}
        </>
      )}
    </PanelShell>
  )
}
