import { useEffect, useRef } from 'react'
import { ORBIT_NODES, useVigilStore, type PanelId } from '../store/vigilStore'
import { dist2 } from '../lib/lerp'
import { sendUltron } from '../lib/ultronWs'
import { pushDwell } from '../training/sampleBus'

function screenPoint(nx: number, ny: number) {
  return { x: nx * window.innerWidth, y: ny * window.innerHeight }
}

function hitOrbit(nx: number, ny: number, hitPx: number): PanelId | 'remote' | null {
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
    if (d < hitPx && (!best || d < best.d)) best = { id: node.id, d }
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
    const head = el.querySelector('.panel-head') as HTMLElement | null
    const rect = (head || el).getBoundingClientRect()
    // Exclude the ops/buttons strip on the right so Close is not stolen as "panel"
    const ops = el.querySelector('.panel-head .ops') as HTMLElement | null
    const opsLeft = ops ? ops.getBoundingClientRect().left - 8 : rect.right
    if (
      pt.x >= rect.left &&
      pt.x < opsLeft &&
      pt.y >= rect.top &&
      pt.y <= rect.bottom
    ) {
      if (p.z >= bestZ) {
        best = p.id
        bestZ = p.z
      }
    }
  }
  return best
}

/** Inflated hit-test for buttons/chips — survives hand jitter. */
function hitPanelAction(nx: number, ny: number, padPx: number): HTMLElement | null {
  const pt = screenPoint(nx, ny)
  const candidates = Array.from(
    document.querySelectorAll<HTMLElement>(
      'button[data-gesture-action], .chip[data-gesture-action], button.chip, .panel-head .ops button',
    ),
  )
  let best: { el: HTMLElement; d: number } | null = null
  for (const el of candidates) {
    if (el.disabled || el.offsetParent === null) continue
    const r = el.getBoundingClientRect()
    const left = r.left - padPx
    const right = r.right + padPx
    const top = r.top - padPx
    const bottom = r.bottom + padPx
    if (pt.x >= left && pt.x <= right && pt.y >= top && pt.y <= bottom) {
      const cx = (r.left + r.right) / 2
      const cy = (r.top + r.bottom) / 2
      const d = dist2(pt.x, pt.y, cx, cy)
      if (!best || d < best.d) best = { el, d }
    }
  }
  return best?.el ?? null
}

function actionHoverId(el: HTMLElement): string {
  return `action:${el.dataset.gestureAction || el.textContent?.trim() || 'btn'}`
}

