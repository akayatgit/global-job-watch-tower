import { useEffect, useRef, useState } from 'react'
import { useFrame } from '@react-three/fiber'
import type { ThreeEvent } from '@react-three/fiber'
import { Html } from '@react-three/drei'
import * as THREE from 'three'
import { api } from '../lib/api'
import { useVigilStore } from '../store/vigilStore'
import { NightCity } from './NightCity'

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

export function CityGlobe() {
  const sceneMode = useVigilStore((s) => s.sceneMode)
  const cityFocus = useVigilStore((s) => s.cityFocus)
  const setCityFocus = useVigilStore((s) => s.setCityFocus)
  const setCityFilter = useVigilStore((s) => s.setCityFilter)
  const focusedPanel = useVigilStore((s) => s.focusedPanel)
  const sceneSpin = useVigilStore((s) => s.sceneSpin)
  const [cities, setCities] = useState<CityNode[]>([])
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
        setCities(
          rows
            .map((r) => ({
              id: r.city || '',
              label: r.label || r.city || '',
              n: r.recent ?? 0,
            }))
            .filter((c) => c.id && CITY_GEO[c.id]),
        )
      })
      .catch(() => {})
    return () => {
      alive = false
    }
  }, [sceneMode])

  useFrame((state) => {
    if (globe.current && !cityFocus) {
      const t = state.clock.elapsedTime
      if (sceneSpin) spinY.current += Math.max(0, t - lastT.current) * 0.1
      lastT.current = t
      globe.current.rotation.y = spinY.current
    }
  })

  if (sceneMode !== 'city') return null

  const maxN = Math.max(...cities.map((c) => c.n), 1)
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
      {cities.map((c) => {
        const geo = CITY_GEO[c.id]
        if (!geo) return null
        const p = latLonToVec(geo.lat, geo.lon, R * 1.05)
        const heat = c.n / maxN
        const size = 0.05 + heat * 0.1
        return (
          <group key={c.id} position={p}>
            {/* Fat pick sphere — click the marker card, not the label */}
            <mesh
              onPointerOver={(e: ThreeEvent<PointerEvent>) => {
                if (!interactive) return
                e.stopPropagation()
                document.body.style.cursor = 'pointer'
                useVigilStore.setState({
                  statusLine: `${geo.label} · ${c.n} jobs — click to enter`,
                })
              }}
              onPointerOut={() => {
                document.body.style.cursor = 'default'
              }}
              onClick={(e: ThreeEvent<MouseEvent>) => {
                if (!interactive) return
                e.stopPropagation()
                const st = useVigilStore.getState()
                const selectId = `city:${c.id}`
                // First click = drone focus on marker; second = enter night city
                if (st.selectFocusId !== selectId) {
                  st.setSceneSpin(false)
                  st.requestCameraFocus({
                    id: selectId,
                    x: p.x,
                    y: p.y,
                    z: p.z,
                    distance: 2.4,
                  })
                  st.setStatus(`FOCUS · ${geo.label} · click again to enter`)
                  return
                }
                setCityFocus(c.id)
                setCityFilter(c.id)
                st.clearCameraFocus()
                st.resetView()
                st.setStatus(`ENTERING ${geo.label}`)
                st.triggerBurst()
              }}
            >
              <sphereGeometry args={[Math.max(size * 2.4, 0.16), 16, 16]} />
              <meshBasicMaterial transparent opacity={0} depthWrite={false} />
            </mesh>
            <mesh>
              <sphereGeometry args={[size, 16, 16]} />
              <meshBasicMaterial
                color={heat > 0.66 ? '#ffaa00' : heat > 0.33 ? '#ff5500' : '#cc4400'}
              />
            </mesh>
            <Html
              center
              distanceFactor={9}
              style={{ pointerEvents: 'none' }}
              zIndexRange={[30, 0]}
            >
              <div className="vigil-tag vigil-tag-city" aria-hidden>
                <span className="vigil-tag-name">{geo.label}</span>
                <span className="vigil-tag-meta">{c.n}</span>
              </div>
            </Html>
          </group>
        )
      })}
    </group>
  )
}
