import { useState, type FormEvent } from 'react'
import { api } from '../lib/api'
import { PanelShell } from './PanelShell'

type Msg = { role: 'user' | 'assistant'; text: string; queued?: boolean }

export function AskPanel() {
  const [input, setInput] = useState('')
  const [busy, setBusy] = useState(false)
  const [msgs, setMsgs] = useState<Msg[]>([
    {
      role: 'assistant',
      text: 'Ask the tower — hiring signals, watchlist, roles, companies. I yield when a search is using Ollama.',
    },
  ])

  const send = async (e?: FormEvent) => {
    e?.preventDefault()
    const q = input.trim()
    if (!q || busy) return
    setInput('')
    setMsgs((m) => [...m, { role: 'user', text: q }])
    setBusy(true)
    try {
      const r = await api.ask(q)
      setMsgs((m) => [
        ...m,
        {
          role: 'assistant',
          text: r.answer || 'No answer',
          queued: Boolean(r.queued),
        },
      ])
    } catch (err: any) {
      setMsgs((m) => [
        ...m,
        { role: 'assistant', text: `Ask failed — ${err?.message || 'error'}` },
      ])
    } finally {
      setBusy(false)
    }
  }

  return (
    <PanelShell id="ask">
      <div className="ask-thread">
        {msgs.map((m, i) => (
          <div
            key={i}
            className={`ask-bubble ${m.role}${m.queued ? ' queued' : ''}`}
          >
            {m.text}
          </div>
        ))}
      </div>
      <form className="ask-form" onSubmit={send}>
        <input
          type="text"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="What’s moving in hiring today?"
          disabled={busy}
          data-gesture-action="ask-input"
        />
        <button
          type="submit"
          className="chip active"
          disabled={busy || !input.trim()}
          data-gesture-action="ask-send"
        >
          {busy ? '…' : 'Ask'}
        </button>
      </form>
    </PanelShell>
  )
}
