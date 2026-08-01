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

export const api = {
  status: () => getJson<any>('/api/ultron/status'),
  tower: () => getJson<any>('/api/ultron/tower'),
  signals: (days = 7) => getJson<any>(`/api/ultron/signals?days=${days}`),
  watchlist: (days = 7, q = '') =>
    getJson<any>(`/api/ultron/watchlist?days=${days}&q=${encodeURIComponent(q)}`),
  health: () => getJson<any>('/api/ultron/health'),
  configs: () => getJson<any[]>('/api/configs'),
  runs: (limit = 50) => getJson<any[]>(`/api/runs?limit=${limit}`),
  jobs: (limit = 80) => getJson<any[]>(`/api/jobs?limit=${limit}`),
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
