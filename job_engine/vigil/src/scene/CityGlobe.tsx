import { useEffect, useMemo, useRef, useState } from 'react'
import { useFrame } from '@react-three/fiber'
import type { ThreeEvent } from '@react-three/fiber'
import { Html } from '@react-three/drei'
import * as THREE from 'three'
import { api } from '../lib/api'
import { useVigilStore } from '../store/vigilStore'

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
type CoRow = { company_id: number; name: string; n: number }

function CityDistrict({
  cityId,
  cityLabel,
  weight,
}: {
  cityId: string
  cityLabel: string
  weight: number
}) {
  const group = useRef<THREE.Group>(null)
  const [companies, setCompanies] = useState<CoRow[]>([])

  useEffect(() => {
    let alive = true
    api
      .topCompanies(7, 20, '', cityId)
      .then((d) => {
        if (!alive) return
        const rows = (d?.companies || d?.top_companies || d || []) as CoRow[]
        const list = Array.isArray(rows) ? rows : []
        setCompanies(
          list
            .map((r: any) => ({
              company_id: r.company_id ?? r.id,
              name: r.name || 'Company',
              n: r.n ?? r.count ?? 1,
            }))
            .filter((r) => r.company_id != null)
            .slice(0, 16),
        )
      })
      .catch(() => setCompanies([]))
    return () => {
      alive = false
    }
  }, [cityId])

  const blocks = useMemo(() => {
    const maxN = Math.max(...companies.map((c) => c.n), 1)
    if (companies.length === 0) {
      // Placeholder skyline until data arrives
      return Array.from({ length: 12 }, (_, i) => ({
        pos: [(i % 6) - 2.5, 0.3, Math.floor(i / 6) - 0.5] as [
          number,
          number,
          number,
        ],
        h: 0.4 + (i % 5) * 0.15,
        glow: 0.4,
        name: '',
        company_id: 0,
        n: 0,
      }))
    }
    return companies.map((c, i) => {
      const gx = (i % 6) - 2.5
      const gz = Math.floor(i / 6) - 0.8
      const h = 0.35 + (c.n / maxN) * 1.6
      return {
        pos: [gx * 0.55, h / 2, gz * 0.55] as [number, number, number],
        h,
        glow: c.n / maxN,
        name: c.name,
        company_id: c.company_id,
        n: c.n,
      }
    })
  }, [companies, weight])

  return (
    <group ref={group} position={[0, -0.5, 0]}>
      <Html center distanceFactor={10} style={{ pointerEvents: 'none' }}>
        <div className="vigil-tag vigil-tag-city-title">{cityLabel}</div>
      </Html>
      <mesh rotation={[-Math.PI / 2, 0, 0]}>
        <circleGeometry args={[2.8, 48]} />
        <meshBasicMaterial color="#0a0604" transparent opacity={0.88} />
      </mesh>
      {blocks.map((b, i) => (
        <group key={i} position={b.pos}>
          {/* Fat invisible pick volume — click the building, not the text */}
          <mesh
            position={[0, 0, 0]}
            onClick={(e: ThreeEvent<MouseEvent>) => {
              if (!b.company_id) return
              e.stopPropagation()
              useVigilStore
                .getState()
                .openCompanyJobs(b.company_id, b.name, 7)
            }}
            onPointerOver={(e: ThreeEvent<PointerEvent>) => {
              if (!b.name) return
              e.stopPropagation()
              document.body.style.cursor = 'pointer'
              useVigilStore.setState({
                statusLine: `${b.name} · ${b.n} jobs in ${cityLabel}`,
              })
            }}
            onPointerOut={() => {
              document.body.style.cursor = 'default'
            }}
          >
            <boxGeometry args={[0.55, Math.max(b.h, 0.5), 0.55]} />
            <meshBasicMaterial transparent opacity={0} depthWrite={false} />
          </mesh>
          <mesh>
            <boxGeometry args={[0.36, b.h, 0.36]} />
            <meshBasicMaterial
              color={
                b.glow > 0.7 ? '#ffaa00' : b.glow > 0.4 ? '#ff5500' : '#cc1100'
              }
              transparent
              opacity={0.92}
            />
          </mesh>
          {b.name && (
            <Html
              position={[0, b.h / 2 + 0.18, 0]}
              center
              distanceFactor={7}
              style={{ pointerEvents: 'none' }}
            >
              <div className="vigil-tag vigil-tag-building" aria-hidden>
                <span className="vigil-tag-name">{b.name}</span>
                <span className="vigil-tag-meta">{b.n}</span>
              </div>
            </Html>
          )}
        </group>
      ))}
    </group>
  )
}

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
    return (
      <CityDistrict
        cityId={cityFocus}
        cityLabel={focusLabel}
        weight={focusRow?.n || 10}
      />
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
                setCityFocus(c.id)
                setCityFilter(c.id)
                useVigilStore.getState().setSceneSpin(false)
                useVigilStore.getState().resetView()
                useVigilStore.getState().setStatus(`ENTERING ${geo.label}`)
                useVigilStore.getState().triggerBurst()
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
