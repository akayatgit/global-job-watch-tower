/**
 * Rank-step focus among campus towers by openings.
 * Higher / lower rung by n; ties → nearest neighbour; still tied → path angle.
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

let towers: CampusTower[] = []
let cityLabel = ''

export function setCampusNav(list: CampusTower[], label: string) {
  towers = list
  cityLabel = label
}

export function clearCampusNav() {
  towers = []
  cityLabel = ''
}

function dist2(a: CampusTower, b: { x: number; z: number }) {
  const dx = a.x - b.x
  const dz = a.z - b.z
  return dx * dx + dz * dz
}

/** Stable campus “path” — angle around pad, then company id */
function pathKey(t: CampusTower) {
  return Math.atan2(t.z - CZ, t.x - CX)
}

function pickNear(
  from: { x: number; z: number },
  candidates: CampusTower[],
): CampusTower | null {
  if (!candidates.length) return null
  return [...candidates].sort((a, b) => {
    const da = dist2(a, from)
    const db = dist2(b, from)
    if (Math.abs(da - db) > 1e-8) return da - db
    const pa = pathKey(a)
    const pb = pathKey(b)
    if (Math.abs(pa - pb) > 1e-8) return pa - pb
    return a.company_id - b.company_id
  })[0]
}

function focusTower(t: CampusTower) {
  const st = useVigilStore.getState()
  const selectId = `company:${t.company_id}`
  const roofY = CITY_Y + t.h + 0.15
  st.setSceneSpin(false)
  st.requestCameraFocus({
    id: selectId,
    x: t.x,
    y: roofY,
    z: t.z,
    distance: 1.55 + t.h * 0.12,
  })
  st.setStatus(
    `FOCUS · ${t.name} · ${t.n} openings in ${cityLabel || 'campus'} · click again to open`,
  )
}

/**
 * dir = higher → next rung up in openings; lower → next rung down.
 * Wrap at ends. No focus → jump to max (higher) or min (lower).
 */
export function stepCampusFocus(dir: 'higher' | 'lower') {
  if (!towers.length) return
  const st = useVigilStore.getState()
  const id = st.selectFocusId
  const curId = id?.startsWith('company:')
    ? Number(id.slice('company:'.length))
    : NaN
  const cur = towers.find((t) => t.company_id === curId) || null
  const origin = cur || { x: CX, z: CZ }

  if (!cur) {
    const targetN =
      dir === 'higher'
        ? Math.max(...towers.map((t) => t.n))
        : Math.min(...towers.map((t) => t.n))
    const pick = pickNear(
      origin,
      towers.filter((t) => t.n === targetN),
    )
    if (pick) focusTower(pick)
    return
  }

  const pool =
    dir === 'higher'
      ? towers.filter((t) => t.n > cur.n)
      : towers.filter((t) => t.n < cur.n)

  if (!pool.length) {
    // Wrap: higher at top → lowest rung; lower at bottom → highest rung
    const wrapN =
      dir === 'higher'
        ? Math.min(...towers.map((t) => t.n))
        : Math.max(...towers.map((t) => t.n))
    const wrap = pickNear(
      origin,
      towers.filter((t) => t.n === wrapN && t.company_id !== cur.company_id),
    )
    // If every tower shares the same n, walk the spatial path instead
    if (!wrap) {
      const same = towers.filter((t) => t.company_id !== cur.company_id)
      const path = [...same].sort((a, b) => {
        const pa = pathKey(a)
        const pb = pathKey(b)
        if (Math.abs(pa - pb) > 1e-8) return pa - pb
        return a.company_id - b.company_id
      })
      // Step along path in dir (higher → clockwise-ish)
      const ordered = dir === 'higher' ? path : [...path].reverse()
      const nearFirst = pickNear(origin, ordered.slice(0, Math.min(3, ordered.length)))
      if (nearFirst) focusTower(nearFirst)
      else if (ordered[0]) focusTower(ordered[0])
      return
    }
    focusTower(wrap)
    return
  }

  const nextN =
    dir === 'higher'
      ? Math.min(...pool.map((t) => t.n))
      : Math.max(...pool.map((t) => t.n))
  const tier = pool.filter((t) => t.n === nextN)
  const pick = pickNear(origin, tier)
  if (pick) focusTower(pick)
}
