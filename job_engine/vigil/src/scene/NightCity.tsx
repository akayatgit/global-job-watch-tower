import { useEffect, useMemo, useRef, useState } from 'react'
import { useFrame } from '@react-three/fiber'
import type { ThreeEvent } from '@react-three/fiber'
import { Billboard } from '@react-three/drei'
import * as THREE from 'three'
import { api } from '../lib/api'
import { useVigilStore } from '../store/vigilStore'

/**
 * Isometric “smart city” district — reference style:
 * matte white dummy fabric · translucent cyan glass corporates · top banners · tight campus.
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
}

type Dummy = { x: number; z: number; w: number; d: number; h: number; seed: number }

const CITY_Y = -1.15
const CAMPUS = { cx: 0, cz: 0, half: 1.65 } // tight corporate plaza
const CITY_HALF = 7.2
const ROAD = [-4.5, -1.5, 1.5, 4.5]

function hash01(n: number) {
  const x = Math.sin(n * 127.1) * 43758.5453
  return x - Math.floor(x)
}

function makeTopBanner(name: string, jobs: number) {
  const c = document.createElement('canvas')
  c.width = 640
  c.height = 128
  const ctx = c.getContext('2d')!
  // Glass card
  ctx.fillStyle = 'rgba(255,255,255,0.92)'
  ctx.beginPath()
  ctx.moveTo(22, 12)
  ctx.arcTo(632, 12, 632, 116, 14)
  ctx.arcTo(632, 116, 8, 116, 14)
  ctx.arcTo(8, 116, 8, 12, 14)
  ctx.arcTo(8, 12, 632, 12, 14)
  ctx.closePath()
  ctx.fill()
  ctx.strokeStyle = 'rgba(56, 189, 248, 0.55)'
  ctx.lineWidth = 3
  ctx.stroke()
  // Soft cyan accent bar
  const g = ctx.createLinearGradient(20, 0, 620, 0)
  g.addColorStop(0, 'rgba(56,189,248,0.15)')
  g.addColorStop(0.5, 'rgba(34,211,238,0.35)')
  g.addColorStop(1, 'rgba(56,189,248,0.15)')
  ctx.fillStyle = g
  ctx.fillRect(20, 20, 600, 88)
  ctx.fillStyle = '#0f172a'
  ctx.font = '800 42px Orbitron, sans-serif'
  ctx.textAlign = 'center'
  const label = name.length > 22 ? `${name.slice(0, 20)}…` : name
  ctx.fillText(label.toUpperCase(), 320, 62)
  ctx.fillStyle = '#0284c7'
  ctx.font = '700 28px Rajdhani, sans-serif'
  ctx.fillText(`${jobs} OPEN`, 320, 98)
  const tex = new THREE.CanvasTexture(c)
  tex.colorSpace = THREE.SRGBColorSpace
  tex.anisotropy = 8
  return tex
}

function makeJobPin(n: number) {
  const c = document.createElement('canvas')
  c.width = 128
  c.height = 128
  const ctx = c.getContext('2d')!
  ctx.clearRect(0, 0, 128, 128)
  const g = ctx.createRadialGradient(64, 52, 4, 64, 52, 36)
  g.addColorStop(0, '#e0f2fe')
  g.addColorStop(0.55, '#38bdf8')
  g.addColorStop(1, '#0284c7')
  ctx.beginPath()
  ctx.arc(64, 50, 34, 0, Math.PI * 2)
  ctx.fillStyle = g
  ctx.shadowColor = 'rgba(56,189,248,0.45)'
  ctx.shadowBlur = 8
  ctx.fill()
  ctx.beginPath()
  ctx.moveTo(44, 76)
  ctx.lineTo(64, 114)
  ctx.lineTo(84, 76)
  ctx.closePath()
  ctx.fill()
  ctx.shadowBlur = 0
  ctx.fillStyle = '#ffffff'
  ctx.font = '800 32px Orbitron, sans-serif'
  ctx.textAlign = 'center'
  ctx.textBaseline = 'middle'
  ctx.fillText(n > 99 ? '99+' : String(n), 64, 48)
  const tex = new THREE.CanvasTexture(c)
  tex.colorSpace = THREE.SRGBColorSpace
  return tex
}

/** Pack corporates tightly on a small campus grid */
function layoutCorporates(companies: SkyCo[], maxN: number): Corp[] {
  const sorted = [...companies].sort((a, b) => b.n - a.n).slice(0, 18)
  const cols = Math.ceil(Math.sqrt(sorted.length))
  const gap = 0.55
  const out: Corp[] = []
  sorted.forEach((c, i) => {
    const row = Math.floor(i / cols)
    const col = i % cols
    const nRows = Math.ceil(sorted.length / cols)
    const ox = (col - (cols - 1) / 2) * gap
    const oz = (row - (nRows - 1) / 2) * gap
    const seed = c.company_id * 13.37
    const heat = c.n / Math.max(maxN, 1)
    const h = 0.85 + heat * 2.6 + hash01(seed) * 0.25
    const w = 0.28 + heat * 0.12 + hash01(seed + 1) * 0.06
    const d = 0.26 + heat * 0.1 + hash01(seed + 2) * 0.05
    out.push({
      company_id: c.company_id,
      name: c.name,
      n: c.n,
      sector_id: c.sector_id,
      sector_label: c.sector_label,
      x: CAMPUS.cx + ox + (hash01(seed + 3) - 0.5) * 0.06,
      z: CAMPUS.cz + oz + (hash01(seed + 4) - 0.5) * 0.06,
      w,
      d,
      h,
      heat,
      seed,
    })
  })
  return out
}

