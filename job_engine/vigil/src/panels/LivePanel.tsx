import { useEffect, useState } from 'react'
import { api, relTime } from '../lib/api'
import { PanelShell } from './PanelShell'

export function LivePanel() {
  const [rows, setRows] = useState<any[]>([])
  const [lastId, setLastId] = useState(0)

  useEffect(() => {
    let alive = true
    const pull = async () => {
      try {
        const batch = await api.console(lastId)
        if (!alive || !batch.length) return
        if (lastId === 0) {
          setRows(batch.slice(-80))
          setLastId(batch[batch.length - 1].id)
        } else {
          setRows((prev) => [...prev, ...batch].slice(-120))
          setLastId(batch[batch.length - 1].id)
        }
      } catch {
        /* ignore */
      }
    }
    pull()
    const id = window.setInterval(pull, 3000)
    return () => {
      alive = false
      clearInterval(id)
    }
  }, [lastId])

  return (
    <PanelShell id="live">
      <div className="muted" style={{ marginBottom: 8 }}>Live feed · auto-scroll newest</div>
      {rows.length === 0 ? (
        <div className="empty">Waiting for tower logs…</div>
      ) : (
        [...rows].reverse().slice(0, 50).map((r) => (
          <div className="list-row" key={r.id}>
            <div>
              <div style={{ whiteSpace: 'pre-wrap' }}>{r.message}</div>
              <div className="meta">{r.source} · {r.level}</div>
            </div>
            <div className="meta" title={r.ts}>{relTime(r.ts)}</div>
          </div>
        ))
      )}
    </PanelShell>
  )
}
