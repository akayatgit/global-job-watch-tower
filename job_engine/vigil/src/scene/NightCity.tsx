import { useEffect, useMemo, useRef, useState } from 'react'
import { useFrame } from '@react-three/fiber'
import type { ThreeEvent } from '@react-three/fiber'
import { Billboard } from '@react-three/drei'
import * as THREE from 'three'
import { api } from '../lib/api'
import { useVigilStore } from '../store/vigilStore'

type SkyCo = {
  company_id: number
  name: string
  n: number
  sector_id: string
  sector_label: string
}

type TowerStyle = 'slab' | 'taper' | 'spire' | 'step' | 'twin'

type Tower = {
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
  style: TowerStyle
  yaw: number
  winCols: number
  winRows: number
}

const CITY_Y = -1.2
/** Manhattan road lines (world X / Z). Buildings sit in the blocks between. */
const ROAD_LINES = [-6, -3, 0, 3, 6]
const CITY_EDGE = 7.5
const LANE_W = 0.075
const SIGNAL_CYCLE = 9
const STOP_DIST = 0.42
const CAR_GAP = 0.28

const SECTOR_BLOCK: Record<string, { x: number; z: number }> = {
  tech_ai: { x: -4.5, z: -4.5 },
  tech_digital: { x: 4.5, z: -4.5 },
  manufacturing_advanced: { x: -4.5, z: 4.5 },
  healthcare: { x: 1.5, z: 4.5 },
  green_economy: { x: 4.5, z: 1.5 },
  logistics: { x: -1.5, z: 1.5 },
  tourism: { x: 1.5, z: -1.5 },
  software: { x: -1.5, z: -1.5 },
}

const STYLES: TowerStyle[] = ['slab', 'taper', 'spire', 'step', 'twin']

const CAR_COLORS = [
  '#c45a2c',
  '#3a6ea5',
  '#2f8f6b',
  '#8b5a2b',
  '#5c6b7a',
  '#a33b3b',
  '#6b5b95',
  '#b8860b',
]

const towerVert = /* glsl */ `
varying vec2 vUv;
void main() {
  vUv = uv;
  gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
}
`

/** Glass-pillar language: cool cyan → warm orange, almost no flicker */
const towerFrag = /* glsl */ `
uniform float uTime;
uniform float uHeat;
uniform float uSeed;
uniform float uCols;
uniform float uRows;
uniform vec3 uShell;
varying vec2 vUv;

float hash(vec2 p) {
  return fract(sin(dot(p + uSeed, vec2(127.1, 311.7))) * 43758.5453);
}

void main() {
  vec3 col = uShell;

  float cols = max(uCols, 6.0);
  float rows = max(uRows, 14.0);
  vec2 gv = vec2(vUv.x * cols, vUv.y * rows);
  vec2 id = floor(gv);
  vec2 f = fract(gv);

  float frame = step(0.2, f.x) * step(f.x, 0.8) * step(0.26, f.y) * step(f.y, 0.8);
  float n = hash(id);
  float on = step(0.28 - uHeat * 0.1, n);
  // Soft breath only — no hard flicker
  float breath = 0.9 + 0.1 * sin(uTime * 0.28 + n * 6.2831);
  float lit = frame * on * breath;

  // Glass chart: cool blue → orange by hiring heat
  vec3 cool = vec3(0.55, 0.78, 0.98);
  vec3 warm = vec3(1.0, 0.42, 0.08);
  vec3 win = mix(cool, warm, clamp(uHeat * 0.85 + n * 0.12, 0.0, 1.0));
  col = mix(col, win, lit * 0.78);

  // Soft base glow like pillar floor light
  float base = smoothstep(0.0, 0.22, vUv.y) * (1.0 - smoothstep(0.0, 0.35, vUv.y));
  col += vec3(1.0, 0.4, 0.08) * base * 0.12 * (0.4 + uHeat);

  gl_FragColor = vec4(col, 1.0);
}
`

