import { useEffect, useMemo, useRef, useState } from 'react'
import { useFrame } from '@react-three/fiber'
import type { ThreeEvent } from '@react-three/fiber'
import { Billboard } from '@react-three/drei'
import * as THREE from 'three'
import { api, openingsCaption } from '../lib/api'
import { useVigilStore } from '../store/vigilStore'
import {
  isMeshInteractionBlocked,
  onPointerGuardChange,
  useMeshInteractionBlocked,
  wasDragClick,
} from './pointerGuard'
import { clearCampusNav, setCampusNav } from './campusNav'

/**
 * Cyberpunk glass campus — frosted glass, edge frames, multi-color glow,
 * dense white fabric, realistic mini cars, roof name/count + role clusters.
 */

type RoleHit = { title: string; n: number }

type SkyCo = {
  company_id: number
  name: string
  n: number
  sector_id: string
  sector_label: string
  roles?: RoleHit[]
}

type Corp = {
  company_id: number
  name: string
  n: number
  sector_id: string
  sector_label: string
  roles: RoleHit[]
  /** City key for multi-cluster campus (Jobs → City view) */
  city_key?: string
  city_label?: string
  x: number
  z: number
  w: number
  d: number
  h: number
  heat: number
  seed: number
  hue: number
  accent: string
  warmCore: boolean
}

type CityCluster = {
  city: string
  label: string
  companies: SkyCo[]
  stats?: { jobs?: number; companies?: number; max_n?: number }
}

type CampusPadSpec = { cx: number; cz: number; half: number; label: string }

type Dummy = {
  x: number
  z: number
  w: number
  d: number
  h: number
  seed: number
  tint: string
}

const CITY_Y = -1.15
const CAMPUS = { cx: 0, cz: 0, half: 1.55 }
const CITY_HALF = 7.0
const ROAD = [-4.2, -1.4, 1.4, 4.2]

/** Sector → cyberpunk accent hues (not all blue) */
const SECTOR_HUE: Record<string, number> = {
  tech_ai: 0.78, // violet
  tech_digital: 0.55, // cyan
  software: 0.58,
  manufacturing_advanced: 0.08, // amber
  healthcare: 0.42, // teal-green
  green_economy: 0.32, // green
  logistics: 0.12, // orange
  tourism: 0.92, // magenta
}

const ACCENTS = ['#38bdf8', '#a78bfa', '#fb923c', '#f472b6', '#34d399', '#fbbf24', '#22d3ee']

function hash01(n: number) {
  const x = Math.sin(n * 127.1) * 43758.5453
  return x - Math.floor(x)
}

function wrapName(name: string, max = 11): string[] {
  const words = name.trim().split(/\s+/)
  const lines: string[] = []
  let cur = ''
  for (const w of words) {
    const next = cur ? `${cur} ${w}` : w
    if (next.length <= max) cur = next
    else {
      if (cur) lines.push(cur)
      // hard-break long tokens
      if (w.length > max) {
        for (let i = 0; i < w.length; i += max) {
          lines.push(w.slice(i, i + max))
        }
        cur = ''
      } else cur = w
    }
  }
  if (cur) lines.push(cur)
  return lines.slice(0, 3)
}

/** Soft neon fill — no hard stroke outlines */
function neonFill(
  ctx: CanvasRenderingContext2D,
  text: string,
  x: number,
  y: number,
  fill: string,
  glow: string,
) {
  ctx.shadowColor = glow
  ctx.shadowBlur = 10
  ctx.fillStyle = fill
  ctx.fillText(text, x, y)
  ctx.shadowBlur = 0
}

function roundRect(
  ctx: CanvasRenderingContext2D,
  x: number,
  y: number,
  w: number,
  h: number,
  r: number,
) {
  const rr = Math.min(r, w / 2, h / 2)
  ctx.beginPath()
  ctx.moveTo(x + rr, y)
  ctx.arcTo(x + w, y, x + w, y + h, rr)
  ctx.arcTo(x + w, y + h, x, y + h, rr)
  ctx.arcTo(x, y + h, x, y, rr)
  ctx.arcTo(x, y, x + w, y, rr)
  ctx.closePath()
}

/** Measure-aware wrap; keeps ×N on the last line. */
function wrapRoleLines(
  ctx: CanvasRenderingContext2D,
  title: string,
  n: number,
  maxW: number,
): string[] {
  const words = title.trim().split(/\s+/).filter(Boolean)
  const lines: string[] = []
  let cur = ''
  for (const w of words) {
    const next = cur ? `${cur} ${w}` : w
    if (ctx.measureText(next).width <= maxW) cur = next
    else {
      if (cur) lines.push(cur)
      // Hard-break very long tokens
      if (ctx.measureText(w).width > maxW) {
        let chunk = ''
        for (const ch of w) {
          const t = chunk + ch
          if (ctx.measureText(t).width > maxW && chunk) {
            lines.push(chunk)
            chunk = ch
          } else chunk = t
        }
        cur = chunk
      } else cur = w
    }
  }
  if (cur) lines.push(cur)
  const out = lines.slice(0, 3)
  if (n > 1 && out.length) {
    const last = `${out[out.length - 1]} ×${n}`
    if (ctx.measureText(last).width <= maxW) out[out.length - 1] = last
    else if (out.length < 3) out.push(`×${n}`)
    else out[out.length - 1] = last // allow slight overflow on ×N
  }
  return out
}

