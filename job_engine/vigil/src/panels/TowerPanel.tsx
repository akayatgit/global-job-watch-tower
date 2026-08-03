import { useEffect, useState } from 'react'
import { CityChips } from '../components/CityChips'
import { ExperienceChips } from '../components/ExperienceChips'
import { GlassCompareChart } from '../components/GlassCompareChart'
import { SectorChips } from '../components/SectorChips'
import { api, relTime } from '../lib/api'
import { useVigilStore } from '../store/vigilStore'
import { PanelShell } from './PanelShell'

export function TowerPanel() {
  const [data, setData] = useState<any>(null)
  const sectorFilter = useVigilStore((s) => s.sectorFilter)
  const cityFilter = useVigilStore((s) => s.cityFilter)
  const experienceFilter = useVigilStore((s) => s.experienceFilter)
  const setSectorOptions = useVigilStore((s) => s.setSectorOptions)
  const setCityOptions = useVigilStore((s) => s.setCityOptions)
  const setExperienceOptions = useVigilStore((s) => s.setExperienceOptions)
  const openRoleHire = useVigilStore((s) => s.openRoleHire)
  const openCompanyJobs = useVigilStore((s) => s.openCompanyJobs)
  const openRankList = useVigilStore((s) => s.openRankList)
  const openPanel = useVigilStore((s) => s.openPanel)
  const setCityFilter = useVigilStore((s) => s.setCityFilter)

  useEffect(() => {
    let alive = true
    const load = () =>
      api
        .tower(sectorFilter, cityFilter, experienceFilter)
        .then((d) => {
          if (!alive) return
          setData(d)
          if (d?.sector_options?.length) setSectorOptions(d.sector_options)
          if (d?.city_options?.length) setCityOptions(d.city_options)
          if (d?.experience_options?.length) setExperienceOptions(d.experience_options)
        })
        .catch(() => {})
    load()
    const id = window.setInterval(load, 8000)
    return () => {
      alive = false
      clearInterval(id)
    }
  }, [
    sectorFilter,
    cityFilter,
    experienceFilter,
    setSectorOptions,
    setCityOptions,
    setExperienceOptions,
  ])

  const stats = data?.stats
  const top = data?.top_companies || []
  const roles = (data?.per_role || []).slice(0, 8)
  const topCities = data?.top_cities || []
  const latest = data?.latest_jobs || []
  const moreRoles = (data?.per_role || []).length > 8

  return (
    <PanelShell id="tower">
      <SectorChips actionPrefix="tower-sector" />
      <CityChips actionPrefix="tower-city" />
      <ExperienceChips actionPrefix="tower-experience" />
      {!data ? (
        <div className="empty">Syncing tower insights…</div>
      ) : (
        <>
          <div className="signal-hero">
            <div className="stat-grid">
              <div className="stat-card signal-stat">
                <div className="n">{stats.total_jobs}</div>
                <div className="l">Jobs</div>
              </div>
              <div className="stat-card">
                <div className="n">{stats.jobs_today}</div>
                <div className="l">Today</div>
              </div>
              <div className="stat-card">
                <div className="n">{stats.companies}</div>
                <div className="l">Companies</div>
              </div>
              <div className="stat-card">
                <div className="n">{stats.runs_active}</div>
                <div className="l">Active</div>
              </div>
            </div>
          </div>

          {topCities.length > 0 && (
            <GlassCompareChart
              title="Top cities for hiring"
              subtitle="Last 7 days — tap to filter Jobs"
              actionPrefix="tower-city-bar"
              maxItems={6}
              items={topCities.slice(0, 6).map((c: any) => ({
                id: String(c.city),
                label: c.label,
                value: c.recent,
                meta: c.delta > 0 ? `+${c.delta}` : c.delta < 0 ? String(c.delta) : undefined,
              }))}
              onSelect={(item) => {
                setCityFilter(item.id)
                openPanel('jobs')
              }}
              action={
                <button
                  type="button"
                  className="show-all"
                  data-gesture-action="tower-show-cities"
                  onClick={() => openPanel('cities')}
                >
                  City signals
                </button>
              }
            />
          )}

          <GlassCompareChart
            title="Top companies hiring"
            subtitle="Last 7 days — tap a company for jobs"
            actionPrefix="tower-co"
            maxItems={8}
            items={top.map((c: any) => ({
              id: String(c.company_id || c.name),
              label: c.name,
              value: c.n,
            }))}
            onSelect={(item) => {
              const id = Number(item.id)
              if (!Number.isNaN(id)) openCompanyJobs(id, item.label, 7)
            }}
            action={
              <button
                type="button"
                className="show-all"
                data-gesture-action="tower-show-companies"
                onClick={() => openRankList('companies', 7)}
              >
                Show all
              </button>
            }
          />

          <GlassCompareChart
            title="Jobs per role"
            subtitle="Fair 7-day window — tap for companies"
            actionPrefix="tower-role"
            maxItems={8}
            items={roles.map((r: any) => ({
              id: String(r.search_id || r.name),
              label: r.name,
              value: r.n,
            }))}
            onSelect={(item) => {
              const id = Number(item.id)
              if (!Number.isNaN(id)) openRoleHire(id, item.label, 7)
            }}
            action={
              moreRoles || roles.length > 0 ? (
                <button
                  type="button"
                  className="show-all"
                  data-gesture-action="tower-show-roles"
                  onClick={() => openRankList('roles')}
                >
                  Show all
                </button>
              ) : null
            }
          />

          <section className="insight-block insight-fresh">
            <header className="insight-block-head">
              <span className="insight-mark" aria-hidden />
              <div>
                <h4>Freshest catches</h4>
                <p>Newest openings — tap to open</p>
              </div>
            </header>
            {latest.map((j: any) => (
              <div className="list-row" key={j.id}>
                <div>
                  <button
                    type="button"
                    className="inline-link title-link"
                    data-gesture-action={`tower-job-${j.id}`}
                    onClick={() => {
                      if (j.job_url) {
                        window.open(j.job_url, '_blank', 'noopener,noreferrer')
                        return
                      }
                      if (j.company_id) {
                        openCompanyJobs(j.company_id, j.company || 'Company', 7)
                      }
                    }}
                    title={j.job_url ? 'Open job posting' : 'Open company jobs'}
                  >
                    {j.title}
                  </button>
                  <div className="meta">
                    {j.company_id ? (
                      <button
                        type="button"
                        className="inline-link"
                        data-gesture-action={`tower-job-co-${j.company_id}`}
                        onClick={() =>
                          openCompanyJobs(j.company_id, j.company || 'Company', 7)
                        }
                      >
                        {j.company || 'Company'}
                      </button>
                    ) : (
                      j.company || '—'
                    )}
                    {' · '}
                    {j.location || '—'}
                    {j.experience_band
                      ? ` · ${String(j.experience_band).replace(/\s*years?$/i, '').replace(/^0-1$/, 'Fresher')}`
                      : ''}
                  </div>
                </div>
                <div className="meta" title={j.posted_date || j.scraped_at}>
                  {relTime(j.posted_date || j.scraped_at)}
                </div>
              </div>
            ))}
          </section>
        </>
      )}
    </PanelShell>
  )
}
