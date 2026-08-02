import { useEffect, useState } from 'react'
import { SectorChips } from '../components/SectorChips'
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
  const sectorFilter = useVigilStore((s) => s.sectorFilter)
  const setSectorOptions = useVigilStore((s) => s.setSectorOptions)
  const openCompanyJobs = useVigilStore((s) => s.openCompanyJobs)
  const openRoleHire = useVigilStore((s) => s.openRoleHire)
  const [days, setDays] = useState(7)
  const [mode, setMode] = useState<'count' | 'rate'>('count')
  const [data, setData] = useState<any>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (rankFocus?.kind === 'companies') setDays(rankFocus.days)
    if (rankFocus?.kind === 'roles' && rankFocus.days != null) setDays(rankFocus.days)
  }, [rankFocus])

  useEffect(() => {
    if (!rankFocus) {
      setData(null)
      return
    }
    let alive = true
    const load =
      rankFocus.kind === 'companies'
        ? api.topCompanies(days, 100, sectorFilter)
        : api.rolesRank(200, days, mode, sectorFilter)
    load
      .then((d) => {
        if (!alive) return
        setData(d)
        setError(null)
        if (d?.sector_options?.length) setSectorOptions(d.sector_options)
      })
      .catch((e: Error) => {
        if (!alive) return
        setData(null)
        setError(e.message || 'Could not load list')
      })
    return () => {
      alive = false
    }
  }, [rankFocus, days, mode, sectorFilter, setSectorOptions])

  if (!rankFocus) {
    return (
      <PanelShell id="rank_list">
        <div className="empty">Open Show all from Tower Insights</div>
      </PanelShell>
    )
  }

  const isCompanies = rankFocus.kind === 'companies'
  const rows = isCompanies ? data?.companies || [] : data?.roles || []
  const maxN = isCompanies
    ? data?.max || Math.max(...rows.map((r: any) => r.n), 1)
    : mode === 'rate'
      ? data?.max_rate || Math.max(...rows.map((r: any) => r.rate), 0.01)
      : data?.max || Math.max(...rows.map((r: any) => r.n), 1)
  const windows = data?.window_options || FALLBACK_WINDOWS

  return (
    <PanelShell id="rank_list">
      <div className="role-hire-hero">
        <div className="muted">{isCompanies ? 'Companies hiring' : 'Jobs per role'}</div>
        <h3>{isCompanies ? 'All top hiring' : 'All roles'}</h3>
        <div className="muted">
          {rows.length} shown · sorted max → min
          {!isCompanies ? ' · fair window (not all-time)' : ''}
        </div>
      </div>
      <SectorChips actionPrefix="rank-sector" />
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
      {!isCompanies && (
        <div className="chip-row wrap">
          <button
            type="button"
            className={`chip ${mode === 'count' ? 'active' : ''}`}
            data-gesture-action="rank-mode-count"
            onClick={() => setMode('count')}
          >
            Count
          </button>
          <button
            type="button"
            className={`chip ${mode === 'rate' ? 'active' : ''}`}
            data-gesture-action="rank-mode-rate"
            onClick={() => setMode('rate')}
            title="Jobs per day in this window — fairer when roles started on different days"
          >
            Per day
          </button>
        </div>
      )}
      {!isCompanies && data?.fair_hint ? (
        <p className="muted" style={{ marginTop: 6 }}>{data.fair_hint}</p>
      ) : null}
      {error ? (
        <div className="empty fail">{error}</div>
      ) : rows.length === 0 ? (
        <div className="empty">Nothing in this window yet</div>
      ) : (
        <div className="hire-bars">
          {rows.map((r: any) => {
            const value = isCompanies ? r.n : mode === 'rate' ? r.rate : r.n
            return (
              <button
                type="button"
                className="hire-bar-row clickable"
                key={isCompanies ? r.company_id : r.search_id}
                data-gesture-action={
                  isCompanies ? `rank-co-${r.company_id}` : `rank-role-${r.search_id}`
                }
                onClick={() => {
                  if (isCompanies) openCompanyJobs(r.company_id, r.name, days)
                  else openRoleHire(r.search_id, r.name, days)
                }}
              >
                <div className="hire-bar-main">
                  <div className="hire-bar-name">
                    {r.name}
                    {r.sector_label ? (
                      <span className="meta"> · {r.sector_label}</span>
                    ) : null}
                  </div>
                  <div className="bar-track tall">
                    <div
                      className="bar-fill"
                      style={{ width: `${(Number(value) / maxN) * 100}%` }}
                    />
                  </div>
                  {!isCompanies && r.coverage_note ? (
                    <div className="meta">{r.coverage_note}</div>
                  ) : null}
                </div>
                <strong className="hire-bar-n">
                  {mode === 'rate' && !isCompanies ? `${r.rate}/d` : r.n}
                </strong>
              </button>
            )
          })}
        </div>
      )}
    </PanelShell>
  )
}
