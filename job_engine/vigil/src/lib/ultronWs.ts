import { useEffect } from 'react'
import { useVigilStore, type PanelId } from '../store/vigilStore'

type UltronEvent = {
  type: string
  panel?: string
  command?: string
  text?: string
  state?: { open?: boolean; x?: number; y?: number }
  status?: string
}

let socket: WebSocket | null = null
let retries = 0

function wsUrl(): string {
  const proto = window.location.protocol === 'https:' ? 'wss' : 'ws'
  return `${proto}://${window.location.host}/ws/ultron`
}

export function sendUltron(event: Record<string, unknown>) {
  if (socket && socket.readyState === WebSocket.OPEN) {
    socket.send(JSON.stringify(event))
  }
}

export function useUltronSocket() {
  const setWsConnected = useVigilStore((s) => s.setWsConnected)
  const setStatus = useVigilStore((s) => s.setStatus)
  const openPanel = useVigilStore((s) => s.openPanel)
  const closePanel = useVigilStore((s) => s.closePanel)
  const movePanel = useVigilStore((s) => s.movePanel)
  const setLatencyMs = useVigilStore((s) => s.setLatencyMs)

  useEffect(() => {
    let closed = false
    let pingTimer: number | undefined

    const connect = () => {
      if (closed) return
      const ws = new WebSocket(wsUrl())
      socket = ws

      ws.onopen = () => {
        retries = 0
        setWsConnected(true)
        setStatus('VIGIL LINKED — ULTRON BUS LIVE')
        pingTimer = window.setInterval(() => {
          const t0 = performance.now()
          sendUltron({ type: 'ultron.ping', t: t0 })
          setLatencyMs(Math.round(performance.now() - t0))
        }, 3000)
      }

      ws.onmessage = (ev) => {
        try {
          const data = JSON.parse(ev.data) as UltronEvent
          if (data.type === 'ultron.hello' && data.status) {
            setStatus(data.status)
          }
          if (data.type === 'ultron.status' && data.text) {
            setStatus(data.text)
          }
          if (data.type === 'ultron.panel' && data.panel) {
            const id = data.panel as PanelId
            if (data.state?.open === false) closePanel(id)
            else openPanel(id)
            if (data.state?.x != null && data.state?.y != null) {
              movePanel(id, data.state.x, data.state.y)
            }
          }
          if (data.type === 'ultron.command' && data.command === 'open_panel' && data.panel) {
            openPanel(data.panel as PanelId)
          }
        } catch {
          /* ignore */
        }
      }

      ws.onclose = () => {
        setWsConnected(false)
        if (pingTimer) window.clearInterval(pingTimer)
        socket = null
        const wait = Math.min(8000, 500 + retries * 700)
        retries += 1
        window.setTimeout(connect, wait)
      }

      ws.onerror = () => {
        ws.close()
      }
    }

    connect()
    return () => {
      closed = true
      if (pingTimer) window.clearInterval(pingTimer)
      socket?.close()
      socket = null
    }
  }, [setWsConnected, setStatus, openPanel, closePanel, movePanel, setLatencyMs])
}
