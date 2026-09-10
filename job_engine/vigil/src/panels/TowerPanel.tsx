import { useEffect, useState } from 'react'
import { CategoryChips, SourceChips } from '../components/SourceChips'
import { GlassCompareChart } from '../components/GlassCompareChart'
import { api, relTime } from '../lib/api'
import { useVigilStore } from '../store/vigilStore'
import { PanelShell } from './PanelShell'

export function TowerPanel() {
  const [data, setData] = useState<any>(null)
  const [scanning, setScanning] = useState(false)
  const sourceFilter = useVigilStore((s) => s.sourceFilter)
  const categoryFilter = useVigilStore((s) => s.categoryFilter)
  const setSourceOptions = useVigilStore((s) => s.setSourceOptions)
  const setCategoryOptions = useVigilStore((s) => s.setCategoryOptions)
  const setSourceFilter = useVigilStore((s) => s.setSourceFilter)
  const setCategoryFilter = useVigilStore((s) => s.setCategoryFilter)
  const openPanel = useVigilStore((s) => s.openPanel)
  const setStatus = useVigilStore((s) => s.setStatus)

  useEffect(() => {
    let alive = true
    const load = () =>
      api
        .promptInsights(7)
        .then((d) => {
          if (!alive) return
          setData(d)
          if (d?.source_options?.length) setSourceOptions(d.source_options)
          if (d?.category_options?.length) setCategoryOptions(d.category_options)
        })
        .catch(() => {})
    load()
    const id = window.setInterval(load, 8000)
    return () => {
      alive = false
      clearInterval(id)
    }
  }, [setSourceOptions, setCategoryOptions])

  const stats = data?.stats
  const sources = data?.top_sources || []
  const cats = (data?.by_category || []).slice(0, 8)
  const latest = data?.latest || []
  const shortlist = data?.shortlist || []

  return (
    <PanelShell id="tower">
      <SourceChips actionPrefix="tower-source" />
      <CategoryChips actionPrefix="tower-category" />
      <div className="chip-row wrap">
        <button
          type="button"
          className={`chip ${scanning ? 'active' : ''}`}
          data-gesture-action="tower-scan"
          disabled={scanning}
          onClick={() => {
            setScanning(true)
            api
              .promptScan()
              .then(() => setStatus('SCAN QUEUED'))
              .catch(() => setStatus('SCAN BUSY'))
              .finally(() => setScanning(false))
          }}
        >
          {scanning ? 'Scanning…' : 'Scan now'}
        </button>
      </div>
      {!data ? (
        <div className="empty">Syncing prompt tower…</div>
      ) : (
        <>
          <div className="signal-hero">
            <div className="stat-grid">
              <div className="stat-card signal-stat">
                <div className="n">{stats.total}</div>
                <div className="l">Prompts</div>
              </div>
              <div className="stat-card">
                <div className="n">{stats.today}</div>
                <div className="l">Today</div>
              </div>
              <div className="stat-card">
                <div className="n">{stats.pending_score}</div>
                <div className="l">To score</div>
              </div>
              <div className="stat-card">
                <div className="n">{stats.shortlisted_today}</div>
                <div className="l">Top 10</div>
              </div>
            </div>
          </div>

          <GlassCompareChart
            title="Top sources"
            subtitle="Last 7 days — tap to open Prompts"
            actionPrefix="tower-src"
            maxItems={8}
            items={sources.map((c: any) => ({
              id: String(c.id),
              label: c.label,
              value: c.n,
            }))}
            onSelect={(item) => {
              setSourceFilter(item.id)
              openPanel('jobs')
            }}
            action={
              <button
                type="button"
                className="show-all"
                data-gesture-action="tower-show-sources"
                onClick={() => openPanel('searches')}
              >
                All sources
              </button>
            }
          />

          <GlassCompareChart
            title="Prompts per category"
            subtitle="Last 7 days — tap to filter"
            actionPrefix="tower-cat"
            maxItems={8}
            items={cats.map((r: any) => ({
              id: String(r.id),
              label: r.label,
              value: r.n,
            }))}
            onSelect={(item) => {
              setCategoryFilter(item.id)
              openPanel('jobs')
            }}
            action={
              <button
                type="button"
                className="show-all"
                data-gesture-action="tower-show-cats"
                onClick={() => openPanel('cities')}
              >
                All categories
              </button>
            }
          />

          <div className="muted" style={{ marginTop: 10 }}>Today’s top 10</div>
          {shortlist.length === 0 ? (
            <div className="empty">No shortlist yet — tap Scan now</div>
          ) : (
            shortlist.map((p: any) => (
              <div className="list-row" key={p.id}>
                <div>
                  <div>
                    {p.rank}. {p.title}
                  </div>
                  <div className="meta">
                    {p.source} · {p.category || '—'} · {p.final_score ?? 'unscored'}
                  </div>
                </div>
                <div className="meta">{p.is_outlier ? 'outlier' : ''}</div>
              </div>
            ))
          )}

          <div className="muted" style={{ marginTop: 10 }}>Freshest catches</div>
          {latest.length === 0 ? (
            <div className="empty">Nothing caught yet</div>
          ) : (
            latest
              .filter((p: any) => {
                if (sourceFilter && p.source !== sourceFilter) return false
                if (categoryFilter && p.category !== categoryFilter) return false
                return true
              })
              .map((p: any) => (
                <button
                  type="button"
                  className="list-row clickable"
                  key={p.id}
                  data-gesture-action={`tower-latest-${p.id}`}
                  onClick={() => openPanel('jobs')}
                >
                  <div>
                    <div>{p.title}</div>
                    <div className="meta">
                      {p.source} · {p.category || '—'}
                    </div>
                  </div>
                  <div className="meta" title={p.collected_at}>
                    {relTime(p.collected_at)}
                  </div>
                </button>
              ))
          )}
        </>
      )}
    </PanelShell>
  )
}
