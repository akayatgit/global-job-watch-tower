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

const SECTOR_BLOCK: Record<string, { x: number; z: number }> = {
  tech_ai: { x: -3.8, z: -2.6 },
  tech_digital: { x: 3.2, z: -2.8 },
  manufacturing_advanced: { x: -4.0, z: 2.4 },
  healthcare: { x: 0.4, z: 3.4 },
  green_economy: { x: 3.6, z: 2.2 },
  logistics: { x: -1.4, z: 0.3 },
  tourism: { x: 1.6, z: 0.5 },
  software: { x: 0.2, z: -0.6 },
}

const STYLES: TowerStyle[] = ['slab', 'taper', 'spire', 'step', 'twin']

const towerVert = /* glsl */ `
varying vec2 vUv;
void main() {
  vUv = uv;
  gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
}
`

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

  // Smaller window squares, thicker mullions
  float frame = step(0.22, f.x) * step(f.x, 0.78) * step(0.28, f.y) * step(f.y, 0.78);
  float n = hash(id);
  float on = step(0.32 - uHeat * 0.12, n);
  float flick = 0.72 + 0.28 * step(0.55, fract(n * 19.0 + uTime * (0.55 + n * 1.8)));
  float lit = frame * on * flick;

  // White office light only
  vec3 win = vec3(0.92, 0.94, 1.0) * (0.55 + 0.45 * uHeat);
  col = mix(col, win, lit * 0.85);

  float rim = pow(1.0 - abs(vUv.x - 0.5) * 2.0, 2.5) * 0.08;
  col += vec3(rim);

  gl_FragColor = vec4(col, 1.0);
}
`

function hash01(n: number) {
  const x = Math.sin(n * 127.1) * 43758.5453
  return x - Math.floor(x)
}

function makeNeonBoard(name: string, jobs: number, hue: number) {
  const c = document.createElement('canvas')
  c.width = 512
  c.height = 140
  const ctx = c.getContext('2d')!
  // Dark glass
  ctx.fillStyle = '#050308'
  ctx.fillRect(0, 0, 512, 140)
  // Neon frame
  ctx.strokeStyle = `hsla(${hue}, 100%, 60%, 0.95)`
  ctx.lineWidth = 5
  ctx.shadowColor = `hsla(${hue}, 100%, 60%, 0.95)`
  ctx.shadowBlur = 18
  ctx.strokeRect(12, 12, 488, 116)
  ctx.shadowBlur = 8
  ctx.strokeRect(20, 20, 472, 100)
  // Accent bar
  const g = ctx.createLinearGradient(24, 0, 488, 0)
  g.addColorStop(0, `hsla(${hue}, 100%, 55%, 0.15)`)
  g.addColorStop(0.5, `hsla(${hue}, 100%, 65%, 0.45)`)
  g.addColorStop(1, `hsla(${hue}, 100%, 55%, 0.15)`)
  ctx.fillStyle = g
  ctx.fillRect(24, 24, 464, 92)
  // Name
  ctx.shadowColor = `hsla(${hue}, 100%, 70%, 0.9)`
  ctx.shadowBlur = 14
  ctx.fillStyle = '#ffffff'
  ctx.font = 'bold 34px Orbitron, sans-serif'
  const label = name.length > 22 ? `${name.slice(0, 20)}…` : name
  ctx.fillText(label.toUpperCase(), 36, 72)
  ctx.shadowBlur = 6
  ctx.fillStyle = `hsla(${hue}, 100%, 70%, 1)`
  ctx.font = '20px Rajdhani, sans-serif'
  ctx.fillText(`${jobs} OPEN ROLES`, 36, 104)
  const tex = new THREE.CanvasTexture(c)
  tex.colorSpace = THREE.SRGBColorSpace
  tex.anisotropy = 8
  return tex
}

function makePinTexture(n: number) {
  const c = document.createElement('canvas')
  c.width = 128
  c.height = 128
  const ctx = c.getContext('2d')!
  ctx.clearRect(0, 0, 128, 128)
  ctx.beginPath()
  ctx.arc(64, 52, 36, 0, Math.PI * 2)
  ctx.fillStyle = '#ffffff'
  ctx.shadowColor = 'rgba(255,255,255,0.9)'
  ctx.shadowBlur = 16
  ctx.fill()
  ctx.beginPath()
  ctx.moveTo(40, 78)
  ctx.lineTo(64, 118)
  ctx.lineTo(88, 78)
  ctx.closePath()
  ctx.fill()
  ctx.shadowBlur = 0
  ctx.fillStyle = '#0a0604'
  ctx.font = 'bold 36px Orbitron, sans-serif'
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
  // Per-building neon hue: orange / amber / cyan / magenta accents
  const hue = [28, 42, 185, 320, 12][Math.floor(hash01(t.seed + 20) * 5)]
  const boardTex = useMemo(
    () => makeNeonBoard(t.name, t.n, hue),
    [t.name, t.n, hue],
  )
  const pinTex = useMemo(() => makePinTexture(t.n), [t.n])
  const pin = useRef<THREE.Group>(null)
  const glow = useRef<THREE.Mesh>(null)
  const selectId = `company:${t.company_id}`
  const focused = useVigilStore((s) => s.selectFocusId === selectId)

  useFrame((state) => {
    if (pin.current) {
      const breath = 1 + Math.sin(state.clock.elapsedTime * 2.4 + t.seed) * 0.08
      pin.current.scale.setScalar(breath)
      pin.current.position.y =
        t.h / 2 + 0.28 + Math.sin(state.clock.elapsedTime * 2.1 + t.seed) * 0.05
    }
    if (glow.current) {
      glow.current.visible = focused
      if (focused) {
        const pulse = 0.25 + Math.sin(state.clock.elapsedTime * 3.0) * 0.18
        glow.current.scale.setScalar(1.2 + Math.sin(state.clock.elapsedTime * 2.2) * 0.1)
        ;(glow.current.material as THREE.MeshBasicMaterial).opacity = pulse
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
      distance: 2.6 + t.h * 0.45,
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
      <mesh onClick={handleClick} onPointerOver={(e) => {
        e.stopPropagation()
        document.body.style.cursor = 'none'
        useVigilStore.setState({
          statusLine: `${t.name} · ${t.n} · ${t.sector_label}`,
        })
      }}>
        <boxGeometry args={[t.w * 1.4, t.h, t.d * 1.4]} />
        <meshBasicMaterial transparent opacity={0} depthWrite={false} />
      </mesh>

      <TowerBody t={t} />
      {focused && (
        <pointLight
          position={[0, t.h * 0.2, 0]}
          color="#ffaa00"
          intensity={1.6}
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
              color={new THREE.Color().setHSL(hue / 360, 1, 0.55)}
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
          <pointLight intensity={0.28} distance={1.2} color="#ffffff" />
        </group>
      </Billboard>
    </group>
  )
}

/** NPC cars — subtle white/grey traffic keeping the city alive */
function Traffic() {
  const cars = useMemo(() => {
    const list: {
      lane: 'h' | 'v'
      offset: number
      speed: number
      phase: number
      y: number
      color: string
    }[] = []
    for (let i = 0; i < 48; i++) {
      list.push({
        lane: i % 2 === 0 ? 'h' : 'v',
        offset: (hash01(i * 3.1) - 0.5) * 10,
        speed: 1.2 + hash01(i * 7.7) * 2.8,
        phase: hash01(i * 2.2) * Math.PI * 2,
        y: 0.06,
        color: hash01(i) > 0.85 ? '#ffffff' : '#c8c8d0',
      })
    }
    return list
  }, [])
  const group = useRef<THREE.Group>(null)
  const meshes = useRef<(THREE.Mesh | null)[]>([])

  useFrame((state) => {
    const t = state.clock.elapsedTime
    cars.forEach((c, i) => {
      const m = meshes.current[i]
      if (!m) return
      const u = (t * c.speed + c.phase * 3) % 16 - 8
      if (c.lane === 'h') {
        m.position.set(u, c.y, c.offset)
        m.rotation.y = Math.sin(t * 0.2 + i) > 0 ? 0 : Math.PI
      } else {
        m.position.set(c.offset, c.y, u)
        m.rotation.y = Math.PI / 2
      }
    })
  })

  return (
    <group ref={group}>
      {cars.map((c, i) => (
        <mesh
          key={i}
          ref={(el) => {
            meshes.current[i] = el
          }}
        >
          <boxGeometry args={[0.22, 0.07, 0.1]} />
          <meshBasicMaterial color={c.color} />
        </mesh>
      ))}
    </group>
  )
}

function Ground() {
  const roadTex = useMemo(() => {
    const c = document.createElement('canvas')
    c.width = 512
    c.height = 512
    const ctx = c.getContext('2d')!
    ctx.fillStyle = '#06060a'
    ctx.fillRect(0, 0, 512, 512)
    // Asphalt noise
    for (let i = 0; i < 4000; i++) {
      ctx.fillStyle = `rgba(255,255,255,${Math.random() * 0.03})`
      ctx.fillRect(Math.random() * 512, Math.random() * 512, 1, 1)
    }
    // Road grid with lane dashes
    ctx.strokeStyle = 'rgba(255,255,255,0.12)'
    ctx.lineWidth = 6
    for (let i = 64; i < 512; i += 128) {
      ctx.beginPath()
      ctx.moveTo(i, 0)
      ctx.lineTo(i, 512)
      ctx.stroke()
      ctx.beginPath()
      ctx.moveTo(0, i)
      ctx.lineTo(512, i)
      ctx.stroke()
    }
    ctx.strokeStyle = 'rgba(255,255,255,0.28)'
    ctx.lineWidth = 2
    ctx.setLineDash([10, 14])
    for (let i = 64; i < 512; i += 128) {
      ctx.beginPath()
      ctx.moveTo(i, 0)
      ctx.lineTo(i, 512)
      ctx.stroke()
      ctx.beginPath()
      ctx.moveTo(0, i)
      ctx.lineTo(512, i)
      ctx.stroke()
    }
    const tex = new THREE.CanvasTexture(c)
    tex.wrapS = tex.wrapT = THREE.RepeatWrapping
    tex.repeat.set(3, 3)
    tex.colorSpace = THREE.SRGBColorSpace
    return tex
  }, [])

  return (
    <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, 0, 0]}>
      <planeGeometry args={[24, 24]} />
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
