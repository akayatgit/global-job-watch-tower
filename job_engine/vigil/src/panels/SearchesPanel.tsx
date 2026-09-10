import { useEffect, useState } from 'react'
import { api, relTime } from '../lib/api'
import { PanelShell } from './PanelShell'
import { useVigilStore } from '../store/vigilStore'

export function SearchesPanel() {
  const [data, setData] = useState<any>(null)
  const [scanning, setScanning] = useState(false)
  const setStatus = useVigilStore((s) => s.setStatus)
  const setSourceFilter = useVigilStore((s) => s.setSourceFilter)
  const openPanel = useVigilStore((s) => s.openPanel)

  const reload = () => api.promptSources().then(setData).catch(() => {})

  useEffect(() => {
    reload()
    const id = window.setInterval(reload, 10000)
    return () => clearInterval(id)
  }, [])

  const families = data?.by_family || []
  const rows = data?.sources || []

  return (
    <PanelShell id="searches">
      <div className="chip-row wrap">
        <button
          type="button"
          className={`chip ${scanning ? 'active' : ''}`}
          data-gesture-action="sources-scan"
          disabled={scanning}
          onClick={() => {
            setScanning(true)
            api
              .promptScan()
              .then(() => {
                setStatus('SCAN QUEUED')
                reload()
              })
              .catch(() => setStatus('SCAN BUSY'))
              .finally(() => setScanning(false))
          }}
        >
          {scanning ? 'Scanning…' : 'Scan now'}
        </button>
      </div>
      <div className="muted" style={{ marginBottom: 8 }}>
        {data?.total_caught ?? 0} caught · next scan {data?.next_scan_at ? relTime(data.next_scan_at) : '—'}
      </div>
      {families.length > 0 && (
        <div className="stat-grid">
          {families.map((f: any) => (
            <button
              type="button"
              className="stat-card"
              key={f.id}
              data-gesture-action={`source-fam-${f.id}`}
              onClick={() => {
                setSourceFilter(f.id)
                openPanel('jobs')
              }}
            >
              <div className="n">{f.n}</div>
              <div className="l">{f.label}</div>
            </button>
          ))}
        </div>
      )}
      {rows.length === 0 ? (
        <div className="empty">No sources configured</div>
      ) : (
        rows.map((c: any) => (
          <div className="list-row" key={c.id}>
            <div>
              <div>{c.name}</div>
              <div className="meta">
                {c.kind} · {c.enabled ? <span className="ok">On</span> : <span className="warn">Off</span>}
                {c.last_at ? ` · ${relTime(c.last_at)}` : ''}
              </div>
            </div>
            <span className="meta">{c.caught ?? ''}</span>
          </div>
        ))
      )}
    </PanelShell>
  )
}
