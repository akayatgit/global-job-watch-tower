/**
 * Rank-step focus among campus towers by openings.
 * Visits EVERY tower: openings ASC, within same count a short nearest path.
 * Camera: smooth short glide (handled by SceneControls city focus).
 */

import { useVigilStore } from '../store/vigilStore'

export type CampusTower = {
  company_id: number
  name: string
  n: number
  x: number
  z: number
  h: number
}

const CITY_Y = -1.15
const CX = 0
const CZ = 0

/** Low → high openings; same-n ordered as a short spatial path */
let ranked: CampusTower[] = []
let cityLabel = ''

function dist2(a: { x: number; z: number }, b: { x: number; z: number }) {
  const dx = a.x - b.x
  const dz = a.z - b.z
  return dx * dx + dz * dz
}

/** Nearest-neighbour path through a same-count group */
function nnPath(
  group: CampusTower[],
  from: { x: number; z: number },
): CampusTower[] {
  const left = [...group]
  const out: CampusTower[] = []
  let cur = from
  while (left.length) {
    left.sort((a, b) => dist2(a, cur) - dist2(b, cur) || a.company_id - b.company_id)
    const next = left.shift()!
    out.push(next)
    cur = next
  }
  return out
}

function rebuildRanked(list: CampusTower[]) {
  const byN = new Map<number, CampusTower[]>()
  for (const t of list) {
    const g = byN.get(t.n)
    if (g) g.push(t)
    else byN.set(t.n, [t])
  }
  const ns = [...byN.keys()].sort((a, b) => a - b)
  const out: CampusTower[] = []
  let cursor: { x: number; z: number } = { x: CX, z: CZ }
  for (const n of ns) {
    const path = nnPath(byN.get(n)!, cursor)
    out.push(...path)
    if (path.length) cursor = path[path.length - 1]
  }
  ranked = out
}

export function setCampusNav(list: CampusTower[], label: string) {
  cityLabel = label
  rebuildRanked(list)
}

export function clearCampusNav() {
  ranked = []
  cityLabel = ''
}

function focusDist(h: number, roleHint = 1) {
  // Match NightCity — pull back so neighbours stay readable
  const rows = Math.max(1, Math.ceil(Math.max(0, roleHint) / 2))
  return 2.85 + h * 0.34 + rows * 0.12
}

function aimOf(t: CampusTower) {
  // Orbit / focus pivot = top-floor center (roof), not building mid-mass
  return { x: t.x, y: CITY_Y + t.h, z: t.z }
}

function focusTower(t: CampusTower) {
  const st = useVigilStore.getState()
  const selectId = `company:${t.company_id}`
  const aim = aimOf(t)
  st.setSceneSpin(false)
  st.setStatus(
    `FOCUS · ${t.name} · ${t.n} openings in ${cityLabel || 'campus'} · click again to open`,
  )
  // Glide first; selectFocus handoff lands at end of camera move
  st.requestCameraFocus({
    id: selectId,
    x: aim.x,
    y: aim.y,
    z: aim.z,
    distance: focusDist(t.h, Math.min(5, Math.max(1, t.n))),
  })
}

/**
 * higher → next in ranked list (more openings / next same-count neighbour)
 * lower → previous. Wraps. Never skips a same-count tower.
 */
export function stepCampusFocus(dir: 'higher' | 'lower') {
  if (!ranked.length) return
  const st = useVigilStore.getState()
  // Prefer in-flight destination so rapid ←/→ steps chain correctly
  const id =
    st.cameraFocus?.id?.startsWith('company:')
      ? st.cameraFocus.id
      : st.selectFocusId
  const curId = id?.startsWith('company:')
    ? Number(id.slice('company:'.length))
    : NaN
  let i = ranked.findIndex((t) => t.company_id === curId)

  if (i < 0) {
    // No focus yet: higher → top hiring, lower → smallest
    i = dir === 'higher' ? ranked.length - 1 : 0
  } else {
    const step = dir === 'higher' ? 1 : -1
    i = (i + step + ranked.length) % ranked.length
  }

  focusTower(ranked[i])
}
