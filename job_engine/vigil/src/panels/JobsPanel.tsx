import { useEffect, useMemo, useState } from 'react'
import { CategoryChips, SourceChips } from '../components/SourceChips'
import { api, relTime } from '../lib/api'
import { useVigilStore } from '../store/vigilStore'
import { PanelShell } from './PanelShell'

export function JobsPanel() {
  const [data, setData] = useState<any>(null)
  const [error, setError] = useState<string | null>(null)
  const [q, setQ] = useState('')
  const [sort, setSort] = useState<'newest' | 'score' | 'rating'>('newest')
  const sourceFilter = useVigilStore((s) => s.sourceFilter)
  const categoryFilter = useVigilStore((s) => s.categoryFilter)
  const setSourceOptions = useVigilStore((s) => s.setSourceOptions)
  const setCategoryOptions = useVigilStore((s) => s.setCategoryOptions)

  useEffect(() => {
    let alive = true
    const load = () => {
      api
        .prompts({
          limit: 120,
          q,
          source: sourceFilter,
          category: categoryFilter,
          sort,
        })
        .then((d) => {
          if (!alive) return
          setData(d)
          setError(null)
        })
        .catch((e: Error) => {
          if (!alive) return
          setData(null)
          setError(e.message || 'Could not load prompts')
        })
    }
    load()
    const id = window.setInterval(load, 8000)
    return () => {
      alive = false
      clearInterval(id)
    }
  }, [q, sort, sourceFilter, categoryFilter])

  useEffect(() => {
    api
      .promptInsights(7)
      .then((d) => {
        if (d?.source_options?.length) setSourceOptions(d.source_options)
        if (d?.category_options?.length) setCategoryOptions(d.category_options)
      })
      .catch(() => {})
  }, [setSourceOptions, setCategoryOptions])

  const rows = data?.prompts || []
  const shown = useMemo(() => rows, [rows])

  return (
    <PanelShell id="jobs">
      <SourceChips actionPrefix="prompts-source" />
      <CategoryChips actionPrefix="prompts-category" />
      <div className="chip-row wrap">
        <input
          className="chip"
          style={{ minWidth: 140 }}
          placeholder="Search title…"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          aria-label="Search prompts"
        />
        {(['newest', 'score', 'rating'] as const).map((key) => (
          <button
            key={key}
            type="button"
            className={`chip ${sort === key ? 'active' : ''}`}
            data-gesture-action={`prompts-sort-${key}`}
            onClick={() => setSort(key)}
          >
            {key === 'newest' ? 'Newest' : key === 'score' ? 'Score' : 'Rating'}
          </button>
        ))}
      </div>
      <div className="muted" style={{ marginBottom: 8 }}>
        {shown.length} shown · {data?.total ?? 0} total · live
      </div>
      {error ? (
        <div className="empty fail">Prompts failed to load — {error}</div>
      ) : shown.length === 0 ? (
        <div className="empty">No prompts match — widen source or category, or tap Scan now on Tower</div>
      ) : (
        shown.slice(0, 80).map((p: any) => (
          <a
            className="list-row clickable"
            key={p.id}
            href={p.source_url || '#'}
            target={p.source_url ? '_blank' : undefined}
            rel="noreferrer"
            data-gesture-action={`prompt-open-${p.id}`}
          >
            <div>
              <div>{p.title}</div>
              <div className="meta">
                {p.source || '—'} · {p.category || '—'} · {p.status}
                {p.final_score != null ? ` · ${p.final_score}` : ' · unscored'}
                {p.is_outlier ? ' · outlier' : ''}
              </div>
            </div>
            <div className="meta" title={p.collected_at}>
              {relTime(p.collected_at)}
            </div>
          </a>
        ))
      )}
    </PanelShell>
  )
}
