async function getJson<T>(url: string): Promise<T> {
  const res = await fetch(url, { headers: { Accept: 'application/json' } })
  if (!res.ok) throw new Error(`${url} → ${res.status}`)
  return res.json() as Promise<T>
}

async function postJson<T>(url: string, body: unknown = {}): Promise<T> {
  const res = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) throw new Error(`${url} → ${res.status}`)
  return res.json() as Promise<T>
}

export type JobsQuery = {
  limit?: number
  search_config_id?: number
  company_id?: number
  company?: string
  title?: string
  sector?: string
  city?: string
  experience?: string
}

function appendSector(p: URLSearchParams, sector?: string) {
  if (sector) p.set('sector', sector)
}

function appendCity(p: URLSearchParams, city?: string) {
  if (city) p.set('city', city)
}

function appendExperience(p: URLSearchParams, experience?: string) {
  if (experience) p.set('experience', experience)
}

function jobsUrl(q: JobsQuery = {}) {
  const p = new URLSearchParams()
  p.set('limit', String(q.limit ?? 80))
  if (q.search_config_id) p.set('search_config_id', String(q.search_config_id))
  if (q.company_id) p.set('company_id', String(q.company_id))
  if (q.company) p.set('company', q.company)
  if (q.title) p.set('title', q.title)
  appendSector(p, q.sector)
  appendCity(p, q.city)
  appendExperience(p, q.experience)
  return `/api/jobs?${p}`
}

export const api = {
  status: () => getJson<any>('/api/ultron/status'),
  tower: (sector = '', city = '', experience = '') => {
    const p = new URLSearchParams()
    appendSector(p, sector)
    appendCity(p, city)
    appendExperience(p, experience)
    const qs = p.toString()
    return getJson<any>(`/api/ultron/tower${qs ? `?${qs}` : ''}`)
  },
  signals: (days = 7, sector = '', city = '', experience = '') => {
    const p = new URLSearchParams({ days: String(days) })
    appendSector(p, sector)
    appendCity(p, city)
    appendExperience(p, experience)
    return getJson<any>(`/api/ultron/signals?${p}`)
  },
  watchlist: (days = 7, q = '', sector = '', city = '', experience = '') => {
    const p = new URLSearchParams({
      days: String(days),
      q,
    })
    appendSector(p, sector)
    appendCity(p, city)
    appendExperience(p, experience)
    return getJson<any>(`/api/ultron/watchlist?${p}`)
  },
  roleCompanies: (
    searchId: number,
    days = 7,
    city = '',
    sector = '',
    experience = '',
  ) => {
    const p = new URLSearchParams({ days: String(days) })
    appendCity(p, city)
    appendSector(p, sector)
    appendExperience(p, experience)
    return getJson<any>(`/api/ultron/roles/${searchId}/companies?${p}`)
  },
  topCompanies: (
    days = 7,
    limit = 80,
    sector = '',
    city = '',
    experience = '',
  ) => {
    const p = new URLSearchParams({
      days: String(days),
      limit: String(limit),
    })
    appendSector(p, sector)
    appendCity(p, city)
    appendExperience(p, experience)
    return getJson<any>(`/api/ultron/top-companies?${p}`)
  },
  rolesRank: (
    limit = 200,
    days = 7,
    mode: 'count' | 'rate' = 'count',
    sector = '',
    city = '',
    experience = '',
  ) => {
    const p = new URLSearchParams({
      limit: String(limit),
      days: String(days),
      mode,
    })
    appendSector(p, sector)
    appendCity(p, city)
    appendExperience(p, experience)
    return getJson<any>(`/api/ultron/roles-rank?${p}`)
  },
  citySignals: (days = 7, sector = '', experience = '') => {
    const p = new URLSearchParams({ days: String(days) })
    appendSector(p, sector)
    appendExperience(p, experience)
    return getJson<any>(`/api/ultron/cities?${p}`)
  },
  citySkyline: (city: string, days = 7, limit = 28) => {
    const p = new URLSearchParams({
      days: String(days),
      limit: String(limit),
    })
    return getJson<any>(
      `/api/ultron/cities/${encodeURIComponent(city)}/skyline?${p}`,
    )
  },
  /** Multi-city clusters from the same filters as the Jobs list. */
  jobsSkyline: (sector = '', city = '', experience = '', limit = 120) => {
    const p = new URLSearchParams({ limit: String(limit) })
    appendSector(p, sector)
    appendCity(p, city)
    appendExperience(p, experience)
    return getJson<any>(`/api/ultron/jobs-skyline?${p}`)
  },

  cityCompare: (
    a: string,
    b: string,
    days = 7,
    sector = '',
    experience = '',
  ) => {
    const p = new URLSearchParams({
      a,
      b,
      days: String(days),
    })
    appendSector(p, sector)
    appendExperience(p, experience)
    return getJson<any>(`/api/ultron/cities/compare?${p}`)
  },
  sectors: () => getJson<any>('/api/ultron/sectors'),
  worldModel: (days = 7) =>
    getJson<any>(`/api/ultron/world-model?days=${days}`),
  health: () => getJson<any>('/api/ultron/health'),
  filterCompare: (window = '24h') =>
    getJson<any>(`/api/ultron/filter-compare?window=${encodeURIComponent(window)}`),
  configs: (sector = '') => {
    const p = new URLSearchParams()
    appendSector(p, sector)
    const qs = p.toString()
    return getJson<any[]>(`/api/configs${qs ? `?${qs}` : ''}`)
  },
  runs: (limit = 50) => getJson<any[]>(`/api/runs?limit=${limit}`),
  jobs: (limitOrQuery: number | JobsQuery = 80) => {
    if (typeof limitOrQuery === 'number') return getJson<any[]>(jobsUrl({ limit: limitOrQuery }))
    return getJson<any[]>(jobsUrl(limitOrQuery))
  },
  console: (afterId = 0) => getJson<any[]>(`/api/console?after_id=${afterId}&limit=120`),
  stats: () => getJson<any>('/api/stats'),
  toggleHeadless: () => postJson<any>('/api/ultron/toggle-headless'),
  dismissAlert: () => postJson<any>('/api/ultron/dismiss-alert'),
  aiCapacity: () => getJson<any>('/api/ultron/ai-capacity'),
  ask: (prompt: string) => postJson<any>('/api/ultron/ask', { prompt }),
  toggleWatch: (companyId: number) =>
    postJson<any>(`/api/ultron/watchlist/${companyId}/toggle`),
  toggleConfig: (id: number) => postJson<any>(`/api/configs/${id}/toggle`),
  runConfig: (id: number) => postJson<any>(`/api/ultron/configs/${id}/run`),
  cancelRun: (id: number) => postJson<any>(`/api/runs/${id}/cancel`),
}

