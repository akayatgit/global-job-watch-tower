import { useEffect, useMemo, useRef, useState, type RefObject } from 'react'
import { useFrame, useThree } from '@react-three/fiber'
import type { ThreeEvent } from '@react-three/fiber'
import { Billboard } from '@react-three/drei'
import * as THREE from 'three'
import { api } from '../lib/api'
import { useVigilStore } from '../store/vigilStore'
import { NightCity } from './NightCity'
import { wasDragClick } from './pointerGuard'

const CITY_GEO: Record<string, { lat: number; lon: number; label: string }> = {
  bengaluru: { lat: 12.97, lon: 77.59, label: 'Bengaluru' },
  hyderabad: { lat: 17.39, lon: 78.49, label: 'Hyderabad' },
  chennai: { lat: 13.08, lon: 80.27, label: 'Chennai' },
  kerala: { lat: 10.85, lon: 76.27, label: 'Kerala' },
  pune: { lat: 18.52, lon: 73.86, label: 'Pune' },
  mumbai: { lat: 19.08, lon: 72.88, label: 'Mumbai' },
  delhi: { lat: 28.61, lon: 77.21, label: 'Delhi' },
  gurugram: { lat: 28.46, lon: 77.03, label: 'Gurugram' },
  noida: { lat: 28.54, lon: 77.39, label: 'Noida' },
  ahmedabad: { lat: 23.02, lon: 72.57, label: 'Ahmedabad' },
  kolkata: { lat: 22.57, lon: 88.36, label: 'Kolkata' },
}

/** Flat “overview” map (India-relative) — used when camera is far */
function overviewPos(lat: number, lon: number) {
  // Wider spacing so cards don’t collide
  const x = ((lon - 78) / 18) * 3.4
  const y = ((lat - 18) / 16) * 2.9
  return new THREE.Vector3(x, y, 2.7)
}

function latLonToVec(lat: number, lon: number, r: number) {
  const phi = (90 - lat) * (Math.PI / 180)
  const theta = (lon + 90) * (Math.PI / 180)
  return new THREE.Vector3(
    r * Math.sin(phi) * Math.cos(theta),
    r * Math.cos(phi),
    r * Math.sin(phi) * Math.sin(theta),
  )
}

function smoothstep(edge0: number, edge1: number, x: number) {
  const t = THREE.MathUtils.clamp((x - edge0) / (edge1 - edge0), 0, 1)
  return t * t * (3 - 2 * t)
}

function makeCityCardTex(
  label: string,
  n: number,
  kind: 'city' | 'remote',
  focused: boolean,
) {
  const c = document.createElement('canvas')
  c.width = 384
  c.height = 112
  const ctx = c.getContext('2d')!
  const accent = kind === 'remote' ? '#7dd3fc' : focused ? '#ffaa00' : '#ff8c40'
  ctx.fillStyle = focused ? '#1c1006' : '#08060c'
  ctx.fillRect(0, 0, 384, 112)
  // Glass-pillar style: cool top wash → orange base glow
  const wash = ctx.createLinearGradient(0, 0, 0, 112)
  wash.addColorStop(0, 'rgba(180, 230, 255, 0.22)')
  wash.addColorStop(0.55, 'rgba(20, 16, 12, 0.2)')
  wash.addColorStop(1, 'rgba(255, 90, 0, 0.35)')
  ctx.fillStyle = wash
  ctx.fillRect(8, 8, 368, 96)
  ctx.strokeStyle = accent
  ctx.shadowColor = accent
  ctx.shadowBlur = focused ? 26 : 14
  ctx.lineWidth = focused ? 5 : 3.5
  ctx.strokeRect(6, 6, 372, 100)
  ctx.shadowBlur = 0
  ctx.fillStyle = '#ffffff'
  ctx.font = '800 36px Orbitron, sans-serif'
  ctx.shadowColor = 'rgba(255,255,255,0.55)'
  ctx.shadowBlur = 8
  const name = label.length > 14 ? `${label.slice(0, 12)}…` : label
  ctx.fillText(name, 20, 48)
  ctx.shadowBlur = 10
  ctx.shadowColor = kind === 'remote' ? 'rgba(125,211,252,0.8)' : 'rgba(255,140,40,0.9)'
  ctx.fillStyle = kind === 'remote' ? '#e0f6ff' : '#ffe0b0'
  ctx.font = '800 34px Rajdhani, sans-serif'
  ctx.fillText(String(n), 20, 88)
  const tex = new THREE.CanvasTexture(c)
  tex.colorSpace = THREE.SRGBColorSpace
  tex.anisotropy = 4
  return tex
}