/** Keep towers off the road bed */
function snapOffRoad(x: number, z: number, halfW: number, halfD: number) {
  let nx = x
  let nz = z
  for (const r of ROAD_LINES) {
    if (Math.abs(nx - r) < 0.55 + halfW) {
      nx = r + (nx >= r ? 1 : -1) * (0.7 + halfW)
    }
    if (Math.abs(nz - r) < 0.55 + halfD) {
      nz = r + (nz >= r ? 1 : -1) * (0.7 + halfD)
    }
  }
  return {
    x: THREE.MathUtils.clamp(nx, -CITY_EDGE + 0.8, CITY_EDGE - 0.8),
    z: THREE.MathUtils.clamp(nz, -CITY_EDGE + 0.8, CITY_EDGE - 0.8),
  }
}

function hash01(n: number) {
  const x = Math.sin(n * 127.1) * 43758.5453
  return x - Math.floor(x)
}

function makeNeonBoard(name: string, jobs: number, heat: number) {
  const c = document.createElement('canvas')
  c.width = 512
  c.height = 140
  const ctx = c.getContext('2d')!
  ctx.fillStyle = '#05080e'
  ctx.fillRect(0, 0, 512, 140)
  // Glass pillar wash: cyan → orange
  const g = ctx.createLinearGradient(0, 0, 0, 140)
  g.addColorStop(0, 'rgba(180, 230, 255, 0.35)')
  g.addColorStop(0.45, 'rgba(40, 50, 70, 0.25)')
  g.addColorStop(1, `rgba(255, ${Math.round(70 + heat * 40)}, 0, 0.55)`)
  ctx.fillStyle = g
  ctx.fillRect(14, 14, 484, 112)
  const rim = heat > 0.55 ? '#7dd3fc' : '#ff8c40'
  ctx.strokeStyle = rim
  ctx.shadowColor = rim
  ctx.shadowBlur = 16
  ctx.lineWidth = 4
  ctx.strokeRect(12, 12, 488, 116)
  ctx.shadowBlur = 0
  ctx.fillStyle = '#ffffff'
  ctx.font = '800 34px Orbitron, sans-serif'
  ctx.shadowColor = 'rgba(255,255,255,0.45)'
  ctx.shadowBlur = 6
  const label = name.length > 22 ? `${name.slice(0, 20)}…` : name
  ctx.fillText(label.toUpperCase(), 36, 68)
  ctx.shadowColor = 'rgba(255, 140, 40, 0.75)'
  ctx.shadowBlur = 8
  ctx.fillStyle = '#ffe0b0'
  ctx.font = '800 22px Rajdhani, sans-serif'
  ctx.fillText(`${jobs} OPEN ROLES`, 36, 102)
  const tex = new THREE.CanvasTexture(c)
  tex.colorSpace = THREE.SRGBColorSpace
  tex.anisotropy = 8
  return tex
}

/** Soft glass-pillar pin — amber/cyan, easy on the eyes */
function makePinTexture(n: number, heat: number) {
  const c = document.createElement('canvas')
  c.width = 128
  c.height = 128
  const ctx = c.getContext('2d')!
  ctx.clearRect(0, 0, 128, 128)
  const top = `rgba(${Math.round(160 + heat * 40)}, ${Math.round(200 - heat * 40)}, 255, 0.95)`
  const bot = `rgba(255, ${Math.round(100 - heat * 30)}, 20, 0.95)`
  const grad = ctx.createRadialGradient(64, 48, 4, 64, 52, 38)
  grad.addColorStop(0, 'rgba(255, 230, 200, 0.95)')
  grad.addColorStop(0.45, top)
  grad.addColorStop(1, bot)
  ctx.beginPath()
  ctx.arc(64, 52, 34, 0, Math.PI * 2)
  ctx.fillStyle = grad
  ctx.shadowColor = 'rgba(255, 120, 40, 0.55)'
  ctx.shadowBlur = 12
  ctx.fill()
  ctx.beginPath()
  ctx.moveTo(42, 78)
  ctx.lineTo(64, 116)
  ctx.lineTo(86, 78)
  ctx.closePath()
  ctx.fillStyle = bot
  ctx.fill()
  ctx.shadowBlur = 0
  ctx.fillStyle = '#1a1008'
  ctx.font = '800 34px Orbitron, sans-serif'
  ctx.textAlign = 'center'
  ctx.textBaseline = 'middle'
  const text = n > 99 ? '99+' : String(n)
  ctx.fillText(text, 64, 50)
  const tex = new THREE.CanvasTexture(c)
  tex.colorSpace = THREE.SRGBColorSpace
  return tex
}

