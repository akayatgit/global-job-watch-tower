import { useEffect, useMemo, useRef, useState } from 'react'
import { useFrame } from '@react-three/fiber'
import type { ThreeEvent } from '@react-three/fiber'
import { Billboard } from '@react-three/drei'
import * as THREE from 'three'
import { api } from '../lib/api'
import { useVigilStore } from '../store/vigilStore'
import { wasDragClick } from './pointerGuard'

/**
 * Cyberpunk glass campus — frosted glass, edge frames, multi-color glow,
 * dense white fabric, realistic mini cars, roof banners + pins.
 */

type SkyCo = {
  company_id: number
  name: string
  n: number
  sector_id: string
  sector_label: string
}

type Corp = {
  company_id: number
  name: string
  n: number
  sector_id: string
  sector_label: string
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

function makeTopBanner(name: string, jobs: number, accent: string) {
  const lines = wrapName(name, 11)
  const c = document.createElement('canvas')
  c.width = 512
  c.height = 48 + lines.length * 36
  const ctx = c.getContext('2d')!
  const h = c.height
  // Frosted glass card
  ctx.fillStyle = 'rgba(12, 16, 28, 0.78)'
  ctx.fillRect(6, 6, 500, h - 12)
  ctx.strokeStyle = accent
  ctx.lineWidth = 3
  ctx.shadowColor = accent
  ctx.shadowBlur = 8
  ctx.strokeRect(6, 6, 500, h - 12)
  ctx.shadowBlur = 0
  // Accent wash
  const g = ctx.createLinearGradient(0, 0, 512, 0)
  g.addColorStop(0, `${accent}33`)
  g.addColorStop(0.5, `${accent}55`)
  g.addColorStop(1, `${accent}22`)
  ctx.fillStyle = g
  ctx.fillRect(10, 10, 492, h - 20)
  ctx.textAlign = 'center'
  ctx.fillStyle = '#ffffff'
  ctx.font = '800 30px Orbitron, sans-serif'
  lines.forEach((ln, i) => {
    ctx.fillText(ln.toUpperCase(), 256, 38 + i * 32)
  })
  ctx.fillStyle = accent
  ctx.font = '700 22px Rajdhani, sans-serif'
  ctx.fillText(`${jobs} OPEN`, 256, h - 14)
  const tex = new THREE.CanvasTexture(c)
  tex.colorSpace = THREE.SRGBColorSpace
  tex.anisotropy = 8
  return { tex, aspect: c.width / c.height }
}

function makeJobPin(n: number, accent: string) {
  const c = document.createElement('canvas')
  c.width = 128
  c.height = 128
  const ctx = c.getContext('2d')!
  ctx.clearRect(0, 0, 128, 128)
  const g = ctx.createRadialGradient(64, 48, 2, 64, 50, 36)
  g.addColorStop(0, '#ffffff')
  g.addColorStop(0.35, accent)
  g.addColorStop(1, '#0a0a12')
  ctx.beginPath()
  ctx.arc(64, 48, 34, 0, Math.PI * 2)
  ctx.fillStyle = g
  ctx.shadowColor = accent
  ctx.shadowBlur = 10
  ctx.fill()
  ctx.beginPath()
  ctx.moveTo(44, 74)
  ctx.lineTo(64, 114)
  ctx.lineTo(84, 74)
  ctx.closePath()
  ctx.fill()
  ctx.shadowBlur = 0
  ctx.fillStyle = '#0a0a12'
  ctx.font = '800 30px Orbitron, sans-serif'
  ctx.textAlign = 'center'
  ctx.textBaseline = 'middle'
  ctx.fillText(n > 99 ? '99+' : String(n), 64, 46)
  const tex = new THREE.CanvasTexture(c)
  tex.colorSpace = THREE.SRGBColorSpace
  return tex
}

function layoutCorporates(companies: SkyCo[], maxN: number): Corp[] {
  const sorted = [...companies].sort((a, b) => b.n - a.n).slice(0, 16)
  const cols = Math.ceil(Math.sqrt(sorted.length))
  const gap = 0.52
  return sorted.map((c, i) => {
    const row = Math.floor(i / cols)
    const col = i % cols
    const nRows = Math.ceil(sorted.length / cols)
    const seed = c.company_id * 13.37
    const heat = c.n / Math.max(maxN, 1)
    const baseHue = SECTOR_HUE[c.sector_id] ?? 0.55
    const hue = (baseHue + (hash01(seed) - 0.5) * 0.08 + 1) % 1
    return {
      company_id: c.company_id,
      name: c.name,
      n: c.n,
      sector_id: c.sector_id,
      sector_label: c.sector_label,
      x: CAMPUS.cx + (col - (cols - 1) / 2) * gap + (hash01(seed) - 0.5) * 0.04,
      z: CAMPUS.cz + (row - (nRows - 1) / 2) * gap + (hash01(seed + 1) - 0.5) * 0.04,
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

function layoutDummies(corps: Corp[]): Dummy[] {
  const list: Dummy[] = []
  let i = 0
  for (let gx = -CITY_HALF; gx <= CITY_HALF; gx += 0.4) {
    for (let gz = -CITY_HALF; gz <= CITY_HALF; gz += 0.4) {
      i++
      if (ROAD.some((r) => Math.abs(gx - r) < 0.36 || Math.abs(gz - r) < 0.36)) continue
      if (
        Math.abs(gx - CAMPUS.cx) < CAMPUS.half + 0.3 &&
        Math.abs(gz - CAMPUS.cz) < CAMPUS.half + 0.3
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
  sceneDimmed,
  onHoverEnter,
  onHoverLeave,
}: {
  t: Corp
  cityLabel: string
  /** True when any tower is focused or hovered — dim non-active ones */
  sceneDimmed: boolean
  onHoverEnter: (id: string) => void
  onHoverLeave: (id: string) => void
}) {
  const selectId = `company:${t.company_id}`
  const focused = useVigilStore((s) => s.selectFocusId === selectId)
  const [hot, setHot] = useState(false)
  const lit = focused || hot
  const dim = sceneDimmed && !lit
  const shell = useRef<THREE.MeshStandardMaterial>(null)
  const pin = useRef<THREE.Group>(null)
  const banner = useMemo(
    () => makeTopBanner(t.name, t.n, t.accent),
    [t.name, t.n, t.accent],
  )
  const pinTex = useMemo(() => makeJobPin(t.n, t.accent), [t.n, t.accent])
  const glassCol = useMemo(() => {
    const c = new THREE.Color()
    c.setHSL(t.hue, 0.72, 0.48)
    return c
  }, [t.hue])
  const warmCol = useMemo(() => new THREE.Color('#fb923c'), [])

  useFrame((state) => {
    const breath = Math.sin(state.clock.elapsedTime * 1.4 + t.seed) * 0.1
    if (shell.current) {
      const base = lit ? 1.05 : dim ? 0.08 : 0.48
      shell.current.emissiveIntensity = base + breath * (lit ? 0.28 : 0.08)
      shell.current.opacity = lit ? 0.82 : dim ? 0.12 : 0.5
    }
    if (pin.current) {
      pin.current.visible = lit || !dim
      const s = 1 + Math.sin(state.clock.elapsedTime * 1.6 + t.seed) * 0.05
      pin.current.scale.setScalar(lit ? s * 1.22 : s)
    }
  })

  const enter = (e: ThreeEvent<PointerEvent>) => {
    e.stopPropagation()
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
    if (wasDragClick()) return
    const st = useVigilStore.getState()
    // Focus on the ROOF / top of building
    const roofY = CITY_Y + t.h + 0.15
    if (st.selectFocusId === selectId) {
      st.openCompanyJobs(t.company_id, t.name, 7)
      st.setStatus(`OPEN · ${t.name}`)
      return
    }
    st.setSceneSpin(false)
    st.requestCameraFocus({
      id: selectId,
      x: t.x,
      y: roofY,
      z: t.z,
      distance: 1.55 + t.h * 0.12,
    })
    st.setStatus(`FOCUS · ${t.name} · ${t.n} in ${cityLabel} · click again to open`)
  }

  const floors = Math.max(4, Math.floor(t.h / 0.22))
  const bannerH = 0.18 + wrapName(t.name, 11).length * 0.06
  const bannerW = (bannerH * banner.aspect) * (lit ? 1.12 : 1)
  const pinY = t.h + 0.12 + bannerH + 0.18
  const cardOrder = lit ? 2000 : dim ? 2 : 20
  const pinOrder = lit ? 2100 : dim ? 3 : 30

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

      {/* Banner — roof top; lit = always drawn on top of scene */}
      <Billboard follow position={[0, t.h + 0.14 + bannerH / 2, 0]}>
        <mesh
          onClick={onClick}
          onPointerOver={enter}
          onPointerOut={leave}
          visible={lit || !dim}
          renderOrder={cardOrder}
          scale={lit ? 1.08 : 1}
        >
          <planeGeometry args={[bannerW, bannerH]} />
          <meshBasicMaterial
            map={banner.tex}
            transparent
            opacity={dim ? 0.12 : 1}
            depthTest={!lit}
            depthWrite={false}
            toneMapped={false}
          />
        </mesh>
        {lit && (
          <mesh position={[0, 0, -0.01]} renderOrder={cardOrder - 1}>
            <planeGeometry args={[bannerW * 1.18, bannerH * 1.35]} />
            <meshBasicMaterial
              color={t.accent}
              transparent
              opacity={0.35}
              depthTest={false}
              depthWrite={false}
              blending={THREE.AdditiveBlending}
              toneMapped={false}
            />
          </mesh>
        )}
      </Billboard>

      {/* Pin ALWAYS at absolute top; lit floats above everything */}
      <Billboard follow>
        <group ref={pin} position={[0, pinY, 0]}>
          <mesh
            onClick={onClick}
            onPointerOver={enter}
            onPointerOut={leave}
            renderOrder={pinOrder}
            scale={lit ? 1.15 : 1}
          >
            <planeGeometry args={[0.3, 0.3]} />
            <meshBasicMaterial
              map={pinTex}
              transparent
              opacity={dim ? 0.1 : 1}
              depthTest={!lit}
              depthWrite={false}
              toneMapped={false}
            />
          </mesh>
          {lit && (
            <mesh position={[0, 0, -0.01]} renderOrder={pinOrder - 1}>
              <circleGeometry args={[0.22, 24]} />
              <meshBasicMaterial
                color={t.accent}
                transparent
                opacity={0.45}
                depthTest={false}
                depthWrite={false}
                blending={THREE.AdditiveBlending}
                toneMapped={false}
              />
            </mesh>
          )}
        </group>
      </Billboard>
    </group>
  )
}

function CampusPad({ dim }: { dim: boolean }) {
  return (
    <group position={[CAMPUS.cx, 0.012, CAMPUS.cz]}>
      <mesh rotation={[-Math.PI / 2, 0, 0]} receiveShadow>
        <planeGeometry args={[CAMPUS.half * 2.25, CAMPUS.half * 2.25]} />
        <meshStandardMaterial
          color="#0f172a"
          roughness={0.45}
          metalness={0.2}
          transparent
          opacity={dim ? 0.5 : 1}
        />
      </mesh>
      <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, 0.004, 0]}>
        <planeGeometry args={[CAMPUS.half * 2.35, CAMPUS.half * 2.35]} />
        <meshBasicMaterial color="#a78bfa" transparent opacity={dim ? 0.15 : 0.4} />
      </mesh>
    </group>
  )
}

function Ground() {
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
      <planeGeometry args={[CITY_HALF * 2.15, CITY_HALF * 2.15]} />
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

export function NightCity({
  cityId,
  cityLabel,
}: {
  cityId: string
  cityLabel: string
}) {
  const [companies, setCompanies] = useState<SkyCo[]>([])
  const [maxN, setMaxN] = useState(1)
  const [hoverId, setHoverId] = useState<string | null>(null)
  const selectFocusId = useVigilStore((s) => s.selectFocusId)
  const anyFocused = Boolean(selectFocusId?.startsWith('company:'))
  const sceneDimmed = anyFocused || Boolean(hoverId)

  useEffect(() => {
    let alive = true
    api
      .citySkyline(cityId, 7, 28)
      .then((d) => {
        if (!alive) return
        setCompanies(d?.companies || [])
        setMaxN(d?.stats?.max_n || 1)
        useVigilStore.getState().setStatus(
          `CAMPUS · ${d?.label || cityLabel} · glass towers = employers`,
        )
      })
      .catch(() => setCompanies([]))
    return () => {
      alive = false
    }
  }, [cityId, cityLabel])

  // Clear hover when leaving the district or changing focus city
  useEffect(() => {
    setHoverId(null)
  }, [cityId, selectFocusId])

  const corps = useMemo(
    () => layoutCorporates(companies, maxN),
    [companies, maxN],
  )
  const dummies = useMemo(() => layoutDummies(corps), [corps])

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
        distance={10}
      />

      <Ground />
      <CampusPad dim={sceneDimmed} />
      <Traffic dim={sceneDimmed} />
      <StreetLamps dim={sceneDimmed} />

      {dummies.map((b, i) => (
        <DummyBuilding key={i} b={b} dim={sceneDimmed} />
      ))}

      {corps.map((t) => (
        <GlassTower
          key={t.company_id}
          t={t}
          cityLabel={cityLabel}
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