/** Floating roof text — name + count + caption. Soft neon, no stroke. */
function makeRoofLabel(
  name: string,
  jobs: number,
  days: number,
  captionOverride?: string,
) {
  const lines = wrapName(name, 11)
  const caption =
    captionOverride ||
    (jobs === 1
      ? openingsCaption(days).replace(/^Openings/, 'Opening')
      : openingsCaption(days))
  const c = document.createElement('canvas')
  c.width = 512
  c.height = 36 + lines.length * 34 + 100
  const ctx = c.getContext('2d')!
  ctx.clearRect(0, 0, c.width, c.height)
  ctx.textAlign = 'center'
  ctx.textBaseline = 'middle'
  const cx = c.width / 2
  ctx.font = '800 26px Orbitron, sans-serif'
  lines.forEach((ln, i) => {
    neonFill(ctx, ln.toUpperCase(), cx, 28 + i * 30, '#ffffff', '#38bdf8')
  })
  const numY = 36 + lines.length * 32 + 26
  const num = jobs > 999 ? '999+' : String(jobs)
  ctx.font = '900 56px Orbitron, sans-serif'
  neonFill(ctx, num, cx, numY, '#ffffff', '#f97316')
  ctx.font = '700 15px Rajdhani, sans-serif'
  neonFill(ctx, caption, cx, numY + 34, '#e0f2fe', '#22d3ee')
  const tex = new THREE.CanvasTexture(c)
  tex.colorSpace = THREE.SRGBColorSpace
  tex.anisotropy = 8
  return { tex, aspect: c.width / c.height }
}

/**
 * Cyberpunk role card — yellow neon text, padded & centered wrap,
 * sized under the openings number (no stroke outlines).
 */
function makeRoleLabel(title: string, n: number) {
  const PAD_X = 20
  const PAD_Y = 14
  const LINE = 28
  const FONT = '700 28px Rajdhani, sans-serif' // ~50% of openings 56
  const innerW = 220
  const measure = document.createElement('canvas').getContext('2d')!
  measure.font = FONT
  const lines = wrapRoleLines(measure, title, n, innerW)
  const contentH = Math.max(LINE, lines.length * LINE)
  const c = document.createElement('canvas')
  c.width = innerW + PAD_X * 2
  c.height = contentH + PAD_Y * 2
  const ctx = c.getContext('2d')!
  ctx.clearRect(0, 0, c.width, c.height)
  // Cyber glass plate
  const inset = 2
  roundRect(ctx, inset, inset, c.width - inset * 2, c.height - inset * 2, 7)
  const g = ctx.createLinearGradient(0, 0, c.width, c.height)
  g.addColorStop(0, 'rgba(12, 8, 28, 0.92)')
  g.addColorStop(1, 'rgba(6, 16, 32, 0.9)')
  ctx.fillStyle = g
  ctx.fill()
  // Neon rim
  ctx.strokeStyle = 'rgba(250, 204, 21, 0.75)'
  ctx.lineWidth = 1.5
  ctx.shadowColor = '#facc15'
  ctx.shadowBlur = 6
  ctx.stroke()
  ctx.shadowBlur = 0
  // Inner cyan hairline
  roundRect(
    ctx,
    inset + 2,
    inset + 2,
    c.width - inset * 2 - 4,
    c.height - inset * 2 - 4,
    5,
  )
  ctx.strokeStyle = 'rgba(34, 211, 238, 0.35)'
  ctx.lineWidth = 1
  ctx.stroke()

  ctx.textAlign = 'center'
  ctx.textBaseline = 'middle'
  ctx.font = FONT
  const cx = c.width / 2
  const startY = PAD_Y + LINE / 2
  lines.forEach((ln, i) => {
    neonFill(ctx, ln, cx, startY + i * LINE, '#fde047', '#f59e0b')
  })
  const tex = new THREE.CanvasTexture(c)
  tex.colorSpace = THREE.SRGBColorSpace
  tex.anisotropy = 8
  return { tex, aspect: c.width / c.height }
}

/**
 * 2-column grid UNDER the name/count — stays inside the roof cluster
 * (no wide left/right that crops off the browser).
 */
function roleGridSlot(
  i: number,
  total: number,
  cardW: number,
  cardH: number,
  bannerH: number,
): [number, number] {
  const cols = 2
  const gapX = 0.018
  const gapY = 0.014
  const col = i % cols
  const row = Math.floor(i / cols)
  const lastAlone = total % 2 === 1 && i === total - 1
  const ox = lastAlone
    ? 0
    : (col - 0.5) * (cardW + gapX)
  const oy = -(bannerH * 0.52) - row * (cardH + gapY) - cardH * 0.5
  return [ox, oy]
}

function focusDistance(h: number) {
  // Tight drone pull-in on the roof
  return 0.78 + h * 0.07
}

/** Role cards must never outnumber openings on the building. */
function capRoles(roles: RoleHit[] | undefined, jobN: number): RoleHit[] {
  if (!roles?.length || jobN <= 0) return []
  const out: RoleHit[] = []
  let used = 0
  for (const r of roles) {
    if (out.length >= Math.min(5, jobN) || used >= jobN) break
    const rn = Math.min(Math.max(1, r.n || 1), jobN - used)
    const title = (r.title || '').trim()
    if (!title) continue
    out.push({ title, n: rn })
    used += rn
  }
  return out
}