function layoutTowers(companies: SkyCo[], maxN: number): Tower[] {
  const bySec = new Map<string, SkyCo[]>()
  for (const c of companies) {
    const sid = c.sector_id || 'tech_digital'
    if (!bySec.has(sid)) bySec.set(sid, [])
    bySec.get(sid)!.push(c)
  }
  const towers: Tower[] = []
  for (const [sid, list] of bySec) {
    const block = SECTOR_BLOCK[sid] || { x: 0, z: 0 }
    const sorted = [...list].sort((a, b) => b.n - a.n)
    sorted.forEach((c, i) => {
      const seed = c.company_id * 13.37
      const heat = c.n / Math.max(maxN, 1)
      const h = 0.7 + heat * 4.2 + hash01(seed) * 0.35
      const style = STYLES[Math.floor(hash01(seed + 1) * STYLES.length)]
      // Organic scatter inside district — not a perfect grid
      const ring = Math.floor(i / 3)
      const a = hash01(seed + 2) * Math.PI * 2 + i * 0.9
      const rad = 0.55 + ring * 0.95 + hash01(seed + 3) * 0.35
      const x = block.x + Math.cos(a) * rad + (hash01(seed + 4) - 0.5) * 0.4
      const z = block.z + Math.sin(a) * rad * 0.85 + (hash01(seed + 5) - 0.5) * 0.4
      const w = 0.32 + heat * 0.28 + hash01(seed + 6) * 0.18
      const d = 0.28 + heat * 0.22 + hash01(seed + 7) * 0.16
      const snapped = snapOffRoad(x, z, w * 0.55, d * 0.55)
      towers.push({
        company_id: c.company_id,
        name: c.name,
        n: c.n,
        sector_id: sid,
        sector_label: c.sector_label,
        x: snapped.x,
        z: snapped.z,
        w,
        d,
        h,
        heat,
        seed,
        style,
        yaw: (hash01(seed + 8) - 0.5) * 0.5,
        winCols: 10 + Math.floor(hash01(seed + 9) * 8),
        winRows: 22 + Math.floor(heat * 28) + Math.floor(hash01(seed + 10) * 8),
      })
    })
  }
  return towers
}

function FacadeMaterial({ t }: { t: Tower }) {
  const mat = useRef<THREE.ShaderMaterial>(null)
  const shellHue = 200 + hash01(t.seed) * 50
  const shell = useMemo(
    () => new THREE.Color().setHSL(shellHue / 360, 0.1, 0.065 + t.heat * 0.04),
    [shellHue, t.heat],
  )
  const uniforms = useMemo(
    () => ({
      uTime: { value: 0 },
      uHeat: { value: t.heat },
      uSeed: { value: t.seed % 100 },
      uCols: { value: t.winCols },
      uRows: { value: t.winRows },
      uShell: { value: shell },
    }),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [t.company_id, t.heat, t.winCols, t.winRows, shell],
  )
  useFrame((state) => {
    if (mat.current) mat.current.uniforms.uTime.value = state.clock.elapsedTime
  })
  return (
    <shaderMaterial
      ref={mat}
      uniforms={uniforms}
      vertexShader={towerVert}
      fragmentShader={towerFrag}
    />
  )
}

