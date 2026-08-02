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
  | 'ask'
  | 'filter_mix'
  | 'role_hire'
  | 'rank_list'

export type RankListFocus =
  | { kind: 'companies'; days: number }
  | { kind: 'roles'; days?: number }
  | null

export type OrbitNode = {
  id: PanelId
  label: string
  angle: number
  radius: number
}

/** Drill-down focus for jobs / role hire panels */
export type InsightFocus =
  | { kind: 'role'; searchId: number; name: string; days?: number }
  | {
      kind: 'company'
      companyId: number
      name: string
      days?: number
      /** When set, Jobs stay scoped to this role (from Companies Hiring). */
      searchId?: number
      roleName?: string
    }
  | null

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
  pinned: boolean
  x: number
  y: number
  scale: number
  z: number
}

/** x/y are viewport % of the panel CENTER (transform translate -50%-50%). */
const PANEL_CENTER = { x: 50, y: 48, scale: 1 }
/** Default home for Tower Insights — pinned on the right. */
export const TOWER_PIN_HOME = { x: 78, y: 48, scale: 1 }

const PANEL_META: { id: PanelId; title: string; x: number; y: number }[] = [
  { id: 'tower', title: 'TOWER INSIGHTS', ...TOWER_PIN_HOME },
  { id: 'signals', title: 'HIRING SIGNALS', ...PANEL_CENTER },
  { id: 'watchlist', title: 'WATCHLIST', ...PANEL_CENTER },
  { id: 'searches', title: 'SEARCHES', ...PANEL_CENTER },
  { id: 'activity', title: 'ACTIVITY', ...PANEL_CENTER },
  { id: 'jobs', title: 'JOBS', ...PANEL_CENTER },
  { id: 'live', title: 'LIVE FEED', ...PANEL_CENTER },
  { id: 'health', title: 'TOWER HEALTH', ...PANEL_CENTER },
  { id: 'ask', title: 'ASK TOWER', ...PANEL_CENTER },
  { id: 'filter_mix', title: 'AI VS KEYWORD', ...PANEL_CENTER },
  { id: 'role_hire', title: 'COMPANIES HIRING', ...PANEL_CENTER },
  { id: 'rank_list', title: 'FULL LIST', ...PANEL_CENTER },
]

/** Panels that can be pinned to the admin dashboard (not transient drill-downs). */
export const PINNABLE_PANELS: PanelId[] = [
  'tower', 'signals', 'watchlist', 'searches', 'activity', 'jobs', 'live', 'health', 'ask', 'filter_mix',
]

export const ORBIT_NODES: OrbitNode[] = [
  { id: 'tower', label: 'Tower', angle: -0.95, radius: 2.55 },
  { id: 'jobs', label: 'Jobs', angle: -0.4, radius: 2.6 },
  { id: 'signals', label: 'Hiring Signals', angle: 0.35, radius: 2.7 },
  { id: 'filter_mix', label: 'AI vs Keyword', angle: 0.7, radius: 2.62 },
  { id: 'searches', label: 'Searches', angle: 1.1, radius: 2.55 },
  { id: 'activity', label: 'Activity', angle: 1.85, radius: 2.65 },
  { id: 'live', label: 'Live', angle: 2.55, radius: 2.5 },
  { id: 'health', label: 'Health', angle: 3.4, radius: 2.7 },
  { id: 'ask', label: 'Ask', angle: 4.7, radius: 2.55 },
  { id: 'watchlist', label: 'Watchlist', angle: 4.2, radius: 2.6 },
]

type PinLayout = {
  pinned: PanelId[]
  positions: Partial<Record<PanelId, { x: number; y: number; scale: number }>>
}

const DEFAULT_PIN_LAYOUT: PinLayout = {
  pinned: ['tower'],
  positions: { tower: { ...TOWER_PIN_HOME } },
}

function loadPinLayout(): PinLayout {
  try {
    const raw = localStorage.getItem('vigil.pins')
    if (!raw) return { ...DEFAULT_PIN_LAYOUT, positions: { ...DEFAULT_PIN_LAYOUT.positions } }
    const parsed = JSON.parse(raw) as PinLayout
    const pinned = (parsed.pinned || []).filter((id) =>
      PINNABLE_PANELS.includes(id),
    ) as PanelId[]
    // Tower always stays on the dashboard pin list
    if (!pinned.includes('tower')) pinned.unshift('tower')
    const positions = { ...DEFAULT_PIN_LAYOUT.positions, ...(parsed.positions || {}) }
    if (!positions.tower) positions.tower = { ...TOWER_PIN_HOME }
    return { pinned, positions }
  } catch {
    return { ...DEFAULT_PIN_LAYOUT, positions: { ...DEFAULT_PIN_LAYOUT.positions } }
  }
}

