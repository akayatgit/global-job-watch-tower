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
 * Editorial daylight miniature campus — documents/vigil-city-aesthetic.md.
 * 45° iso, content-sized cream cards (hover/focus only), spaced towers, soft PBR.
 * Interaction unchanged.
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
const CAMPUS = { cx: 0, cz: 0, half: 2.15 }
const CITY_HALF = 7.0
const ROAD = [-4.2, -1.4, 1.4, 4.2]
/** Canvas px → world units — cards hug content, not a fixed plate */
const CARD_PX_PER_WORLD = 380

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

const ACCENTS = ['#5b8def', '#7aa2f7', '#89b4fa', '#74c0fc', '#4c6ef5']
const ROLE_DOTS = ['#5b8def', '#74c0fc', '#69db7c', '#868e96', '#adb5bd']
const CARD_FONT =
  'Georgia, "Iowan Old Style", "Times New Roman", "Segoe UI", serif'
const TITLE_FONT =
  'system-ui, "Segoe UI", "Helvetica Neue", Arial, sans-serif'

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

/** Soft film grain — album-cover dusk, not noise mud. */
function sprinkleGrain(
  ctx: CanvasRenderingContext2D,
  w: number,
  h: number,
  amount = 0.04,
) {
  const n = Math.floor((w * h) / 900)
  for (let i = 0; i < n; i++) {
    const x = Math.random() * w
    const y = Math.random() * h
    const a = Math.random() * amount
    ctx.fillStyle = `rgba(255,255,255,${a})`
    ctx.fillRect(x, y, 1.2, 1.2)
  }
}

/** Soft-edge dissolve so cards melt into the dusk (no hard sticker frame). */
function softEdgeDissolve(
  ctx: CanvasRenderingContext2D,
  w: number,
  h: number,
  fade = 18,
) {
  ctx.save()
  ctx.globalCompositeOperation = 'destination-in'
  const g = ctx.createLinearGradient(0, 0, 0, h)
  // Keep most of the plate; dissolve only the rim
  const t = fade / h
  g.addColorStop(0, 'rgba(0,0,0,0.15)')
  g.addColorStop(t, '#000')
  g.addColorStop(1 - t, '#000')
  g.addColorStop(1, 'rgba(0,0,0,0.15)')
  ctx.fillStyle = g
  ctx.fillRect(0, 0, w, h)
  const gx = ctx.createLinearGradient(0, 0, w, 0)
  const tx = fade / w
  gx.addColorStop(0, 'rgba(0,0,0,0.15)')
  gx.addColorStop(tx, '#000')
  gx.addColorStop(1 - tx, '#000')
  gx.addColorStop(1, 'rgba(0,0,0,0.15)')
  ctx.fillStyle = gx
  ctx.fillRect(0, 0, w, h)
  ctx.restore()
}

/** Warm cream editorial glass — lyric-card face. */
function paintGlassPlate(
  ctx: CanvasRenderingContext2D,
  w: number,
  h: number,
  r = 28,
) {
  const inset = 5
  roundRect(ctx, inset + 2, inset + 4, w - inset * 2 - 2, h - inset * 2 - 2, r)
  ctx.fillStyle = 'rgba(20, 16, 28, 0.14)'
  ctx.fill()
  roundRect(ctx, inset, inset, w - inset * 2, h - inset * 2, r)
  const g = ctx.createLinearGradient(0, 0, 0, h)
  g.addColorStop(0, 'rgba(255, 252, 247, 0.94)')
  g.addColorStop(0.5, 'rgba(250, 246, 240, 0.9)')
  g.addColorStop(1, 'rgba(236, 242, 250, 0.84)')
  ctx.fillStyle = g
  ctx.fill()
  roundRect(
    ctx,
    inset + 1.5,
    inset + 1.5,
    w - inset * 2 - 3,
    h - inset * 2 - 3,
    r - 2,
  )
  ctx.strokeStyle = 'rgba(255, 255, 255, 0.65)'
  ctx.lineWidth = 1.25
  ctx.stroke()
  roundRect(ctx, inset, inset, w - inset * 2, h - inset * 2, r)
  ctx.strokeStyle = 'rgba(148, 163, 184, 0.28)'
  ctx.lineWidth = 1
  ctx.stroke()
  sprinkleGrain(ctx, w, h, 0.035)
}

