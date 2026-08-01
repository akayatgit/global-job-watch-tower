import { ORBIT_NODES, useVigilStore, type PanelId } from '../store/vigilStore'
import { dist2 } from '../lib/lerp'

export function screenPoint(nx: number, ny: number) {
  return { x: nx * window.innerWidth, y: ny * window.innerHeight }
}

export function hitOrbit(nx: number, ny: number, hitPx: number): PanelId | 'remote' | null {
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

export function hitPanelHeader(
  nx: number,
  ny: number,
  padPx = 0,
  /** Layer stack: only the focused window receives hits */
  onlyId?: PanelId | null,
): PanelId | null {
  const panels = useVigilStore.getState().panels
  const pt = screenPoint(nx, ny)
  let best: PanelId | null = null
  let bestZ = -1
  for (const p of Object.values(panels)) {
    if (!p.open) continue
    if (onlyId && p.id !== onlyId) continue
    const el = document.querySelector(`[data-panel-id="${p.id}"]`) as HTMLElement | null
    if (!el) continue
    const head = el.querySelector('.panel-head') as HTMLElement | null
    if (!head) continue
    const rect = head.getBoundingClientRect()
    // Title bar is the grab strip — ignore tiny Close buttons unless pad is huge
    const ops = head.querySelector('.ops') as HTMLElement | null
    const opsLeft = ops ? ops.getBoundingClientRect().left - 8 : rect.right
    if (
      pt.x >= rect.left - padPx &&
      pt.x < opsLeft + padPx &&
      pt.y >= rect.top - padPx &&
      pt.y <= rect.bottom + padPx
    ) {
      if (p.z >= bestZ) {
        best = p.id
        bestZ = p.z
      }
    }
  }
  return best
}

export function hitPanelBody(
  nx: number,
  ny: number,
  onlyId?: PanelId | null,
): PanelId | null {
  const panels = useVigilStore.getState().panels
  const pt = screenPoint(nx, ny)
  let best: PanelId | null = null
  let bestZ = -1
  for (const p of Object.values(panels)) {
    if (!p.open) continue
    if (onlyId && p.id !== onlyId) continue
    const el = document.querySelector(`[data-panel-id="${p.id}"]`) as HTMLElement | null
    if (!el) continue
    const body = el.querySelector('.panel-body') as HTMLElement | null
    const rect = (body || el).getBoundingClientRect()
    if (pt.x >= rect.left && pt.x <= rect.right && pt.y >= rect.top && pt.y <= rect.bottom) {
      if (p.z >= bestZ) {
        best = p.id
        bestZ = p.z
      }
    }
  }
  return best
}

export function hitAnyPanel(
  nx: number,
  ny: number,
  onlyId?: PanelId | null,
): PanelId | null {
  return hitPanelHeader(nx, ny, 0, onlyId) || hitPanelBody(nx, ny, onlyId)
}

export function hitPanelAction(
  nx: number,
  ny: number,
  padPx: number,
  /** When set, only actions inside that panel (plus train/hud chips outside panels) */
  onlyPanelId?: PanelId | null,
  /** Layer focus: ignore dock / orbit chrome so dwell can't poke through */
  layerLock?: boolean,
): HTMLElement | null {
  const pt = screenPoint(nx, ny)
  const candidates = Array.from(
    document.querySelectorAll<HTMLElement>(
      'button[data-gesture-action], .chip[data-gesture-action], button.chip, .panel-head .ops button, .train-hit',
    ),
  )
  let best: { el: HTMLElement; d: number } | null = null
  for (const el of candidates) {
    if ((el instanceof HTMLButtonElement && el.disabled) || el.offsetParent === null) continue
    const action = el.dataset.gestureAction || ''
    if (layerLock) {
      const inPanel = el.closest('[data-panel-id]') as HTMLElement | null
      const panelId = inPanel?.dataset.panelId
      const isHud =
        action.startsWith('train-') ||
        action === 'start-training' ||
        el.closest('.status-right') != null ||
        el.closest('.training-coach') != null
      if (onlyPanelId) {
        if (panelId && panelId !== onlyPanelId) continue
        if (!panelId && !isHud && action.startsWith('dock-')) continue
        if (!panelId && action.startsWith('dock-')) continue
      } else if (action.startsWith('dock-')) {
        continue
      }
    }
    const r = el.getBoundingClientRect()
    if (
      pt.x >= r.left - padPx &&
      pt.x <= r.right + padPx &&
      pt.y >= r.top - padPx &&
      pt.y <= r.bottom + padPx
    ) {
      const d = dist2(pt.x, pt.y, (r.left + r.right) / 2, (r.top + r.bottom) / 2)
      if (!best || d < best.d) best = { el, d }
    }
  }
  return best?.el ?? null
}

export function scrollPanelBody(id: PanelId, dyPx: number) {
  const el = document.querySelector(
    `[data-panel-id="${id}"] .panel-body`,
  ) as HTMLElement | null
  if (el) el.scrollTop += dyPx
}

export function actionHoverId(el: HTMLElement): string {
  return `action:${el.dataset.gestureAction || el.textContent?.trim() || 'btn'}`
}
