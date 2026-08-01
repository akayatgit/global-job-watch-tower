import { useEffect, useRef } from 'react'
import { ORBIT_NODES, useVigilStore, type PanelId } from '../store/vigilStore'
import { dist2 } from '../lib/lerp'
import { sendUltron } from '../lib/ultronWs'

const DWELL_MS = 700
const HIT_PX = 56

function screenPoint(nx: number, ny: number) {
  return { x: nx * window.innerWidth, y: ny * window.innerHeight }
}

function hitOrbit(nx: number, ny: number): PanelId | 'remote' | null {
  // Orbit nodes are projected roughly around center
  const cx = window.innerWidth / 2
  const cy = window.innerHeight / 2
  const px = nx * window.innerWidth
  const py = ny * window.innerHeight
  let best: { id: PanelId | 'remote'; d: number } | null = null
  for (const node of ORBIT_NODES) {
    const r = Math.min(window.innerWidth, window.innerHeight) * 0.28
    const x = cx + Math.cos(node.angle) * r
    const y = cy + Math.sin(node.angle) * r * 0.72
    const d = dist2(px, py, x, y)
    if (d < HIT_PX && (!best || d < best.d)) best = { id: node.id, d }
  }
  return best?.id ?? null
}

function hitPanelHeader(nx: number, ny: number): PanelId | null {
  const panels = useVigilStore.getState().panels
  const pt = screenPoint(nx, ny)
  let best: PanelId | null = null
  let bestZ = -1
  for (const p of Object.values(panels)) {
    if (!p.open) continue
    const el = document.querySelector(`[data-panel-id="${p.id}"]`) as HTMLElement | null
    if (!el) continue
    const rect = el.getBoundingClientRect()
    const headerH = 42
    if (
      pt.x >= rect.left &&
      pt.x <= rect.right &&
      pt.y >= rect.top &&
      pt.y <= rect.top + headerH
    ) {
      if (p.z >= bestZ) {
        best = p.id
        bestZ = p.z
      }
    }
  }
  return best
}

function hitPanelAction(nx: number, ny: number): HTMLElement | null {
  const pt = screenPoint(nx, ny)
  const els = document.elementsFromPoint(pt.x, pt.y)
  for (const el of els) {
    if (!(el instanceof HTMLElement)) continue
    if (el.dataset.gestureAction || el.classList.contains('chip') || el.tagName === 'BUTTON') {
      return el
    }
  }
  return null
}