function TowerBody({ t }: { t: Tower }) {
  if (t.style === 'taper') {
    return (
      <mesh>
        <cylinderGeometry args={[t.w * 0.35, t.w * 0.55, t.h, 6]} />
        <FacadeMaterial t={t} />
      </mesh>
    )
  }
  if (t.style === 'spire') {
    return (
      <group>
        <mesh position={[0, -t.h * 0.08, 0]}>
          <boxGeometry args={[t.w, t.h * 0.84, t.d]} />
          <FacadeMaterial t={t} />
        </mesh>
        <mesh position={[0, t.h * 0.42, 0]}>
          <coneGeometry args={[t.w * 0.28, t.h * 0.22, 4]} />
          <meshBasicMaterial color="#1a1a22" />
        </mesh>
      </group>
    )
  }
  if (t.style === 'step') {
    return (
      <group>
        <mesh position={[0, -t.h * 0.15, 0]}>
          <boxGeometry args={[t.w * 1.15, t.h * 0.55, t.d * 1.1]} />
          <FacadeMaterial t={t} />
        </mesh>
        <mesh position={[0, t.h * 0.22, 0]}>
          <boxGeometry args={[t.w * 0.75, t.h * 0.45, t.d * 0.75]} />
          <FacadeMaterial t={t} />
        </mesh>
      </group>
    )
  }
  if (t.style === 'twin') {
    return (
      <group>
        <mesh position={[-t.w * 0.32, 0, 0]}>
          <boxGeometry args={[t.w * 0.55, t.h, t.d]} />
          <FacadeMaterial t={t} />
        </mesh>
        <mesh position={[t.w * 0.32, t.h * 0.06, 0]}>
          <boxGeometry args={[t.w * 0.55, t.h * 0.88, t.d * 0.9]} />
          <FacadeMaterial t={t} />
        </mesh>
      </group>
    )
  }
  return (
    <mesh>
      <boxGeometry args={[t.w, t.h, t.d]} />
      <FacadeMaterial t={t} />
    </mesh>
  )
}

function WorkTower({ t, cityLabel }: { t: Tower; cityLabel: string }) {
  const boardTex = useMemo(
    () => makeNeonBoard(t.name, t.n, t.heat),
    [t.name, t.n, t.heat],
  )
  const pinTex = useMemo(() => makePinTexture(t.n, t.heat), [t.n, t.heat])
  const pin = useRef<THREE.Group>(null)
  const glow = useRef<THREE.Mesh>(null)
  const pick = useRef<THREE.Mesh>(null)
  const [hot, setHot] = useState(false)
  const selectId = `company:${t.company_id}`
  const focused = useVigilStore((s) => s.selectFocusId === selectId)

  useFrame((state) => {
    if (pin.current) {
      // Gentle breath — not aggressive flicker
      const breath = 1 + Math.sin(state.clock.elapsedTime * 1.1 + t.seed) * 0.045
      pin.current.scale.setScalar(breath)
      pin.current.position.y =
        t.h / 2 + 0.28 + Math.sin(state.clock.elapsedTime * 0.9 + t.seed) * 0.03
    }
    if (glow.current) {
      glow.current.visible = focused
      if (focused) {
        const pulse = 0.22 + Math.sin(state.clock.elapsedTime * 2.0) * 0.1
        glow.current.scale.setScalar(1.15 + Math.sin(state.clock.elapsedTime * 1.6) * 0.06)
        ;(glow.current.material as THREE.MeshBasicMaterial).opacity = pulse
      }
    }
    if (pick.current) {
      pick.current.visible = hot && !focused
      if (hot && !focused) {
        const pulse = 0.28 + Math.sin(state.clock.elapsedTime * 5) * 0.18
        pick.current.scale.setScalar(1.08 + Math.sin(state.clock.elapsedTime * 4) * 0.05)
        ;(pick.current.material as THREE.MeshBasicMaterial).opacity = pulse
      }
    }
  })

  const handleClick = (e: ThreeEvent<MouseEvent>) => {
    e.stopPropagation()
    const st = useVigilStore.getState()
    const worldY = CITY_Y + t.h * 0.42
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
      distance: 1.55 + t.h * 0.28,
    })
    st.setStatus(`FOCUS · ${t.name} · ${t.n} in ${cityLabel} · click again to open`)
  }

  const boardW = Math.min(Math.max(t.w, t.d) * 1.25, 1.05)
  const boardH = 0.18 + t.heat * 0.05
  const faces: [number, number, number, number][] = [
    [0, 0, t.d / 2 + 0.03, 0],
    [0, 0, -t.d / 2 - 0.03, Math.PI],
    [t.w / 2 + 0.03, 0, 0, Math.PI / 2],
    [-t.w / 2 - 0.03, 0, 0, -Math.PI / 2],
  ]
  const boardY = -t.h / 2 + Math.min(t.h * 0.55, t.h - 0.25)

  return (
    <group position={[t.x, t.h / 2, t.z]} rotation={[0, t.yaw, 0]}>
      <mesh
        onClick={handleClick}
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
        <boxGeometry args={[t.w * 1.4, t.h, t.d * 1.4]} />
        <meshBasicMaterial transparent opacity={0} depthWrite={false} />
      </mesh>

      <TowerBody t={t} />
      {(focused || hot) && (
        <pointLight
          position={[0, t.h * 0.2, 0]}
          color="#ffaa00"
          intensity={focused ? 1.6 : 1.1}
          distance={3.5}
        />
      )}
      <mesh ref={glow} position={[0, 0, 0]} visible={false}>
        <sphereGeometry args={[Math.max(t.w, t.d) * 1.1, 24, 24]} />
        <meshBasicMaterial
          color="#ff8800"
          transparent
          opacity={0.25}
          depthWrite={false}
          blending={THREE.AdditiveBlending}
        />
      </mesh>
      <mesh ref={pick} position={[0, 0, 0]} visible={false}>
        <sphereGeometry args={[Math.max(t.w, t.d) * 1.05, 20, 20]} />
        <meshBasicMaterial
          color="#38bdf8"
          transparent
          opacity={0.3}
          depthWrite={false}
          blending={THREE.AdditiveBlending}
        />
      </mesh>

      {/* Neon name boards — all four façades */}
      {faces.map(([fx, , fz, rot], i) => (
        <group key={i} position={[fx, boardY, fz]} rotation={[0, rot, 0]}>
          <mesh onClick={handleClick}>
            <boxGeometry args={[boardW, boardH, 0.05]} />
            <meshBasicMaterial
              map={boardTex}
              toneMapped={false}
              transparent
              opacity={0.98}
            />
          </mesh>
          {/* Neon edge glow */}
          <mesh position={[0, 0, 0.03]}>
            <planeGeometry args={[boardW * 1.05, boardH * 1.15]} />
            <meshBasicMaterial
              color={t.heat > 0.55 ? '#7dd3fc' : '#ff8c40'}
              transparent
              opacity={0.22}
              depthWrite={false}
              blending={THREE.AdditiveBlending}
            />
          </mesh>
        </group>
      ))}

      {/* Breathing notification pin with job count — always faces camera */}
      <Billboard follow>
        <group ref={pin} position={[0, t.h / 2 + 0.28, 0]}>
          <mesh onClick={handleClick}>
            <planeGeometry args={[0.42, 0.42]} />
            <meshBasicMaterial
              map={pinTex}
              transparent
              depthWrite={false}
              toneMapped={false}
            />
          </mesh>
          <pointLight intensity={0.2} distance={1.1} color="#ff8c40" />
        </group>
      </Billboard>
    </group>
  )
}

