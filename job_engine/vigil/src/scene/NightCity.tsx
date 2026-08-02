import { useEffect, useMemo, useRef, useState } from 'react'
import { useFrame } from '@react-three/fiber'
import type { ThreeEvent } from '@react-three/fiber'
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
}

/** Block origins per sector — industry districts across the night city */
const SECTOR_BLOCK: Record<string, { x: number; z: number; yaw: number }> = {
  tech_ai: { x: -3.4, z: -2.2, yaw: 0.05 },
  tech_digital: { x: 2.8, z: -2.4, yaw: -0.08 },
  manufacturing_advanced: { x: -3.6, z: 2.0, yaw: 0.12 },
  healthcare: { x: 0.2, z: 3.0, yaw: -0.04 },
  green_economy: { x: 3.2, z: 1.8, yaw: 0.1 },
  logistics: { x: -1.2, z: 0.2, yaw: 0 },
  tourism: { x: 1.4, z: 0.4, yaw: -0.06 },
  software: { x: 0, z: -0.5, yaw: 0 },
}

const towerVert = /* glsl */ `
varying vec2 vUv;
varying vec3 vPos;
void main() {
  vUv = uv;
  vPos = position;
  gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
}
`

const towerFrag = /* glsl */ `
uniform float uTime;
uniform float uHeat;
uniform float uSeed;
uniform vec3 uBase;
varying vec2 vUv;
varying vec3 vPos;

float hash(vec2 p) {
  return fract(sin(dot(p, vec2(127.1 + uSeed, 311.7))) * 43758.5453);
}

void main() {
  // Building shell
  vec3 col = uBase * (0.35 + 0.25 * uHeat);

  // Window grid — busy night offices
  float floors = 18.0 + floor(uHeat * 22.0);
  float cols = 8.0;
  vec2 gv = vec2(vUv.x * cols, vUv.y * floors);
  vec2 id = floor(gv);
  vec2 f = fract(gv);
  float frame = step(0.12, f.x) * step(f.x, 0.88) * step(0.18, f.y) * step(f.y, 0.82);

  float n = hash(id);
  // Some windows always on in tall busy towers; flicker others
  float on = step(0.38 - uHeat * 0.18, n);
  float flick = 0.65 + 0.35 * step(0.5, fract(n * 17.0 + uTime * (0.7 + n * 2.2)));
  float lit = frame * on * flick;

  vec3 win = mix(vec3(1.0, 0.72, 0.28), vec3(0.55, 0.85, 1.0), step(0.7, n));
  col = mix(col, win, lit * (0.55 + 0.45 * uHeat));

  // Soft vertical edge rim
  float rim = pow(1.0 - abs(vUv.x - 0.5) * 2.0, 3.0) * 0.15 * uHeat;
  col += vec3(1.0, 0.45, 0.1) * rim;

  // Rooftop brighter on tallest (high heat)
  float roof = smoothstep(0.92, 1.0, vUv.y) * uHeat;
  col += vec3(1.0, 0.7, 0.25) * roof * 0.55;

  gl_FragColor = vec4(col, 1.0);
}
`

function makeNameBoardTexture(name: string, jobs: number, sector: string) {
  const c = document.createElement('canvas')
  c.width = 512
  c.height = 128
  const ctx = c.getContext('2d')!
  ctx.fillStyle = '#0a0604'
  ctx.fillRect(0, 0, 512, 128)
  // Brushed metal strip
  const g = ctx.createLinearGradient(0, 0, 512, 0)
  g.addColorStop(0, '#3a2210')
  g.addColorStop(0.5, '#6a3a12')
  g.addColorStop(1, '#3a2210')
  ctx.fillStyle = g
  ctx.fillRect(8, 8, 496, 112)
  ctx.strokeStyle = '#ffaa00'
  ctx.lineWidth = 3
  ctx.strokeRect(14, 14, 484, 100)
  ctx.fillStyle = '#ffe8c8'
  ctx.font = 'bold 36px Rajdhani, sans-serif'
  const label = name.length > 28 ? `${name.slice(0, 26)}…` : name
  ctx.fillText(label, 28, 62)
  ctx.fillStyle = '#ffaa00'
  ctx.font = '22px Orbitron, sans-serif'
  ctx.fillText(`${jobs} open · ${sector}`, 28, 96)
  const tex = new THREE.CanvasTexture(c)
  tex.colorSpace = THREE.SRGBColorSpace
  tex.anisotropy = 4
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
    const block = SECTOR_BLOCK[sid] || { x: 0, z: 0, yaw: 0 }
    const sorted = [...list].sort((a, b) => b.n - a.n)
    sorted.forEach((c, i) => {
      const cols = Math.min(4, Math.max(2, Math.ceil(Math.sqrt(sorted.length))))
      const gx = i % cols
      const gz = Math.floor(i / cols)
      const heat = c.n / Math.max(maxN, 1)
      // Tallest = hiring most
      const h = 0.55 + heat * 3.6
      const w = 0.38 + heat * 0.22
      const d = 0.36 + heat * 0.18
      const lx = (gx - (cols - 1) / 2) * 0.85
      const lz = gz * 0.9
      // Rotate block slightly
      const ca = Math.cos(block.yaw)
      const sa = Math.sin(block.yaw)
      const x = block.x + lx * ca - lz * sa
      const z = block.z + lx * sa + lz * ca
      towers.push({
        company_id: c.company_id,
        name: c.name,
        n: c.n,
        sector_id: sid,
        sector_label: c.sector_label,
        x,
        z,
        w,
        d,
        h,
        heat,
        seed: (c.company_id * 17.13) % 100,
      })
    })
  }
  return towers
}

