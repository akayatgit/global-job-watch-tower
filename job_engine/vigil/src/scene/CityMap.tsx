/**
 * MapLibre hiring map — replaces R3F CityGlobe + NightCity campus.
 * Real geography, 3D building extrusions, company overlays from skyline APIs.
 */
import { useEffect, useMemo, useRef, useState } from 'react'
import maplibregl, {
  type GeoJSONSource,
  type Map as MlMap,
  type MapLayerMouseEvent,
} from 'maplibre-gl'
import 'maplibre-gl/dist/maplibre-gl.css'
import { api, openingsCaption } from '../lib/api'
import { useVigilStore } from '../store/vigilStore'
import {
  CITY_GEO,
  CITY_VIEW,
  INDIA_VIEW,
  companyLatLon,
} from './cityGeo'

type CityNode = { id: string; label: string; n: number }
type RoleHit = { title: string; n: number }
type CoHit = {
  company_id: number
  name: string
  n: number
  roles?: RoleHit[]
  city_key?: string
  city_label?: string
  lon: number
  lat: number
}

const STYLE_URL = 'https://tiles.openfreemap.org/styles/liberty'
const CITIES_SRC = 'wt-cities'
const COS_SRC = 'wt-companies'
const BUILDINGS_LAYER = 'wt-3d-buildings'

function hash01(n: number) {
  const x = Math.sin(n * 127.1) * 43758.5453
  return x - Math.floor(x)
}

function ensureBuildings(map: MlMap) {
  if (map.getLayer(BUILDINGS_LAYER)) return
  const style = map.getStyle()
  const sources = style?.sources || {}
  let sourceId =
    'openmaptiles' in sources
      ? 'openmaptiles'
      : Object.keys(sources).find((id) => {
          const s = sources[id] as { type?: string; url?: string }
          return s?.type === 'vector'
        })
  if (!sourceId) {
    if (!map.getSource('openfreemap-planet')) {
      map.addSource('openfreemap-planet', {
        type: 'vector',
        url: 'https://tiles.openfreemap.org/planet',
      })
    }
    sourceId = 'openfreemap-planet'
  }
  let beforeId: string | undefined
  for (const layer of style?.layers || []) {
    if (layer.type === 'symbol' && (layer.layout as { 'text-field'?: unknown })?.['text-field']) {
      beforeId = layer.id
      break
    }
  }
  try {
    map.addLayer(
      {
        id: BUILDINGS_LAYER,
        source: sourceId,
        'source-layer': 'building',
        type: 'fill-extrusion',
        minzoom: 14,
        filter: ['!=', ['get', 'hide_3d'], true],
        paint: {
          'fill-extrusion-color': '#c5d0dc',
          'fill-extrusion-height': [
            'interpolate',
            ['linear'],
            ['zoom'],
            14,
            0,
            14.8,
            ['coalesce', ['get', 'render_height'], ['get', 'height'], 16],
          ],
          'fill-extrusion-base': [
            'coalesce',
            ['get', 'render_min_height'],
            ['get', 'min_height'],
            0,
          ],
          'fill-extrusion-opacity': 0.9,
        },
      },
      beforeId,
    )
  } catch {
    // Style source-layer mismatch — map still usable without extrusions
  }
}

function ensureGeoJsonSource(map: MlMap, id: string) {
  if (map.getSource(id)) return
  map.addSource(id, {
    type: 'geojson',
    data: { type: 'FeatureCollection', features: [] },
  })
}

