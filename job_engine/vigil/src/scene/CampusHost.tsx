/**
 * Nightlife R3F campus — no globe. Uses cityFocus or multi-city Jobs clusters.
 */
import { NightCity, JOBS_CITY_FOCUS } from './NightCity'
import { CITY_GEO } from './cityGeo'
import { useVigilStore } from '../store/vigilStore'

export function CampusHost() {
  const cityFocus = useVigilStore((s) => s.cityFocus)

  if (!cityFocus || cityFocus === JOBS_CITY_FOCUS) {
    return (
      <NightCity mode="jobs" cityId={JOBS_CITY_FOCUS} cityLabel="Jobs" />
    )
  }

  const label = CITY_GEO[cityFocus]?.label || cityFocus
  return <NightCity cityId={cityFocus} cityLabel={label} />
}