/** Shared time-window chips when an API payload has not arrived yet. */
export const WINDOW_FALLBACK = [
  { days: 0, label: 'Last 24 hours' },
  { days: 1, label: 'Today' },
  { days: 2, label: 'Last 2 days' },
  { days: 4, label: 'Last 4 days' },
  { days: 7, label: 'Last 7 days' },
  { days: 14, label: 'Last 14 days' },
  { days: 30, label: 'Last 30 days' },
]

export function chipLabel(days: number, label?: string): string {
  if (label) {
    if (days === 0) return '24h'
    if (days === 1) return 'Today'
    if (label.startsWith('Last ')) return label.replace('Last ', '').replace(' days', 'd')
    return label
  }
  if (days === 0) return '24h'
  if (days === 1) return 'Today'
  return `${days}d`
}

/** Hook line under campus openings number */
export function openingsCaption(days: number): string {
  if (days === 0) return 'Openings in 24h'
  if (days === 1) return 'Openings Today'
  if (days === 7) return 'Openings this week'
  if (days === 14) return 'Openings in 2 weeks'
  if (days === 30) return 'Openings this month'
  return `Openings in ${days} days`
}

export function relTime(iso?: string | null): string {
  if (!iso) return '—'
  const t = new Date(iso).getTime()
  if (Number.isNaN(t)) return iso
  const secs = Math.round((Date.now() - t) / 1000)
  if (secs < 60) return `${secs}s ago`
  if (secs < 3600) return `${Math.floor(secs / 60)}m ago`
  if (secs < 86400) return `${Math.floor(secs / 3600)}h ago`
  return `${Math.floor(secs / 86400)}d ago`
}