function layoutCorporates(
  companies: SkyCo[],
  maxN: number,
  ox = CAMPUS.cx,
  oz = CAMPUS.cz,
  cityKey?: string,
  cityLabel?: string,
  maxBuildings = 16,
): Corp[] {
  const sorted = [...companies].sort((a, b) => b.n - a.n).slice(0, maxBuildings)
  const cols = Math.ceil(Math.sqrt(sorted.length))
  const gap = 0.52
  return sorted.map((c, i) => {
    const row = Math.floor(i / cols)
    const col = i % cols
    const nRows = Math.ceil(sorted.length / cols)
    const seed = c.company_id * 13.37 + (cityKey ? hash01(cityKey.length * 9.1) * 100 : 0)
    const heat = c.n / Math.max(maxN, 1)
    const baseHue = SECTOR_HUE[c.sector_id] ?? 0.55
    const hue = (baseHue + (hash01(seed) - 0.5) * 0.08 + 1) % 1
    return {
      company_id: c.company_id,
      name: c.name,
      n: c.n,
      sector_id: c.sector_id,
      sector_label: c.sector_label,
      roles: capRoles(c.roles, c.n),
      city_key: cityKey,
      city_label: cityLabel,
      x: ox + (col - (cols - 1) / 2) * gap + (hash01(seed) - 0.5) * 0.04,
      z: oz + (row - (nRows - 1) / 2) * gap + (hash01(seed + 1) - 0.5) * 0.04,
      w: 0.3 + heat * 0.14 + hash01(seed + 2) * 0.05,
      d: 0.28 + heat * 0.12 + hash01(seed + 3) * 0.05,
      h: 0.95 + heat * 2.8 + hash01(seed + 4) * 0.3,
      heat,
      seed,
      hue,
      accent: ACCENTS[Math.floor(hash01(seed + 5) * ACCENTS.length)],
      warmCore: hash01(seed + 6) > 0.72,
    }
  })
}

/** Spread city districts along X — one campus pad per city. */
function layoutJobClusters(clusters: CityCluster[]): {
  corps: Corp[]
  pads: CampusPadSpec[]
  maxN: number
} {
  const n = clusters.length
  const gap = n <= 2 ? 5.4 : n <= 4 ? 4.8 : 4.2
  const pads: CampusPadSpec[] = []
  const corps: Corp[] = []
  let maxN = 1
  clusters.forEach((cl) => {
    maxN = Math.max(maxN, cl.stats?.max_n || 1)
    for (const c of cl.companies || []) maxN = Math.max(maxN, c.n)
  })
  clusters.forEach((cl, i) => {
    const cx = (i - (n - 1) / 2) * gap
    const cz = 0
    const half = Math.min(1.7, 1.15 + Math.sqrt((cl.companies || []).length) * 0.18)
    pads.push({ cx, cz, half, label: cl.label })
    corps.push(
      ...layoutCorporates(
        cl.companies || [],
        maxN,
        cx,
        cz,
        cl.city,
        cl.label,
        10,
      ),
    )
  })
  return { corps, pads, maxN }
}

function layoutDummies(corps: Corp[], pads: CampusPadSpec[]): Dummy[] {
  const list: Dummy[] = []
  let i = 0
  const half = Math.max(CITY_HALF, ...pads.map((p) => Math.abs(p.cx) + p.half + 2.5), 7)
  for (let gx = -half; gx <= half; gx += 0.4) {
    for (let gz = -CITY_HALF; gz <= CITY_HALF; gz += 0.4) {
      i++
      if (ROAD.some((r) => Math.abs(gx - r) < 0.36 || Math.abs(gz - r) < 0.36)) continue
      if (
        pads.some(
          (p) =>
            Math.abs(gx - p.cx) < p.half + 0.3 && Math.abs(gz - p.cz) < p.half + 0.3,
        )
      )
        continue
      if (hash01(i * 3.1) < 0.1) continue
      if (corps.some((c) => Math.hypot(c.x - gx, c.z - gz) < 0.42)) continue
      const seed = i * 7.7
      const tint =
        hash01(seed) > 0.85
          ? '#e2e8f0'
          : hash01(seed + 1) > 0.9
            ? '#cbd5e1'
            : '#f1f5f9'
      list.push({
        x: gx + (hash01(seed) - 0.5) * 0.06,
        z: gz + (hash01(seed + 1) - 0.5) * 0.06,
        w: 0.2 + hash01(seed + 2) * 0.2,
        d: 0.18 + hash01(seed + 3) * 0.18,
        h: 0.22 + hash01(seed + 4) * 1.35,
        seed,
        tint,
      })
    }
  }
  return list
}

function EdgeFrame({
  w,
  h,
  d,
  color,
  opacity,
}: {
  w: number
  h: number
  d: number
  color: string
  opacity: number
}) {
  const t = 0.012
  const mats = (
    <meshBasicMaterial color={color} transparent opacity={opacity} />
  )
  return (
    <group>
      {/* Vertical corners */}
      {[
        [w / 2, 0, d / 2],
        [-w / 2, 0, d / 2],
        [w / 2, 0, -d / 2],
        [-w / 2, 0, -d / 2],
      ].map(([x, , z], i) => (
        <mesh key={`v${i}`} position={[x as number, h / 2, z as number]}>
          <boxGeometry args={[t, h, t]} />
          {mats}
        </mesh>
      ))}
      {/* Top rim */}
      <mesh position={[0, h, 0]}>
        <boxGeometry args={[w + t, t, d + t]} />
        {mats}
      </mesh>
      {/* Mid belt */}
      <mesh position={[0, h * 0.55, 0]}>
        <boxGeometry args={[w + t * 0.5, t * 0.7, d + t * 0.5]} />
        {mats}
      </mesh>
    </group>
  )
}

