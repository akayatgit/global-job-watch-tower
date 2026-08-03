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
 * Clean-tech glass campus (govt-presentable) — frosted glassmorphic cards,
 * soft ice-blue towers, sunset silhouette fabric. Interaction unchanged.
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

/** Sector → soft cool hues (narrow, institutional — no neon rainbow) */
const SECTOR_HUE: Record<string, number> = {
  tech_ai: 0.58, // ice blue
  tech_digital: 0.55, // cyan-blue
  software: 0.56,
  manufacturing_advanced: 0.52, // steel blue
  healthcare: 0.48, // soft teal
  green_economy: 0.46,
  logistics: 0.54,
  tourism: 0.6, // soft periwinkle
}

const ACCENTS = ['#3b82f6', '#0ea5e9', '#38bdf8', '#60a5fa', '#2563eb']
const ROLE_DOTS = ['#3b82f6', '#22d3ee', '#34d399', '#64748b', '#94a3b8']
const CARD_FONT = 'system-ui, "Segoe UI", "Helvetica Neue", Arial, sans-serif'

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

function paintGlassPlate(
  ctx: CanvasRenderingContext2D,
  w: number,
  h: number,
  r = 28,
) {
  const inset = 4
  // Soft drop for depth (not neon bloom)
  roundRect(ctx, inset + 3, inset + 5, w - inset * 2 - 2, h - inset * 2 - 2, r)
  ctx.fillStyle = 'rgba(15, 23, 42, 0.12)'
  ctx.fill()
  // Frosted glass face
  roundRect(ctx, inset, inset, w - inset * 2, h - inset * 2, r)
  const g = ctx.createLinearGradient(0, 0, 0, h)
  g.addColorStop(0, 'rgba(255, 255, 255, 0.92)')
  g.addColorStop(0.45, 'rgba(248, 250, 252, 0.88)')
  g.addColorStop(1, 'rgba(226, 239, 255, 0.82)')
  ctx.fillStyle = g
  ctx.fill()
  // Inner highlight
  roundRect(ctx, inset + 1.5, inset + 1.5, w - inset * 2 - 3, h - inset * 2 - 3, r - 2)
  ctx.strokeStyle = 'rgba(255, 255, 255, 0.75)'
  ctx.lineWidth = 1.5
  ctx.stroke()
  // Soft blue rim
  roundRect(ctx, inset, inset, w - inset * 2, h - inset * 2, r)
  ctx.strokeStyle = 'rgba(59, 130, 246, 0.28)'
  ctx.lineWidth = 1.25
  ctx.stroke()
}

/**
 * Single glassmorphic tower card (inspiration-style):
 * company · big count · caption · optional role rows.
 * Expanded only when lit so the campus stays readable.
 */
