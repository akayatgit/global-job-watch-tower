import { useEffect, useRef } from 'react'
import { ORBIT_NODES, useVigilStore, type PanelId } from '../store/vigilStore'
import { sendUltron } from '../lib/ultronWs'
import { pushDwell } from '../training/sampleBus'
import { logTrain } from '../training/sessionLog'
import {
  actionHoverId,
  hitAnyPanel,
  hitOrbit,
  hitPanelAction,
  hitPanelBody,
  hitPanelHeader,
  scrollPanelBody,
} from './hitTest'

/**
 * Gesture state machine:
 * - dwell: hover + hold → click (layer-locked to focused window)
 * - drag_panel: one-hand pinch on header → move window
 * - scroll_panel: one-hand pinch on body + vertical move → scroll
 * - zoom_panel: two-hand pinch while pointer over window → scale window
 * - flick zoom: pinch then snap fingers wide fast → max zoom current window
 * - fist close: five fingers curled → close window under hand / focused
 * - pan_canvas: one-hand pinch on empty canvas → pan left/right
 * - core_zoom: two-hand pinch on empty canvas (locked) → core scale
 */
export function useGestureOS() {
  const dwellRef = useRef<{
    id: string
    since: number
    el: HTMLElement | null
    lostSince: number | null
  } | null>(null)
  const grabOffset = useRef<{ dx: number; dy: number } | null>(null)
  const lastPinch = useRef(false)
  const lastY = useRef<number | null>(null)
  const lastX = useRef<number | null>(null)
  const scrollPanel = useRef<PanelId | null>(null)
  const zoomPanel = useRef<PanelId | null>(null)
  const twoHandLock = useRef<{ since: number; baseDist: number } | null>(null)
  const modeRef = useRef<string>('none')
  const pinchTrail = useRef<{ t: number; dist: number }[]>([])
  const lastFist = useRef(false)
  const fistCooldown = useRef(0)
  const lastHoverLog = useRef<string | null>(null)

  useEffect(() => {
    let raf = 0
    const tick = () => {
      const st = useVigilStore.getState()
      if (!st.vigilMode) {
        if (st.pressProgress || st.hoverTarget || st.grabTarget || st.gestureMode !== 'none') {
          st.setPressProgress(0)
          st.setHoverTarget(null)
          st.setGrabTarget(null)
          st.setMagnet(null)
          st.setGestureMode('none')
        }
        dwellRef.current = null
        twoHandLock.current = null
        modeRef.current = 'none'
        raf = requestAnimationFrame(tick)
        return
      }

      const idx = st.smoothIndex
      const hands = st.hands
      const primary = hands.right || hands.left
      const pinching = Boolean(primary?.pinch)
      const dwellMs = st.calibration.dwellMs
      const hitPx = st.calibration.hitPx
      const stickMs = Math.max(280, Math.min(600, Math.round(dwellMs * 0.55)))
      const btnPad = Math.max(28, Math.min(56, Math.round(hitPx * 0.55)))
      const training = st.trainingActive
      const now = performance.now()

      const trainStep = st.trainingStep
      const trainMove = training && trainStep === 'move'
      const trainScroll = training && trainStep === 'scroll'
      const headerPad = trainMove ? Math.max(48, Math.round(hitPx * 0.7)) : training ? 24 : 12
      // Layer stack: only the focused window is interactive (prevents dwell mistakes)
      const layerId = !training && st.focusedPanel ? st.focusedPanel : null
      const layerLock = Boolean(layerId)

      const actionEl = hitPanelAction(idx.x, idx.y, btnPad, layerId, layerLock)
      // During move/scroll drills: ignore random buttons, keep Skip chips usable
      const skipAction = Boolean(actionEl?.dataset.gestureAction?.startsWith('train-skip'))
      const action = (trainMove || trainScroll) && !skipAction ? null : actionEl
      const header = action ? null : hitPanelHeader(idx.x, idx.y, headerPad, layerId)
      const body = action || header ? null : hitPanelBody(idx.x, idx.y, layerId)
      const overPanel = hitAnyPanel(idx.x, idx.y, layerId)
      const orbit =
        training || overPanel || layerLock ? null : hitOrbit(idx.x, idx.y, hitPx)

      let hover: string | null = null
      if (action) hover = actionHoverId(action)
      else if (header) hover = `panel:${header}`
      else if (body) hover = `body:${body}`
      else if (orbit) hover = `orbit:${orbit}`
      st.setHoverTarget(hover)
      if (hover && hover !== lastHoverLog.current) {
        lastHoverLog.current = hover
        logTrain('hover', { hover, layer: layerId, training })
      }

      if (orbit) {
        const cx = window.innerWidth / 2
        const cy = window.innerHeight / 2
        const node = ORBIT_NODES.find((n) => n.id === orbit)!
        const r = Math.min(window.innerWidth, window.innerHeight) * 0.28
        st.setMagnet({
          x: (cx + Math.cos(node.angle) * r) / window.innerWidth,
          y: (cy + Math.sin(node.angle) * r * 0.72) / window.innerHeight,
        })
      } else st.setMagnet(null)

      // ——— Two-hand: lock before zoom (stops random zoom) ———
      const bothPinch = Boolean(hands.left?.pinch && hands.right?.pinch)
      if (bothPinch) {
        if (!twoHandLock.current) {
          twoHandLock.current = { since: now, baseDist: hands.twoHandDist || 0.2 }
        } else if (now - twoHandLock.current.since > 280) {
          const dist = hands.twoHandDist
          const base = twoHandLock.current.baseDist || dist
          const delta = dist - base
          // Dead zone — ignore tiny noise
          if (Math.abs(delta) > 0.025) {
            if (overPanel) {
              zoomPanel.current = overPanel
              const p = st.panels[overPanel]
              st.scalePanel(overPanel, p.scale + delta * 1.8)
              st.setGestureMode('zoom_panel')
              modeRef.current = 'zoom_panel'
              st.setStatus(`ZOOM WINDOW ${overPanel.toUpperCase()}`)
            } else if (!training) {
              st.setCoreScale(st.coreScale + delta * 1.6)
              st.setGestureMode('core_zoom')
              modeRef.current = 'core_zoom'
              if (st.coreScale > 1.45) st.triggerBurst()
            }
            twoHandLock.current.baseDist = dist
          }
        }
        lastPinch.current = pinching
        st.setPressProgress(0)
        raf = requestAnimationFrame(tick)
        return
      }
      twoHandLock.current = null
      if (modeRef.current === 'zoom_panel' || modeRef.current === 'core_zoom') {
        modeRef.current = 'none'
        st.setGestureMode('none')
        zoomPanel.current = null
      }

      // Early training steps: only dwell/pinch practice — no pan/scroll steal
      const trainLock =
        training &&
        ['hub', 'intro', 'show_hand', 'pinch', 'close', 'press', 'fist_close'].includes(trainStep)

      // Track pinch trail for flick-to-max-zoom
      if (pinching && primary) {
        pinchTrail.current.push({ t: now, dist: primary.pinchDist })
        if (pinchTrail.current.length > 24) pinchTrail.current.shift()
      }

      // ——— Fist close (five fingers) ———
      const fisting = Boolean(primary?.fist)
      if (fisting && !lastFist.current && now > fistCooldown.current) {
        const target =
          overPanel ||
          layerId ||
          (st.focusedPanel && st.panels[st.focusedPanel]?.open ? st.focusedPanel : null)
        if (target && (!training || trainStep === 'fist_close' || trainStep === 'close')) {
          logTrain('gesture_fist_close', { target, training, step: trainStep })
          st.closePanel(target)
          st.setStatus(`FIST CLOSE ${target.toUpperCase()}`)
          st.triggerBurst()
          fistCooldown.current = now + 700
          if (training && (trainStep === 'fist_close' || trainStep === 'close')) {
            st.setTrainingFeedback('Fist close OK')
            if (st.trainingPractice) st.setTrainingStep('hub')
            else if (trainStep === 'fist_close') st.setTrainingStep('hub')
          }
        }
      }
      lastFist.current = fisting

      // ——— One-hand pinch start ———
      if (pinching && !lastPinch.current && !trainLock) {
        pinchTrail.current = [{ t: now, dist: primary?.pinchDist || 0 }]
        // Move drill: grab from title bar OR anywhere on the SAMPLE window
        const grabId = header || (trainMove ? body || overPanel : null)
        if (grabId) {
          st.setGrabTarget(grabId)
          st.focusPanel(grabId)
          const p = st.panels[grabId]
          grabOffset.current = { dx: idx.x * 100 - p.x, dy: idx.y * 100 - p.y }
          st.setGestureMode('drag_panel')
          modeRef.current = 'drag_panel'
          st.setStatus(`MOVE ${p.title}`)
          st.triggerBurst()
          logTrain('gesture_drag_start', { panel: grabId, training })
        } else if (body && (!training || trainScroll)) {
          scrollPanel.current = body
          lastY.current = idx.y
          st.focusPanel(body)
          st.setGestureMode('scroll_panel')
          modeRef.current = 'scroll_panel'
          st.setStatus(`SCROLL ${body.toUpperCase()}`)
          logTrain('gesture_scroll_start', { panel: body, training })
        } else if (!action && !orbit && !training && !layerLock) {
          lastX.current = idx.x
          lastY.current = idx.y
          st.setGestureMode('pan_canvas')
          modeRef.current = 'pan_canvas'
          st.setStatus('PAN CANVAS')
          logTrain('gesture_pan_start')
        }
      }

      // Drag panel (training allows farther right into DROP ZONE)
      if (pinching && modeRef.current === 'drag_panel' && st.grabTarget && grabOffset.current) {
        const id = st.grabTarget as PanelId
        const maxX = training ? 88 : 70
        const maxY = training ? 72 : 70
        st.movePanel(
          id,
          Math.max(1, Math.min(maxX, idx.x * 100 - grabOffset.current.dx)),
          Math.max(8, Math.min(maxY, idx.y * 100 - grabOffset.current.dy)),
        )
      }

      // Scroll panel body (pinch + move up/down)
      if (pinching && modeRef.current === 'scroll_panel' && scrollPanel.current && lastY.current != null) {
        const boost = training ? 2.2 : 1
        const dy = (idx.y - lastY.current) * window.innerHeight * boost
        scrollPanelBody(scrollPanel.current, dy)
        lastY.current = idx.y
      }

      // Pan canvas left/right (and slight up/down)
      if (pinching && modeRef.current === 'pan_canvas' && lastX.current != null) {
        const dx = (idx.x - lastX.current) * 4
        const dy = lastY.current != null ? (idx.y - lastY.current) * 2.5 : 0
        st.setCanvasPan({ x: st.canvasPan.x + dx, y: st.canvasPan.y - dy })
        lastX.current = idx.x
        lastY.current = idx.y
      }

      if (!pinching && lastPinch.current) {
        // Include the open-hand frame so flick distance is measured after release
        if (primary) pinchTrail.current.push({ t: now, dist: primary.pinchDist })
        // Flick release: pinch → snap fingers wide & fast → max zoom current window
        const trail = pinchTrail.current
        if (trail.length >= 3 && primary) {
          const first = trail[0]
          const last = trail[trail.length - 1]
          const dt = Math.max(1, last.t - first.t)
          const dDist = last.dist - Math.min(...trail.map((s) => s.dist))
          const speed = dDist / (dt / 1000)
          const extreme = last.dist > Math.max(0.14, st.calibration.pinchThreshold * 3.2)
          const wasDragOrIdle = ['drag_panel', 'none', 'scroll_panel', 'dwell'].includes(
            modeRef.current,
          )
          if (
            extreme &&
            speed > 0.55 &&
            dt < 280 &&
            wasDragOrIdle &&
            (!training || trainStep === 'flick_zoom' || trainStep === 'zoom_window')
          ) {
            const target =
              (st.grabTarget as PanelId | null) ||
              overPanel ||
              layerId ||
              st.focusedPanel
            if (target && st.panels[target]?.open) {
              st.scalePanel(target, 1.8)
              st.focusPanel(target)
              st.setStatus(`FLICK ZOOM MAX ${target.toUpperCase()}`)
              st.triggerBurst()
              logTrain('gesture_flick_zoom', {
                target,
                speed,
                dist: last.dist,
                dt,
                training,
              })
              if (training && (trainStep === 'flick_zoom' || trainStep === 'zoom_window')) {
                st.setTrainingFeedback('Flick zoom OK')
                if (st.trainingPractice || trainStep === 'flick_zoom') st.setTrainingStep('hub')
              }
            }
          }
        }
        pinchTrail.current = []

        if (st.grabTarget) {
          const id = st.grabTarget as PanelId
          const p = st.panels[id]
          sendUltron({ type: 'ultron.panel', panel: id, state: { open: true, x: p.x, y: p.y } })
          logTrain('gesture_drag_end', { panel: id, x: p.x, y: p.y })
        }
        st.setGrabTarget(null)
        grabOffset.current = null
        scrollPanel.current = null
        lastY.current = null
        lastX.current = null
        if (['drag_panel', 'scroll_panel', 'pan_canvas'].includes(modeRef.current)) {
          modeRef.current = 'none'
          st.setGestureMode('none')
        }
      }
      lastPinch.current = pinching

      // ——— Dwell click (not while pinching / dragging) ———
      if (!pinching && modeRef.current === 'none') {
        if (hover) {
          if (!dwellRef.current || dwellRef.current.id !== hover) {
            const switchingToAction = hover.startsWith('action:')
            const mid = dwellRef.current && now - dwellRef.current.since > 80
            if (!dwellRef.current || switchingToAction || !mid) {
              dwellRef.current = { id: hover, since: now, el: action, lostSince: null }
              st.setPressProgress(0)
              st.setGestureMode('dwell')
            }
          } else {
            dwellRef.current.lostSince = null
            if (action) dwellRef.current.el = action
            const prog = Math.min(1, (now - dwellRef.current.since) / dwellMs)
            st.setPressProgress(prog)
            if (prog >= 1) {
              pushDwell(now - dwellRef.current.since)
              const fireId = dwellRef.current.id
              const fireEl = dwellRef.current.el
              dwellRef.current = { id: fireId + ':done', since: now, el: null, lostSince: null }
              st.setPressProgress(0)
              st.setGestureMode('none')
              logTrain('gesture_dwell_fire', { fireId, training, layer: layerId })
              if (fireId.startsWith('orbit:')) {
                st.openPanel(fireId.slice(6) as PanelId)
                st.triggerBurst()
              } else if (fireId.startsWith('panel:')) {
                st.focusPanel(fireId.slice(6) as PanelId)
              } else if (fireEl) {
                fireEl.click()
                st.setStatus(`TRIGGER ${fireEl.textContent?.trim() || 'ACTION'}`)
              }
            }
          }
        } else if (dwellRef.current && !dwellRef.current.id.endsWith(':done')) {
          if (dwellRef.current.lostSince == null) dwellRef.current.lostSince = now
          if (now - dwellRef.current.lostSince < stickMs) {
            st.setPressProgress(Math.min(1, (now - dwellRef.current.since) / dwellMs))
          } else {
            dwellRef.current = null
            st.setPressProgress(0)
            if (st.gestureMode === 'dwell') st.setGestureMode('none')
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