type CarSim = {
  axis: 'h' | 'v'
  fixed: number
  lane: number
  dir: 1 | -1
  pos: number
  speed: number
  maxSpeed: number
  color: string
}

/** Is this axis green at the nearest intersection? */
function axisGreen(axis: 'h' | 'v', ix: number, iz: number, t: number) {
  const phase = (t + (ix * 2.3 + iz * 1.7)) % SIGNAL_CYCLE
  // NS (v) green, all-red gap, EW (h) green, all-red gap
  if (axis === 'v') return phase < 3.4
  return phase >= 4.5 && phase < 7.9
}

function nextIntersection(pos: number, dir: number) {
  let best: number | null = null
  let bestDist = Infinity
  for (const r of ROAD_LINES) {
    const d = (r - pos) * dir
    if (d > 0.02 && d < bestDist) {
      bestDist = d
      best = r
    }
  }
  return best
}

function Traffic() {
  const sims = useMemo(() => {
    const list: CarSim[] = []
    let i = 0
    // East–west traffic on each Z road
    for (const roadZ of ROAD_LINES) {
      for (const dir of [1, -1] as const) {
        for (const laneSign of [-1, 1] as const) {
          for (let k = 0; k < 2; k++) {
            list.push({
              axis: 'h',
              fixed: roadZ + laneSign * LANE_W,
              lane: laneSign,
              dir,
              pos: -CITY_EDGE + 0.4 + hash01(i * 13.1 + k) * (CITY_EDGE * 1.7),
              speed: 0,
              maxSpeed: 0.85 + hash01(i * 4.2 + k) * 0.65,
              color: CAR_COLORS[i % CAR_COLORS.length],
            })
            i++
          }
        }
      }
    }
    // North–south traffic on each X road
    for (const roadX of ROAD_LINES) {
      for (const dir of [1, -1] as const) {
        for (const laneSign of [-1, 1] as const) {
          for (let k = 0; k < 2; k++) {
            list.push({
              axis: 'v',
              fixed: roadX + laneSign * LANE_W,
              lane: laneSign,
              dir,
              pos: -CITY_EDGE + 0.4 + hash01(i * 9.7 + k) * (CITY_EDGE * 1.7),
              speed: 0,
              maxSpeed: 0.85 + hash01(i * 5.1 + k) * 0.65,
              color: CAR_COLORS[i % CAR_COLORS.length],
            })
            i++
          }
        }
      }
    }
    return list.slice(0, 48)
  }, [])

  const groups = useRef<(THREE.Group | null)[]>([])
  const lightMats = useRef<(THREE.MeshBasicMaterial | null)[]>([])

  useFrame((state, dt) => {
    const t = state.clock.elapsedTime
    const step = Math.min(dt, 0.05)

    for (let i = 0; i < sims.length; i++) {
      const c = sims[i]
      let want = c.maxSpeed

      // Signal stop line at next cross-street
      const nxt = nextIntersection(c.pos, c.dir)
      if (nxt != null) {
        const dist = (nxt - c.pos) * c.dir
        if (dist < STOP_DIST) {
          const nearX =
            c.axis === 'h'
              ? nxt
              : ROAD_LINES.reduce((a, b) =>
                  Math.abs(b - c.fixed) < Math.abs(a - c.fixed) ? b : a,
                )
          const nearZ =
            c.axis === 'v'
              ? nxt
              : ROAD_LINES.reduce((a, b) =>
                  Math.abs(b - c.fixed) < Math.abs(a - c.fixed) ? b : a,
                )
          if (!axisGreen(c.axis, nearX, nearZ, t)) {
            want = dist < 0.12 ? 0 : Math.min(want, dist * 1.4)
          }
        }
      }

      // Car ahead on same lane — keep gap (no accidents)
      let aheadDist = Infinity
      for (let j = 0; j < sims.length; j++) {
        if (i === j) continue
        const o = sims[j]
        if (o.axis !== c.axis || o.dir !== c.dir) continue
        if (Math.abs(o.fixed - c.fixed) > 0.04) continue
        const d = (o.pos - c.pos) * c.dir
        if (d > 0.01 && d < aheadDist) aheadDist = d
      }
      if (aheadDist < CAR_GAP) {
        want = 0
      } else if (aheadDist < CAR_GAP * 2.2) {
        want = Math.min(want, c.maxSpeed * ((aheadDist - CAR_GAP) / CAR_GAP))
      }

      // Smooth accel / brake
      c.speed += (want - c.speed) * Math.min(1, step * 4)
      if (c.speed < 0.01) c.speed = 0
      c.pos += c.dir * c.speed * step
      if (c.pos > CITY_EDGE) c.pos = -CITY_EDGE
      if (c.pos < -CITY_EDGE) c.pos = CITY_EDGE

      const g = groups.current[i]
      if (!g) continue
      if (c.axis === 'h') {
        g.position.set(c.pos, 0.035, c.fixed)
        g.rotation.y = c.dir > 0 ? 0 : Math.PI
      } else {
        g.position.set(c.fixed, 0.035, c.pos)
        g.rotation.y = c.dir > 0 ? -Math.PI / 2 : Math.PI / 2
      }
      const lm = lightMats.current[i]
      if (lm) lm.opacity = 0.45 + Math.min(0.45, c.speed * 0.35)
    }
  })

  return (
    <group>
      {/* Traffic signal heads at intersections */}
      {ROAD_LINES.map((x) =>
        ROAD_LINES.map((z) => (
          <Signal key={`${x},${z}`} x={x} z={z} />
        )),
      )}
      {sims.map((c, i) => (
        <group
          key={i}
          ref={(el) => {
            groups.current[i] = el
          }}
        >
          {/* Tiny body */}
          <mesh>
            <boxGeometry args={[0.085, 0.028, 0.042]} />
            <meshBasicMaterial color={c.color} transparent opacity={0.82} />
          </mesh>
          {/* Cabin */}
          <mesh position={[0.01, 0.02, 0]}>
            <boxGeometry args={[0.04, 0.02, 0.034]} />
            <meshBasicMaterial color="#1a2030" transparent opacity={0.7} />
          </mesh>
          {/* Front lights */}
          <mesh position={[0.048, 0.008, 0.012]}>
            <boxGeometry args={[0.012, 0.01, 0.01]} />
            <meshBasicMaterial
              ref={(m) => {
                lightMats.current[i] = m
              }}
              color="#ffe6a0"
              transparent
              opacity={0.7}
              depthWrite={false}
              blending={THREE.AdditiveBlending}
            />
          </mesh>
          <mesh position={[0.048, 0.008, -0.012]}>
            <boxGeometry args={[0.012, 0.01, 0.01]} />
            <meshBasicMaterial
              color="#ffe6a0"
              transparent
              opacity={0.65}
              depthWrite={false}
              blending={THREE.AdditiveBlending}
            />
          </mesh>
        </group>
      ))}
    </group>
  )
}

