import { create } from 'zustand'

export type PanelId =
  | 'tower'
  | 'signals'
  | 'watchlist'
  | 'searches'
  | 'activity'
  | 'jobs'
  | 'live'
  | 'health'

export type OrbitNode = {
  id: PanelId | 'remote'
  label: string
  angle: number
  radius: number
}

export type HandSample = {
  index: { x: number; y: number } | null
  thumb: { x: number; y: number } | null
  pinch: boolean
  pinchDist: number
  centroid: { x: number; y: number } | null
}

export type HandsState = {
  left: HandSample | null
  right: HandSample | null
  twoHandPinch: boolean
  twoHandDist: number
}

export type PanelState = {
  id: PanelId
  title: string
  open: boolean
  x: number
  y: number
  scale: number
  z: number
}

const PANEL_META: { id: PanelId; title: string; x: number; y: number }[] = [
  { id: 'tower', title: 'TOWER INSIGHTS', x: 4, y: 14 },
  { id: 'signals', title: 'HIRING SIGNALS', x: 58, y: 12 },
  { id: 'watchlist', title: 'WATCHLIST', x: 62, y: 48 },
  { id: 'searches', title: 'SEARCHES', x: 6, y: 48 },
  { id: 'activity', title: 'ACTIVITY', x: 32, y: 56 },
  { id: 'jobs', title: 'JOBS', x: 55, y: 30 },
  { id: 'live', title: 'LIVE FEED', x: 8, y: 30 },
  { id: 'health', title: 'TOWER HEALTH', x: 38, y: 10 },
]

export const ORBIT_NODES: OrbitNode[] = [
  { id: 'jobs', label: 'Tech Jobs', angle: -0.4, radius: 2.6 },
  { id: 'signals', label: 'Hiring Signals', angle: 0.35, radius: 2.7 },
  { id: 'searches', label: 'Searches', angle: 1.1, radius: 2.55 },
  { id: 'activity', label: 'Activity', angle: 1.85, radius: 2.65 },
  { id: 'live', label: 'Live', angle: 2.55, radius: 2.5 },
  { id: 'health', label: 'Health', angle: 3.4, radius: 2.7 },
  { id: 'watchlist', label: 'Watchlist', angle: 4.2, radius: 2.6 },
  { id: 'remote', label: 'Remote Trends', angle: 5.0, radius: 2.55 },
]

type VigilStore = {
  statusLine: string
  setStatus: (text: string) => void
  coreScale: number
  setCoreScale: (n: number) => void
  coreBurst: number
  triggerBurst: () => void
  hands: HandsState
  setHands: (h: HandsState) => void
  smoothIndex: { x: number; y: number }
  smoothThumb: { x: number; y: number }
  pressProgress: number
  setPressProgress: (n: number) => void
  hoverTarget: string | null
  setHoverTarget: (id: string | null) => void
  grabTarget: string | null
  setGrabTarget: (id: string | null) => void
  focusedPanel: PanelId | null
  panels: Record<PanelId, PanelState>
  openPanel: (id: PanelId) => void
  closePanel: (id: PanelId) => void
  movePanel: (id: PanelId, x: number, y: number) => void
  focusPanel: (id: PanelId) => void
  vitals: any | null
  setVitals: (v: any) => void
  latencyMs: number
  setLatencyMs: (n: number) => void
  wsConnected: boolean
  setWsConnected: (v: boolean) => void
  magnet: { x: number; y: number } | null
  setMagnet: (m: { x: number; y: number } | null) => void
}

function initialPanels(): Record<PanelId, PanelState> {
  const out = {} as Record<PanelId, PanelState>
  PANEL_META.forEach((p, i) => {
    out[p.id] = {
      id: p.id,
      title: p.title,
      open: false,
      x: p.x,
      y: p.y,
      scale: 1,
      z: i,
    }
  })
  return out
}

export const useVigilStore = create<VigilStore>((set, get) => ({
  statusLine: 'VIGIL ONLINE — JOB MARKET CORE ACTIVE',
  setStatus: (text) => set({ statusLine: text }),
  coreScale: 1,
  setCoreScale: (n) => set({ coreScale: Math.max(0.7, Math.min(2.2, n)) }),
  coreBurst: 0,
  triggerBurst: () => set({ coreBurst: performance.now() }),
  hands: { left: null, right: null, twoHandPinch: false, twoHandDist: 0 },
  setHands: (h) => set({ hands: h }),
  smoothIndex: { x: 0.5, y: 0.5 },
  smoothThumb: { x: 0.5, y: 0.55 },
  pressProgress: 0,
  setPressProgress: (n) => set({ pressProgress: n }),
  hoverTarget: null,
  setHoverTarget: (id) => set({ hoverTarget: id }),
  grabTarget: null,
  setGrabTarget: (id) => set({ grabTarget: id }),
  focusedPanel: null,
  panels: initialPanels(),
  openPanel: (id) => {
    const panels = { ...get().panels }
    const maxZ = Math.max(...Object.values(panels).map((p) => p.z), 0)
    panels[id] = { ...panels[id], open: true, z: maxZ + 1 }
    set({
      panels,
      focusedPanel: id,
      statusLine: `OPENING ${panels[id].title}`,
    })
  },
  closePanel: (id) => {
    const panels = { ...get().panels }
    panels[id] = { ...panels[id], open: false }
    set({
      panels,
      focusedPanel: get().focusedPanel === id ? null : get().focusedPanel,
      statusLine: `CLOSED ${panels[id].title}`,
    })
  },
  movePanel: (id, x, y) => {
    const panels = { ...get().panels }
    panels[id] = { ...panels[id], x, y }
    set({ panels })
  },
  focusPanel: (id) => {
    const panels = { ...get().panels }
    const maxZ = Math.max(...Object.values(panels).map((p) => p.z), 0)
    panels[id] = { ...panels[id], z: maxZ + 1, open: true }
    set({ panels, focusedPanel: id })
  },
  vitals: null,
  setVitals: (v) => set({ vitals: v }),
  latencyMs: 0,
  setLatencyMs: (n) => set({ latencyMs: n }),
  wsConnected: false,
  setWsConnected: (v) => set({ wsConnected: v }),
  magnet: null,
  setMagnet: (m) => set({ magnet: m }),
}))

export function panelFromQuery(): PanelId | null {
  const params = new URLSearchParams(window.location.search)
  const p = params.get('panel')
  const valid: PanelId[] = [
    'tower', 'signals', 'watchlist', 'searches', 'activity', 'jobs', 'live', 'health',
  ]
  return p && (valid as string[]).includes(p) ? (p as PanelId) : null
}
