/**
 * Ignore mesh "clicks" that are actually orbit/pan drag releases.
 * Pointerdown clears; movement past threshold marks a drag; click handlers
 * call wasDragClick() before acting.
 */

const THRESH_PX = 6

let downX = 0
let downY = 0
let dragged = false
let listening = false

function onDown(e: PointerEvent) {
  if (e.button !== 0 && e.button !== 2) return
  dragged = false
  downX = e.clientX
  downY = e.clientY
}

function onMove(e: PointerEvent) {
  if (dragged) return
  if (Math.hypot(e.clientX - downX, e.clientY - downY) >= THRESH_PX) {
    dragged = true
  }
}

/** Attach once to the WebGL canvas. */
export function attachPointerGuard(el: HTMLElement) {
  if (listening) return () => {}
  listening = true
  el.addEventListener('pointerdown', onDown, { capture: true })
  el.addEventListener('pointermove', onMove, { capture: true })
  return () => {
    listening = false
    el.removeEventListener('pointerdown', onDown, { capture: true })
    el.removeEventListener('pointermove', onMove, { capture: true })
  }
}

/** True if the current press moved enough to count as a camera drag. */
export function wasDragClick(): boolean {
  return dragged
}
