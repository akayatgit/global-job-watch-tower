import { useEffect, useMemo, useState } from 'react'
import { api, relTime } from '../lib/api'
import { PanelShell } from './PanelShell'

export function JobsPanel() {
  const [jobs, setJobs] = useState<any[]>([])
  const [filter, setFilter] = useState<'all' | 'remote' | 'tech'>('all')

  useEffect(() => {
    let alive = true
    const load = () => api.jobs(100).then((d) => alive && setJobs(d)).catch(() => {})
    load()
    const id = window.setInterval(load, 10000)
    return () => {
      alive = false
      clearInterval(id)
    }
  }, [])

  const filtered = useMemo(() => {
    return jobs.filter((j) => {
      const blob = `${j.title || ''} ${j.location || ''} ${j.company || ''}`.toLowerCase()
      if (filter === 'remote') return blob.includes('remote')
      if (filter === 'tech') {
        return /engineer|developer|software|data|ai|ml|cloud|devops|sre/.test(blob)
      }
      return true
    })
  }, [jobs, filter])

  return (
    <PanelShell id="jobs">
      <div className="chip-row">
        {([
          ['all', 'All roles'],
          ['tech', 'Tech Jobs'],
          ['remote', 'Remote Trends'],
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
      </div>
      <div className="muted" style={{ marginBottom: 8 }}>
        {filtered.length} shown · {jobs.length} loaded
      </div>
      {filtered.length === 0 ? (
        <div className="empty">No jobs match — widen the chip filter</div>
      ) : (
        filtered.slice(0, 40).map((j) => (
          <div className="list-row" key={j.id}>
            <div>
              <div>{j.title}</div>
              <div className="meta">{j.company || '—'} · {j.location || '—'}</div>
            </div>
            <div className="meta" title={j.scraped_at}>{relTime(j.scraped_at)}</div>
          </div>
        ))
      )}
    </PanelShell>
  )
}