/**
 * Content-sized glass card — width/height follow text + roles.
 * No fixed plate; no empty padding bands.
 */
function makeTowerCard(
  name: string,
  jobs: number,
  days: number,
  roles: RoleHit[],
  captionOverride?: string,
) {
  const caption =
    captionOverride ||
    (jobs === 1
      ? openingsCaption(days).replace(/^Openings/, 'Opening')
      : openingsCaption(days))
  const nameLines = wrapName(name, 18)
  const showRoles = roles.slice(0, 5)
  const num = jobs > 999 ? '999+' : String(jobs)
  const roleLabels = showRoles.map((r) => {
    const t = (r.title || '').trim()
    return r.n > 1 ? `${t}  ·  ${r.n}` : t
  })

  const measure = document.createElement('canvas').getContext('2d')!
  const nameFont = `600 20px ${CARD_FONT}`
  const numFont = `700 56px ${TITLE_FONT}`
  const capFont = `500 13px ${TITLE_FONT}`
  const roleFont = `500 13px ${TITLE_FONT}`
  let contentW = 0
  measure.font = nameFont
  for (const ln of nameLines) contentW = Math.max(contentW, measure.measureText(ln).width)
  measure.font = numFont
  contentW = Math.max(contentW, measure.measureText(num).width)
  measure.font = capFont
  contentW = Math.max(contentW, measure.measureText(caption).width)
  measure.font = roleFont
  for (const ln of roleLabels) {
    contentW = Math.max(contentW, measure.measureText(ln).width + 22)
  }

  const padX = 22
  const padTop = 18
  const padBot = 16
  const nameLineH = 24
  const numH = 58
  const capH = 18
  const roleRowH = 28
  const gapName = 6
  const gapNum = 4
  const gapRoles = showRoles.length ? 10 : 0
  const W = Math.ceil(
    Math.min(480, Math.max(168, contentW + padX * 2 + 8)),
  )
  const H = Math.ceil(
    padTop +
      nameLines.length * nameLineH +
      gapName +
      numH +
      gapNum +
      capH +
      gapRoles +
      showRoles.length * roleRowH +
      padBot,
  )

  const c = document.createElement('canvas')
  c.width = W
  c.height = H
  const ctx = c.getContext('2d')!
  ctx.clearRect(0, 0, W, H)
  paintGlassPlate(ctx, W, H, Math.min(26, Math.floor(H * 0.18)))

  const cx = W / 2
  let y = padTop
  ctx.textAlign = 'center'
  ctx.textBaseline = 'middle'
  ctx.fillStyle = '#3d4a5c'
  ctx.font = nameFont
  nameLines.forEach((ln, i) => {
    ctx.fillText(ln, cx, y + nameLineH / 2 + i * nameLineH)
  })
  y += nameLines.length * nameLineH + gapName

  ctx.fillStyle = '#1a2332'
  ctx.font = numFont
  ctx.fillText(num, cx, y + numH / 2)
  y += numH + gapNum

  ctx.fillStyle = '#8a93a3'
  ctx.font = capFont
  ctx.fillText(caption, cx, y + capH / 2)
  y += capH + gapRoles

  if (showRoles.length) {
    const rowLeft = padX
    roleLabels.forEach((label, i) => {
      const ry = y + roleRowH / 2 + i * roleRowH
      const dot = ROLE_DOTS[i % ROLE_DOTS.length]
      ctx.beginPath()
      ctx.arc(rowLeft + 5, ry, 3.5, 0, Math.PI * 2)
      ctx.fillStyle = dot
      ctx.fill()
      ctx.font = roleFont
      ctx.textAlign = 'left'
      ctx.fillStyle = '#4a5568'
      ctx.fillText(label, rowLeft + 16, ry)
    })
  }

  softEdgeDissolve(ctx, W, H, 14)
  const tex = new THREE.CanvasTexture(c)
  tex.colorSpace = THREE.SRGBColorSpace
  tex.anisotropy = 8
  return {
    tex,
    worldW: W / CARD_PX_PER_WORLD,
    worldH: H / CARD_PX_PER_WORLD,
  }
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
  // Aximoris-style breathing room between towers
  const gap = 0.92
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
      x: ox + (col - (cols - 1) / 2) * gap + (hash01(seed) - 0.5) * 0.05,
      z: oz + (row - (nRows - 1) / 2) * gap + (hash01(seed + 1) - 0.5) * 0.05,
      w: 0.28 + heat * 0.12 + hash01(seed + 2) * 0.04,
      d: 0.26 + heat * 0.1 + hash01(seed + 3) * 0.04,
      h: 0.9 + heat * 2.6 + hash01(seed + 4) * 0.28,
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
  const gap = n <= 2 ? 6.8 : n <= 4 ? 6.0 : 5.2
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
    const half = Math.min(2.6, 1.65 + Math.sqrt((cl.companies || []).length) * 0.28)
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
  // Daylight fabric — soft matte clay blocks (Spline-calm)
  const wash = neighborGlow > 0.08
  const body = b.tint || '#e8edf3'
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
          emissive={wash ? spillColor : '#ffffff'}
          emissiveIntensity={wash ? neighborGlow * 0.06 : 0.02}
          roughness={0.88}
          metalness={0.02}
          transparent
          opacity={dim ? 0.45 : 0.95}
        />
      </mesh>
      <mesh position={[0, b.h * 0.55, b.d / 2 + 0.002]} raycast={() => null}>
        <planeGeometry args={[b.w * 0.48, b.h * 0.32]} />
        <meshBasicMaterial
          color={wash ? spillColor : '#cbd5e1'}
          transparent
          opacity={dim ? 0.04 : 0.08 + neighborGlow * 0.06}
        />
      </mesh>
      <EdgeFrame
        w={b.w}
        h={b.h}
        d={b.d}
        color={wash ? spillColor : '#94a3b8'}
        opacity={dim ? 0.1 : 0.18 + neighborGlow * 0.1}
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
  /** Kept for call-site compatibility (daylight uses softer dim, not spill) */
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
  // Cards only when hovered / focused — geometry first (Aximoris calm)
  const card = useMemo(
    () =>
      lit
        ? makeTowerCard(
            t.name,
            t.n,
            windowDays,
            t.roles,
            openingsCaptionText,
          )
        : null,
    [t.name, t.n, windowDays, t.roles, lit, openingsCaptionText],
  )
  const glassCol = useMemo(() => {
    const c = new THREE.Color()
    c.setHSL(t.hue, 0.22, 0.72)
    return c
  }, [t.hue])
  const whiteCore = useMemo(() => new THREE.Color('#ffffff'), [])
  const softBlue = useMemo(() => new THREE.Color('#c5d8f0'), [])

  useEffect(() => {
    if (interactionBlocked && hot) {
      setHot(false)
      onHoverLeave(selectId)
    }
  }, [interactionBlocked, hot, onHoverLeave, selectId])

  useFrame((state) => {
    const breath = Math.sin(state.clock.elapsedTime * 1.0 + t.seed) * 0.04
    if (shell.current) {
      shell.current.emissiveIntensity = lit
        ? 0.08 + breath * 0.03
        : dim
          ? 0.02
          : 0.03
      shell.current.opacity = lit ? 0.72 : dim ? 0.4 : 0.58
      shell.current.emissive.copy(lit ? softBlue : glassCol)
    }
    if (core.current) {
      core.current.emissiveIntensity = lit ? 0.1 + breath * 0.02 : 0.02
      core.current.opacity = lit ? 0.85 : dim ? 0.35 : 0.55
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
  const cardH = card?.worldH ?? 0
  const cardW = card?.worldW ?? 0
  const cardOrder = 2000
  const dimOpacity = 0.45

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

      {/* Soft white core */}
      <mesh position={[0, t.h * 0.52, 0]} raycast={() => null}>
        <boxGeometry args={[t.w * 0.26, t.h * 0.7, t.d * 0.26]} />
        <meshStandardMaterial
          ref={core}
          color={whiteCore}
          emissive={whiteCore}
          emissiveIntensity={lit ? 0.1 : 0.02}
          transparent
          opacity={lit ? 0.8 : dim ? 0.35 : 0.55}
          roughness={0.5}
          metalness={0.04}
          depthWrite={false}
        />
      </mesh>

      <mesh position={[0, t.h * 0.45, 0]} raycast={() => null}>
        <boxGeometry args={[t.w * 0.52, t.h * 0.74, t.d * 0.52]} />
        <meshStandardMaterial
          color="#f4f7fb"
          emissive={lit ? softBlue : '#ffffff'}
          emissiveIntensity={lit ? 0.06 : 0.02}
          transparent
          opacity={dim ? dimOpacity : 0.55}
          roughness={0.6}
        />
      </mesh>

      {Array.from({ length: floors }).map((_, i) => {
        const y = 0.1 + (i / floors) * (t.h - 0.15)
        return (
          <mesh key={i} position={[0, y, 0]} raycast={() => null}>
            <boxGeometry args={[t.w * 0.9, 0.012, t.d * 0.9]} />
            <meshStandardMaterial
              color="#ffffff"
              roughness={0.42}
              metalness={0.05}
              transparent
              opacity={dim ? dimOpacity : 0.92}
            />
          </mesh>
        )
      })}

      {/* Soft ice glass — daylight matte */}
      <mesh position={[0, t.h / 2, 0]} castShadow raycast={() => null}>
        <boxGeometry args={[t.w, t.h, t.d]} />
        <meshStandardMaterial
          ref={shell}
          color={glassCol}
          emissive={glassCol}
          emissiveIntensity={0.04}
          transparent
          opacity={dim ? dimOpacity : lit ? 0.55 : 0.45}
          roughness={0.22}
          metalness={0.18}
          depthWrite={false}
        />
      </mesh>

      {[
        [0, t.h / 2, t.d / 2 + 0.003],
        [0, t.h / 2, -t.d / 2 - 0.003],
      ].map(([x, y, z], i) => (
        <mesh key={`f${i}`} position={[x, y, z]} raycast={() => null}>
          <planeGeometry args={[t.w * 0.96, t.h * 0.96]} />
          <meshBasicMaterial
            color="#94b8e0"
            transparent
            opacity={dim ? 0.04 : lit ? 0.1 : 0.06}
            side={THREE.DoubleSide}
          />
        </mesh>
      ))}

      <EdgeFrame
        w={t.w}
        h={t.h}
        d={t.d}
        color={lit ? '#7aa2f7' : '#cbd5e1'}
        opacity={dim ? 0.2 : lit ? 0.4 : 0.28}
      />

      {lit && (
        <pointLight
          position={[0, t.h * 0.7, 0]}
          color="#ffffff"
          intensity={focused ? 0.18 : 0.12}
          distance={2.2}
          decay={2}
        />
      )}

      {/* Content-sized card — only while hovered / focused */}
      {card && (
        <Billboard follow position={[0, t.h + 0.14 + cardH / 2, 0]}>
          <mesh raycast={() => null} renderOrder={cardOrder}>
            <planeGeometry args={[cardW, cardH]} />
            <meshBasicMaterial
              map={card.tex}
              transparent
              depthTest
              depthWrite={false}
              toneMapped={false}
            />
          </mesh>
        </Billboard>
      )}
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
  const size = pad.half * 2.4
  return (
    <group position={[pad.cx, 0.01, pad.cz]}>
      {/* Rounded pedestal — miniature baseplate */}
      <mesh rotation={[-Math.PI / 2, 0, 0]} receiveShadow>
        <circleGeometry args={[pad.half * 1.35, 48]} />
        <meshStandardMaterial
          color="#eef2f7"
          roughness={0.78}
          metalness={0.04}
          transparent
          opacity={dim ? 0.55 : 0.95}
        />
      </mesh>
      <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, 0.003, 0]}>
        <ringGeometry args={[pad.half * 1.28, pad.half * 1.35, 48]} />
        <meshBasicMaterial
          color="#94a3b8"
          transparent
          opacity={dim ? 0.12 : 0.22}
        />
      </mesh>
      <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, -0.006, 0]} receiveShadow>
        <planeGeometry args={[size, size]} />
        <meshStandardMaterial
          color="#dce3ec"
          roughness={0.9}
          transparent
          opacity={dim ? 0.2 : 0.35}
        />
      </mesh>
    </group>
  )
}

