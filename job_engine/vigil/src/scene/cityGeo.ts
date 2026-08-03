/** Shared metro centers for MapLibre city mode (India hiring map). */

export type CityGeo = { lat: number; lon: number; label: string }

export const CITY_GEO: Record<string, CityGeo> = {
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

export const INDIA_VIEW = {
  center: [78.96, 22.5] as [number, number],
  zoom: 4.35,
  pitch: 0,
  bearing: 0,
}

export const CITY_VIEW = {
  zoom: 14.6,
  pitch: 58,
  bearing: -18,
}

/** Deterministic offset around a city center (no company geocode yet). */
export function companyLatLon(
  cityLat: number,
  cityLon: number,
  companyId: number,
  index: number,
  total: number,
): [number, number] {
  const seed = Math.sin(companyId * 12.9898) * 43758.5453
  const frac = seed - Math.floor(seed)
  const angle = (index / Math.max(total, 1)) * Math.PI * 2 + frac * Math.PI
  const ring = 0.0035 + (index % 4) * 0.0012 + frac * 0.0008
  const lon = cityLon + Math.cos(angle) * ring
  const lat = cityLat + Math.sin(angle) * ring * 0.82
  return [lon, lat]
}
