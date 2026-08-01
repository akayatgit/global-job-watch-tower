import { create } from 'zustand'
import {
  loadCalibration,
  saveCalibration,
  type VigilCalibration,
} from '../training/calibration'
import { endTrainLog, startTrainLog } from '../training/sessionLog'

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
  /** All five digits curled (fist) — close window under hand */
  fist: boolean
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

function readStoredVigilMode(): boolean {
  try {
    return localStorage.getItem('vigil.mode') === 'on'
  } catch {
    return false
  }
}

export type TrainingStepId =
  | 'idle'
  | 'hub'
  | 'intro'
  | 'show_hand'
  | 'pinch'
  | 'move'
  | 'scroll'
  | 'zoom_window'
  | 'two_hand'
  | 'close'
  | 'press'
  | 'done'
  | 'fail'
  | 'flick_zoom'
  | 'fist_close'

export type GestureMode =
  | 'none'
  | 'dwell'
  | 'drag_panel'
  | 'scroll_panel'
  | 'zoom_panel'
  | 'pan_canvas'
  | 'core_zoom'

type VigilStore = {
  vigilMode: boolean
  setVigilMode: (on: boolean) => void
  calibration: VigilCalibration
  setCalibration: (c: VigilCalibration) => void
  trainingActive: boolean
  trainingStep: TrainingStepId
  trainingFeedback: string
  trainingFailReport: string
  /** Free practice: pick any drill, return to hub on pass (no robotic chain) */
  trainingPractice: boolean
  startTraining: () => void
  stopTraining: () => void
  setTrainingStep: (step: TrainingStepId) => void
  setTrainingFeedback: (text: string) => void
  setTrainingFailReport: (text: string) => void
  setTrainingPractice: (on: boolean) => void
  statusLine: string
  setStatus: (text: string) => void
  coreScale: number
  setCoreScale: (n: number) => void
  coreBurst: number
  triggerBurst: () => void
  canvasPan: { x: number; y: number }
  setCanvasPan: (p: { x: number; y: number }) => void
  hands: HandsState
  setHands: (h: HandsState) => void
  /** Primary (right) hand guides */
  smoothIndex: { x: number; y: number }
  smoothThumb: { x: number; y: number }
  /** Secondary (left) hand guides — cyan */
  smoothLeftIndex: { x: number; y: number }
  smoothLeftThumb: { x: number; y: number }
  leftHandVisible: boolean
  pressProgress: number
  setPressProgress: (n: number) => void
  hoverTarget: string | null
  setHoverTarget: (id: string | null) => void
  grabTarget: string | null
  setGrabTarget: (id: string | null) => void
  gestureMode: GestureMode
  setGestureMode: (m: GestureMode) => void
  focusedPanel: PanelId | null
  panels: Record<PanelId, PanelState>
  openPanel: (id: PanelId) => void
  closePanel: (id: PanelId) => void
  movePanel: (id: PanelId, x: number, y: number) => void
  scalePanel: (id: PanelId, scale: number) => void
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
  vigilMode: readStoredVigilMode(),
  setVigilMode: (on) => {
    try {
      localStorage.setItem('vigil.mode', on ? 'on' : 'off')
    } catch {
      /* ignore */
    }
    if (on && !get().trainingActive) startTrainLog('live')
    else if (!on && !get().trainingActive) endTrainLog({ reason: 'vigil_off' })
    set({
      vigilMode: on,
      pressProgress: 0,
      hoverTarget: null,
      grabTarget: null,
      magnet: null,
      gestureMode: 'none',
      hands: { left: null, right: null, twoHandPinch: false, twoHandDist: 0 },
      trainingActive: on ? get().trainingActive : false,
      trainingStep: on ? get().trainingStep : 'idle',
      statusLine: on
        ? 'VIGIL MODE ON — HAND CONTROL'
        : 'DESKTOP MODE — MOUSE & KEYBOARD',
    })
  },
  calibration: loadCalibration(),
  setCalibration: (c) => {
    saveCalibration(c)
    set({ calibration: c })
  },
  trainingActive: false,
  trainingStep: 'idle',
  trainingFeedback: '',
  trainingFailReport: '',
  trainingPractice: false,
  startTraining: () => {
    try {
      localStorage.setItem('vigil.mode', 'on')
    } catch {
      /* ignore */
    }
    startTrainLog('training')
    set({
      vigilMode: true,
      trainingActive: true,
      trainingStep: 'hub',
      trainingPractice: false,
      trainingFeedback: 'Pick a drill anytime — or skip back to the tower',
      trainingFailReport: '',
      statusLine: 'TRAINING GROUND',
      pressProgress: 0,
      grabTarget: null,
      gestureMode: 'none',
      canvasPan: { x: 0, y: 0 },
    })
  },
  stopTraining: () => {
    endTrainLog({ reason: 'exit' })
    if (get().vigilMode) startTrainLog('live')
    set({
      trainingActive: false,
      trainingStep: 'idle',
      trainingPractice: false,
      trainingFeedback: '',
      trainingFailReport: '',
      gestureMode: 'none',
      statusLine: get().vigilMode
        ? 'VIGIL MODE ON — HAND CONTROL'
        : 'DESKTOP MODE — MOUSE & KEYBOARD',
    })
  },
  setTrainingStep: (step) => set({ trainingStep: step }),
  setTrainingFeedback: (text) => set({ trainingFeedback: text }),
  setTrainingFailReport: (text) => set({ trainingFailReport: text }),
  setTrainingPractice: (on) => set({ trainingPractice: on }),
  statusLine: readStoredVigilMode()
    ? 'VIGIL MODE ON — HAND CONTROL'
    : 'DESKTOP MODE — MOUSE & KEYBOARD',
  setStatus: (text) => set({ statusLine: text }),
  coreScale: 1,
  setCoreScale: (n) => set({ coreScale: Math.max(0.7, Math.min(2.4, n)) }),
  coreBurst: 0,
  triggerBurst: () => set({ coreBurst: performance.now() }),
  canvasPan: { x: 0, y: 0 },
  setCanvasPan: (p) =>
    set({
      canvasPan: {
        x: Math.max(-2.5, Math.min(2.5, p.x)),
        y: Math.max(-1.5, Math.min(1.5, p.y)),
      },
    }),
  hands: { left: null, right: null, twoHandPinch: false, twoHandDist: 0 },
  setHands: (h) => set({ hands: h }),
  smoothIndex: { x: 0.5, y: 0.5 },
  smoothThumb: { x: 0.5, y: 0.55 },
  smoothLeftIndex: { x: 0.35, y: 0.5 },
  smoothLeftThumb: { x: 0.32, y: 0.55 },
  leftHandVisible: false,
  pressProgress: 0,
  setPressProgress: (n) => set({ pressProgress: n }),
  hoverTarget: null,
  setHoverTarget: (id) => set({ hoverTarget: id }),
  grabTarget: null,
  setGrabTarget: (id) => set({ grabTarget: id }),
  gestureMode: 'none',
  setGestureMode: (m) => set({ gestureMode: m }),
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
    const remaining = Object.values(panels)
      .filter((p) => p.open)
      .sort((a, b) => b.z - a.z)
    const next = remaining[0]?.id ?? null
    set({
      panels,
      focusedPanel: next,
      statusLine: next
        ? `CLOSED ${panels[id].title} → ${panels[next].title}`
        : `CLOSED ${panels[id].title}`,
    })
  },
  movePanel: (id, x, y) => {
    const panels = { ...get().panels }
    panels[id] = { ...panels[id], x, y }
    set({ panels })
  },
  scalePanel: (id, scale) => {
    const panels = { ...get().panels }
    panels[id] = {
      ...panels[id],
      scale: Math.max(0.65, Math.min(1.8, scale)),
    }
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