type CityNode = { id: string; label: string; n: number }

function FocusGlow({ active }: { active: boolean }) {
  const ring = useRef<THREE.Mesh>(null)
  useFrame((state) => {
    if (!ring.current) return
    ring.current.visible = active
    if (!active) return
    const pulse = 0.55 + Math.sin(state.clock.elapsedTime * 3.2) * 0.35
    const s = 1.15 + Math.sin(state.clock.elapsedTime * 2.4) * 0.12
    ring.current.scale.setScalar(s)
    const mat = ring.current.material as THREE.MeshBasicMaterial
    mat.opacity = pulse
  })
  return (
    <mesh ref={ring} visible={false}>
      <ringGeometry args={[0.22, 0.32, 48]} />
      <meshBasicMaterial
        color="#ffaa00"
        transparent
        opacity={0.7}
        side={THREE.DoubleSide}
        depthWrite={false}
        blending={THREE.AdditiveBlending}
      />
    </mesh>
  )
}

function CityMarker({
  city,
  remoteN,
  globeR,
  globeRef,
  interactive,
}: {
  city: CityNode
  remoteN: number
  globeR: number
  globeRef: RefObject<THREE.Group | null>
  interactive: boolean
}) {
  const geo = CITY_GEO[city.id]
  const group = useRef<THREE.Group>(null)
  const remoteGroup = useRef<THREE.Group>(null)
  const { camera } = useThree()
  const selectFocusId = useVigilStore((s) => s.selectFocusId)
  const citySelect = `city:${city.id}`
  const remoteSelect = `remote-twin:${city.id}`
  const cityFocused = selectFocusId === citySelect
  const remoteFocused = selectFocusId === remoteSelect
  const [remoteHot, setRemoteHot] = useState(false)
  const [cityHot, setCityHot] = useState(false)
  const pickGlow = useRef<THREE.Mesh>(null)

  const cityTex = useMemo(
    () => makeCityCardTex(geo.label, city.n, 'city', cityFocused),
    [geo.label, city.n, cityFocused],
  )
  const remoteTex = useMemo(
    () => makeCityCardTex('Remote', remoteN, 'remote', remoteFocused || remoteHot),
    [remoteN, remoteFocused, remoteHot],
  )

  const geoPos = useMemo(
    () => latLonToVec(geo.lat, geo.lon, globeR * 1.06),
    [geo.lat, geo.lon, globeR],
  )
  const overPos = useMemo(
    () => overviewPos(geo.lat, geo.lon),
    [geo.lat, geo.lon],
  )

  const tmp = useRef({
    pos: new THREE.Vector3(),
    world: new THREE.Vector3(),
    scale: 1,
    camDir: new THREE.Vector3(),
  }).current

  useFrame(() => {
    if (!group.current) return
    const camDist = camera.position.length()
    // Far → overview map (large cards). Near → geo on globe (small cards).
    const nearness = smoothstep(9.5, 3.4, camDist)
    tmp.pos.lerpVectors(overPos, geoPos, nearness)
    // If this city is focused, snap harder to geo + pull slightly out
    if (cityFocused || remoteFocused) {
      tmp.pos.lerp(geoPos, 0.9)
      const out = geoPos.clone().normalize().multiplyScalar(0.14)
      tmp.pos.add(out)
    }
    group.current.position.copy(tmp.pos)

    // Hide cards on the far side of the globe — stops all-sides interference
    if (globeRef.current && nearness > 0.35) {
      tmp.world.copy(tmp.pos)
      globeRef.current.localToWorld(tmp.world)
      tmp.camDir.copy(camera.position).sub(tmp.world).normalize()
      const outward = tmp.world.clone().normalize()
      const facing = outward.dot(tmp.camDir)
      const show = facing > 0.18 || cityFocused || remoteFocused || remoteHot
      group.current.visible = show
      if (!show) return
    } else {
      group.current.visible = true
    }

    tmp.scale = THREE.MathUtils.lerp(1.05, 0.34, nearness)
    if (cityFocused) tmp.scale *= 1.2
    group.current.scale.setScalar(tmp.scale)

    // Remote twin — only when near / hovered / focused (cuts clutter)
    if (remoteGroup.current) {
      const showRemote =
        nearness > 0.45 || remoteHot || remoteFocused || cityFocused
      remoteGroup.current.visible = showRemote
      const back = remoteHot || remoteFocused ? 0.03 : -0.12
      const lift = remoteHot || remoteFocused ? 0.1 : -0.03
      remoteGroup.current.position.set(0.05, lift, back)
      const rs = remoteHot || remoteFocused ? 0.9 : 0.68
      remoteGroup.current.scale.setScalar(rs)
    }

    if (pickGlow.current) {
      const on = cityHot && !cityFocused
      pickGlow.current.visible = on
      if (on) {
        const pulse = 0.4 + Math.sin(performance.now() * 0.006) * 0.25
        pickGlow.current.scale.setScalar(1.15 + Math.sin(performance.now() * 0.005) * 0.08)
        ;(pickGlow.current.material as THREE.MeshBasicMaterial).opacity = pulse
      }
    }
  })

  const worldFocus = (local: THREE.Vector3, id: string, distance: number) => {
    const st = useVigilStore.getState()
    const w = local.clone()
    if (globeRef.current) globeRef.current.localToWorld(w)
    else if (group.current) group.current.parent?.localToWorld(w)
    st.setSceneSpin(false)
    st.requestCameraFocus({
      id,
      x: w.x,
      y: w.y,
      z: w.z,
      distance,
    })
  }

  const onCityClick = (e: ThreeEvent<MouseEvent>) => {
    if (!interactive) return
    e.stopPropagation()
    if (wasDragClick()) return
    const st = useVigilStore.getState()
    if (st.selectFocusId !== citySelect) {
      worldFocus(geoPos.clone().multiplyScalar(1.04), citySelect, 1.35)
      st.setStatus(`FOCUS · ${geo.label} · click again to enter`)
      return
    }
    st.setCityFocus(city.id)
    st.setCityFilter(city.id)
    st.clearCameraFocus()
    st.resetView()
    st.setStatus(`ENTERING ${geo.label}`)
    st.triggerBurst()
  }

  const onRemoteClick = (e: ThreeEvent<MouseEvent>) => {
    if (!interactive) return
    e.stopPropagation()
    if (wasDragClick()) return
    const st = useVigilStore.getState()
    if (st.selectFocusId !== remoteSelect) {
      const behind = geoPos.clone().multiplyScalar(0.98)
      worldFocus(behind, remoteSelect, 1.25)
      st.setStatus(`FOCUS · Remote @ ${geo.label} · click again to open`)
      return
    }
    st.setCityFilter('remote')
    st.clearInsightFocus()
    st.openPanel('jobs')
    st.setStatus(`JOBS · Remote`)
    st.triggerBurst()
  }

  return (
    <group ref={group}>
      <FocusGlow active={cityFocused || remoteFocused} />
      {cityFocused && (
        <pointLight color="#ffaa00" intensity={1.4} distance={2.2} />
      )}

      {/* City card (front) */}
      <Billboard follow>
        <mesh ref={pickGlow} position={[0, 0, -0.02]} visible={false}>
          <planeGeometry args={[1.2, 0.48]} />
          <meshBasicMaterial
            color="#ffaa00"
            transparent
            opacity={0.4}
            depthWrite={false}
            blending={THREE.AdditiveBlending}
          />
        </mesh>
        <mesh
          onClick={onCityClick}
          onPointerOver={(e) => {
            if (!interactive) return
            e.stopPropagation()
            setCityHot(true)
            useVigilStore.setState({
              statusLine: cityFocused
                ? `FOCUSED · ${geo.label} · click again to enter`
                : `PICK · ${geo.label} · ${city.n}`,
            })
          }}
          onPointerOut={() => setCityHot(false)}
        >
          <planeGeometry args={[0.95, 0.3]} />
          <meshBasicMaterial
            map={cityTex}
            transparent
            toneMapped={false}
            depthWrite={false}
          />
        </mesh>
        {/* Soft glow plate behind focused city */}
        {(cityFocused || cityHot) && (
          <mesh position={[0, 0, -0.01]}>
            <planeGeometry args={[1.15, 0.42]} />
            <meshBasicMaterial
              color="#ff8800"
              transparent
              opacity={cityFocused ? 0.35 : 0.28}
              depthWrite={false}
              blending={THREE.AdditiveBlending}
            />
          </mesh>
        )}

        {/* Remote twin — slightly behind; pops out on hover */}
        <group ref={remoteGroup}>
          <mesh
            onClick={onRemoteClick}
            onPointerOver={(e) => {
              if (!interactive) return
              e.stopPropagation()
              setRemoteHot(true)
              useVigilStore.setState({
                statusLine: remoteFocused
                  ? `FOCUSED · Remote · click again to open jobs`
                  : `Remote · ${remoteN} — touch to pop out`,
              })
            }}
            onPointerOut={() => setRemoteHot(false)}
          >
            <planeGeometry args={[0.78, 0.24]} />
            <meshBasicMaterial
              map={remoteTex}
              transparent
              opacity={remoteHot || remoteFocused ? 0.98 : 0.78}
              toneMapped={false}
              depthWrite={false}
            />
          </mesh>
          {(remoteHot || remoteFocused) && (
            <mesh position={[0, 0, -0.01]}>
              <planeGeometry args={[0.9, 0.32]} />
              <meshBasicMaterial
                color="#38bdf8"
                transparent
                opacity={0.3}
                depthWrite={false}
                blending={THREE.AdditiveBlending}
              />
            </mesh>
          )}
        </group>
      </Billboard>

    </group>
  )
}