function ensureCityLayers(map: MlMap) {
  ensureGeoJsonSource(map, CITIES_SRC)
  if (!map.getLayer('wt-cities-glow')) {
    map.addLayer({
      id: 'wt-cities-glow',
      type: 'circle',
      source: CITIES_SRC,
      paint: {
        'circle-radius': ['interpolate', ['linear'], ['get', 'n'], 0, 10, 50, 22],
        'circle-color': '#ff7700',
        'circle-opacity': 0.22,
        'circle-blur': 0.55,
      },
    })
  }
  if (!map.getLayer('wt-cities-dot')) {
    map.addLayer({
      id: 'wt-cities-dot',
      type: 'circle',
      source: CITIES_SRC,
      paint: {
        'circle-radius': ['interpolate', ['linear'], ['get', 'n'], 0, 5, 50, 11],
        'circle-color': '#ff5500',
        'circle-stroke-width': 2,
        'circle-stroke-color': '#ffffff',
      },
    })
  }
  if (!map.getLayer('wt-cities-label')) {
    map.addLayer({
      id: 'wt-cities-label',
      type: 'symbol',
      source: CITIES_SRC,
      layout: {
        'text-field': ['concat', ['get', 'label'], '\n', ['to-string', ['get', 'n']]],
        'text-size': 13,
        'text-font': ['Noto Sans Regular'],
        'text-offset': [0, 1.35],
        'text-anchor': 'top',
        'text-allow-overlap': true,
      },
      paint: {
        'text-color': '#1e293b',
        'text-halo-color': '#ffffff',
        'text-halo-width': 1.4,
      },
    })
  }
}

function ensureCompanyLayers(map: MlMap) {
  ensureGeoJsonSource(map, COS_SRC)
  if (!map.getLayer('wt-cos-col')) {
    map.addLayer({
      id: 'wt-cos-col',
      type: 'circle',
      source: COS_SRC,
      paint: {
        'circle-radius': [
          'interpolate',
          ['linear'],
          ['get', 'n'],
          1,
          7,
          20,
          16,
        ],
        'circle-color': '#3b82f6',
        'circle-opacity': 0.88,
        'circle-stroke-width': 2,
        'circle-stroke-color': '#ffffff',
      },
    })
  }
  if (!map.getLayer('wt-cos-label')) {
    map.addLayer({
      id: 'wt-cos-label',
      type: 'symbol',
      source: COS_SRC,
      layout: {
        'text-field': ['get', 'name'],
        'text-size': 11,
        'text-font': ['Noto Sans Regular'],
        'text-offset': [0, 1.2],
        'text-anchor': 'top',
        'text-max-width': 10,
      },
      paint: {
        'text-color': '#0f172a',
        'text-halo-color': 'rgba(255,255,255,0.92)',
        'text-halo-width': 1.2,
      },
    })
  }
}

type GjFeature = {
  type: 'Feature'
  properties: Record<string, string | number>
  geometry: { type: 'Point'; coordinates: [number, number] }
}

function setSourceData(map: MlMap, id: string, features: GjFeature[]) {
  const src = map.getSource(id) as GeoJSONSource | undefined
  src?.setData({ type: 'FeatureCollection', features })
}

