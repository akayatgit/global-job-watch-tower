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
}

function appendSector(p: URLSearchParams, sector?: string) {
  if (sector) p.set('sector', sector)
}

function appendCity(p: URLSearchParams, city?: string) {
  if (city) p.set('city', city)
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
  return `/api/jobs?${p}`
}

export const api = {
  status: () => getJson<any>('/api/ultron/status'),
  tower: (sector = '', city = '') => {
    const p = new URLSearchParams()
    appendSector(p, sector)
    appendCity(p, city)
    const qs = p.toString()
    return getJson<any>(`/api/ultron/tower${qs ? `?${qs}` : ''}`)
  },
  signals: (days = 7, sector = '', city = '') => {
    const p = new URLSearchParams({ days: String(days) })
    appendSector(p, sector)
    appendCity(p, city)
    return getJson<any>(`/api/ultron/signals?${p}`)
  },
  watchlist: (days = 7, q = '', sector = '', city = '') => {
    const p = new URLSearchParams({
      days: String(days),
      q,
    })
    appendSector(p, sector)
    appendCity(p, city)
    return getJson<any>(`/api/ultron/watchlist?${p}`)
  },
  roleCompanies: (searchId: number, days = 7, city = '', sector = '') => {
    const p = new URLSearchParams({ days: String(days) })
    appendCity(p, city)
    appendSector(p, sector)
    return getJson<any>(`/api/ultron/roles/${searchId}/companies?${p}`)
  },
  topCompanies: (days = 7, limit = 80, sector = '', city = '') => {
    const p = new URLSearchParams({
      days: String(days),
      limit: String(limit),
    })
    appendSector(p, sector)
    appendCity(p, city)
    return getJson<any>(`/api/ultron/top-companies?${p}`)
  },
  rolesRank: (
    limit = 200,
    days = 7,
    mode: 'count' | 'rate' = 'count',
    sector = '',
    city = '',
  ) => {
    const p = new URLSearchParams({
      limit: String(limit),
      days: String(days),
      mode,
    })
    appendSector(p, sector)
    appendCity(p, city)
    return getJson<any>(`/api/ultron/roles-rank?${p}`)
  },
  citySignals: (days = 7, sector = '') => {
    const p = new URLSearchParams({ days: String(days) })
    appendSector(p, sector)
    return getJson<any>(`/api/ultron/cities?${p}`)
  },
  cityCompare: (a: string, b: string, days = 7, sector = '') => {
    const p = new URLSearchParams({
      a,
      b,
      days: String(days),
    })
    appendSector(p, sector)
    return getJson<any>(`/api/ultron/cities/compare?${p}`)
  },
  sectors: () => getJson<any>('/api/ultron/sectors'),
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