/** Dense white filler fabric — avoid campus + roads */
function layoutDummies(corps: Corp[]): Dummy[] {
  const list: Dummy[] = []
  let i = 0
  for (let gx = -CITY_HALF; gx <= CITY_HALF; gx += 0.42) {
    for (let gz = -CITY_HALF; gz <= CITY_HALF; gz += 0.42) {
      i++
      // Skip roads
      if (ROAD.some((r) => Math.abs(gx - r) < 0.38 || Math.abs(gz - r) < 0.38)) continue
      // Skip corporate campus
      if (
        Math.abs(gx - CAMPUS.cx) < CAMPUS.half + 0.35 &&
        Math.abs(gz - CAMPUS.cz) < CAMPUS.half + 0.35
      )
        continue
      // Sparse holes for plazas
      if (hash01(i * 3.1) < 0.12) continue
      // Don't overlap a corporate footprint
      const nearCorp = corps.some(
        (c) => Math.hypot(c.x - gx, c.z - gz) < 0.45,
      )
      if (nearCorp) continue
      const seed = i * 7.7
      list.push({
        x: gx + (hash01(seed) - 0.5) * 0.08,
        z: gz + (hash01(seed + 1) - 0.5) * 0.08,
        w: 0.22 + hash01(seed + 2) * 0.18,
        d: 0.2 + hash01(seed + 3) * 0.16,
        h: 0.25 + hash01(seed + 4) * 1.1,
        seed,
      })
    }
  }
  return list
}

function DummyBuilding({ b }: { b: Dummy }) {
  return (
    <mesh position={[b.x, b.h / 2, b.z]} castShadow receiveShadow>
      <boxGeometry args={[b.w, b.h, b.d]} />
      <meshStandardMaterial
        color="#f4f6f8"
        roughness={0.82}
        metalness={0.05}
      />
    </mesh>
  )
}

