import { useEffect, useState } from 'react'
import { api, relTime } from '../lib/api'
import { PanelShell } from './PanelShell'

type TraceSummary = {
  id: string
  started_at?: string
  finished_at?: string | null
  status?: string
  user_text?: string
  node_count?: number
  hints?: number
  outcome_kind?: string | null
}

export function DirectorTracePanel() {
  const [traces, setTraces] = useState<TraceSummary[]>([])
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [detail, setDetail] = useState<any | null>(null)
  const [err, setErr] = useState('')

  const reload = () =>
    api
      .directorTraces(40)
      .then((d) => {
        setTraces(d.traces || [])
        setErr('')
      })
      .catch((e) => setErr(String(e.message || e)))

  useEffect(() => {
    reload()
    const id = window.setInterval(reload, 4000)
    return () => clearInterval(id)
  }, [])

  useEffect(() => {
    if (!selectedId) {
      setDetail(null)
      return
    }
    let alive = true
    api
      .directorTrace(selectedId)
      .then((d) => {
        if (alive) setDetail(d)
      })
      .catch(() => {
        if (alive) setDetail(null)
      })
    return () => {
      alive = false
    }
  }, [selectedId])

  const nodes: any[] = detail?.nodes || []
  const hints: any[] = detail?.loophole_hints || []

  return (
    <PanelShell id="director_traces">
      <div className="muted" style={{ marginBottom: 8 }}>
        Telegram → DIRECTOR workflow audit · {traces.length} recent
        {err ? ` · ${err}` : ''}
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1.2fr', gap: 12, minHeight: 0 }}>
        <div style={{ overflow: 'auto', maxHeight: '100%' }}>
          {traces.length === 0 ? (
            <div className="empty">No workflows yet — send a Telegram message to Vigil</div>
          ) : (
            traces.map((t) => (
              <div
                className="list-row"
                key={t.id}
                data-gesture-action={`trace-${t.id}`}
                onClick={() => setSelectedId(t.id)}
                style={{
                  cursor: 'pointer',
                  outline: selectedId === t.id ? '1px solid #FF5500' : undefined,
                }}
              >
                <div>
                  <div>{(t.user_text || '—').slice(0, 72)}</div>
                  <div className="meta" title={t.started_at}>
                    {relTime(t.started_at)} · {t.status || '—'} · {t.node_count || 0} nodes
                    {t.hints ? ` · ${t.hints} hints` : ''}
                  </div>
                </div>
              </div>
            ))
          )}
        </div>
        <div style={{ overflow: 'auto', maxHeight: '100%' }}>
          {!selectedId ? (
            <div className="empty">Click a message workflow to inspect every node</div>
          ) : !detail ? (
            <div className="empty">Loading workflow…</div>
          ) : (
            <>
              <div style={{ marginBottom: 10 }}>
                <div style={{ color: '#FF5500', fontWeight: 700 }}>WORKFLOW {detail.id}</div>
                <div className="meta">
                  {detail.status} · chat {detail.chat} · {(detail.user_text || '').slice(0, 120)}
                </div>
              </div>
              {hints.length > 0 && (
                <div style={{ marginBottom: 12 }}>
                  <div style={{ color: '#FFAA00', fontWeight: 700, marginBottom: 6 }}>LOOPHOLE HINTS</div>
                  {hints.map((h, i) => (
                    <div className="list-row" key={`h-${i}`}>
                      <div>{h.hint}</div>
                      <span className="meta">{relTime(h.ts)}</span>
                    </div>
                  ))}
                </div>
              )}
              <div style={{ color: '#FF7700', fontWeight: 700, marginBottom: 6 }}>NODES</div>
              {nodes.map((n, i) => (
                <div className="list-row" key={`${n.ts}-${i}`} style={{ alignItems: 'flex-start' }}>
                  <div style={{ minWidth: 0, flex: 1 }}>
                    <div>
                      <strong>{n.kind}</strong>
                      {n.tool ? ` · ${n.tool}` : ''}
                      {n.attempt != null ? ` · try ${n.attempt}` : ''}
                    </div>
                    <div className="meta" title={n.ts}>
                      {relTime(n.ts)}
                    </div>
                    {n.arguments != null && (
                      <pre
                        style={{
                          whiteSpace: 'pre-wrap',
                          wordBreak: 'break-word',
                          fontSize: 11,
                          margin: '6px 0 0',
                          opacity: 0.85,
                          maxHeight: 120,
                          overflow: 'auto',
                        }}
                      >
                        args: {typeof n.arguments === 'string' ? n.arguments : JSON.stringify(n.arguments, null, 0)}
                      </pre>
                    )}
                    {n.result != null && (
                      <pre
                        style={{
                          whiteSpace: 'pre-wrap',
                          wordBreak: 'break-word',
                          fontSize: 11,
                          margin: '6px 0 0',
                          opacity: 0.85,
                          maxHeight: 140,
                          overflow: 'auto',
                        }}
                      >
                        result: {typeof n.result === 'string' ? n.result : JSON.stringify(n.result, null, 0)}
                      </pre>
                    )}
                    {n.system_prompt != null && (
                      <pre
                        style={{
                          whiteSpace: 'pre-wrap',
                          wordBreak: 'break-word',
                          fontSize: 10,
                          margin: '6px 0 0',
                          opacity: 0.7,
                          maxHeight: 100,
                          overflow: 'auto',
                        }}
                      >
                        system: {String(n.system_prompt).slice(0, 1200)}
                      </pre>
                    )}
                    {n.final_output != null && (
                      <div className="meta" style={{ marginTop: 4 }}>
                        final: {String(n.final_output).slice(0, 200)}
                      </div>
                    )}
                    {n.output_preview != null && (
                      <pre
                        style={{
                          whiteSpace: 'pre-wrap',
                          wordBreak: 'break-word',
                          fontSize: 10,
                          margin: '6px 0 0',
                          opacity: 0.7,
                          maxHeight: 100,
                          overflow: 'auto',
                        }}
                      >
                        llm: {String(n.output_preview).slice(0, 1000)}
                      </pre>
                    )}
                  </div>
                </div>
              ))}
            </>
          )}
        </div>
      </div>
    </PanelShell>
  )
}
