import { useEffect, useState } from 'react'
import { CityChips } from '../components/CityChips'
import { GlassCompareChart } from '../components/GlassCompareChart'
import { SectorChips } from '../components/SectorChips'
import { api, chipLabel, WINDOW_FALLBACK } from '../lib/api'
import { useVigilStore } from '../store/vigilStore'
import { PanelShell } from './PanelShell'

export function RankListPanel() {
  const rankFocus = useVigilStore((s) => s.rankFocus)
  const sectorFilter = useVigilStore((s) => s.sectorFilter)
  const cityFilter = useVigilStore((s) => s.cityFilter)
  const setSectorOptions = useVigilStore((s) => s.setSectorOptions)
  const setCityOptions = useVigilStore((s) => s.setCityOptions)
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
        ? api.topCompanies(days, 100, sectorFilter, cityFilter)
        : api.rolesRank(200, days, mode, sectorFilter, cityFilter)
    load
      .then((d) => {
        if (!alive) return
        setData(d)
        setError(null)
        if (d?.sector_options?.length) setSectorOptions(d.sector_options)
        if (d?.city_options?.length) setCityOptions(d.city_options)
      })
      .catch((e: Error) => {
        if (!alive) return
        setData(null)
        setError(e.message || 'Could not load list')
      })
    return () => {
      alive = false
    }
  }, [rankFocus, days, mode, sectorFilter, cityFilter, setSectorOptions, setCityOptions])

  if (!rankFocus) {
    return (
      <PanelShell id="rank_list">
        <div className="empty">Open Show all from Tower Insights</div>
      </PanelShell>
    )
  }

  const isCompanies = rankFocus.kind === 'companies'
  const rows = isCompanies ? data?.companies || [] : data?.roles || []
  const windows = data?.window_options || WINDOW_FALLBACK
  const glassItems = rows.slice(0, 12).map((r: any) => {
    if (isCompanies) {
      return {
        id: String(r.company_id),
        label: r.name,
        value: r.n as number,
      }
    }
    const value = mode === 'rate' ? Number(r.rate) : Number(r.n)
    return {
      id: String(r.search_id),
      label: r.name,
      value,
      meta: mode === 'rate' ? `${r.n} total` : r.sector_label || undefined,
    }
  })

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
      <CityChips actionPrefix="rank-city" />
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
      ) : (
        <GlassCompareChart
          title={isCompanies ? 'Top companies hiring' : 'Jobs per role'}
          subtitle={
            rows.length > 12
              ? `Top 12 of ${rows.length} — tap to open`
              : 'Tap a pillar to open'
          }
          actionPrefix={isCompanies ? 'rank-co' : 'rank-role'}
          maxItems={12}
          emptyText="Nothing in this window yet"
          formatValue={
            !isCompanies && mode === 'rate'
              ? (n) => `${n}/d`
              : (n) => String(n)
          }
          items={glassItems}
          onSelect={(item) => {
            const id = Number(item.id)
            if (Number.isNaN(id)) return
            if (isCompanies) openCompanyJobs(id, item.label, days)
            else openRoleHire(id, item.label, days)
          }}
        />
      )}
    </PanelShell>
  )
}
