/**
 * Rank-step focus among campus towers by openings.
 * Higher / lower rung by n; ties → nearest neighbour; still tied → path angle.
 * Camera: Spiderman whip-arcs between roofs.
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

function focusDist(h: number) {
  return 0.78 + h * 0.07
}

function roofOf(t: CampusTower) {
  return { x: t.x, y: CITY_Y + t.h + 0.15, z: t.z }
}

function focusTower(t: CampusTower, from: CampusTower | null) {
  const st = useVigilStore.getState()
  const selectId = `company:${t.company_id}`
  const roof = roofOf(t)
  const dist = focusDist(t.h)

  st.setSceneSpin(false)
  // Highlight immediately while the whip flies
  st.setSelectFocusId(selectId)
  st.setStatus(
    `FOCUS · ${t.name} · ${t.n} openings in ${cityLabel || 'campus'} · click again to open`,
  )

  if (from && from.company_id !== t.company_id) {
    const dx = t.x - from.x
    const dz = t.z - from.z
    const len = Math.hypot(dx, dz) || 1
    // Perpendicular swing + soar — Spiderman whip mid-beat
    const swing = Math.min(1.35, 0.55 + len * 0.45)
    const sx = (-dz / len) * swing
    const sz = (dx / len) * swing
    const midY =
      CITY_Y + Math.max(from.h, t.h) + 0.85 + Math.min(1.1, len * 0.35)
    const start = roofOf(from)
    st.requestCameraPath({
      waypoints: [
        start,
        {
          x: (from.x + t.x) * 0.5 + sx,
          y: midY,
          z: (from.z + t.z) * 0.5 + sz,
        },
        roof,
      ],
      distance: dist,
      endFocusId: selectId,
    })
    return
  }

  st.requestCameraFocus({
    id: selectId,
    x: roof.x,
    y: roof.y,
    z: roof.z,
    distance: dist,
  })
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
    if (pick) focusTower(pick, null)
    return
  }

  const pool =
    dir === 'higher'
      ? towers.filter((t) => t.n > cur.n)
      : towers.filter((t) => t.n < cur.n)

  if (!pool.length) {
    const wrapN =
      dir === 'higher'
        ? Math.min(...towers.map((t) => t.n))
        : Math.max(...towers.map((t) => t.n))
    const wrap = pickNear(
      origin,
      towers.filter((t) => t.n === wrapN && t.company_id !== cur.company_id),
    )
    if (!wrap) {
      const same = towers.filter((t) => t.company_id !== cur.company_id)
      const path = [...same].sort((a, b) => {
        const pa = pathKey(a)
        const pb = pathKey(b)
        if (Math.abs(pa - pb) > 1e-8) return pa - pb
        return a.company_id - b.company_id
      })
      const ordered = dir === 'higher' ? path : [...path].reverse()
      const nearFirst = pickNear(
        origin,
        ordered.slice(0, Math.min(3, ordered.length)),
      )
      if (nearFirst) focusTower(nearFirst, cur)
      else if (ordered[0]) focusTower(ordered[0], cur)
      return
    }
    focusTower(wrap, cur)
    return
  }

  const nextN =
    dir === 'higher'
      ? Math.min(...pool.map((t) => t.n))
      : Math.max(...pool.map((t) => t.n))
  const tier = pool.filter((t) => t.n === nextN)
  const pick = pickNear(origin, tier)
  if (pick) focusTower(pick, cur)
}
