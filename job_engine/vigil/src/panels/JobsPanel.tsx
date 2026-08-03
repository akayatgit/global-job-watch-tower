import { useEffect, useMemo, useState } from 'react'
import { CityChips } from '../components/CityChips'
import { ExperienceChips } from '../components/ExperienceChips'
import { SectorChips } from '../components/SectorChips'
import { api, relTime } from '../lib/api'
import { useVigilStore } from '../store/vigilStore'
import { PanelShell } from './PanelShell'

function experienceLabel(band: string | null | undefined): string | null {
  if (!band) return null
  if (band === 'Fresher' || band === '0-1 years') return 'Fresher'
  if (band === '1-2 years' || band === '1-3 years') return '1–2'
  if (band === '3-5 years') return '3–5'
  if (band === '6-8 years' || band === '5-8 years') return '6–8'
  if (band === '9-12 years' || band === '8-12 years') return '9–12'
  if (band === '13+ years' || band === '12+ years') return '13+'
  return band.replace(/\s*years?$/i, '')
}

export function JobsPanel() {
  const [jobs, setJobs] = useState<any[]>([])
  const [error, setError] = useState<string | null>(null)
  const [remoteOnly, setRemoteOnly] = useState(false)
  const insightFocus = useVigilStore((s) => s.insightFocus)
  const clearInsightFocus = useVigilStore((s) => s.clearInsightFocus)
  const sectorFilter = useVigilStore((s) => s.sectorFilter)
  const cityFilter = useVigilStore((s) => s.cityFilter)
  const experienceFilter = useVigilStore((s) => s.experienceFilter)

  useEffect(() => {
    let alive = true
    const load = () => {
      const q: Parameters<typeof api.jobs>[0] = { limit: 120 }
      if (sectorFilter) q.sector = sectorFilter
      if (cityFilter) q.city = cityFilter
      if (experienceFilter) q.experience = experienceFilter
      if (insightFocus?.kind === 'company') {
        q.company_id = insightFocus.companyId
        if (insightFocus.searchId) q.search_config_id = insightFocus.searchId
      }
      if (insightFocus?.kind === 'role') q.search_config_id = insightFocus.searchId
      api
        .jobs(q)
        .then((d) => {
          if (!alive) return
          setJobs(Array.isArray(d) ? d : [])
          setError(null)
        })
        .catch((e: Error) => {
          if (!alive) return
          setJobs([])
          setError(e.message || 'Could not load jobs')
        })
    }
    load()
    const id = window.setInterval(load, 10000)
    return () => {
      alive = false
      clearInterval(id)
    }
  }, [insightFocus, sectorFilter, cityFilter, experienceFilter])

  const roleScoped =
    insightFocus?.kind === 'company' && Boolean(insightFocus.searchId)

  const filtered = useMemo(() => {
    if (!remoteOnly) return jobs
    return jobs.filter((j) => {
      const blob = `${j.title || ''} ${j.location || ''} ${j.company || ''}`.toLowerCase()
      return blob.includes('remote') || j.city_key === 'remote'
    })
  }, [jobs, remoteOnly])

  const focusLabel =
    insightFocus?.kind === 'company'
      ? insightFocus.roleName
        ? `${insightFocus.roleName} @ ${insightFocus.name}`
        : `At ${insightFocus.name}`
      : insightFocus?.kind === 'role'
        ? `Role: ${insightFocus.name}`
        : null

  return (
    <PanelShell id="jobs">
      <SectorChips actionPrefix="jobs-sector" />
      <CityChips actionPrefix="jobs-city" />
      <ExperienceChips actionPrefix="jobs-experience" />
      <div className="chip-row">
        <button
          type="button"
          className={`chip ${remoteOnly ? 'active' : ''}`}
          data-gesture-action="jobs-remote"
          onClick={() => setRemoteOnly((v) => !v)}
        >
          Remote
        </button>
        {focusLabel && (
          <button
            type="button"
            className="chip active"
            data-gesture-action="jobs-clear-focus"
            onClick={() => clearInsightFocus()}
            title="Clear filter"
          >
            {focusLabel} ×
          </button>
        )}
      </div>
      <div className="muted" style={{ marginBottom: 8 }}>
        {filtered.length} shown · {jobs.length} loaded
        {roleScoped ? ' · role + company' : ''}
      </div>
      {error ? (
        <div className="empty fail">Jobs failed to load — {error}</div>
      ) : filtered.length === 0 ? (
        <div className="empty">No jobs match — widen sector, city, or experience</div>
      ) : (
        filtered.slice(0, 60).map((j) => {
          const exp = experienceLabel(j.experience_band)
          const when = j.posted_date
            ? relTime(j.posted_date)
            : relTime(j.scraped_at)
          const whenTitle = j.posted_date || j.scraped_at
          return (
            <a
              className="list-row clickable"
              key={j.id}
              href={j.job_url || '#'}
              target="_blank"
              rel="noreferrer"
              data-gesture-action={`job-open-${j.id}`}
            >
              <div>
                <div>{j.title}</div>
                <div className="meta">
                  {j.company || '—'} · {j.location || '—'}
                  {exp ? ` · ${exp}` : ''}
                </div>
              </div>
              <div className="meta" title={whenTitle}>{when}</div>
            </a>
          )
        })
      )}
    </PanelShell>
  )
}