function GlassTower({
  t,
  cityLabel,
}: {
  t: Corp
  cityLabel: string
}) {
  const selectId = `company:${t.company_id}`
  const focused = useVigilStore((s) => s.selectFocusId === selectId)
  const [hot, setHot] = useState(false)
  const glow = useRef<THREE.MeshStandardMaterial>(null)
  const pin = useRef<THREE.Group>(null)
  const bannerTex = useMemo(
    () => makeTopBanner(t.name, t.n),
    [t.name, t.n],
  )
  const pinTex = useMemo(() => makeJobPin(t.n), [t.n])

  useFrame((state) => {
    const breath = 0.35 + Math.sin(state.clock.elapsedTime * 1.3 + t.seed) * 0.08
    if (glow.current) {
      glow.current.emissiveIntensity = focused || hot ? 0.85 + breath : 0.45 + breath * 0.5
      glow.current.opacity = focused || hot ? 0.72 : 0.55
    }
    if (pin.current) {
      const s = 1 + Math.sin(state.clock.elapsedTime * 1.5 + t.seed) * 0.04
      pin.current.scale.setScalar(s)
    }
  })

  const onClick = (e: ThreeEvent<MouseEvent>) => {
    e.stopPropagation()
    const st = useVigilStore.getState()
    const worldY = CITY_Y + t.h * 0.45
    if (st.selectFocusId === selectId) {
      st.openCompanyJobs(t.company_id, t.name, 7)
      st.setStatus(`OPEN · ${t.name}`)
      return
    }
    st.setSceneSpin(false)
    st.requestCameraFocus({
      id: selectId,
      x: t.x,
      y: worldY,
      z: t.z,
      distance: 1.85 + t.h * 0.2,
    })
    st.setStatus(`FOCUS · ${t.name} · ${t.n} in ${cityLabel} · click again to open`)
  }

  // Soft cyan–blue by heat (more hiring = greener cyan)
  const glass = useMemo(() => {
    const c = new THREE.Color()
    c.setHSL(0.52 - t.heat * 0.06, 0.75, 0.48 + t.heat * 0.08)
    return c
  }, [t.heat])

  return (
    <group position={[t.x, 0, t.z]}>
      {/* Hit volume */}
      <mesh
        position={[0, t.h / 2, 0]}
        onClick={onClick}
        onPointerOver={(e) => {
          e.stopPropagation()
          setHot(true)
          useVigilStore.setState({
            statusLine: focused
              ? `FOCUSED · ${t.name} · click again to open`
              : `PICK · ${t.name} · ${t.n}`,
          })
        }}
        onPointerOut={() => setHot(false)}
      >
        <boxGeometry args={[t.w * 1.35, t.h, t.d * 1.35]} />
        <meshBasicMaterial transparent opacity={0} depthWrite={false} />
      </mesh>

      {/* White floor plates inside glass */}
      {Array.from({ length: Math.max(3, Math.floor(t.h / 0.28)) }).map((_, i) => {
        const y = 0.12 + i * 0.28
        if (y > t.h - 0.1) return null
        return (
          <mesh key={i} position={[0, y, 0]} receiveShadow>
            <boxGeometry args={[t.w * 0.92, 0.03, t.d * 0.92]} />
            <meshStandardMaterial color="#f8fafc" roughness={0.7} metalness={0.05} />
          </mesh>
        )
      })}

      {/* Translucent glass shell */}
      <mesh position={[0, t.h / 2, 0]} castShadow>
        <boxGeometry args={[t.w, t.h, t.d]} />
        <meshStandardMaterial
          ref={glow}
          color={glass}
          emissive={glass}
          emissiveIntensity={0.5}
          transparent
          opacity={0.55}
          roughness={0.15}
          metalness={0.2}
          depthWrite={false}
        />
      </mesh>

      {/* Soft rim light */}
      {(focused || hot) && (
        <pointLight
          position={[0, t.h * 0.6, 0]}
          color="#38bdf8"
          intensity={1.1}
          distance={2.4}
          decay={2}
        />
      )}

      {/* Banner ALWAYS on top */}
      <Billboard follow position={[0, t.h + 0.22, 0]}>
        <mesh onClick={onClick}>
          <planeGeometry args={[0.95, 0.2]} />
          <meshBasicMaterial
            map={bannerTex}
            transparent
            depthWrite={false}
            toneMapped={false}
          />
        </mesh>
      </Billboard>

      {/* Job pin above banner */}
      <Billboard follow>
        <group ref={pin} position={[0, t.h + 0.48, 0]}>
          <mesh onClick={onClick}>
            <planeGeometry args={[0.28, 0.28]} />
            <meshBasicMaterial
              map={pinTex}
              transparent
              depthWrite={false}
              toneMapped={false}
            />
          </mesh>
        </group>
      </Billboard>
    </group>
  )
}

function CampusPad() {
  return (
    <group position={[CAMPUS.cx, 0.01, CAMPUS.cz]}>
      <mesh rotation={[-Math.PI / 2, 0, 0]} receiveShadow>
        <planeGeometry args={[CAMPUS.half * 2.3, CAMPUS.half * 2.3]} />
        <meshStandardMaterial color="#ffffff" roughness={0.55} metalness={0.08} />
      </mesh>
      {/* Cyan neon pad edge */}
      <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, 0.008, 0]}>
        <planeGeometry args={[CAMPUS.half * 2.42, CAMPUS.half * 2.42]} />
        <meshBasicMaterial color="#38bdf8" transparent opacity={0.35} />
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
    ctx.fillStyle = '#eef2f6'
    ctx.fillRect(0, 0, 1024, 1024)
    // Soft block grid
    ctx.strokeStyle = 'rgba(148,163,184,0.18)'
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
    const half = (0.42 / (CITY_HALF * 2)) * 1024
    for (const r of ROAD) {
      const p = toPx(r)
      ctx.fillStyle = '#1e293b'
      ctx.fillRect(p - half, 0, half * 2, 1024)
      ctx.fillRect(0, p - half, 1024, half * 2)
    }
    ctx.strokeStyle = 'rgba(255,255,255,0.55)'
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
    const tex = new THREE.CanvasTexture(c)
    tex.colorSpace = THREE.SRGBColorSpace
    return tex
  }, [])

  return (
    <mesh rotation={[-Math.PI / 2, 0, 0]} receiveShadow>
      <planeGeometry args={[CITY_HALF * 2.2, CITY_HALF * 2.2]} />
      <meshStandardMaterial map={roadTex} roughness={0.9} metalness={0.02} />
    </mesh>
  )
}