function Signal({ x, z }: { x: number; z: number }) {
  const lamp = useRef<THREE.MeshBasicMaterial>(null)
  useFrame((state) => {
    if (!lamp.current) return
    const phase = (state.clock.elapsedTime + (x * 2.3 + z * 1.7)) % SIGNAL_CYCLE
    // Show EW state on the lamp (orange/red/green cycle feel)
    if (phase < 3.4) {
      lamp.current.color.set('#22c55e') // NS green → EW red implied; show green pulse
      lamp.current.opacity = 0.55
    } else if (phase < 4.5) {
      lamp.current.color.set('#f59e0b')
      lamp.current.opacity = 0.7
    } else if (phase < 7.9) {
      lamp.current.color.set('#ef4444')
      lamp.current.opacity = 0.5
    } else {
      lamp.current.color.set('#f59e0b')
      lamp.current.opacity = 0.65
    }
  })
  return (
    <mesh position={[x + 0.22, 0.28, z + 0.22]}>
      <boxGeometry args={[0.04, 0.12, 0.04]} />
      <meshBasicMaterial ref={lamp} color="#22c55e" transparent opacity={0.5} />
    </mesh>
  )
}

function Ground() {
  const roadTex = useMemo(() => {
    const c = document.createElement('canvas')
    c.width = 1024
    c.height = 1024
    const ctx = c.getContext('2d')!
    // Blocks
    ctx.fillStyle = '#0a0c12'
    ctx.fillRect(0, 0, 1024, 1024)
    for (let i = 0; i < 6000; i++) {
      ctx.fillStyle = `rgba(255,255,255,${Math.random() * 0.025})`
      ctx.fillRect(Math.random() * 1024, Math.random() * 1024, 1, 1)
    }
    // Map world -7.5..7.5 → 0..1024
    const toPx = (w: number) => ((w + CITY_EDGE) / (CITY_EDGE * 2)) * 1024
    const roadHalf = ((0.55) / (CITY_EDGE * 2)) * 1024
    for (const r of ROAD_LINES) {
      const p = toPx(r)
      // Vertical road
      ctx.fillStyle = '#141820'
      ctx.fillRect(p - roadHalf, 0, roadHalf * 2, 1024)
      // Horizontal road
      ctx.fillRect(0, p - roadHalf, 1024, roadHalf * 2)
    }
    // Lane dashes
    ctx.strokeStyle = 'rgba(255, 200, 120, 0.35)'
    ctx.lineWidth = 2
    ctx.setLineDash([12, 16])
    for (const r of ROAD_LINES) {
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
    // Intersection boxes
    ctx.setLineDash([])
    ctx.fillStyle = 'rgba(255, 140, 40, 0.08)'
    for (const x of ROAD_LINES) {
      for (const z of ROAD_LINES) {
        const px = toPx(x)
        const pz = toPx(z)
        ctx.fillRect(px - roadHalf, pz - roadHalf, roadHalf * 2, roadHalf * 2)
      }
    }
    const tex = new THREE.CanvasTexture(c)
    tex.colorSpace = THREE.SRGBColorSpace
    return tex
  }, [])

  return (
    <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, 0, 0]}>
      <planeGeometry args={[CITY_EDGE * 2, CITY_EDGE * 2]} />
      <meshBasicMaterial map={roadTex} />
    </mesh>
  )
}