function persistPinLayout(panels: Record<PanelId, PanelState>) {
  const pinned = PINNABLE_PANELS.filter((id) => panels[id]?.pinned)
  if (!pinned.includes('tower')) pinned.unshift('tower')
  const positions: PinLayout['positions'] = {}
  for (const id of pinned) {
    const p = panels[id]
    if (!p) continue
    positions[id] = { x: p.x, y: p.y, scale: p.scale }
  }
  if (!positions.tower) positions.tower = { ...TOWER_PIN_HOME }
  try {
    localStorage.setItem('vigil.pins', JSON.stringify({ pinned, positions }))
  } catch {
    /* ignore */
  }
}

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

function readRailOpen(): boolean {
  try {
    const raw = localStorage.getItem('vigil.rail')
    if (raw === null) return true
    return raw === '1' || raw === 'true' || raw === 'open'
  } catch {
    return true
  }
}

type VigilStore = {
  vigilMode: boolean
  setVigilMode: (on: boolean) => void
  /** Left module rail visible (separate from widget canvas). */
  railOpen: boolean
  setRailOpen: (open: boolean) => void
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
  closePanel: (id: PanelId, opts?: { force?: boolean }) => void
  movePanel: (id: PanelId, x: number, y: number) => void
  scalePanel: (id: PanelId, scale: number) => void
  focusPanel: (id: PanelId) => void
  togglePin: (id: PanelId) => void
  restoreDashboard: () => void
  insightFocus: InsightFocus
  rankFocus: RankListFocus
  openRoleHire: (searchId: number, name: string, days?: number) => void
  openCompanyJobs: (
    companyId: number,
    name: string,
    days?: number,
    opts?: { searchId?: number; roleName?: string },
  ) => void
  openRoleJobs: (searchId: number, name: string) => void
  openRankList: (kind: 'companies' | 'roles', days?: number) => void
  clearInsightFocus: () => void
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
  const layout = loadPinLayout()
  const out = {} as Record<PanelId, PanelState>
  PANEL_META.forEach((p, i) => {
    const pinned = layout.pinned.includes(p.id) || p.id === 'tower'
    const pos = layout.positions[p.id]
    out[p.id] = {
      id: p.id,
      title: p.title,
      open: false,
      pinned,
      x: pos?.x ?? p.x,
      y: pos?.y ?? p.y,
      scale: pos?.scale ?? 1,
      z: i,
    }
  })
  // Tower always pinned
  out.tower.pinned = true
  if (!layout.positions.tower) {
    out.tower.x = TOWER_PIN_HOME.x
    out.tower.y = TOWER_PIN_HOME.y
    out.tower.scale = TOWER_PIN_HOME.scale
  }
  return out
}