export function useGestureOS() {
  const dwellRef = useRef<{
    id: string
    since: number
    el: HTMLElement | null
    lostSince: number | null
  } | null>(null)
  const grabOffset = useRef<{ dx: number; dy: number } | null>(null)
  const lastTwoDist = useRef<number | null>(null)
  const lastPinch = useRef(false)

  useEffect(() => {
    let raf = 0
    const tick = () => {
      const st = useVigilStore.getState()
      if (!st.vigilMode) {
        if (st.pressProgress !== 0 || st.hoverTarget || st.grabTarget) {
          st.setPressProgress(0)
          st.setHoverTarget(null)
          st.setGrabTarget(null)
          st.setMagnet(null)
        }
        dwellRef.current = null
        raf = requestAnimationFrame(tick)
        return
      }
      const idx = st.smoothIndex
      const hands = st.hands
      const primary = hands.right || hands.left
      const pinching = Boolean(primary?.pinch)
      const dwellMs = st.calibration.dwellMs
      const hitPx = st.calibration.hitPx
      // Sticky grace + fat buttons — scaled by calibrated jitter feel
      const stickMs = Math.max(280, Math.min(600, Math.round(dwellMs * 0.55)))
      const btnPad = Math.max(28, Math.min(56, Math.round(hitPx * 0.55)))

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

      const training = st.trainingActive
      const orbit =
        training &&
        ['pinch', 'move', 'close', 'press', 'show_hand', 'intro'].includes(st.trainingStep)
          ? null
          : hitOrbit(idx.x, idx.y, hitPx)

      // Buttons FIRST — Close must win over panel header
      const actionEl = hitPanelAction(idx.x, idx.y, btnPad)
      const header = actionEl ? null : hitPanelHeader(idx.x, idx.y)

      let hover: string | null = null
      if (actionEl) hover = actionHoverId(actionEl)
      else if (header) hover = `panel:${header}`
      else if (orbit) hover = `orbit:${orbit}`

      st.setHoverTarget(hover)

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

      // Grab only on header title area (not Close)
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

      // Press-by-dot with sticky dwell (grace before reset)
      const now = performance.now()
      if (!pinching && !st.grabTarget) {
        if (hover) {
          if (!dwellRef.current || dwellRef.current.id !== hover) {
            // Only hard-switch if we weren't mid-progress, or new target is a button
            const switchingToAction = hover.startsWith('action:')
            const mid = dwellRef.current && now - dwellRef.current.since > 80
            if (!dwellRef.current || switchingToAction || !mid) {
              dwellRef.current = {
                id: hover,
                since: now,
                el: actionEl,
                lostSince: null,
              }
              st.setPressProgress(0)
            }
          } else {
            dwellRef.current.lostSince = null
            if (actionEl) dwellRef.current.el = actionEl
            const prog = Math.min(1, (now - dwellRef.current.since) / dwellMs)
            st.setPressProgress(prog)
            if (prog >= 1) {
              const held = now - dwellRef.current.since
              pushDwell(held)
              const fireId = dwellRef.current.id
              const fireEl = dwellRef.current.el
              dwellRef.current = { id: fireId + ':done', since: now, el: null, lostSince: null }
              st.setPressProgress(0)
              if (fireId.startsWith('orbit:')) {
                const id = fireId.slice(6) as PanelId | 'remote'
                if (id === 'remote') {
                  st.openPanel('jobs')
                  st.setStatus('REMOTE TRENDS → JOBS FILTER')
                  sendUltron({ type: 'ultron.command', command: 'open_panel', panel: 'jobs' })
                } else {
                  st.openPanel(id)
                  sendUltron({ type: 'ultron.command', command: 'open_panel', panel: id })
                }
                st.triggerBurst()
              } else if (fireId.startsWith('panel:')) {
                st.focusPanel(fireId.slice(6) as PanelId)
              } else if (fireEl) {
                fireEl.click()
                st.setStatus(`TRIGGER ${fireEl.textContent?.trim() || 'ACTION'}`)
                sendUltron({
                  type: 'ultron.command',
                  command: 'click',
                  label: fireEl.textContent?.trim(),
                })
              }
            }
          }
        } else if (dwellRef.current && !dwellRef.current.id.endsWith(':done')) {
          // Sticky: keep filling for stickMs after leaving target
          if (dwellRef.current.lostSince == null) {
            dwellRef.current.lostSince = now
          }
          const lostFor = now - dwellRef.current.lostSince
          if (lostFor < stickMs) {
            const prog = Math.min(1, (now - dwellRef.current.since) / dwellMs)
            st.setPressProgress(prog)
            if (prog >= 1 && dwellRef.current.el) {
              const held = now - dwellRef.current.since
              pushDwell(held)
              const el = dwellRef.current.el
              dwellRef.current = {
                id: dwellRef.current.id + ':done',
                since: now,
                el: null,
                lostSince: null,
              }
              st.setPressProgress(0)
              el.click()
              st.setStatus(`TRIGGER ${el.textContent?.trim() || 'ACTION'}`)
            }
          } else {
            dwellRef.current = null
            st.setPressProgress(0)
          }
        } else {
          st.setPressProgress(0)
        }
      }

      raf = requestAnimationFrame(tick)
    }
    raf = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(raf)
  }, [])
}
