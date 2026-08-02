import { useEffect, useMemo, useState } from 'react'
import { api, relTime } from '../lib/api'
import { useVigilStore } from '../store/vigilStore'
import { PanelShell } from './PanelShell'

export function JobsPanel() {
  const [jobs, setJobs] = useState<any[]>([])
  const [error, setError] = useState<string | null>(null)
  const [filter, setFilter] = useState<'all' | 'remote' | 'tech'>('all')
  const insightFocus = useVigilStore((s) => s.insightFocus)
  const clearInsightFocus = useVigilStore((s) => s.clearInsightFocus)

  // Role-scoped company drills must not keep a leftover Tech chip
  useEffect(() => {
    if (insightFocus?.kind === 'company' && insightFocus.searchId) {
      setFilter('all')
    }
  }, [insightFocus])

  useEffect(() => {
    let alive = true
    const load = () => {
      const q: Parameters<typeof api.jobs>[0] = { limit: 120 }
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
  }, [insightFocus])

  const roleScoped =
    insightFocus?.kind === 'company' && Boolean(insightFocus.searchId)

  const filtered = useMemo(() => {
    return jobs.filter((j) => {
      const blob = `${j.title || ''} ${j.location || ''} ${j.company || ''}`.toLowerCase()
      if (filter === 'remote') return blob.includes('remote')
      // Skip Tech chip when already scoped to a non-tech role drill
      if (filter === 'tech' && !roleScoped) {
        return /engineer|developer|software|data|ai|ml|cloud|devops|sre/.test(blob)
      }
      if (filter === 'tech' && roleScoped) return true
      return true
    })
  }, [jobs, filter, roleScoped])

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
      <div className="chip-row">
        {([
          ['all', 'All'],
          ['tech', 'Tech'],
          ['remote', 'Remote'],
        ] as const).map(([k, label]) => (
          <button
            key={k}
            type="button"
            className={`chip ${filter === k ? 'active' : ''}`}
            data-gesture-action={`jobs-${k}`}
            onClick={() => setFilter(k)}
          >
            {label}
          </button>
        ))}
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
        <div className="empty">No jobs match — widen the chip filter</div>
      ) : (
        filtered.slice(0, 60).map((j) => (
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
              <div className="meta">{j.company || '—'} · {j.location || '—'}</div>
            </div>
            <div className="meta" title={j.scraped_at}>{relTime(j.scraped_at)}</div>
          </a>
        ))
      )}
    </PanelShell>
  )
}
