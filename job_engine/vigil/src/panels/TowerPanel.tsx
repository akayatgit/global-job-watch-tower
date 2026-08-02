import { useEffect, useState } from 'react'
import { api, relTime } from '../lib/api'
import { useVigilStore } from '../store/vigilStore'
import { PanelShell } from './PanelShell'

export function TowerPanel() {
  const [data, setData] = useState<any>(null)
  const openRoleHire = useVigilStore((s) => s.openRoleHire)
  const openCompanyJobs = useVigilStore((s) => s.openCompanyJobs)
  const openRankList = useVigilStore((s) => s.openRankList)

  useEffect(() => {
    let alive = true
    const load = () => api.tower().then((d) => alive && setData(d)).catch(() => {})
    load()
    const id = window.setInterval(load, 8000)
    return () => {
      alive = false
      clearInterval(id)
    }
  }, [])

  const stats = data?.stats
  const top = data?.top_companies || []
  const maxC = Math.max(...top.map((c: any) => c.n), 1)
  const roles = (data?.per_role || []).slice(0, 8)
  const maxR = Math.max(...roles.map((r: any) => r.n), 1)
  const latest = data?.latest_jobs || []
  const moreRoles = (data?.per_role || []).length > 8

  return (
    <PanelShell id="tower">
      {!data ? (
        <div className="empty">Syncing tower insights…</div>
      ) : (
        <>
          <div className="stat-grid">
            <div className="stat-card"><div className="n">{stats.total_jobs}</div><div className="l">Jobs</div></div>
            <div className="stat-card"><div className="n">{stats.jobs_today}</div><div className="l">Today</div></div>
            <div className="stat-card"><div className="n">{stats.companies}</div><div className="l">Companies</div></div>
            <div className="stat-card"><div className="n">{stats.runs_active}</div><div className="l">Active</div></div>
          </div>

          <div className="section-head">
            <span className="muted">Top hiring (7d)</span>
            <button
              type="button"
              className="show-all"
              data-gesture-action="tower-show-companies"
              onClick={() => openRankList('companies', 7)}
            >
              Show all
            </button>
          </div>
          {top.map((c: any) => (
            <button
              type="button"
              className="bar-row clickable"
              key={c.company_id || c.name}
              data-gesture-action={`tower-co-${c.company_id || c.name}`}
              onClick={() => {
                if (c.company_id) openCompanyJobs(c.company_id, c.name, 7)
              }}
            >
              <div>
                <div>{c.name}</div>
                <div className="bar-track"><div className="bar-fill" style={{ width: `${(c.n / maxC) * 100}%` }} /></div>
              </div>
              <strong>{c.n}</strong>
            </button>
          ))}

          <div className="section-head">
            <span className="muted">Jobs per role (7d fair window) — click for companies</span>
            {(moreRoles || roles.length > 0) && (
              <button
                type="button"
                className="show-all"
                data-gesture-action="tower-show-roles"
                onClick={() => openRankList('roles')}
              >
                Show all
              </button>
            )}
          </div>
          {roles.map((r: any) => (
            <button
              type="button"
              className="bar-row clickable"
              key={r.search_id || r.name}
              data-gesture-action={`tower-role-${r.search_id || r.name}`}
              onClick={() => {
                if (r.search_id) openRoleHire(r.search_id, r.name, 7)
              }}
            >
              <div>
                <div>{r.name}</div>
                <div className="bar-track"><div className="bar-fill" style={{ width: `${(r.n / maxR) * 100}%` }} /></div>
              </div>
              <strong>{r.n}</strong>
            </button>
          ))}

          <div className="section-head">
            <span className="muted">Freshest catches — click to open</span>
          </div>
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
                  {' · '}{j.location || '—'}
                </div>
              </div>
              <div className="meta" title={j.scraped_at}>{relTime(j.scraped_at)}</div>
            </div>
          ))}
        </>
      )}
    </PanelShell>
  )
}