function WorkTower({
  t,
  cityLabel,
}: {
  t: Tower
  cityLabel: string
}) {
  const mat = useRef<THREE.ShaderMaterial>(null)
  const boardTex = useMemo(
    () => makeNameBoardTexture(t.name, t.n, t.sector_label),
    [t.name, t.n, t.sector_label],
  )

  useFrame((state) => {
    if (mat.current) mat.current.uniforms.uTime.value = state.clock.elapsedTime
  })

  const uniforms = useMemo(
    () => ({
      uTime: { value: 0 },
      uHeat: { value: t.heat },
      uSeed: { value: t.seed },
      uBase: { value: new THREE.Color('#1a0c08') },
    }),
    [t.heat, t.seed],
  )

  const onEnter = (e: ThreeEvent<PointerEvent>) => {
    e.stopPropagation()
    document.body.style.cursor = 'pointer'
    useVigilStore.setState({
      statusLine: `${t.name} · ${t.n} jobs · ${t.sector_label} · ${cityLabel}`,
    })
  }
  const onLeave = () => {
    document.body.style.cursor = 'default'
  }
  const onClick = (e: ThreeEvent<MouseEvent>) => {
    e.stopPropagation()
    useVigilStore.getState().openCompanyJobs(t.company_id, t.name, 7)
  }

  // Name board on the front facade — same facing as the tower (not screen billboard)
  const boardY = Math.min(t.h * 0.55, t.h - 0.15)
  const boardW = Math.min(t.w * 1.35, 0.95)
  const boardH = 0.16 + t.heat * 0.06

  return (
    <group position={[t.x, t.h / 2, t.z]}>
      {/* Fat pick volume */}
      <mesh
        onPointerOver={onEnter}
        onPointerOut={onLeave}
        onClick={onClick}
      >
        <boxGeometry args={[t.w * 1.35, t.h, t.d * 1.35]} />
        <meshBasicMaterial transparent opacity={0} depthWrite={false} />
      </mesh>

      {/* Tower body with night windows */}
      <mesh>
        <boxGeometry args={[t.w, t.h, t.d]} />
        <shaderMaterial
          ref={mat}
          uniforms={uniforms}
          vertexShader={towerVert}
          fragmentShader={towerFrag}
        />
      </mesh>

      {/* Rooftop beacon on busiest towers */}
      {t.heat > 0.55 && (
        <mesh position={[0, t.h / 2 + 0.06, 0]}>
          <boxGeometry args={[t.w * 0.35, 0.08, t.d * 0.35]} />
          <meshBasicMaterial color="#ffaa00" />
        </mesh>
      )}

      {/* Facade name board — locked to building angle */}
      <group position={[0, boardY - t.h / 2, t.d / 2 + 0.02]}>
        <mesh onPointerOver={onEnter} onPointerOut={onLeave} onClick={onClick}>
          <boxGeometry args={[boardW, boardH, 0.04]} />
          <meshBasicMaterial map={boardTex} toneMapped={false} />
        </mesh>
        {/* Warm under-glow on the sign */}
        <mesh position={[0, -boardH * 0.55, 0.01]}>
          <planeGeometry args={[boardW * 0.95, 0.03]} />
          <meshBasicMaterial
            color="#ff5500"
            transparent
            opacity={0.35 + t.heat * 0.4}
            depthWrite={false}
          />
        </mesh>
      </group>
    </group>
  )
}

function SectorPlaque({
  label,
  x,
  z,
}: {
  label: string
  x: number
  z: number
}) {
  const tex = useMemo(() => {
    const c = document.createElement('canvas')
    c.width = 256
    c.height = 64
    const ctx = c.getContext('2d')!
    ctx.fillStyle = '#050302'
    ctx.fillRect(0, 0, 256, 64)
    ctx.strokeStyle = '#ff5500'
    ctx.strokeRect(4, 4, 248, 56)
    ctx.fillStyle = '#ffaa00'
    ctx.font = 'bold 22px Orbitron, sans-serif'
    ctx.fillText(label, 16, 40)
    const t = new THREE.CanvasTexture(c)
    t.colorSpace = THREE.SRGBColorSpace
    return t
  }, [label])
  return (
    <mesh
      rotation={[-Math.PI / 2, 0, 0]}
      position={[x, 0.02, z - 1.1]}
    >
      <planeGeometry args={[1.4, 0.35]} />
      <meshBasicMaterial map={tex} transparent opacity={0.9} toneMapped={false} />
    </mesh>
  )
}

