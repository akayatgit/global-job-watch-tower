/** Compact remaining time for the rail footer — e.g. "1m 2s to go". */
export function formatCountdownSecs(secs: number | null | undefined): string {
  if (secs == null || !Number.isFinite(secs) || secs < 0) return '—'
  const s = Math.max(0, Math.round(secs))
  if (s < 60) return `${s}s to go`
  const m = Math.floor(s / 60)
  const r = s % 60
  if (m < 60) return r > 0 ? `${m}m ${r}s to go` : `${m}m to go`
  const h = Math.floor(m / 60)
  const rm = m % 60
  return rm > 0 ? `${h}h ${rm}m to go` : `${h}h to go`
}

export function railCountdownLabel(
  mode: string | undefined,
  secs: number | null | undefined,
): string {
  if (mode === 'paused') return 'paused'
  if (mode === 'idle') return 'idle'
  if (secs == null) return '—'
  return formatCountdownSecs(secs)
}