function SectorPlaque({ label, x, z }: { label: string; x: number; z: number }) {
  const tex = useMemo(() => {
    const c = document.createElement('canvas')
    c.width = 256
    c.height = 64
    const ctx = c.getContext('2d')!
    ctx.fillStyle = '#050508'
    ctx.fillRect(0, 0, 256, 64)
    ctx.strokeStyle = '#ffffff'
    ctx.shadowColor = '#ffffff'
    ctx.shadowBlur = 10
    ctx.strokeRect(4, 4, 248, 56)
    ctx.fillStyle = '#ffffff'
    ctx.font = 'bold 20px Orbitron, sans-serif'
    ctx.fillText(label, 16, 40)
    const t = new THREE.CanvasTexture(c)
    t.colorSpace = THREE.SRGBColorSpace
    return t
  }, [label])
  return (
    <mesh rotation={[-Math.PI / 2, 0, 0]} position={[x, 0.02, z]}>
      <planeGeometry args={[1.5, 0.38]} />
      <meshBasicMaterial map={tex} transparent toneMapped={false} />
    </mesh>
  )
}

function CityTitleBoard({ label, jobs }: { label: string; jobs: number }) {
  const tex = useMemo(() => {
    const c = document.createElement('canvas')
    c.width = 512
    c.height = 128
    const ctx = c.getContext('2d')!
    ctx.fillStyle = '#050508'
    ctx.fillRect(0, 0, 512, 128)
    ctx.strokeStyle = '#ffffff'
    ctx.shadowColor = 'rgba(255,255,255,0.8)'
    ctx.shadowBlur = 16
    ctx.lineWidth = 3
    ctx.strokeRect(10, 10, 492, 108)
    ctx.fillStyle = '#ffffff'
    ctx.font = 'bold 40px Orbitron, sans-serif'
    ctx.fillText(label.toUpperCase(), 28, 68)
    ctx.font = '20px Rajdhani, sans-serif'
    ctx.fillStyle = 'rgba(255,255,255,0.75)'
    ctx.fillText(`${jobs} openings · night district`, 28, 98)
    const t = new THREE.CanvasTexture(c)
    t.colorSpace = THREE.SRGBColorSpace
    return t
  }, [label, jobs])
  return (
    <group position={[0, 0.4, 5.4]}>
      <mesh>
        <boxGeometry args={[2.5, 0.58, 0.12]} />
        <meshBasicMaterial color="#0a0a10" />
      </mesh>
      <mesh position={[0, 0, 0.07]}>
        <planeGeometry args={[2.35, 0.5]} />
        <meshBasicMaterial map={tex} toneMapped={false} />
      </mesh>
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
  const [sectors, setSectors] = useState<{ id: string; label: string }[]>([])

  useEffect(() => {
    let alive = true
    api
      .citySkyline(cityId, 7, 28)
      .then((d) => {
        if (!alive) return
        setCompanies(d?.companies || [])
        setMaxN(d?.stats?.max_n || 1)
        setSectors(d?.sectors || [])
        useVigilStore.getState().setStatus(
          `NIGHT CITY · ${d?.label || cityLabel} · click tower to focus`,
        )
      })
      .catch(() => setCompanies([]))
    return () => {
      alive = false
    }
  }, [cityId, cityLabel])

  const towers = useMemo(
    () => layoutTowers(companies, maxN),
    [companies, maxN],
  )

  return (
    <group position={[0, CITY_Y, 0]}>
      <ambientLight intensity={0.08} color="#101018" />
      <hemisphereLight args={['#151520', '#050508', 0.25]} />
      <directionalLight position={[-5, 9, -3]} intensity={0.12} color="#c8d0e0" />
      <pointLight position={[0, 5, 2]} intensity={0.25} color="#ffffff" distance={20} />

      <Ground />
      <Traffic />

      {sectors.map((s) => {
        const b = SECTOR_BLOCK[s.id]
        if (!b) return null
        return <SectorPlaque key={s.id} label={s.label} x={b.x} z={b.z} />
      })}

      {towers.map((t) => (
        <WorkTower key={t.company_id} t={t} cityLabel={cityLabel} />
      ))}

      <CityTitleBoard
        label={cityLabel}
        jobs={companies.reduce((a, c) => a + c.n, 0)}
      />
    </group>
  )
}