function GeoPin({
  city,
  globeR,
  focused,
}: {
  city: CityNode
  globeR: number
  focused: boolean
}) {
  const geo = CITY_GEO[city.id]
  const p = useMemo(
    () => latLonToVec(geo.lat, geo.lon, globeR * 1.02),
    [geo.lat, geo.lon, globeR],
  )
  return (
    <mesh position={p}>
      <sphereGeometry args={[0.035 + Math.min(city.n, 400) / 400 * 0.05, 12, 12]} />
      <meshBasicMaterial
        color={focused ? '#ffaa00' : '#ff5500'}
        transparent
        opacity={0.95}
      />
    </mesh>
  )
}

export function CityGlobe() {
  const sceneMode = useVigilStore((s) => s.sceneMode)
  const cityFocus = useVigilStore((s) => s.cityFocus)
  const focusedPanel = useVigilStore((s) => s.focusedPanel)
  const sceneSpin = useVigilStore((s) => s.sceneSpin)
  const selectFocusId = useVigilStore((s) => s.selectFocusId)
  const [cities, setCities] = useState<CityNode[]>([])
  const [remoteN, setRemoteN] = useState(0)
  const globe = useRef<THREE.Group>(null)
  const spinY = useRef(0)
  const lastT = useRef(0)

  useEffect(() => {
    if (sceneMode !== 'city') return
    let alive = true
    api
      .citySignals(7)
      .then((d) => {
        if (!alive) return
        const rows = (d?.cities || []) as {
          city?: string
          label?: string
          recent?: number
        }[]
        const mapped = rows.map((r) => ({
          id: r.city || '',
          label: r.label || r.city || '',
          n: r.recent ?? 0,
        }))
        const rem = mapped.find((c) => c.id === 'remote')
        setRemoteN(rem?.n ?? 0)
        setCities(mapped.filter((c) => c.id && CITY_GEO[c.id]))
      })
      .catch(() => {})
    return () => {
      alive = false
    }
  }, [sceneMode])

  useFrame((state) => {
    if (globe.current && !cityFocus) {
      const t = state.clock.elapsedTime
      const focused = useVigilStore.getState().selectFocusId
      // Freeze spin while a city/remote is focused
      if (sceneSpin && !focused) {
        spinY.current += Math.max(0, t - lastT.current) * 0.1
      }
      lastT.current = t
      globe.current.rotation.y = spinY.current
    }
  })

  if (sceneMode !== 'city') return null

  const focusRow = cities.find((c) => c.id === cityFocus)
  const focusLabel =
    focusRow?.label || CITY_GEO[cityFocus || '']?.label || cityFocus || ''

  if (cityFocus) {
    return <NightCity cityId={cityFocus} cityLabel={focusLabel} />
  }

  const R = 1.85
  const interactive = !focusedPanel

  return (
    <group ref={globe}>
      <mesh>
        <sphereGeometry args={[R, 48, 48]} />
        <meshBasicMaterial color="#120804" transparent opacity={0.92} />
      </mesh>
      {/* Soft India glow under the map */}
      <mesh position={[0, 0.15, 1.55]}>
        <circleGeometry args={[1.8, 48]} />
        <meshBasicMaterial
          color="#ff5500"
          transparent
          opacity={0.06}
          depthWrite={false}
          blending={THREE.AdditiveBlending}
        />
      </mesh>
      {cities.map((c) => (
        <group key={c.id}>
          <GeoPin
            city={c}
            globeR={R}
            focused={selectFocusId === `city:${c.id}`}
          />
          <CityMarker
            city={c}
            remoteN={remoteN}
            globeR={R}
            globeRef={globe}
            interactive={interactive}
          />
        </group>
      ))}
    </group>
  )
}