export const useVigilStore = create<VigilStore>((set, get) => ({
  vigilMode: readStoredVigilMode(),
  railOpen: readRailOpen(),
  setRailOpen: (open) => {
    try {
      localStorage.setItem('vigil.rail', open ? '1' : '0')
    } catch {
      /* ignore */
    }
    set({
      railOpen: open,
      statusLine: open ? 'MODULE RAIL OPEN' : 'MODULE RAIL HIDDEN',
    })
  },
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
  insightFocus: null,
  rankFocus: null,
  openPanel: (id) => {
    const panels = { ...get().panels }
    const maxZ = Math.max(...Object.values(panels).map((p) => p.z), 0)
    const cur = panels[id]
    const pinned = cur.pinned || id === 'tower'
    panels[id] = {
      ...cur,
      open: true,
      pinned: id === 'tower' ? true : cur.pinned,
      z: maxZ + 1,
      // Pinned widgets reopen at their dashboard spot; others center
      x: pinned ? cur.x : PANEL_CENTER.x,
      y: pinned ? cur.y : PANEL_CENTER.y,
      scale: pinned ? cur.scale : 1,
    }
    set({
      panels,
      focusedPanel: id,
      statusLine: `OPENING ${panels[id].title}`,
    })
  },
  closePanel: (id, opts) => {
    const panels = { ...get().panels }
    // Tower Insights stays on the canvas while pinned — snap home instead of closing
    if (id === 'tower' && panels.tower.pinned && !opts?.force) {
      panels.tower = {
        ...panels.tower,
        open: true,
        x: TOWER_PIN_HOME.x,
        y: TOWER_PIN_HOME.y,
        scale: panels.tower.scale || TOWER_PIN_HOME.scale,
      }
      persistPinLayout(panels)
      set({
        panels,
        focusedPanel: 'tower',
        statusLine: 'TOWER STAYS PINNED ON THE RIGHT',
      })
      return
    }
    panels[id] = { ...panels[id], open: false }
    const remaining = Object.values(panels)
      .filter((p) => p.open)
      .sort((a, b) => b.z - a.z)
    const next = remaining[0]?.id ?? null
    set({
      panels,
      focusedPanel: next,
      ...(id === 'role_hire' ? { insightFocus: null as InsightFocus } : {}),
      ...(id === 'rank_list' ? { rankFocus: null as RankListFocus } : {}),
      statusLine: next
        ? `CLOSED ${panels[id].title} → ${panels[next].title}`
        : `CLOSED ${panels[id].title}`,
    })
  },
  movePanel: (id, x, y) => {
    const panels = { ...get().panels }
    // Center-point clamps — keep window mostly on-screen
    panels[id] = {
      ...panels[id],
      x: Math.max(22, Math.min(82, x)),
      y: Math.max(22, Math.min(78, y)),
    }
    if (panels[id].pinned) persistPinLayout(panels)
    set({ panels })
  },
  scalePanel: (id, scale) => {
    const panels = { ...get().panels }
    panels[id] = {
      ...panels[id],
      scale: Math.max(0.75, Math.min(1.6, scale)),
    }
    if (panels[id].pinned) persistPinLayout(panels)
    set({ panels })
  },
  focusPanel: (id) => {
    const panels = { ...get().panels }
    const maxZ = Math.max(...Object.values(panels).map((p) => p.z), 0)
    panels[id] = { ...panels[id], z: maxZ + 1, open: true }
    set({ panels, focusedPanel: id })
  },
  togglePin: (id) => {
    if (!PINNABLE_PANELS.includes(id)) {
      set({ statusLine: 'THIS WINDOW CANNOT BE PINNED' })
      return
    }
    const panels = { ...get().panels }
    const cur = panels[id]
    // Tower cannot be fully unpinned from the dashboard — keep pin, snap right
    if (id === 'tower' && cur.pinned) {
      panels.tower = {
        ...panels.tower,
        open: true,
        pinned: true,
        x: TOWER_PIN_HOME.x,
        y: TOWER_PIN_HOME.y,
      }
      persistPinLayout(panels)
      set({
        panels,
        focusedPanel: 'tower',
        statusLine: 'TOWER ALWAYS STAYS PINNED — SNAPPED RIGHT',
      })
      return
    }
    const nextPinned = !cur.pinned
    panels[id] = {
      ...cur,
      pinned: nextPinned,
      open: true,
      ...(nextPinned && id === 'tower' ? { ...TOWER_PIN_HOME } : {}),
    }
    persistPinLayout(panels)
    set({
      panels,
      focusedPanel: id,
      statusLine: nextPinned
        ? `PINNED ${cur.title} TO DASHBOARD`
        : `UNPINNED ${cur.title}`,
    })
  },
  restoreDashboard: () => {
    const layout = loadPinLayout()
    const panels = { ...get().panels }
    let maxZ = Math.max(...Object.values(panels).map((p) => p.z), 0)
    let focus: PanelId | null = null
    for (const id of layout.pinned) {
      const pos = layout.positions[id] || (id === 'tower' ? TOWER_PIN_HOME : PANEL_CENTER)
      maxZ += 1
      panels[id] = {
        ...panels[id],
        open: true,
        pinned: true,
        x: pos.x,
        y: pos.y,
        scale: pos.scale ?? 1,
        z: maxZ,
      }
      focus = id
    }
    // Prefer focusing a non-tower panel if several are pinned; else tower
    const nonTower = layout.pinned.filter((id) => id !== 'tower')
    if (nonTower.length) focus = nonTower[nonTower.length - 1]
    else focus = 'tower'
    panels.tower = {
      ...panels.tower,
      open: true,
      pinned: true,
      x: layout.positions.tower?.x ?? TOWER_PIN_HOME.x,
      y: layout.positions.tower?.y ?? TOWER_PIN_HOME.y,
      scale: layout.positions.tower?.scale ?? TOWER_PIN_HOME.scale,
    }
    persistPinLayout(panels)
    set({
      panels,
      focusedPanel: focus,
      statusLine:
        layout.pinned.length > 1
          ? `DASHBOARD · ${layout.pinned.length} PINNED`
          : 'TOWER PINNED ON THE RIGHT',
    })
  },
  openRoleHire: (searchId, name, days = 7) => {
    const panels = { ...get().panels }
    const maxZ = Math.max(...Object.values(panels).map((p) => p.z), 0)
    panels.role_hire = {
      ...panels.role_hire,
      open: true,
      z: maxZ + 1,
      x: PANEL_CENTER.x,
      y: PANEL_CENTER.y,
      scale: 1,
      title: `HIRING · ${name.toUpperCase()}`,
    }
    set({
      panels,
      focusedPanel: 'role_hire',
      insightFocus: { kind: 'role', searchId, name, days },
      statusLine: `COMPANIES HIRING · ${name}`,
    })
  },
  openCompanyJobs: (companyId, name, days = 7, opts) => {
    const panels = { ...get().panels }
    const maxZ = Math.max(...Object.values(panels).map((p) => p.z), 0)
    const roleBit = opts?.roleName ? ` · ${opts.roleName}` : ''
    panels.jobs = {
      ...panels.jobs,
      open: true,
      z: maxZ + 1,
      x: PANEL_CENTER.x,
      y: PANEL_CENTER.y,
      scale: 1,
      title: `JOBS · ${name.toUpperCase()}${roleBit ? roleBit.toUpperCase() : ''}`,
    }
    set({
      panels,
      focusedPanel: 'jobs',
      insightFocus: {
        kind: 'company',
        companyId,
        name,
        days,
        searchId: opts?.searchId,
        roleName: opts?.roleName,
      },
      statusLine: opts?.roleName
        ? `JOBS · ${opts.roleName} @ ${name}`
        : `JOBS AT ${name}`,
    })
  },
  openRoleJobs: (searchId, name) => {
    const panels = { ...get().panels }
    const maxZ = Math.max(...Object.values(panels).map((p) => p.z), 0)
    panels.jobs = {
      ...panels.jobs,
      open: true,
      z: maxZ + 1,
      x: PANEL_CENTER.x,
      y: PANEL_CENTER.y,
      scale: 1,
      title: `JOBS · ${name.toUpperCase()}`,
    }
    set({
      panels,
      focusedPanel: 'jobs',
      insightFocus: { kind: 'role', searchId, name },
      statusLine: `JOBS FOR ${name}`,
    })
  },
  openRankList: (kind, days = 7) => {
    const panels = { ...get().panels }
    const maxZ = Math.max(...Object.values(panels).map((p) => p.z), 0)
    const title = kind === 'companies' ? 'ALL TOP HIRING' : 'ALL ROLES'
    panels.rank_list = {
      ...panels.rank_list,
      open: true,
      z: maxZ + 1,
      x: PANEL_CENTER.x,
      y: PANEL_CENTER.y,
      scale: 1,
      title,
    }
    set({
      panels,
      focusedPanel: 'rank_list',
      rankFocus:
        kind === 'companies'
          ? { kind: 'companies', days }
          : { kind: 'roles', days },
      statusLine: title,
    })
  },
  clearInsightFocus: () => {
    const panels = { ...get().panels }
    panels.jobs = { ...panels.jobs, title: 'JOBS' }
    panels.role_hire = { ...panels.role_hire, title: 'COMPANIES HIRING' }
    set({ insightFocus: null, panels })
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
    'tower', 'signals', 'watchlist', 'searches', 'activity', 'jobs', 'live', 'health', 'ask', 'filter_mix', 'role_hire', 'rank_list',
  ]
  return p && (valid as string[]).includes(p) ? (p as PanelId) : null
}