/**
 * Title-dominant city name — soft slate on daylight, freestanding.
 */
function makeCityFlag(label: string) {
  const text = label.trim().toUpperCase()
  const c = document.createElement('canvas')
  c.width = 1280
  c.height = 280
  const ctx = c.getContext('2d')!
  ctx.clearRect(0, 0, c.width, c.height)
  const cx = c.width / 2
  const cy = c.height / 2 - 8
  ctx.textAlign = 'center'
  ctx.textBaseline = 'middle'
  ctx.font = `800 112px ${TITLE_FONT}`
  ctx.shadowColor = 'rgba(255, 255, 255, 0.85)'
  ctx.shadowBlur = 14
  ctx.fillStyle = 'rgba(30, 41, 59, 0.35)'
  ctx.fillText(text, cx, cy)
  ctx.shadowBlur = 4
  ctx.fillStyle = '#1e293b'
  ctx.fillText(text, cx, cy)
  ctx.shadowBlur = 0
  softEdgeDissolve(ctx, c.width, c.height, 40)
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
  const mat = useRef<THREE.MeshBasicMaterial>(null)
  useFrame((state) => {
    if (mat.current) {
      mat.current.opacity = dim
        ? 0.38
        : 0.88 + Math.sin(state.clock.elapsedTime * 0.7) * 0.04
    }
  })
  if (!label) return null
  const w = Math.min(4.2, 1.7 + label.length * 0.16)
  return (
    <Billboard position={[x, y, z]} follow>
      <mesh raycast={() => null}>
        <planeGeometry args={[w, w * (280 / 1280)]} />
        <meshBasicMaterial
          ref={mat}
          map={tex}
          transparent
          depthWrite={false}
          depthTest
          opacity={0.9}
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
    // Soft daylight concrete + quiet grid
    ctx.fillStyle = '#e8edf3'
    ctx.fillRect(0, 0, 1024, 1024)
    ctx.strokeStyle = 'rgba(148, 163, 184, 0.28)'
    ctx.lineWidth = 1
    for (let i = 0; i < 1024; i += 32) {
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
      ctx.fillStyle = '#d1d9e4'
      ctx.fillRect(p - half, 0, half * 2, 1024)
      ctx.fillRect(0, p - half, 1024, half * 2)
    }
    ctx.strokeStyle = 'rgba(255, 255, 255, 0.55)'
    ctx.lineWidth = 2
    ctx.setLineDash([14, 16])
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
    ctx.fillStyle = 'rgba(100, 116, 139, 0.18)'
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

/** Soft daylight studio dome — pale sky, gentle horizon. */
function DaySky() {
  const tex = useMemo(() => {
    const c = document.createElement('canvas')
    c.width = 4
    c.height = 256
    const ctx = c.getContext('2d')!
    const g = ctx.createLinearGradient(0, 0, 0, 256)
    g.addColorStop(0, '#dce8f5') // zenith soft blue
    g.addColorStop(0.45, '#e8eef5')
    g.addColorStop(0.75, '#f2f5f8')
    g.addColorStop(1, '#fafbfc') // bright horizon
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
              color="#f8fafc"
              transparent
              opacity={dim ? 0.06 : 0.14}
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
    const half = Math.min(
      2.8,
      Math.max(CAMPUS.half, 1.7 + Math.sqrt(single.length) * 0.32),
    )
    return {
      corps: single,
      pads: [
        {
          cx: CAMPUS.cx,
          cz: CAMPUS.cz,
          half,
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
      <DaySky />
      {/* Well-lit daylight studio */}
      <ambientLight intensity={sceneDimmed ? 0.55 : 0.78} color="#f0f4f8" />
      <hemisphereLight
        args={['#ffffff', '#c5d0dc', sceneDimmed ? 0.55 : 0.85]}
      />
      <directionalLight
        position={[6, 9, 4]}
        intensity={sceneDimmed ? 0.85 : 1.35}
        color="#fff7e8"
        castShadow
        shadow-mapSize-width={1024}
        shadow-mapSize-height={1024}
      />
      <directionalLight
        position={[-5, 5, -3]}
        intensity={sceneDimmed ? 0.25 : 0.4}
        color="#dbeafe"
      />
      <pointLight
        position={[0, 2.2, 0]}
        intensity={sceneDimmed ? 0.08 : 0.14}
        color="#ffffff"
        distance={jobsMode && clusters.length > 2 ? 22 : 14}
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