function DummyBuilding({
  b,
  dim,
}: {
  b: Dummy
  dim: boolean
}) {
  return (
    <group position={[b.x, 0, b.z]}>
      <mesh position={[0, b.h / 2, 0]} castShadow receiveShadow>
        <boxGeometry args={[b.w, b.h, b.d]} />
        <meshStandardMaterial
          color={b.tint}
          roughness={0.78}
          metalness={0.08}
          transparent
          opacity={dim ? 0.35 : 1}
        />
      </mesh>
      {/* Tiny window dots */}
      <mesh position={[0, b.h * 0.55, b.d / 2 + 0.002]}>
        <planeGeometry args={[b.w * 0.7, b.h * 0.55]} />
        <meshBasicMaterial
          color="#94a3b8"
          transparent
          opacity={dim ? 0.08 : 0.18}
        />
      </mesh>
      <EdgeFrame
        w={b.w}
        h={b.h}
        d={b.d}
        color="#94a3b8"
        opacity={dim ? 0.15 : 0.35}
      />
    </group>
  )
}

function GlassTower({
  t,
  cityLabel,
  windowDays,
  openingsCaptionText,
  sceneDimmed,
  onHoverEnter,
  onHoverLeave,
}: {
  t: Corp
  cityLabel: string
  windowDays: number
  /** When set (Jobs city view), replaces the hiring-window caption. */
  openingsCaptionText?: string
  /** True when any tower is focused or hovered — dim non-active ones */
  sceneDimmed: boolean
  onHoverEnter: (id: string) => void
  onHoverLeave: (id: string) => void
}) {
  const selectId = `company:${t.company_id}`
  const focused = useVigilStore((s) => s.selectFocusId === selectId)
  const [hot, setHot] = useState(false)
  const interactionBlocked = useMeshInteractionBlocked()
  const lit = focused || (hot && !interactionBlocked)
  const dim = sceneDimmed && !lit
  const shell = useRef<THREE.MeshStandardMaterial>(null)
  const banner = useMemo(
    () => makeRoofLabel(t.name, t.n, windowDays, openingsCaptionText),
    [t.name, t.n, windowDays, openingsCaptionText],
  )
  const roleTex = useMemo(
    () => t.roles.map((r) => makeRoleLabel(r.title, r.n)),
    [t.roles],
  )
  const glassCol = useMemo(() => {
    const c = new THREE.Color()
    c.setHSL(t.hue, 0.72, 0.48)
    return c
  }, [t.hue])
  const warmCol = useMemo(() => new THREE.Color('#fb923c'), [])

  useEffect(() => {
    if (interactionBlocked && hot) {
      setHot(false)
      onHoverLeave(selectId)
    }
  }, [interactionBlocked, hot, onHoverLeave, selectId])

  useFrame((state) => {
    const breath = Math.sin(state.clock.elapsedTime * 1.4 + t.seed) * 0.1
    if (shell.current) {
      const base = lit ? 1.05 : dim ? 0.08 : 0.48
      shell.current.emissiveIntensity = base + breath * (lit ? 0.28 : 0.08)
      shell.current.opacity = lit ? 0.82 : dim ? 0.12 : 0.5
    }
  })

  const enter = (e: ThreeEvent<PointerEvent>) => {
    e.stopPropagation()
    // No hover while button held / orbiting / post-drag release
    if (isMeshInteractionBlocked()) return
    setHot(true)
    onHoverEnter(selectId)
    useVigilStore.setState({
      statusLine: focused
        ? `FOCUSED · ${t.name} · click again to open`
        : `PICK · ${t.name} · ${t.n}`,
    })
  }
  const leave = () => {
    setHot(false)
    onHoverLeave(selectId)
  }

  const onClick = (e: ThreeEvent<MouseEvent>) => {
    e.stopPropagation()
    // Drag-orbit release must never focus a tower
    if (wasDragClick() || isMeshInteractionBlocked()) return
    const st = useVigilStore.getState()
    // Focus on the ROOF / top of building
    const roofY = CITY_Y + t.h + 0.15
    const place = t.city_label || cityLabel
    if (st.selectFocusId === selectId) {
      if (t.city_key) st.setCityFilter(t.city_key)
      st.openCompanyJobs(t.company_id, t.name, windowDays || 7)
      st.setStatus(`OPEN · ${t.name}`)
      return
    }
    st.setSceneSpin(false)
    st.requestCameraFocus({
      id: selectId,
      x: t.x,
      y: roofY,
      z: t.z,
      distance: focusDistance(t.h),
    })
    st.setStatus(
      `FOCUS · ${t.name} · ${t.n} in ${place} · click again to open`,
    )
  }

  const floors = Math.max(4, Math.floor(t.h / 0.22))
  const bannerH = 0.2 + wrapName(t.name, 11).length * 0.048
  const bannerW = bannerH * banner.aspect * (lit ? 1.03 : 1)
  const cardOrder = lit ? 2000 : dim ? 2 : 20
  // Compact role cards under the label — width capped so they stay on screen
  const roleH = bannerH * 0.26
  const roleWMax = bannerW * 0.46

  return (
    <group position={[t.x, 0, t.z]}>
      <mesh
        position={[0, t.h / 2, 0]}
        onClick={onClick}
        onPointerOver={enter}
        onPointerOut={leave}
      >
        <boxGeometry args={[t.w * 1.4, t.h, t.d * 1.4]} />
        <meshBasicMaterial transparent opacity={0} depthWrite={false} />
      </mesh>

      {/* Interior core (warm accent on some towers) */}
      <mesh position={[0, t.h * 0.45, 0]}>
        <boxGeometry args={[t.w * 0.55, t.h * 0.75, t.d * 0.55]} />
        <meshStandardMaterial
          color={t.warmCore ? warmCol : '#1e293b'}
          emissive={t.warmCore ? warmCol : glassCol}
          emissiveIntensity={dim ? 0.03 : lit ? 0.75 : t.warmCore ? 0.55 : 0.2}
          transparent
          opacity={dim ? 0.1 : 0.85}
        />
      </mesh>

      {/* Floor plates + mullion feel */}
      {Array.from({ length: floors }).map((_, i) => {
        const y = 0.1 + (i / floors) * (t.h - 0.15)
        return (
          <group key={i}>
            <mesh position={[0, y, 0]}>
              <boxGeometry args={[t.w * 0.94, 0.018, t.d * 0.94]} />
              <meshStandardMaterial
                color="#e2e8f0"
                roughness={0.55}
                transparent
                opacity={dim ? 0.08 : 0.85}
              />
            </mesh>
            {!dim && i % 2 === 0 && (
              <mesh position={[t.w * 0.15, y + 0.02, 0]}>
                <boxGeometry args={[0.04, 0.02, t.d * 0.35]} />
                <meshBasicMaterial color="#64748b" transparent opacity={0.5} />
              </mesh>
            )}
          </group>
        )
      })}

      {/* Glass facade shell */}
      <mesh position={[0, t.h / 2, 0]} castShadow>
        <boxGeometry args={[t.w, t.h, t.d]} />
        <meshStandardMaterial
          ref={shell}
          color={glassCol}
          emissive={glassCol}
          emissiveIntensity={0.5}
          transparent
          opacity={0.52}
          roughness={0.12}
          metalness={0.35}
          depthWrite={false}
        />
      </mesh>

      {/* Window grid planes (glass morphism detail) */}
      {[
        [0, t.h / 2, t.d / 2 + 0.003],
        [0, t.h / 2, -t.d / 2 - 0.003],
      ].map(([x, y, z], i) => (
        <mesh key={`f${i}`} position={[x, y, z]}>
          <planeGeometry args={[t.w * 0.96, t.h * 0.96]} />
          <meshBasicMaterial
            color={t.accent}
            transparent
            opacity={dim ? 0.03 : lit ? 0.22 : 0.12}
            side={THREE.DoubleSide}
          />
        </mesh>
      ))}

      <EdgeFrame
        w={t.w}
        h={t.h}
        d={t.d}
        color={lit ? t.accent : '#e2e8f0'}
        opacity={dim ? 0.08 : lit ? 0.95 : 0.55}
      />

      {lit && (
        <pointLight
          position={[0, t.h * 0.7, 0]}
          color={t.accent}
          intensity={focused ? 1.55 : 1.15}
          distance={2.8}
          decay={2}
        />
      )}

      {/* Roof cluster: name/count + 2-col cyberpunk role cards underneath */}
      <Billboard
        follow
        position={[
          0,
          t.h +
            0.14 +
            bannerH / 2 +
            Math.ceil(roleTex.length / 2) * roleH * 0.28,
          0,
        ]}
      >
        <group scale={lit ? 1.04 : 1}>
          <mesh
            onClick={onClick}
            onPointerOver={enter}
            onPointerOut={leave}
            visible={lit || !dim}
            renderOrder={cardOrder}
          >
            <planeGeometry args={[bannerW, bannerH]} />
            <meshBasicMaterial
              map={banner.tex}
              transparent
              opacity={dim ? 0.18 : 1}
              depthTest={!lit}
              depthWrite={false}
              toneMapped={false}
            />
          </mesh>
          {roleTex.map((rt, i) => {
            const rh = roleH
            const rw = Math.min(rh * rt.aspect, roleWMax)
            const [ox, oy] = roleGridSlot(
              i,
              roleTex.length,
              roleWMax,
              rh,
              bannerH,
            )
            return (
              <mesh
                key={i}
                position={[ox, oy, 0.02]}
                onClick={onClick}
                onPointerOver={enter}
                onPointerOut={leave}
                visible={lit || !dim}
                renderOrder={cardOrder + 1}
              >
                <planeGeometry args={[rw, rh]} />
                <meshBasicMaterial
                  map={rt.tex}
                  transparent
                  opacity={dim ? 0.14 : 1}
                  depthTest={!lit}
                  depthWrite={false}
                  toneMapped={false}
                />
              </mesh>
            )
          })}
        </group>
      </Billboard>
    </group>
  )
}