export function useGestureOS() {
  const dwellRef = useRef<{ id: string; since: number } | null>(null)
  const grabOffset = useRef<{ dx: number; dy: number } | null>(null)
  const lastTwoDist = useRef<number | null>(null)
  const lastPinch = useRef(false)

  useEffect(() => {
    let raf = 0
    const tick = () => {
      const st = useVigilStore.getState()
      // Desktop mode: hands never drive panels — mouse/keyboard only
      if (!st.vigilMode) {
        if (st.pressProgress !== 0 || st.hoverTarget || st.grabTarget) {
          st.setPressProgress(0)
          st.setHoverTarget(null)
          st.setGrabTarget(null)
          st.setMagnet(null)
        }
        raf = requestAnimationFrame(tick)
        return
      }
      const idx = st.smoothIndex
      const hands = st.hands
      const primary = hands.right || hands.left
      const pinching = Boolean(primary?.pinch)

      // Two-hand pinch zoom → core scale
      if (hands.twoHandPinch) {
        if (lastTwoDist.current != null) {
          const delta = hands.twoHandDist - lastTwoDist.current
          st.setCoreScale(st.coreScale + delta * 2.4)
          if (Math.abs(delta) > 0.01) {
            st.setStatus(
              st.coreScale > 1.3
                ? 'SYNCING DASHBOARD — CORE EXPANDED'
                : 'JOB MARKET CORE ACTIVE',
            )
            if (st.coreScale > 1.45) st.triggerBurst()
          }
        }
        lastTwoDist.current = hands.twoHandDist
      } else {
        lastTwoDist.current = null
      }

      const orbit = hitOrbit(idx.x, idx.y)
      const header = hitPanelHeader(idx.x, idx.y)
      const actionEl = hitPanelAction(idx.x, idx.y)

      let hover: string | null = null
      if (header) hover = `panel:${header}`
      else if (orbit) hover = `orbit:${orbit}`
      else if (actionEl) hover = `action:${actionEl.dataset.gestureAction || actionEl.textContent}`

      st.setHoverTarget(hover)

      // Magnet toward nearest orbit
      if (orbit) {
        const cx = window.innerWidth / 2
        const cy = window.innerHeight / 2
        const node = ORBIT_NODES.find((n) => n.id === orbit)!
        const r = Math.min(window.innerWidth, window.innerHeight) * 0.28
        st.setMagnet({
          x: (cx + Math.cos(node.angle) * r) / window.innerWidth,
          y: (cy + Math.sin(node.angle) * r * 0.72) / window.innerHeight,
        })
      } else {
        st.setMagnet(null)
      }

      // Grab / drag panels
      if (pinching && !lastPinch.current) {
        if (header) {
          st.setGrabTarget(header)
          st.focusPanel(header)
          const p = st.panels[header]
          grabOffset.current = {
            dx: idx.x * 100 - p.x,
            dy: idx.y * 100 - p.y,
          }
          st.setStatus(`GRABBED ${p.title}`)
          st.triggerBurst()
          sendUltron({
            type: 'ultron.gesture',
            gesture: 'grab',
            panel: header,
          })
        }
      }

      if (pinching && st.grabTarget && grabOffset.current) {
        const grabId = st.grabTarget as PanelId
        const x = idx.x * 100 - grabOffset.current.dx
        const y = idx.y * 100 - grabOffset.current.dy
        st.movePanel(
          grabId,
          Math.max(1, Math.min(70, x)),
          Math.max(8, Math.min(70, y)),
        )
      }

      if (!pinching && lastPinch.current && st.grabTarget) {
        const grabId = st.grabTarget as PanelId
        const p = st.panels[grabId]
        sendUltron({
          type: 'ultron.panel',
          panel: grabId,
          state: { open: true, x: p.x, y: p.y },
        })
        st.setGrabTarget(null)
        grabOffset.current = null
        st.setStatus('PANEL DOCKED')
      }
      lastPinch.current = pinching

      // Press-by-dot dwell (when not grabbing)
      if (!pinching && !st.grabTarget && hover) {
        const now = performance.now()
        if (!dwellRef.current || dwellRef.current.id !== hover) {
          dwellRef.current = { id: hover, since: now }
          st.setPressProgress(0)
        } else {
          const prog = Math.min(1, (now - dwellRef.current.since) / DWELL_MS)
          st.setPressProgress(prog)
          if (prog >= 1) {
            // Fire once
            dwellRef.current = { id: hover + ':done', since: now }
            st.setPressProgress(0)
            if (hover.startsWith('orbit:')) {
              const id = hover.slice(6) as PanelId | 'remote'
              if (id === 'remote') {
                st.openPanel('jobs')
                st.setStatus('REMOTE TRENDS → JOBS FILTER')
                sendUltron({ type: 'ultron.command', command: 'open_panel', panel: 'jobs' })
              } else {
                st.openPanel(id)
                sendUltron({ type: 'ultron.command', command: 'open_panel', panel: id })
              }
              st.triggerBurst()
            } else if (hover.startsWith('panel:')) {
              st.focusPanel(hover.slice(6) as PanelId)
            } else if (actionEl) {
              actionEl.click()
              st.setStatus(`TRIGGER ${actionEl.textContent?.trim() || 'ACTION'}`)
              sendUltron({
                type: 'ultron.command',
                command: 'click',
                label: actionEl.textContent?.trim(),
              })
            }
          }
        }
      } else if (!hover) {
        dwellRef.current = null
        st.setPressProgress(0)
      }

      raf = requestAnimationFrame(tick)
    }
    raf = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(raf)
  }, [])
}
