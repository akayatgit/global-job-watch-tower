import { useEffect, useMemo, useRef, useState } from 'react'
import { useFrame } from '@react-three/fiber'
import type { ThreeEvent } from '@react-three/fiber'
import * as THREE from 'three'
import { api } from '../lib/api'
import { useVigilStore } from '../store/vigilStore'

/** Rough India-metro lat/lon for globe placement (visual, not GIS-perfect). */
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
  remote: { lat: 5.0, lon: 80.0, label: 'Remote' },
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

type CityNode = { id: string; label: string; n: number }

function CityDistrict({
  cityId,
  weight,
}: {
  cityId: string
  weight: number
}) {
  const group = useRef<THREE.Group>(null)
  const blocks = useMemo(() => {
    const count = Math.min(48, 12 + Math.floor(Math.sqrt(weight) * 2))
    const items: { pos: [number, number, number]; h: number; glow: number }[] = []
    for (let i = 0; i < count; i++) {
      const gx = (i % 8) - 3.5
      const gz = Math.floor(i / 8) - 2.5
      const h = 0.25 + ((i * 17) % 9) * 0.12 + (weight % 7) * 0.02
      const glow = 0.35 + (h / 2.2) * 0.65
      items.push({ pos: [gx * 0.38, h / 2, gz * 0.38], h, glow })
    }
    return items
  }, [cityId, weight])

  useFrame((state) => {
    if (group.current) {
      group.current.rotation.y = state.clock.elapsedTime * 0.08
    }
  })

  return (
    <group ref={group} position={[0, -0.4, 0]}>
      <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, 0, 0]}>
        <circleGeometry args={[2.4, 48]} />
        <meshBasicMaterial color="#0a0604" transparent opacity={0.85} />
      </mesh>
      {blocks.map((b, i) => (
        <mesh key={i} position={b.pos}>
          <boxGeometry args={[0.28, b.h, 0.28]} />
          <meshBasicMaterial
            color={b.glow > 0.7 ? '#ffaa00' : b.glow > 0.45 ? '#ff5500' : '#cc1100'}
            transparent
            opacity={0.9}
          />
        </mesh>
      ))}
    </group>
  )
}

export function CityGlobe() {
  const sceneMode = useVigilStore((s) => s.sceneMode)
  const cityFocus = useVigilStore((s) => s.cityFocus)
  const setCityFocus = useVigilStore((s) => s.setCityFocus)
  const setCityFilter = useVigilStore((s) => s.setCityFilter)
  const setSceneZoom = useVigilStore((s) => s.setSceneZoom)
  const focusedPanel = useVigilStore((s) => s.focusedPanel)
  const [cities, setCities] = useState<CityNode[]>([])
  const globe = useRef<THREE.Group>(null)

  useEffect(() => {
    if (sceneMode !== 'city') return
    let alive = true
    api
      .citySignals(7)
      .then((d) => {
        if (!alive) return
        const rows = (d?.cities || []) as {
          city?: string
          id?: string
          label?: string
          recent?: number
          n?: number
        }[]
        const mapped: CityNode[] = rows
          .map((r) => ({
            id: r.city || r.id || '',
            label: r.label || r.city || '',
            n: r.recent ?? r.n ?? 0,
          }))
          .filter((c) => c.id && CITY_GEO[c.id])
        setCities(mapped)
      })
      .catch(() => {})
    return () => {
      alive = false
    }
  }, [sceneMode])

  useFrame((state) => {
    if (globe.current && !cityFocus) {
      globe.current.rotation.y = state.clock.elapsedTime * 0.12
    }
  })

  if (sceneMode !== 'city') return null

  const maxN = Math.max(...cities.map((c) => c.n), 1)
  const focusRow = cities.find((c) => c.id === cityFocus)

  if (cityFocus && focusRow) {
    return (
      <group>
        <CityDistrict cityId={cityFocus} weight={focusRow.n} />
      </group>
    )
  }

  const R = 1.85
  const interactive = !focusedPanel

  return (
    <group ref={globe}>
      <mesh>
        <sphereGeometry args={[R, 48, 48]} />
        <meshBasicMaterial color="#120804" transparent opacity={0.92} />
      </mesh>
      <mesh>
        <sphereGeometry args={[R * 1.02, 32, 32]} />
        <meshBasicMaterial
          color="#ff5500"
          transparent
          opacity={0.06}
          depthWrite={false}
        />
      </mesh>
      {cities.map((c) => {
        const geo = CITY_GEO[c.id]
        if (!geo) return null
        const p = latLonToVec(geo.lat, geo.lon, R * 1.04)
        const heat = c.n / maxN
        const size = 0.05 + heat * 0.1
        return (
          <mesh
            key={c.id}
            position={p}
            onPointerOver={(e: ThreeEvent<PointerEvent>) => {
              if (!interactive) return
              e.stopPropagation()
              document.body.style.cursor = 'pointer'
              useVigilStore.setState({
                statusLine: `${geo.label} · ${c.n} jobs — click to enter city`,
              })
            }}
            onPointerOut={() => {
              document.body.style.cursor = 'default'
            }}
            onClick={(e: ThreeEvent<MouseEvent>) => {
              if (!interactive) return
              e.stopPropagation()
              setCityFocus(c.id)
              setCityFilter(c.id)
              setSceneZoom(0.72)
              useVigilStore.getState().setStatus(`ENTERING ${geo.label}`)
              useVigilStore.getState().triggerBurst()
            }}
          >
            <sphereGeometry args={[size, 16, 16]} />
            <meshBasicMaterial
              color={heat > 0.66 ? '#ffaa00' : heat > 0.33 ? '#ff5500' : '#cc4400'}
            />
          </mesh>
        )
      })}
    </group>
  )
}