function CampusPad({
  dim,
  pad = { cx: CAMPUS.cx, cz: CAMPUS.cz, half: CAMPUS.half, label: '' },
}: {
  dim: boolean
  pad?: CampusPadSpec
}) {
  return (
    <group position={[pad.cx, 0.012, pad.cz]}>
      <mesh rotation={[-Math.PI / 2, 0, 0]} receiveShadow>
        <planeGeometry args={[pad.half * 2.25, pad.half * 2.25]} />
        <meshStandardMaterial
          color="#0f172a"
          roughness={0.45}
          metalness={0.2}
          transparent
          opacity={dim ? 0.5 : 1}
        />
      </mesh>
      <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, 0.004, 0]}>
        <planeGeometry args={[pad.half * 2.35, pad.half * 2.35]} />
        <meshBasicMaterial color="#a78bfa" transparent opacity={dim ? 0.15 : 0.4} />
      </mesh>
    </group>
  )
}

/** Collective city name — no card, big bold white, subtle glow, above roofs. */
function makeCityFlag(label: string) {
  const text = label.trim().toUpperCase()
  const c = document.createElement('canvas')
  c.width = 1024
  c.height = 160
  const ctx = c.getContext('2d')!
  ctx.clearRect(0, 0, c.width, c.height)
  ctx.textAlign = 'center'
  ctx.textBaseline = 'middle'
  ctx.font = '900 92px Orbitron, Rajdhani, sans-serif'
  // Soft bloom layers (no plate / card)
  ctx.shadowColor = 'rgba(255,255,255,0.85)'
  ctx.shadowBlur = 28
  ctx.fillStyle = 'rgba(255,255,255,0.55)'
  ctx.fillText(text, c.width / 2, c.height / 2)
  ctx.shadowBlur = 14
  ctx.fillStyle = 'rgba(255,255,255,0.9)'
  ctx.fillText(text, c.width / 2, c.height / 2)
  ctx.shadowBlur = 4
  ctx.fillStyle = '#ffffff'
  ctx.fillText(text, c.width / 2, c.height / 2)
  ctx.shadowBlur = 0
  const tex = new THREE.CanvasTexture(c)
  tex.colorSpace = THREE.SRGBColorSpace
  tex.anisotropy = 8
  return tex
}

