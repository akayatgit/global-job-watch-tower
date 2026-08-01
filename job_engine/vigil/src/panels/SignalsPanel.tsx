import { useEffect, useState } from 'react'
import { api } from '../lib/api'
import { PanelShell } from './PanelShell'

export function SignalsPanel() {
  const [days, setDays] = useState(7)
  const [data, setData] = useState<any>(null)

  useEffect(() => {
    let alive = true
    api.signals(days).then((d) => alive && setData(d)).catch(() => {})
    return () => { alive = false }
  }, [days])

  const s = data?.signals

  return (
    <PanelShell id="signals">
      <div className="chip-row">
        {[7, 14, 30].map((d) => (
          <button
            key={d}
            type="button"
            className={`chip ${days === d ? 'active' : ''}`}
            data-gesture-action={`signals-${d}`}
            onClick={() => setDays(d)}
          >
            Last {d}d
          </button>
        ))}
      </div>
      {!s ? (
        <div className="empty">Reading hiring signals…</div>
      ) : (
        <>
          <div className="stat-grid">
            <div className="stat-card"><div className="n">{s.recent_total}</div><div className="l">Recent</div></div>
            <div className="stat-card"><div className="n">{s.prior_total}</div><div className="l">Prior</div></div>
          </div>
          <p className="muted">{s.headline}</p>
          <div className="muted" style={{ marginTop: 8 }}>Growing roles</div>
          {(s.growing_roles || []).slice(0, 8).map((r: any) => (
            <div className="list-row" key={r.search_id}>
              <div>{r.name}<div className="meta">{r.recent} recent</div></div>
              <span className="ok">+{r.delta}</span>
            </div>
          ))}
          <div className="muted" style={{ marginTop: 8 }}>Fastest companies</div>
          {(s.fastest_companies || []).slice(0, 8).map((c: any) => (
            <div className="list-row" key={c.company_id}>
              <div>{c.name}<div className="meta">{c.recent} recent</div></div>
              <span className="ok">+{c.delta}</span>
            </div>
          ))}
        </>
      )}
    </PanelShell>
  )
}
