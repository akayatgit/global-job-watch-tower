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
}

function jobsUrl(q: JobsQuery = {}) {
  const p = new URLSearchParams()
  p.set('limit', String(q.limit ?? 80))
  if (q.search_config_id) p.set('search_config_id', String(q.search_config_id))
  if (q.company_id) p.set('company_id', String(q.company_id))
  if (q.company) p.set('company', q.company)
  if (q.title) p.set('title', q.title)
  return `/api/jobs?${p}`
}

export const api = {
  status: () => getJson<any>('/api/ultron/status'),
  tower: () => getJson<any>('/api/ultron/tower'),
  signals: (days = 7) => getJson<any>(`/api/ultron/signals?days=${days}`),
  watchlist: (days = 7, q = '') =>
    getJson<any>(`/api/ultron/watchlist?days=${days}&q=${encodeURIComponent(q)}`),
  roleCompanies: (searchId: number, days = 7) =>
    getJson<any>(`/api/ultron/roles/${searchId}/companies?days=${days}`),
  health: () => getJson<any>('/api/ultron/health'),
  configs: () => getJson<any[]>('/api/configs'),
  runs: (limit = 50) => getJson<any[]>(`/api/runs?limit=${limit}`),
  jobs: (limitOrQuery: number | JobsQuery = 80) => {
    if (typeof limitOrQuery === 'number') return getJson<any[]>(jobsUrl({ limit: limitOrQuery }))
    return getJson<any[]>(jobsUrl(limitOrQuery))
  },
  console: (afterId = 0) => getJson<any[]>(`/api/console?after_id=${afterId}&limit=120`),
  stats: () => getJson<any>('/api/stats'),
  toggleHeadless: () => postJson<any>('/api/ultron/toggle-headless'),
  dismissAlert: () => postJson<any>('/api/ultron/dismiss-alert'),
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
