import { useEffect, useState } from 'react'
import { GlassCompareChart } from '../components/GlassCompareChart'
import { api, relTime } from '../lib/api'
import { PanelShell } from './PanelShell'
import { useVigilStore } from '../store/vigilStore'

export function WatchlistPanel() {
  const [data, setData] = useState<any>(null)
  const openPanel = useVigilStore((s) => s.openPanel)

  const reload = () => api.promptWinners().then(setData).catch(() => {})

  useEffect(() => {
    reload()
    const id = window.setInterval(reload, 10000)
    return () => clearInterval(id)
  }, [])

  return (
    <PanelShell id="watchlist">
      {!data ? (
        <div className="empty">Loading winners…</div>
      ) : (
        <>
          <GlassCompareChart
            title="RAG exemplars"
            subtitle="Top performed — used to score tomorrow"
            actionPrefix="win-ex"
            maxItems={8}
            emptyText="No winners yet — rate a prompt after posting"
            items={(data.exemplars || []).slice(0, 8).map((c: any) => ({
              id: String(c.id),
              label: c.title || `#${c.id}`,
              value: c.performance_score ?? c.rating ?? c.final_score ?? 0,
            }))}
            onSelect={() => openPanel('jobs')}
          />
          <div className="muted" style={{ marginTop: 10 }}>Posted</div>
          {(data.posted || []).length === 0 ? (
            <div className="empty">Nothing marked posted yet</div>
          ) : (
            (data.posted || []).slice(0, 12).map((p: any) => (
              <div className="list-row" key={p.id}>
                <div>
                  <div>{p.title}</div>
                  <div className="meta">
                    {p.source} · {p.final_score ?? '—'}
                  </div>
                </div>
                <div className="meta" title={p.posted_at}>
                  {relTime(p.posted_at)}
                </div>
              </div>
            ))
          )}
          <div className="muted" style={{ marginTop: 10 }}>Your ratings</div>
          {(data.rated || []).length === 0 ? (
            <div className="empty">No stars yet</div>
          ) : (
            (data.rated || []).slice(0, 12).map((p: any) => (
              <div className="list-row" key={p.id}>
                <div>
                  <div>{p.title}</div>
                  <div className="meta">{p.source}</div>
                </div>
                <span className="meta">{'★'.repeat(p.rating || 0)}</span>
              </div>
            ))
          )}
        </>
      )}
    </PanelShell>
  )
}