export function CityMap() {
  const wrapRef = useRef<HTMLDivElement>(null)
  const mapRef = useRef<MlMap | null>(null)
  const readyRef = useRef(false)
  const cityFocus = useVigilStore((s) => s.cityFocus)
  const cityWindowDays = useVigilStore((s) => s.cityWindowDays)
  const sectorFilter = useVigilStore((s) => s.sectorFilter)
  const cityFilter = useVigilStore((s) => s.cityFilter)
  const experienceFilter = useVigilStore((s) => s.experienceFilter)
  const selectFocusId = useVigilStore((s) => s.selectFocusId)
  const [cities, setCities] = useState<CityNode[]>([])
  const [companies, setCompanies] = useState<CoHit[]>([])
  const [hoverCo, setHoverCo] = useState<CoHit | null>(null)

  const focusLabel = useMemo(() => {
    if (!cityFocus || cityFocus === '__jobs__') return cityFocus === '__jobs__' ? 'India hiring' : ''
    return CITY_GEO[cityFocus]?.label || cityFocus
  }, [cityFocus])

  // Init map once
  useEffect(() => {
    const el = wrapRef.current
    if (!el || mapRef.current) return
    const map = new maplibregl.Map({
      container: el,
      style: STYLE_URL,
      center: INDIA_VIEW.center,
      zoom: INDIA_VIEW.zoom,
      pitch: INDIA_VIEW.pitch,
      bearing: INDIA_VIEW.bearing,
      attributionControl: { compact: true },
      maxPitch: 70,
    })
    map.addControl(new maplibregl.NavigationControl({ visualizePitch: true }), 'bottom-right')
    mapRef.current = map

    const kickResize = () => {
      map.resize()
    }
    const ro = new ResizeObserver(() => kickResize())
    ro.observe(el)

    map.on('load', () => {
      ensureBuildings(map)
      ensureCityLayers(map)
      ensureCompanyLayers(map)
      readyRef.current = true
      // Container often lays out after first paint — resize or map stays 0-height
      kickResize()
      requestAnimationFrame(kickResize)
      setTimeout(kickResize, 50)
      setTimeout(kickResize, 250)
      useVigilStore.getState().setStatus('MAP · India hiring · click a city')
    })
    map.on('error', (e) => {
      const msg = (e as { error?: { message?: string } })?.error?.message || 'map error'
      useVigilStore.getState().setStatus(`MAP · ${msg}`)
    })

    const onCityClick = (e: MapLayerMouseEvent) => {
      const f = e.features?.[0]
      if (!f?.properties?.id) return
      e.originalEvent.stopPropagation()
      const id = String(f.properties.id)
      const st = useVigilStore.getState()
      st.setSceneSpin(false)
      st.clearCameraFocus()
      st.setCityFocus(id)
      st.setStatus(`CITY · ${f.properties.label || id}`)
    }
    const onCoClick = (e: MapLayerMouseEvent) => {
      const f = e.features?.[0]
      if (!f?.properties?.company_id) return
      e.originalEvent.stopPropagation()
      const cid = Number(f.properties.company_id)
      const name = String(f.properties.name || 'Company')
      const selectId = `company:${cid}`
      const st = useVigilStore.getState()
      if (st.selectFocusId === selectId) {
        if (f.properties.city_key) st.setCityFilter(String(f.properties.city_key))
        st.openCompanyJobs(cid, name, st.cityWindowDays || 7)
        st.setStatus(`OPEN · ${name}`)
        return
      }
      st.setSceneSpin(false)
      st.setSelectFocusId(selectId)
      st.setStatus(`FOCUS · ${name} · click again to open`)
      const g = f.geometry
      if (g.type !== 'Point') return
      map.easeTo({
        center: g.coordinates as [number, number],
        zoom: Math.max(map.getZoom(), 15.2),
        duration: 700,
      })
    }
    const onCoEnter = (e: MapLayerMouseEvent) => {
      map.getCanvas().style.cursor = 'pointer'
      const f = e.features?.[0]
      if (!f?.properties || f.geometry.type !== 'Point') return
      const coords = f.geometry.coordinates as [number, number]
      setHoverCo({
        company_id: Number(f.properties.company_id),
        name: String(f.properties.name || ''),
        n: Number(f.properties.n || 0),
        roles: (() => {
          try {
            return JSON.parse(String(f.properties.roles_json || '[]')) as RoleHit[]
          } catch {
            return []
          }
        })(),
        city_key: f.properties.city_key ? String(f.properties.city_key) : undefined,
        city_label: f.properties.city_label
          ? String(f.properties.city_label)
          : undefined,
        lon: coords[0],
        lat: coords[1],
      })
    }
    const onCoLeave = () => {
      map.getCanvas().style.cursor = ''
      setHoverCo(null)
    }
    const onCityEnter = () => {
      map.getCanvas().style.cursor = 'pointer'
    }
    const onCityLeave = () => {
      map.getCanvas().style.cursor = ''
    }

    map.on('click', 'wt-cities-dot', onCityClick)
    map.on('click', 'wt-cities-glow', onCityClick)
    map.on('click', 'wt-cos-col', onCoClick)
    map.on('mouseenter', 'wt-cos-col', onCoEnter)
    map.on('mouseleave', 'wt-cos-col', onCoLeave)
    map.on('mouseenter', 'wt-cities-dot', onCityEnter)
    map.on('mouseleave', 'wt-cities-dot', onCityLeave)

    return () => {
      readyRef.current = false
      ro.disconnect()
      map.remove()
      mapRef.current = null
    }
  }, [])

  // Load city signals (India overview)
  useEffect(() => {
    let alive = true
    api
      .citySignals(cityWindowDays)
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
      .catch(() => {
        if (alive) setCities([])
      })
    return () => {
      alive = false
    }
  }, [cityWindowDays])

  // Load companies for focused city / jobs view
  useEffect(() => {
    let alive = true
    if (!cityFocus) {
      setCompanies([])
      return
    }
    if (cityFocus === '__jobs__') {
      api
        .jobsSkyline(sectorFilter, cityFilter, experienceFilter, 120)
        .then((d) => {
          if (!alive) return
          const clusters = (d?.clusters || []) as {
            city?: string
            label?: string
            companies?: {
              company_id: number
              name: string
              n: number
              roles?: RoleHit[]
            }[]
          }[]
          const out: CoHit[] = []
          for (const cl of clusters) {
            const geo = CITY_GEO[cl.city || '']
            if (!geo) continue
            const list = (cl.companies || []).slice(0, 12)
            list.forEach((c, i) => {
              const [lon, lat] = companyLatLon(
                geo.lat,
                geo.lon,
                c.company_id,
                i,
                list.length,
              )
              out.push({
                company_id: c.company_id,
                name: c.name,
                n: c.n,
                roles: c.roles || [],
                city_key: cl.city,
                city_label: cl.label || geo.label,
                lon,
                lat,
              })
            })
          }
          setCompanies(out)
        })
        .catch(() => {
          if (alive) setCompanies([])
        })
      return () => {
        alive = false
      }
    }
    api
      .citySkyline(cityFocus, cityWindowDays, 28)
      .then((d) => {
        if (!alive) return
        const geo = CITY_GEO[cityFocus]
        if (!geo) {
          setCompanies([])
          return
        }
        const list = (d?.companies || []) as {
          company_id: number
          name: string
          n: number
          roles?: RoleHit[]
        }[]
        setCompanies(
          list.map((c, i) => {
            const [lon, lat] = companyLatLon(
              geo.lat,
              geo.lon,
              c.company_id,
              i,
              list.length,
            )
            return {
              company_id: c.company_id,
              name: c.name,
              n: c.n,
              roles: c.roles || [],
              city_key: cityFocus,
              city_label: d?.label || geo.label,
              lon,
              lat,
            }
          }),
        )
        useVigilStore
          .getState()
          .setStatus(
            `MAP · ${d?.label || geo.label} · ${d?.window_caption || openingsCaption(cityWindowDays)}`,
          )
      })
      .catch(() => {
        if (alive) setCompanies([])
      })
    return () => {
      alive = false
    }
  }, [
    cityFocus,
    cityWindowDays,
    sectorFilter,
    cityFilter,
    experienceFilter,
  ])

  // Push GeoJSON + camera
  useEffect(() => {
    const map = mapRef.current
    if (!map) return
    const apply = () => {
      if (!readyRef.current) return
      ensureCityLayers(map)
      ensureCompanyLayers(map)
      ensureBuildings(map)

      const cityFeatures: GjFeature[] = cities.map((c) => {
        const g = CITY_GEO[c.id]
        return {
          type: 'Feature',
          properties: { id: c.id, label: c.label || g.label, n: c.n },
          geometry: { type: 'Point', coordinates: [g.lon, g.lat] },
        }
      })
      setSourceData(map, CITIES_SRC, cityFocus ? [] : cityFeatures)

      const coFeatures: GjFeature[] = companies.map((c) => ({
        type: 'Feature',
        properties: {
          company_id: c.company_id,
          name: c.name,
          n: c.n,
          city_key: c.city_key || '',
          city_label: c.city_label || '',
          roles_json: JSON.stringify((c.roles || []).slice(0, 5)),
          focused: selectFocusId === `company:${c.company_id}` ? 1 : 0,
        },
        geometry: { type: 'Point', coordinates: [c.lon, c.lat] },
      }))
      setSourceData(map, COS_SRC, coFeatures)

      if (!cityFocus) {
        map.easeTo({ ...INDIA_VIEW, duration: 900 })
        map.setLayoutProperty('wt-cities-dot', 'visibility', 'visible')
        map.setLayoutProperty('wt-cities-glow', 'visibility', 'visible')
        map.setLayoutProperty('wt-cities-label', 'visibility', 'visible')
        return
      }
      map.setLayoutProperty('wt-cities-dot', 'visibility', 'none')
      map.setLayoutProperty('wt-cities-glow', 'visibility', 'none')
      map.setLayoutProperty('wt-cities-label', 'visibility', 'none')

      if (cityFocus === '__jobs__') {
        // Fit India metros that have companies
        const bounds = new maplibregl.LngLatBounds()
        let any = false
        for (const c of companies) {
          bounds.extend([c.lon, c.lat])
          any = true
        }
        if (any) {
          map.fitBounds(bounds, {
            padding: 80,
            pitch: 45,
            bearing: -12,
            duration: 1000,
            maxZoom: 12.5,
          })
        } else {
          map.easeTo({ ...INDIA_VIEW, pitch: 35, duration: 900 })
        }
        return
      }
      const geo = CITY_GEO[cityFocus]
      if (geo) {
        map.easeTo({
          center: [geo.lon, geo.lat],
          zoom: CITY_VIEW.zoom,
          pitch: CITY_VIEW.pitch,
          bearing: CITY_VIEW.bearing + hash01(cityFocus.length) * 20,
          duration: 1100,
        })
      }
    }
    if (readyRef.current) apply()
    else map.once('load', apply)
  }, [cities, companies, cityFocus, selectFocusId])

  // Highlight focused company circle
  useEffect(() => {
    const map = mapRef.current
    if (!map || !readyRef.current || !map.getLayer('wt-cos-col')) return
    const cid = selectFocusId?.startsWith('company:')
      ? Number(selectFocusId.slice('company:'.length))
      : -1
    map.setPaintProperty('wt-cos-col', 'circle-color', [
      'case',
      ['==', ['get', 'company_id'], cid],
      '#ff5500',
      '#3b82f6',
    ])
  }, [selectFocusId])

  const card = hoverCo || (selectFocusId?.startsWith('company:')
    ? companies.find(
        (c) => `company:${c.company_id}` === selectFocusId,
      ) || null
    : null)

  return (
    <div className="city-map-root">
      <div className="city-map-canvas" ref={wrapRef} />
      {focusLabel && cityFocus && (
        <div className="city-map-title" title="City">
          {focusLabel}
        </div>
      )}
      {card && (
        <div className="city-map-card">
          <div className="city-map-card-name">{card.name}</div>
          <div className="city-map-card-n">{card.n}</div>
          <div className="city-map-card-cap">
            {card.city_label
              ? `${openingsCaption(cityWindowDays)} · ${card.city_label}`
              : openingsCaption(cityWindowDays)}
          </div>
          {(card.roles || []).slice(0, 5).map((r, i) => (
            <div key={i} className="city-map-card-role">
              <span className="city-map-card-dot" />
              {r.title}
              {r.n > 1 ? ` · ${r.n}` : ''}
            </div>
          ))}
          <div className="city-map-card-hint">
            {selectFocusId === `company:${card.company_id}`
              ? 'Click again to open jobs'
              : 'Click to focus'}
          </div>
        </div>
      )}
    </div>
  )
}