function CityFlag({
  label,
  x,
  y,
  z,
  dim,
}: {
  label: string
  x: number
  y: number
  z: number
  dim: boolean
}) {
  const tex = useMemo(() => makeCityFlag(label), [label])
  const pulse = useRef(0)
  const mat = useRef<THREE.MeshBasicMaterial>(null)
  useFrame((state) => {
    pulse.current = 0.82 + Math.sin(state.clock.elapsedTime * 1.1) * 0.1
    if (mat.current) {
      mat.current.opacity = dim ? 0.28 : pulse.current
    }
  })
  if (!label) return null
  const w = Math.min(3.6, 1.4 + label.length * 0.14)
  return (
    <Billboard position={[x, y, z]} follow>
      <mesh>
        <planeGeometry args={[w, w * (160 / 1024)]} />
        <meshBasicMaterial
          ref={mat}
          map={tex}
          transparent
          depthWrite={false}
          opacity={0.92}
        />
      </mesh>
    </Billboard>
  )
}

function Ground({ half = CITY_HALF }: { half?: number }) {
  const roadTex = useMemo(() => {
    const c = document.createElement('canvas')
    c.width = 1024
    c.height = 1024
    const ctx = c.getContext('2d')!
    ctx.fillStyle = '#dbe3ec'
    ctx.fillRect(0, 0, 1024, 1024)
    ctx.strokeStyle = 'rgba(100,116,139,0.2)'
    ctx.lineWidth = 1
    for (let i = 0; i < 1024; i += 28) {
      ctx.beginPath()
      ctx.moveTo(i, 0)
      ctx.lineTo(i, 1024)
      ctx.stroke()
      ctx.beginPath()
      ctx.moveTo(0, i)
      ctx.lineTo(1024, i)
      ctx.stroke()
    }
    const toPx = (w: number) => ((w + CITY_HALF) / (CITY_HALF * 2)) * 1024
    const half = (0.48 / (CITY_HALF * 2)) * 1024
    for (const r of ROAD) {
      const p = toPx(r)
      // Deep navy cyberpunk asphalt
      ctx.fillStyle = '#0b1220'
      ctx.fillRect(p - half, 0, half * 2, 1024)
      ctx.fillRect(0, p - half, 1024, half * 2)
    }
    // Lane marks + crosswalks
    ctx.strokeStyle = 'rgba(255,255,255,0.7)'
    ctx.lineWidth = 2
    ctx.setLineDash([16, 14])
    for (const r of ROAD) {
      const p = toPx(r)
      ctx.beginPath()
      ctx.moveTo(p, 0)
      ctx.lineTo(p, 1024)
      ctx.stroke()
      ctx.beginPath()
      ctx.moveTo(0, p)
      ctx.lineTo(1024, p)
      ctx.stroke()
    }
    ctx.setLineDash([])
    ctx.fillStyle = 'rgba(255,255,255,0.55)'
    for (const x of ROAD) {
      for (const z of ROAD) {
        const px = toPx(x)
        const pz = toPx(z)
        for (let k = -6; k <= 6; k++) {
          ctx.fillRect(px - half * 0.7, pz + k * 5 - 1, half * 1.4, 2)
        }
      }
    }
    const tex = new THREE.CanvasTexture(c)
    tex.colorSpace = THREE.SRGBColorSpace
    return tex
  }, [])

  return (
    <mesh rotation={[-Math.PI / 2, 0, 0]} receiveShadow>
      <planeGeometry args={[half * 2.15, Math.max(CITY_HALF, half * 0.55) * 2.15]} />
      <meshStandardMaterial map={roadTex} roughness={0.88} metalness={0.05} />
    </mesh>
  )
}