function makeTowerCard(
  name: string,
  jobs: number,
  days: number,
  roles: RoleHit[],
  expanded: boolean,
  captionOverride?: string,
) {
  const caption =
    captionOverride ||
    (jobs === 1
      ? openingsCaption(days).replace(/^Openings/, 'Opening')
      : openingsCaption(days))
  const nameLines = wrapName(name, 16)
  const showRoles = expanded ? roles.slice(0, 5) : []
  const W = 420
  const padX = 36
  const padTop = 28
  const nameLineH = 28
  const numH = 72
  const capH = 22
  const roleRowH = 34
  const padBot = 26
  const gapName = 10
  const gapNum = 6
  const gapRoles = showRoles.length ? 16 : 0
  const H =
    padTop +
    nameLines.length * nameLineH +
    gapName +
    numH +
    gapNum +
    capH +
    gapRoles +
    showRoles.length * roleRowH +
    padBot

  const c = document.createElement('canvas')
  c.width = W
  c.height = H
  const ctx = c.getContext('2d')!
  ctx.clearRect(0, 0, W, H)
  paintGlassPlate(ctx, W, H, 32)

  const cx = W / 2
  let y = padTop
  ctx.textAlign = 'center'
  ctx.textBaseline = 'middle'
  ctx.fillStyle = '#1e3a5f'
  ctx.font = `700 22px ${CARD_FONT}`
  nameLines.forEach((ln, i) => {
    ctx.fillText(ln, cx, y + nameLineH / 2 + i * nameLineH)
  })
  y += nameLines.length * nameLineH + gapName

  const num = jobs > 999 ? '999+' : String(jobs)
  ctx.fillStyle = '#0f172a'
  ctx.font = `800 64px ${CARD_FONT}`
  ctx.fillText(num, cx, y + numH / 2)
  y += numH + gapNum

  ctx.fillStyle = '#64748b'
  ctx.font = `600 15px ${CARD_FONT}`
  ctx.fillText(caption, cx, y + capH / 2)
  y += capH + gapRoles

  if (showRoles.length) {
    const rowLeft = padX + 8
    const rowRight = W - padX - 8
    const labelMax = rowRight - rowLeft - 36
    showRoles.forEach((r, i) => {
      const ry = y + roleRowH / 2 + i * roleRowH
      const dot = ROLE_DOTS[i % ROLE_DOTS.length]
      ctx.beginPath()
      ctx.arc(rowLeft + 6, ry, 5, 0, Math.PI * 2)
      ctx.fillStyle = dot
      ctx.fill()
      let label = (r.title || '').trim()
      if (r.n > 1) label = `${label}  ·  ${r.n}`
      ctx.font = `600 15px ${CARD_FONT}`
      ctx.textAlign = 'left'
      ctx.fillStyle = '#334155'
      // Truncate cleanly
      while (label.length > 4 && ctx.measureText(label).width > labelMax) {
        label = `${label.slice(0, -2)}…`
      }
      ctx.fillText(label, rowLeft + 20, ry)
    })
  }

  const tex = new THREE.CanvasTexture(c)
  tex.colorSpace = THREE.SRGBColorSpace
  tex.anisotropy = 8
  return { tex, aspect: W / H, heightPx: H }
}

/** Camera distance — close enough to read the glass card. */
function focusDistance(h: number, roleCount = 0) {
  const roleExtra = Math.min(5, Math.max(0, roleCount)) * 0.1
  return (2.05 + h * 0.2 + roleExtra) / 1.5
}

/** Orbit / focus pivot = center of the top floor (roof), not building mid-mass. */
function focusRoofY(h: number) {
  return CITY_Y + h
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
      warmCore: false,
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
  const noRay = () => null
  return (
    <group>
      {/* Vertical corners */}
      {[
        [w / 2, 0, d / 2],
        [-w / 2, 0, d / 2],
        [w / 2, 0, -d / 2],
        [-w / 2, 0, -d / 2],
      ].map(([x, , z], i) => (
        <mesh
          key={`v${i}`}
          position={[x as number, h / 2, z as number]}
          raycast={noRay}
        >
          <boxGeometry args={[t, h, t]} />
          {mats}
        </mesh>
      ))}
      {/* Top rim */}
      <mesh position={[0, h, 0]} raycast={noRay}>
        <boxGeometry args={[w + t, t, d + t]} />
        {mats}
      </mesh>
      {/* Mid belt */}
      <mesh position={[0, h * 0.55, 0]} raycast={noRay}>
        <boxGeometry args={[w + t * 0.5, t * 0.7, d + t * 0.5]} />
        {mats}
      </mesh>
    </group>
  )
}

