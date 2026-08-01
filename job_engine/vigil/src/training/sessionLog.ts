/** Client-side training session log — mirrored to server for Akay improvements. */

export type TrainLogEvent = {
  t: number
  iso: string
  type: string
  detail?: Record<string, unknown>
}

type Session = {
  id: string
  startedAt: string
  events: TrainLogEvent[]
}

const LS_KEY = 'vigil.training.logs'
const MAX_SESSIONS = 20
const MAX_EVENTS = 800

let current: Session | null = null

function nowEvent(type: string, detail?: Record<string, unknown>): TrainLogEvent {
  const t = performance.now()
  return { t, iso: new Date().toISOString(), type, detail }
}

function persistLocal() {
  if (!current) return
  try {
    const raw = localStorage.getItem(LS_KEY)
    const all: Session[] = raw ? JSON.parse(raw) : []
    const idx = all.findIndex((s) => s.id === current!.id)
    if (idx >= 0) all[idx] = current
    else all.unshift(current)
    localStorage.setItem(LS_KEY, JSON.stringify(all.slice(0, MAX_SESSIONS)))
  } catch {
    /* ignore */
  }
}

async function flushServer() {
  if (!current) return
  try {
    await fetch('/api/ultron/training-log', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(current),
    })
  } catch {
    /* offline ok — still in localStorage */
  }
}

export function startTrainLog() {
  current = {
    id: `train-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
    startedAt: new Date().toISOString(),
    events: [nowEvent('session_start')],
  }
  persistLocal()
  void flushServer()
  return current.id
}

export function logTrain(type: string, detail?: Record<string, unknown>) {
  if (!current) startTrainLog()
  current!.events.push(nowEvent(type, detail))
  if (current!.events.length > MAX_EVENTS) {
    current!.events = current!.events.slice(-MAX_EVENTS)
  }
  // Persist every few events + on important ones
  if (
    current!.events.length % 8 === 0 ||
    type.startsWith('step_') ||
    type.includes('fail') ||
    type.includes('camera') ||
    type.includes('hand_')
  ) {
    persistLocal()
  }
  if (type.startsWith('step_') || type.includes('fail') || type === 'session_end') {
    void flushServer()
  }
}

export function endTrainLog(detail?: Record<string, unknown>) {
  if (!current) return null
  current.events.push(nowEvent('session_end', detail))
  persistLocal()
  void flushServer()
  const id = current.id
  current = null
  return id
}

export function getCurrentTrainLog(): Session | null {
  return current
}

export function getRecentTrainLogs(): Session[] {
  try {
    const raw = localStorage.getItem(LS_KEY)
    return raw ? JSON.parse(raw) : []
  } catch {
    return []
  }
}