/** More realistic mini cars — body + cabin + lights */
function Traffic({ dim }: { dim: boolean }) {
  const cars = useMemo(() => {
    const colors = ['#fb923c', '#e2e8f0', '#38bdf8', '#1e293b', '#f472b6', '#a78bfa']
    const list: {
      axis: 'h' | 'v'
      fixed: number
      dir: 1 | -1
      pos: number
      speed: number
      color: string
    }[] = []
    let i = 0
    for (const r of ROAD) {
      for (const dir of [1, -1] as const) {
        for (let k = 0; k < 3; k++) {
          list.push({
            axis: i % 2 === 0 ? 'h' : 'v',
            fixed: r + (k % 2 === 0 ? 0.12 : -0.12),
            dir,
            pos: -CITY_HALF + hash01(i * 9 + k) * CITY_HALF * 1.9,
            speed: 0.55 + hash01(i + k) * 0.55,
            color: colors[(i + k) % colors.length],
          })
          i++
        }
      }
    }
    return list.slice(0, 28)
  }, [])
  const refs = useRef<(THREE.Group | null)[]>([])

  useFrame((_, dt) => {
    cars.forEach((c, i) => {
      c.pos += c.dir * c.speed * dt
      if (c.pos > CITY_HALF) c.pos = -CITY_HALF
      if (c.pos < -CITY_HALF) c.pos = CITY_HALF
      const g = refs.current[i]
      if (!g) return
      if (c.axis === 'h') {
        g.position.set(c.pos, 0.045, c.fixed)
        g.rotation.y = c.dir > 0 ? 0 : Math.PI
      } else {
        g.position.set(c.fixed, 0.045, c.pos)
        g.rotation.y = c.dir > 0 ? -Math.PI / 2 : Math.PI / 2
      }
    })
  })

  return (
    <group>
      {cars.map((c, i) => (
        <group
          key={i}
          ref={(el) => {
            refs.current[i] = el
          }}
        >
          {/* Body */}
          <mesh>
            <boxGeometry args={[0.1, 0.032, 0.048]} />
            <meshStandardMaterial
              color={c.color}
              roughness={0.35}
              metalness={0.4}
              transparent
              opacity={dim ? 0.25 : 1}
            />
          </mesh>
          {/* Cabin */}
          <mesh position={[0.01, 0.028, 0]}>
            <boxGeometry args={[0.045, 0.022, 0.04]} />
            <meshStandardMaterial
              color="#0f172a"
              transparent
              opacity={dim ? 0.2 : 0.75}
            />
          </mesh>
          {/* Headlights */}
          <mesh position={[0.052, 0.01, 0.014]}>
            <boxGeometry args={[0.012, 0.01, 0.01]} />
            <meshBasicMaterial
              color="#fff7d6"
              transparent
              opacity={dim ? 0.15 : 0.9}
            />
          </mesh>
          <mesh position={[0.052, 0.01, -0.014]}>
            <boxGeometry args={[0.012, 0.01, 0.01]} />
            <meshBasicMaterial
              color="#fff7d6"
              transparent
              opacity={dim ? 0.15 : 0.9}
            />
          </mesh>
          {/* Taillights */}
          <mesh position={[-0.05, 0.01, 0]}>
            <boxGeometry args={[0.01, 0.01, 0.03]} />
            <meshBasicMaterial
              color="#ef4444"
              transparent
              opacity={dim ? 0.15 : 0.85}
            />
          </mesh>
        </group>
      ))}
    </group>
  )
}

function StreetLamps({ dim }: { dim: boolean }) {
  const lamps = useMemo(() => {
    const pts: { x: number; z: number; color: string }[] = []
    for (const r of ROAD) {
      for (let u = -CITY_HALF + 1; u < CITY_HALF; u += 2.2) {
        pts.push({ x: r + 0.28, z: u, color: '#38bdf8' })
        pts.push({ x: u, z: r + 0.28, color: '#a78bfa' })
      }
    }
    return pts.slice(0, 40)
  }, [])
  return (
    <group>
      {lamps.map((l, i) => (
        <group key={i} position={[l.x, 0, l.z]}>
          <mesh position={[0, 0.22, 0]}>
            <cylinderGeometry args={[0.008, 0.01, 0.44, 6]} />
            <meshStandardMaterial
              color="#94a3b8"
              transparent
              opacity={dim ? 0.2 : 0.9}
            />
          </mesh>
          <mesh position={[0, 0.45, 0]}>
            <sphereGeometry args={[0.025, 8, 8]} />
            <meshBasicMaterial
              color={l.color}
              transparent
              opacity={dim ? 0.15 : 0.85}
            />
          </mesh>
        </group>
      ))}
    </group>
  )
}

/** Sentinel cityFocus for Jobs → multi-city campus */
export const JOBS_CITY_FOCUS = '__jobs__'