function DummyBuilding({
  b,
  dim,
  neighborGlow = 0,
  spillColor = '#fb923c',
}: {
  b: Dummy
  dim: boolean
  neighborGlow?: number
  spillColor?: string
}) {
  // Cinematic silhouette — soft dusk mass, cool spill only
  const wash = neighborGlow > 0.08
  const body = '#121826'
  return (
    <group position={[b.x, 0, b.z]}>
      <mesh
        position={[0, b.h / 2, 0]}
        castShadow
        receiveShadow
        raycast={() => null}
      >
        <boxGeometry args={[b.w, b.h, b.d]} />
        <meshStandardMaterial
          color={body}
          emissive={wash ? spillColor : '#1e293b'}
          emissiveIntensity={wash ? neighborGlow * 0.14 : 0.02}
          roughness={0.94}
          metalness={0.04}
          transparent
          opacity={dim ? 0.5 : 0.92}
        />
      </mesh>
      <mesh position={[0, b.h * 0.55, b.d / 2 + 0.002]} raycast={() => null}>
        <planeGeometry args={[b.w * 0.5, b.h * 0.35]} />
        <meshBasicMaterial
          color={wash ? spillColor : '#93c5fd'}
          transparent
          opacity={dim ? 0.03 : 0.05 + neighborGlow * 0.12}
        />
      </mesh>
      <EdgeFrame
        w={b.w}
        h={b.h}
        d={b.d}
        color={wash ? spillColor : '#334155'}
        opacity={dim ? 0.1 : 0.16 + neighborGlow * 0.18}
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
  neighborGlow = 0,
  spillColor,
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
  /** 0–1 wash from a nearby lit tower's neon spill */
  neighborGlow?: number
  spillColor?: string
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
  const core = useRef<THREE.MeshStandardMaterial>(null)
  const card = useMemo(
    () =>
      makeTowerCard(
        t.name,
        t.n,
        windowDays,
        t.roles,
        lit,
        openingsCaptionText,
      ),
    [t.name, t.n, windowDays, t.roles, lit, openingsCaptionText],
  )
  const glassCol = useMemo(() => {
    const c = new THREE.Color()
    // Soft ice glass — low saturation for institutional calm
    c.setHSL(t.hue, 0.42, 0.58)
    return c
  }, [t.hue])
  const spill = useMemo(
    () => new THREE.Color(spillColor || t.accent),
    [spillColor, t.accent],
  )
  const whiteCore = useMemo(() => new THREE.Color('#f8fafc'), [])
  const softBlue = useMemo(() => new THREE.Color('#93c5fd'), [])

  useEffect(() => {
    if (interactionBlocked && hot) {
      setHot(false)
      onHoverLeave(selectId)
    }
  }, [interactionBlocked, hot, onHoverLeave, selectId])

  useFrame((state) => {
    const breath = Math.sin(state.clock.elapsedTime * 1.1 + t.seed) * 0.06
    const spillBoost = neighborGlow * 0.18
    if (shell.current) {
      const base = lit ? 0.28 : dim ? 0.08 + spillBoost : 0.14 + spillBoost
      shell.current.emissiveIntensity = base + breath * (lit ? 0.08 : 0.02)
      shell.current.opacity = lit ? 0.62 : dim ? 0.36 : 0.48
      if (!lit && neighborGlow > 0.05) {
        shell.current.emissive.copy(spill)
      } else if (!lit) {
        shell.current.emissive.copy(glassCol)
      }
    }
    if (core.current) {
      const cBase = lit ? 0.22 : neighborGlow * 0.14
      core.current.emissiveIntensity = cBase + breath * (lit ? 0.06 : 0.02)
      core.current.opacity = lit ? 0.72 : Math.max(0.18, neighborGlow * 0.35)
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

  const floors = Math.max(4, Math.floor(t.h / 0.22))
  // One card: taller when expanded with roles; world size tuned for readability
  const cardH =
    (lit ? 0.78 : 0.52) +
    wrapName(t.name, 16).length * 0.04 +
    (lit ? Math.min(5, t.roles.length) * 0.07 : 0)
  const cardW = cardH * card.aspect
  const cardOrder = lit ? 2000 : dim ? 2 : 20
  const dimOpacity = 0.4

  const onClick = (e: ThreeEvent<MouseEvent>) => {
    e.stopPropagation()
    // Drag-orbit release must never focus a tower
    if (wasDragClick() || isMeshInteractionBlocked()) return
    const st = useVigilStore.getState()
    const place = t.city_label || cityLabel
    if (st.selectFocusId === selectId) {
      if (t.city_key) st.setCityFilter(t.city_key)
      st.openCompanyJobs(t.company_id, t.name, windowDays || 7)
      st.setStatus(`OPEN · ${t.name}`)
      return
    }
    st.setSceneSpin(false)
    // Pivot = top-floor center; distance still frames name + roles
    st.requestCameraFocus({
      id: selectId,
      x: t.x,
      y: focusRoofY(t.h),
      z: t.z,
      distance: focusDistance(t.h, t.roles.length),
    })
    st.setStatus(
      `FOCUS · ${t.name} · ${t.n} in ${place} · click again to open`,
    )
  }

  return (
    <group position={[t.x, 0, t.z]} scale={focused ? 1.06 : lit ? 1.03 : 1}>
      {/* Hit volume = building body only (labels never steal hover/focus) */}
      <mesh
        position={[0, t.h / 2, 0]}
        onClick={onClick}
        onPointerOver={enter}
        onPointerOut={leave}
      >
        <boxGeometry args={[t.w * 1.15, t.h * 1.05, t.d * 1.15]} />
        <meshBasicMaterial transparent opacity={0} depthWrite={false} />
      </mesh>

      {/* Soft white core (data tower spine) */}
      <mesh position={[0, t.h * 0.52, 0]} raycast={() => null}>
        <boxGeometry args={[t.w * 0.28, t.h * 0.72, t.d * 0.28]} />
        <meshStandardMaterial
          ref={core}
          color={whiteCore}
          emissive={whiteCore}
          emissiveIntensity={lit ? 0.22 : neighborGlow * 0.12}
          transparent
          opacity={lit ? 0.78 : Math.max(0.16, neighborGlow * 0.35)}
          roughness={0.35}
          metalness={0.08}
          depthWrite={false}
        />
      </mesh>

      {/* Cool mid shell */}
      <mesh position={[0, t.h * 0.45, 0]} raycast={() => null}>
        <boxGeometry args={[t.w * 0.55, t.h * 0.75, t.d * 0.55]} />
        <meshStandardMaterial
          color="#e2e8f0"
          emissive={lit || neighborGlow > 0.08 ? softBlue : glassCol}
          emissiveIntensity={
            dim ? 0.05 + neighborGlow * 0.1 : lit ? 0.18 : 0.06 + neighborGlow * 0.12
          }
          transparent
          opacity={dim ? dimOpacity : 0.55}
        />
      </mesh>

      {/* Floor plates — clean white slabs like the inspiration tower */}
      {Array.from({ length: floors }).map((_, i) => {
        const y = 0.1 + (i / floors) * (t.h - 0.15)
        return (
          <mesh key={i} position={[0, y, 0]} raycast={() => null}>
            <boxGeometry args={[t.w * 0.92, 0.014, t.d * 0.92]} />
            <meshStandardMaterial
              color="#f8fafc"
              roughness={0.45}
              metalness={0.05}
              transparent
              opacity={dim ? dimOpacity : 0.9}
            />
          </mesh>
        )
      })}

      {/* Ice glass facade */}
      <mesh position={[0, t.h / 2, 0]} castShadow raycast={() => null}>
        <boxGeometry args={[t.w, t.h, t.d]} />
        <meshStandardMaterial
          ref={shell}
          color={glassCol}
          emissive={glassCol}
          emissiveIntensity={0.12}
          transparent
          opacity={dim ? dimOpacity : lit ? 0.55 : 0.42}
          roughness={0.08}
          metalness={0.22}
          depthWrite={false}
        />
      </mesh>

      {/* Soft facade wash */}
      {[
        [0, t.h / 2, t.d / 2 + 0.003],
        [0, t.h / 2, -t.d / 2 - 0.003],
      ].map(([x, y, z], i) => (
        <mesh key={`f${i}`} position={[x, y, z]} raycast={() => null}>
          <planeGeometry args={[t.w * 0.96, t.h * 0.96]} />
          <meshBasicMaterial
            color="#93c5fd"
            transparent
            opacity={
              dim
                ? 0.04 + neighborGlow * 0.06
                : lit
                  ? 0.12
                  : 0.06 + neighborGlow * 0.06
            }
            side={THREE.DoubleSide}
          />
        </mesh>
      ))}

      <EdgeFrame
        w={t.w}
        h={t.h}
        d={t.d}
        color={lit || neighborGlow > 0.15 ? '#60a5fa' : '#e2e8f0'}
        opacity={dim ? dimOpacity * 0.7 : lit ? 0.45 : 0.28 + neighborGlow * 0.2}
      />

      {/* Soft spill — no neon bloom */}
      {lit && (
        <>
          <pointLight
            position={[0, t.h * 0.85, 0]}
            color="#ffffff"
            intensity={focused ? 0.28 : 0.18}
            distance={2.0}
            decay={2}
          />
          <pointLight
            position={[0, t.h * 0.55, 0]}
            color="#93c5fd"
            intensity={focused ? 0.35 : 0.24}
            distance={3.6}
            decay={1.8}
          />
        </>
      )}
      {!lit && neighborGlow > 0.12 && (
        <pointLight
          position={[0, t.h * 0.5, 0]}
          color={spillColor || '#93c5fd'}
          intensity={neighborGlow * 0.16}
          distance={2.0}
          decay={2}
        />
      )}

      {/* Single glass card — visual only; building hit owns pick */}
      <Billboard follow position={[0, t.h + 0.18 + cardH / 2, 0]}>
        <mesh
          scale={lit ? 1.18 : dim ? 0.92 : 1.05}
          raycast={() => null}
          renderOrder={cardOrder}
        >
          <planeGeometry args={[cardW, cardH]} />
          <meshBasicMaterial
            map={card.tex}
            transparent
            opacity={dim ? dimOpacity : 1}
            depthTest
            depthWrite={false}
            toneMapped={false}
          />
        </mesh>
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
          roughness={0.6}
          metalness={0.12}
          transparent
          opacity={dim ? 0.5 : 0.92}
        />
      </mesh>
      <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, 0.004, 0]}>
        <planeGeometry args={[pad.half * 2.35, pad.half * 2.35]} />
        <meshBasicMaterial
          color="#60a5fa"
          transparent
          opacity={dim ? 0.08 : 0.16}
        />
      </mesh>
    </group>
  )
}

/** City name — frosted glass pill, navy type (not neon yellow). */
function makeCityFlag(label: string) {
  const text = label.trim().toUpperCase()
  const c = document.createElement('canvas')
  c.width = 1024
  c.height = 180
  const ctx = c.getContext('2d')!
  ctx.clearRect(0, 0, c.width, c.height)
  paintGlassPlate(ctx, c.width, c.height, 40)
  ctx.textAlign = 'center'
  ctx.textBaseline = 'middle'
  ctx.font = `800 78px ${CARD_FONT}`
  ctx.fillStyle = '#0f172a'
  ctx.fillText(text, c.width / 2, c.height / 2)
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
    pulse.current = 0.78 + Math.sin(state.clock.elapsedTime * 1.1) * 0.05
    if (mat.current) {
      mat.current.opacity = dim ? 0.4 : pulse.current
    }
  })
  if (!label) return null
  const w = Math.min(3.2, 1.35 + label.length * 0.12)
  return (
    <Billboard position={[x, y, z]} follow>
      <mesh raycast={() => null}>
        <planeGeometry args={[w, w * (180 / 1024)]} />
        <meshBasicMaterial
          ref={mat}
          map={tex}
          transparent
          depthWrite={false}
          depthTest
          opacity={0.94}
          toneMapped={false}
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
    // Warm dusk pavement
    ctx.fillStyle = '#140a12'
    ctx.fillRect(0, 0, 1024, 1024)
    ctx.strokeStyle = 'rgba(80, 40, 50, 0.35)'
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
      ctx.fillStyle = '#08040a'
      ctx.fillRect(p - half, 0, half * 2, 1024)
      ctx.fillRect(0, p - half, 1024, half * 2)
    }
    // Amber dusk lane marks
    ctx.strokeStyle = 'rgba(255, 180, 100, 0.35)'
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
    ctx.fillStyle = 'rgba(255, 160, 90, 0.28)'
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
      <meshStandardMaterial map={roadTex} roughness={0.92} metalness={0.04} />
    </mesh>
  )
}

