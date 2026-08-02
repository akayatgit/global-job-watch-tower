import { useEffect, useState } from 'react'
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

export function RankListPanel() {
  const rankFocus = useVigilStore((s) => s.rankFocus)
  const openCompanyJobs = useVigilStore((s) => s.openCompanyJobs)
  const openRoleHire = useVigilStore((s) => s.openRoleHire)
  const [days, setDays] = useState(7)
  const [data, setData] = useState<any>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (rankFocus?.kind === 'companies') setDays(rankFocus.days)
  }, [rankFocus])

  useEffect(() => {
    if (!rankFocus) {
      setData(null)
      return
    }
    let alive = true
    const load =
      rankFocus.kind === 'companies'
        ? api.topCompanies(days, 100)
        : api.rolesRank(200)
    load
      .then((d) => {
        if (!alive) return
        setData(d)
        setError(null)
      })
      .catch((e: Error) => {
        if (!alive) return
        setData(null)
        setError(e.message || 'Could not load list')
      })
    return () => {
      alive = false
    }
  }, [rankFocus, days])

  if (!rankFocus) {
    return (
      <PanelShell id="rank_list">
        <div className="empty">Open Show all from Tower Insights</div>
      </PanelShell>
    )
  }

  const isCompanies = rankFocus.kind === 'companies'
  const rows = isCompanies ? data?.companies || [] : data?.roles || []
  const maxN = data?.max || Math.max(...rows.map((r: any) => r.n), 1)
  const windows = data?.window_options || FALLBACK_WINDOWS

  return (
    <PanelShell id="rank_list">
      <div className="role-hire-hero">
        <div className="muted">{isCompanies ? 'Companies hiring' : 'Jobs per role'}</div>
        <h3>{isCompanies ? 'All top hiring' : 'All roles'}</h3>
        <div className="muted">
          {rows.length} shown · sorted max → min
        </div>
      </div>
      {isCompanies && (
        <div className="chip-row wrap">
          {windows.map((w: { days: number; label: string }) => (
            <button
              key={w.days}
              type="button"
              className={`chip ${days === w.days ? 'active' : ''}`}
              data-gesture-action={`rank-days-${w.days}`}
              onClick={() => setDays(w.days)}
            >
              {chipLabel(w.days, w.label)}
            </button>
          ))}
        </div>
      )}
      {error ? (
        <div className="empty fail">{error}</div>
      ) : rows.length === 0 ? (
        <div className="empty">Nothing in this window yet</div>
      ) : (
        <div className="hire-bars">
          {rows.map((r: any) => (
            <button
              type="button"
              className="hire-bar-row clickable"
              key={isCompanies ? r.company_id : r.search_id}
              data-gesture-action={
                isCompanies ? `rank-co-${r.company_id}` : `rank-role-${r.search_id}`
              }
              onClick={() => {
                if (isCompanies) openCompanyJobs(r.company_id, r.name, days)
                else openRoleHire(r.search_id, r.name, 7)
              }}
            >
              <div className="hire-bar-main">
                <div className="hire-bar-name">{r.name}</div>
                <div className="bar-track tall">
                  <div
                    className="bar-fill"
                    style={{ width: `${(r.n / maxN) * 100}%` }}
                  />
                </div>
              </div>
              <strong className="hire-bar-n">{r.n}</strong>
            </button>
          ))}
        </div>
      )}
    </PanelShell>
  )
}