/** Tiny accent cars on roads only */
function MiniTraffic() {
  const cars = useMemo(() => {
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
        for (let k = 0; k < 2; k++) {
          list.push({
            axis: i % 2 === 0 ? 'h' : 'v',
            fixed: r + (dir > 0 ? 0.1 : -0.1),
            dir,
            pos: -CITY_HALF + hash01(i * 5 + k) * CITY_HALF * 1.8,
            speed: 0.7 + hash01(i + k) * 0.5,
            color: hash01(i * 2 + k) > 0.7 ? '#fb923c' : '#38bdf8',
          })
          i++
        }
      }
    }
    return list.slice(0, 24)
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
        g.position.set(c.pos, 0.04, c.fixed)
        g.rotation.y = c.dir > 0 ? 0 : Math.PI
      } else {
        g.position.set(c.fixed, 0.04, c.pos)
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
          <mesh>
            <boxGeometry args={[0.07, 0.025, 0.035]} />
            <meshStandardMaterial
              color={c.color}
              emissive={c.color}
              emissiveIntensity={0.35}
              roughness={0.4}
            />
          </mesh>
        </group>
      ))}
    </group>
  )
}

function CityTitle({ label, jobs }: { label: string; jobs: number }) {
  const tex = useMemo(() => {
    const c = document.createElement('canvas')
    c.width = 512
    c.height = 96
    const ctx = c.getContext('2d')!
    ctx.fillStyle = 'rgba(255,255,255,0.9)'
    ctx.fillRect(8, 12, 496, 72)
    ctx.strokeStyle = 'rgba(56,189,248,0.5)'
    ctx.lineWidth = 2
    ctx.strokeRect(8, 12, 496, 72)
    ctx.fillStyle = '#0f172a'
    ctx.font = '800 36px Orbitron, sans-serif'
    ctx.fillText(label.toUpperCase(), 24, 48)
    ctx.fillStyle = '#0284c7'
    ctx.font = '700 22px Rajdhani, sans-serif'
    ctx.fillText(`${jobs} openings · campus view`, 24, 74)
    const t = new THREE.CanvasTexture(c)
    t.colorSpace = THREE.SRGBColorSpace
    return t
  }, [label, jobs])
  return (
    <Billboard follow position={[0, 0.55, CAMPUS.half + 1.1]}>
      <mesh>
        <planeGeometry args={[2.2, 0.42]} />
        <meshBasicMaterial map={tex} transparent depthWrite={false} toneMapped={false} />
      </mesh>
    </Billboard>
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

  const corps = useMemo(
    () => layoutCorporates(companies, maxN),
    [companies, maxN],
  )
  const dummies = useMemo(() => layoutDummies(corps), [corps])
  const totalJobs = companies.reduce((a, c) => a + c.n, 0)

  return (
    <group position={[0, CITY_Y, 0]}>
      <ambientLight intensity={0.72} color="#f8fafc" />
      <hemisphereLight args={['#ffffff', '#cbd5e1', 0.55]} />
      <directionalLight
        position={[6, 14, 4]}
        intensity={1.15}
        color="#fffaf0"
        castShadow
        shadow-mapSize-width={1024}
        shadow-mapSize-height={1024}
      />
      <directionalLight position={[-4, 6, -5]} intensity={0.35} color="#bae6fd" />

      <Ground />
      <CampusPad />
      <MiniTraffic />

      {dummies.map((b, i) => (
        <DummyBuilding key={i} b={b} />
      ))}

      {corps.map((t) => (
        <GlassTower key={t.company_id} t={t} cityLabel={cityLabel} />
      ))}

      <CityTitle label={cityLabel} jobs={totalJobs} />
    </group>
  )
}