function Ground() {
  return (
    <group>
      <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, 0, 0]} receiveShadow>
        <planeGeometry args={[22, 22]} />
        <meshStandardMaterial color="#07040a" roughness={0.92} metalness={0.15} />
      </mesh>
      {/* Street grid glow */}
      {[-4, -2, 0, 2, 4].map((x) => (
        <mesh key={`vx${x}`} rotation={[-Math.PI / 2, 0, 0]} position={[x, 0.01, 0]}>
          <planeGeometry args={[0.06, 18]} />
          <meshBasicMaterial color="#ff5500" transparent opacity={0.12} />
        </mesh>
      ))}
      {[-4, -2, 0, 2, 4].map((z) => (
        <mesh key={`hz${z}`} rotation={[-Math.PI / 2, 0, 0]} position={[0, 0.01, z]}>
          <planeGeometry args={[18, 0.06]} />
          <meshBasicMaterial color="#ff7700" transparent opacity={0.08} />
        </mesh>
      ))}
      {/* Horizon haze */}
      <mesh position={[0, 1.2, -9]}>
        <planeGeometry args={[28, 4]} />
        <meshBasicMaterial
          color="#1a0a04"
          transparent
          opacity={0.55}
          depthWrite={false}
        />
      </mesh>
    </group>
  )
}

function StreetLamps() {
  const lamps = useMemo(() => {
    const pts: [number, number, number][] = []
    for (let x = -5; x <= 5; x += 2.5) {
      for (let z = -5; z <= 5; z += 2.5) {
        if ((x + z) % 5 === 0) pts.push([x, 0, z])
      }
    }
    return pts
  }, [])
  return (
    <group>
      {lamps.map((p, i) => (
        <group key={i} position={p}>
          <mesh position={[0, 0.55, 0]}>
            <cylinderGeometry args={[0.03, 0.04, 1.1, 6]} />
            <meshBasicMaterial color="#1a120c" />
          </mesh>
          <mesh position={[0, 1.15, 0]}>
            <sphereGeometry args={[0.08, 8, 8]} />
            <meshBasicMaterial color="#ffaa66" />
          </mesh>
          <pointLight
            position={[0, 1.15, 0]}
            intensity={0.35}
            distance={3.2}
            color="#ff8844"
            decay={2}
          />
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
  const [sectors, setSectors] = useState<{ id: string; label: string }[]>([])
  const root = useRef<THREE.Group>(null)

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
          `NIGHT CITY · ${d?.label || cityLabel} · ${d?.stats?.companies || 0} towers`,
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
    <group ref={root} position={[0, -1.2, 0]}>
      <ambientLight intensity={0.12} color="#1a1030" />
      <hemisphereLight args={['#1a2240', '#0a0402', 0.35]} />
      <directionalLight
        position={[-6, 8, -4]}
        intensity={0.15}
        color="#4466aa"
      />
      <pointLight position={[0, 4, 2]} intensity={0.4} color="#ff5500" distance={18} />

      <Ground />
      <StreetLamps />

      {sectors.map((s) => {
        const b = SECTOR_BLOCK[s.id]
        if (!b) return null
        return (
          <SectorPlaque key={s.id} label={s.label} x={b.x} z={b.z} />
        )
      })}

      {towers.map((t) => (
        <WorkTower key={t.company_id} t={t} cityLabel={cityLabel} />
      ))}

      {towers.length === 0 && (
        <mesh position={[0, 0.8, 0]}>
          <boxGeometry args={[2.2, 0.4, 0.1]} />
          <meshBasicMaterial color="#1a0c08" />
        </mesh>
      )}

      {/* City title as street monument (not floating Html tag) */}
      <mesh position={[0, 0.35, 5.2]}>
        <boxGeometry args={[2.4, 0.55, 0.12]} />
        <meshBasicMaterial color="#120804" />
      </mesh>
      <CityTitleBoard label={cityLabel} jobs={companies.reduce((a, c) => a + c.n, 0)} />
    </group>
  )
}

function CityTitleBoard({ label, jobs }: { label: string; jobs: number }) {
  const tex = useMemo(() => {
    const c = document.createElement('canvas')
    c.width = 512
    c.height = 128
    const ctx = c.getContext('2d')!
    ctx.fillStyle = '#0a0604'
    ctx.fillRect(0, 0, 512, 128)
    ctx.strokeStyle = '#ff5500'
    ctx.lineWidth = 4
    ctx.strokeRect(10, 10, 492, 108)
    ctx.fillStyle = '#ffaa00'
    ctx.font = 'bold 44px Orbitron, sans-serif'
    ctx.fillText(label.toUpperCase(), 28, 70)
    ctx.fillStyle = '#ffe0c0'
    ctx.font = '22px Rajdhani, sans-serif'
    ctx.fillText(`${jobs} openings · night district`, 28, 100)
    const t = new THREE.CanvasTexture(c)
    t.colorSpace = THREE.SRGBColorSpace
    return t
  }, [label, jobs])
  return (
    <mesh position={[0, 0.35, 5.28]}>
      <planeGeometry args={[2.3, 0.5]} />
      <meshBasicMaterial map={tex} toneMapped={false} />
    </mesh>
  )
}
