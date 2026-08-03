/**
 * Ignore mesh hover/focus during camera orbit/pan.
 *
 * While the mouse button is down (and especially while dragging), towers must
 * not light up or take focus. After a drag release, suppress hover until the
 * cursor moves again so the release position is not treated as a hover/focus.
 */

import { useEffect, useState } from 'react'

const THRESH_PX = 6

let downX = 0
let downY = 0
let upX = 0
let upY = 0
let pointerDown = false
let dragged = false
/** After a drag, ignore hover until the cursor moves again. */
let hoverSuppressed = false
let listening = false

type Listener = () => void
const listeners = new Set<Listener>()

function notify() {
  listeners.forEach((cb) => cb())
}

function onDown(e: PointerEvent) {
  if (e.button !== 0 && e.button !== 2) return
  pointerDown = true
  dragged = false
  hoverSuppressed = false
  downX = e.clientX
  downY = e.clientY
  notify()
}

function onMove(e: PointerEvent) {
  if (pointerDown && !dragged) {
    if (Math.hypot(e.clientX - downX, e.clientY - downY) >= THRESH_PX) {
      dragged = true
      hoverSuppressed = true
      notify()
    }
  }
  if (hoverSuppressed && !pointerDown) {
    if (Math.hypot(e.clientX - upX, e.clientY - upY) >= THRESH_PX) {
      hoverSuppressed = false
      notify()
    }
  }
}

function onUp(e: PointerEvent) {
  if (e.button !== 0 && e.button !== 2) return
  pointerDown = false
  upX = e.clientX
  upY = e.clientY
  if (dragged) {
    // Release after orbit/pan must not count as hover or focus.
    hoverSuppressed = true
  }
  notify()
  // Keep `dragged` true through the synthetic click, then clear.
  if (dragged) {
    window.setTimeout(() => {
      dragged = false
    }, 0)
  }
}

/** Attach once to the WebGL canvas. */
export function attachPointerGuard(el: HTMLElement) {
  if (listening) return () => {}
  listening = true
  el.addEventListener('pointerdown', onDown, { capture: true })
  el.addEventListener('pointermove', onMove, { capture: true })
  el.addEventListener('pointerup', onUp, { capture: true })
  el.addEventListener('pointercancel', onUp, { capture: true })
  return () => {
    listening = false
    el.removeEventListener('pointerdown', onDown, { capture: true })
    el.removeEventListener('pointermove', onMove, { capture: true })
    el.removeEventListener('pointerup', onUp, { capture: true })
    el.removeEventListener('pointercancel', onUp, { capture: true })
  }
}

/** Subscribe to drag / button-state changes (for clearing hover). */
export function onPointerGuardChange(cb: Listener) {
  listeners.add(cb)
  return () => {
    listeners.delete(cb)
  }
}

/** True while LMB/RMB is held — no hover or focus while pressing. */
export function isPointerDown(): boolean {
  return pointerDown
}

/** True if the current press moved enough to count as a camera drag. */
export function wasDragClick(): boolean {
  return dragged
}

/**
 * Mesh hover/focus blocked: button down, mid-drag, or post-drag until move.
 */
export function isMeshInteractionBlocked(): boolean {
  return pointerDown || hoverSuppressed
}

/** React hook — re-renders when drag/button block state changes. */
export function useMeshInteractionBlocked(): boolean {
  const [blocked, setBlocked] = useState(() => isMeshInteractionBlocked())
  useEffect(() => {
    const sync = () => setBlocked(isMeshInteractionBlocked())
    sync()
    return onPointerGuardChange(sync)
  }, [])
  return blocked
}