/** Magical sunset sky dome — warm horizon, violet zenith. */
function SunsetSky() {
  const tex = useMemo(() => {
    const c = document.createElement('canvas')
    c.width = 4
    c.height = 256
    const ctx = c.getContext('2d')!
    const g = ctx.createLinearGradient(0, 0, 0, 256)
    g.addColorStop(0, '#1a0830') // zenith violet
    g.addColorStop(0.35, '#3b1248')
    g.addColorStop(0.55, '#8b2d4a')
    g.addColorStop(0.72, '#e85d2a')
    g.addColorStop(0.88, '#ffb15a')
    g.addColorStop(1, '#ffd9a0') // horizon glow
    ctx.fillStyle = g
    ctx.fillRect(0, 0, 4, 256)
    const t = new THREE.CanvasTexture(c)
    t.colorSpace = THREE.SRGBColorSpace
    t.magFilter = THREE.LinearFilter
    t.minFilter = THREE.LinearFilter
    return t
  }, [])
  return (
    <mesh scale={[-1, 1, 1]} raycast={() => null}>
      <sphereGeometry args={[42, 32, 24]} />
      <meshBasicMaterial map={tex} side={THREE.BackSide} depthWrite={false} />
    </mesh>
  )
}

/** More realistic mini cars — body + cabin + lights */
function Traffic({ dim }: { dim: boolean }) {
  const cars = useMemo(() => {
    const colors = ['#3b82f6', '#60a5fa', '#94a3b8', '#0ea5e9', '#cbd5e1']
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
        pts.push({ x: r + 0.28, z: u, color: '#93c5fd' })
        pts.push({ x: u, z: r + 0.28, color: '#fdba74' })
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
              opacity={dim ? 0.18 : 0.75}
            />
          </mesh>
          <mesh position={[0, 0.45, 0]}>
            <sphereGeometry args={[0.022, 8, 8]} />
            <meshBasicMaterial
              color={l.color}
              transparent
              opacity={dim ? 0.1 : 0.28}
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

  // Neon spill origin — focused tower, else hovered
  const glowSrc = useMemo(() => {
    const id = selectFocusId || (interactionBlocked ? null : hoverId)
    if (!id?.startsWith('company:')) return null
    const cid = Number(id.slice('company:'.length))
    return corps.find((c) => c.company_id === cid) || null
  }, [selectFocusId, hoverId, interactionBlocked, corps])

  const spillFor = (x: number, z: number) => {
    if (!glowSrc) return { glow: 0, color: '#38bdf8' }
    const d = Math.hypot(x - glowSrc.x, z - glowSrc.z)
    if (d < 0.05) return { glow: 0, color: glowSrc.accent }
    // Falloff across nearby blocks
    const glow = Math.max(0, 1 - d / 4.2)
    return { glow: glow * glow, color: glowSrc.accent }
  }

  return (
    <group position={[0, CITY_Y, 0]}>
      <SunsetSky />
      {/* Soft cinematic dusk — warm key, cool fill (no neon wash) */}
      <ambientLight intensity={sceneDimmed ? 0.16 : 0.24} color="#2a2038" />
      <hemisphereLight
        args={['#ffc9a0', '#1a1528', sceneDimmed ? 0.32 : 0.48]}
      />
      <directionalLight
        position={[8, 3.2, -4]}
        intensity={sceneDimmed ? 0.45 : 0.72}
        color="#ffb07a"
        castShadow
        shadow-mapSize-width={1024}
        shadow-mapSize-height={1024}
      />
      <directionalLight
        position={[-5, 2.5, 6]}
        intensity={sceneDimmed ? 0.18 : 0.32}
        color="#93c5fd"
      />
      <pointLight
        position={[0, 1.2, 0]}
        intensity={sceneDimmed ? 0.08 : 0.14}
        color="#fde68a"
        distance={jobsMode && clusters.length > 2 ? 20 : 12}
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

      {dummies.map((b, i) => {
        const spill = spillFor(b.x, b.z)
        return (
          <DummyBuilding
            key={i}
            b={b}
            dim={sceneDimmed}
            neighborGlow={spill.glow}
            spillColor={spill.color}
          />
        )
      })}

      {corps.map((t) => {
        const spill = spillFor(t.x, t.z)
        return (
          <GlassTower
            key={`${t.city_key || 'c'}-${t.company_id}`}
            t={t}
            cityLabel={t.city_label || cityLabel || placeLabel}
            windowDays={cityWindowDays}
            openingsCaptionText={roofCaption ? roofCaption(t.n) : undefined}
            sceneDimmed={sceneDimmed}
            neighborGlow={spill.glow}
            spillColor={spill.color}
            onHoverEnter={setHoverId}
            onHoverLeave={(id) =>
              setHoverId((cur) => (cur === id ? null : cur))
            }
          />
        )
      })}
    </group>
  )
}
