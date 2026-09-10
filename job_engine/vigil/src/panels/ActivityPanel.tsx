import { useEffect, useState } from 'react'
import { api, relTime } from '../lib/api'
import { PanelShell } from './PanelShell'

export function ActivityPanel() {
  const [events, setEvents] = useState<any[]>([])

  const reload = () =>
    api
      .promptActivity(50)
      .then((d) => setEvents(d?.events || []))
      .catch(() => {})

  useEffect(() => {
    reload()
    const id = window.setInterval(reload, 5000)
    return () => clearInterval(id)
  }, [])

  return (
    <PanelShell id="activity">
      <div className="muted" style={{ marginBottom: 8 }}>
        Showing {events.length} · newest first · catch / score / video
      </div>
      {events.length === 0 ? (
        <div className="empty">No prompt activity yet — tap Scan now on Tower</div>
      ) : (
        events.map((r) => (
          <div className="list-row" key={r.id}>
            <div>
              <div>
                {r.kind} · {r.title}
              </div>
              <div className="meta" title={r.at}>
                {relTime(r.at)} · {r.meta}
              </div>
            </div>
            <span className="meta">{r.status}</span>
          </div>
        ))
      )}
    </PanelShell>
  )
}
