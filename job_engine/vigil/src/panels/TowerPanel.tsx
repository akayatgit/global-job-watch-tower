import { useEffect, useState } from 'react'
import { api, relTime } from '../lib/api'
import { PanelShell } from './PanelShell'

export function TowerPanel() {
  const [data, setData] = useState<any>(null)

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
          <div className="muted" style={{ marginBottom: 6 }}>Top hiring (7d)</div>
          {top.map((c: any) => (
            <div className="bar-row" key={c.name}>
              <div>
                <div>{c.name}</div>
                <div className="bar-track"><div className="bar-fill" style={{ width: `${(c.n / maxC) * 100}%` }} /></div>
              </div>
              <strong>{c.n}</strong>
            </div>
          ))}
          <div className="muted" style={{ margin: '10px 0 6px' }}>Jobs per role</div>
          {roles.map((r: any) => (
            <div className="bar-row" key={r.name}>
              <div>
                <div>{r.name}</div>
                <div className="bar-track"><div className="bar-fill" style={{ width: `${(r.n / maxR) * 100}%` }} /></div>
              </div>
              <strong>{r.n}</strong>
            </div>
          ))}
          <div className="muted" style={{ margin: '10px 0 6px' }}>Freshest catches</div>
          {latest.map((j: any) => (
            <div className="list-row" key={j.id}>
              <div>
                <div>{j.title}</div>
                <div className="meta">{j.company || '—'} · {j.location || '—'}</div>
              </div>
              <div className="meta" title={j.scraped_at}>{relTime(j.scraped_at)}</div>
            </div>
          ))}
        </>
      )}
    </PanelShell>
  )
}