export function NightCity({
  cityId,
  cityLabel,
  mode = 'city',
}: {
  cityId?: string
  cityLabel?: string
  mode?: 'city' | 'jobs'
}) {
  const jobsMode = mode === 'jobs' || cityId === JOBS_CITY_FOCUS
  const [companies, setCompanies] = useState<SkyCo[]>([])
  const [clusters, setClusters] = useState<CityCluster[]>([])
  const [maxN, setMaxN] = useState(1)
  const [hoverId, setHoverId] = useState<string | null>(null)
  const selectFocusId = useVigilStore((s) => s.selectFocusId)
  const cityWindowDays = useVigilStore((s) => s.cityWindowDays)
  const sectorFilter = useVigilStore((s) => s.sectorFilter)
  const cityFilter = useVigilStore((s) => s.cityFilter)
  const experienceFilter = useVigilStore((s) => s.experienceFilter)
  const anyFocused = Boolean(selectFocusId?.startsWith('company:'))
  const interactionBlocked = useMeshInteractionBlocked()
  const sceneDimmed =
    anyFocused || (Boolean(hoverId) && !interactionBlocked)

  useEffect(() => {
    return onPointerGuardChange(() => {
      if (isMeshInteractionBlocked()) setHoverId(null)
    })
  }, [])

  useEffect(() => {
    let alive = true
    if (jobsMode) {
      api
        .jobsSkyline(sectorFilter, cityFilter, experienceFilter, 120)
        .then((d) => {
          if (!alive) return
          const cls: CityCluster[] = d?.clusters || []
          setClusters(cls)
          setCompanies([])
          setMaxN(d?.stats?.max_n || 1)
          const nCities = d?.stats?.cities ?? cls.length
          useVigilStore.getState().setStatus(
            nCities > 1
              ? `CITY VIEW · ${nCities} CITIES · FROM JOBS`
              : `CITY VIEW · ${cls[0]?.label || 'CAMPUS'} · FROM JOBS`,
          )
        })
        .catch(() => {
          if (!alive) return
          setClusters([])
        })
    } else if (cityId) {
      api
        .citySkyline(cityId, cityWindowDays, 28)
        .then((d) => {
          if (!alive) return
          setClusters([])
          setCompanies(d?.companies || [])
          setMaxN(d?.stats?.max_n || 1)
          const cap = d?.window_caption || openingsCaption(cityWindowDays)
          useVigilStore.getState().setStatus(
            `CAMPUS · ${d?.label || cityLabel || ''} · ${cap}`,
          )
        })
        .catch(() => {
          if (!alive) return
          setCompanies([])
        })
    }
    return () => {
      alive = false
    }
  }, [
    jobsMode,
    cityId,
    cityLabel,
    cityWindowDays,
    sectorFilter,
    cityFilter,
    experienceFilter,
  ])

  // Clear hover when leaving the district or changing focus city
  useEffect(() => {
    setHoverId(null)
  }, [cityId, jobsMode, selectFocusId, sectorFilter, cityFilter, experienceFilter])

  const { corps, pads } = useMemo(() => {
    if (jobsMode && clusters.length) {
      return layoutJobClusters(clusters)
    }
    const single = layoutCorporates(
      companies,
      maxN,
      CAMPUS.cx,
      CAMPUS.cz,
      cityId,
      cityLabel,
    )
    return {
      corps: single,
      pads: [
        {
          cx: CAMPUS.cx,
          cz: CAMPUS.cz,
          half: CAMPUS.half,
          label: cityLabel || '',
        },
      ] as CampusPadSpec[],
    }
  }, [jobsMode, clusters, companies, maxN, cityId, cityLabel])

  const dummies = useMemo(() => layoutDummies(corps, pads), [corps, pads])
  const groundHalf = useMemo(() => {
    if (!pads.length) return CITY_HALF
    return Math.max(
      CITY_HALF,
      ...pads.map((p) => Math.abs(p.cx) + p.half + 2.2),
    )
  }, [pads])
  const flagHeights = useMemo(() => {
    const map = new Map<string, number>()
    for (const p of pads) {
      const key = `${p.cx}|${p.cz}`
      let maxH = 1.6
      for (const t of corps) {
        if (Math.hypot(t.x - p.cx, t.z - p.cz) <= p.half + 0.6) {
          maxH = Math.max(maxH, t.h)
        }
      }
      // Above company name + role cards stack
      map.set(key, maxH + 1.35)
    }
    return map
  }, [pads, corps])
  const roofCaption = jobsMode
    ? (n: number) => (n === 1 ? 'Opening' : 'Openings')
    : undefined
  const placeLabel =
    jobsMode && clusters.length > 1
      ? `${clusters.length} cities`
      : jobsMode
        ? clusters[0]?.label || 'Jobs'
        : cityLabel || ''

  useEffect(() => {
    setCampusNav(
      corps.map((t) => ({
        company_id: t.company_id,
        name: t.name,
        n: t.n,
        x: t.x,
        z: t.z,
        h: t.h,
      })),
      placeLabel,
    )
    return () => clearCampusNav()
  }, [corps, placeLabel])

  return (
    <group position={[0, CITY_Y, 0]}>
      <ambientLight intensity={sceneDimmed ? 0.32 : 0.55} color="#e2e8f0" />
      <hemisphereLight
        args={['#f8fafc', '#64748b', sceneDimmed ? 0.22 : 0.45]}
      />
      <directionalLight
        position={[5, 16, 3]}
        intensity={sceneDimmed ? 0.55 : 1.05}
        color="#fff7ed"
        castShadow
        shadow-mapSize-width={1024}
        shadow-mapSize-height={1024}
      />
      <directionalLight
        position={[-6, 5, -4]}
        intensity={sceneDimmed ? 0.18 : 0.4}
        color="#c4b5fd"
      />
      <pointLight
        position={[0, 3, 0]}
        intensity={sceneDimmed ? 0.15 : 0.35}
        color="#67e8f9"
        distance={jobsMode && clusters.length > 2 ? 18 : 10}
      />

      <Ground half={groundHalf} />
      {pads.map((p) => (
        <CampusPad key={`${p.cx}-${p.cz}-${p.label}`} dim={sceneDimmed} pad={p} />
      ))}
      {pads.map((p) =>
        p.label ? (
          <CityFlag
            key={`flag-${p.cx}-${p.cz}-${p.label}`}
            label={p.label}
            x={p.cx}
            y={flagHeights.get(`${p.cx}|${p.cz}`) || 3.2}
            z={p.cz}
            dim={sceneDimmed}
          />
        ) : null,
      )}
      <Traffic dim={sceneDimmed} />
      <StreetLamps dim={sceneDimmed} />

      {dummies.map((b, i) => (
        <DummyBuilding key={i} b={b} dim={sceneDimmed} />
      ))}

      {corps.map((t) => (
        <GlassTower
          key={`${t.city_key || 'c'}-${t.company_id}`}
          t={t}
          cityLabel={t.city_label || cityLabel || placeLabel}
          windowDays={cityWindowDays}
          openingsCaptionText={roofCaption ? roofCaption(t.n) : undefined}
          sceneDimmed={sceneDimmed}
          onHoverEnter={setHoverId}
          onHoverLeave={(id) =>
            setHoverId((cur) => (cur === id ? null : cur))
          }
        />
      ))}
    </group>
  )
}
