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
  | 'cities'

export type RankListFocus =
  | { kind: 'companies'; days: number }
  | { kind: 'roles'; days?: number }
  | null

/** Sector chip id; empty string = all sectors */
export type SectorOption = { id: string; label: string; industry?: string }

/** City chip id; empty string = all cities */
export type CityOption = { id: string; label: string }

function readStoredSector(): string {
  try {
    const raw = localStorage.getItem('vigil.sector')
    if (raw == null) return ''
    return raw
  } catch {
    return ''
  }
}

function readStoredCity(): string {
  try {
    const raw = localStorage.getItem('vigil.city')
    if (raw == null) return ''
    return raw
  } catch {
    return ''
  }
}

const DEFAULT_SECTOR_FAVS = ['tech_ai', 'tech_digital']
const DEFAULT_CITY_FAVS = ['bengaluru', 'chennai', 'kerala']

function readStoredFavs(key: string, fallback: string[]): string[] {
  try {
    const raw = localStorage.getItem(key)
    if (!raw) return [...fallback]
    const parsed = JSON.parse(raw) as string[]
    if (!Array.isArray(parsed)) return [...fallback]
    return parsed.filter((x) => typeof x === 'string' && x)
  } catch {
    return [...fallback]
  }
}

function persistFavs(key: string, ids: string[]) {
  try {
    localStorage.setItem(key, JSON.stringify(ids))
  } catch {
    /* ignore */
  }
}

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
  /** Center of panel as % of .vigil-stage */
  x: number
  y: number
  /** Size as % of .vigil-stage (persisted; corner-resize) */
  w: number
  h: number
  scale: number
  z: number
}

type PanelGeo = { x: number; y: number; w: number; h: number; scale: number }

/** x/y are stage % of the panel CENTER (transform translate -50%-50%). */
const PANEL_CENTER: PanelGeo = { x: 50, y: 50, w: 46, h: 68, scale: 1 }
/** Default Tower home — inset so the right edge never clips. */
export const TOWER_PIN_HOME: PanelGeo = { x: 56, y: 52, w: 48, h: 72, scale: 1 }

const MIN_W = 28
const MAX_W = 92
const MIN_H = 32
const MAX_H = 90

const PANEL_META: { id: PanelId; title: string }[] = [
  { id: 'tower', title: 'TOWER INSIGHTS' },
  { id: 'signals', title: 'HIRING SIGNALS' },
  { id: 'watchlist', title: 'WATCHLIST' },
  { id: 'searches', title: 'SEARCHES' },
  { id: 'activity', title: 'ACTIVITY' },
  { id: 'jobs', title: 'JOBS' },
  { id: 'live', title: 'LIVE FEED' },
  { id: 'health', title: 'TOWER HEALTH' },
  { id: 'ask', title: 'ASK TOWER' },
  { id: 'filter_mix', title: 'AI VS KEYWORD' },
  { id: 'cities', title: 'CITY SIGNALS' },
  { id: 'role_hire', title: 'COMPANIES HIRING' },
  { id: 'rank_list', title: 'FULL LIST' },
]

function clamp(n: number, lo: number, hi: number) {
  return Math.max(lo, Math.min(hi, n))
}

/** Keep the full panel (by center + size) inside the stage. */
export function clampPanelGeo(geo: PanelGeo): PanelGeo {
  const w = clamp(geo.w, MIN_W, MAX_W)
  const h = clamp(geo.h, MIN_H, MAX_H)
  const pad = 1.5
  const halfW = w / 2
  const halfH = h / 2
  return {
    w,
    h,
    scale: clamp(geo.scale, 0.75, 1.6),
    x: clamp(geo.x, halfW + pad, 100 - halfW - pad),
    y: clamp(geo.y, halfH + pad, 100 - halfH - pad),
  }
}

function defaultGeo(id: PanelId): PanelGeo {
  return id === 'tower' ? { ...TOWER_PIN_HOME } : { ...PANEL_CENTER }
}

/** Panels that can be pinned to the admin dashboard (not transient drill-downs). */
export const PINNABLE_PANELS: PanelId[] = [
  'tower', 'signals', 'watchlist', 'searches', 'activity', 'jobs', 'live', 'health', 'ask', 'filter_mix', 'cities',
]

export const ORBIT_NODES: OrbitNode[] = [
  { id: 'tower', label: 'Tower', angle: -0.95, radius: 2.55 },
  { id: 'jobs', label: 'Jobs', angle: -0.4, radius: 2.6 },
  { id: 'signals', label: 'Hiring Signals', angle: 0.35, radius: 2.7 },
  { id: 'cities', label: 'Cities', angle: 0.52, radius: 2.68 },
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
  positions: Partial<Record<PanelId, PanelGeo>>
}

const DEFAULT_PIN_LAYOUT: PinLayout = {
  pinned: ['tower'],
  positions: { tower: { ...TOWER_PIN_HOME } },
}

function loadGeometry(): Partial<Record<PanelId, PanelGeo>> {
  try {
    const raw = localStorage.getItem('vigil.geometry')
    if (!raw) return {}
    const parsed = JSON.parse(raw) as Partial<Record<PanelId, PanelGeo>>
    return parsed && typeof parsed === 'object' ? parsed : {}
  } catch {
    return {}
  }
}

function persistGeometry(panels: Record<PanelId, PanelState>) {
  const geo: Partial<Record<PanelId, PanelGeo>> = { ...loadGeometry() }
  for (const id of Object.keys(panels) as PanelId[]) {
    const p = panels[id]
    if (!p) continue
    // Remember last size/place for every panel that has been positioned
    geo[id] = clampPanelGeo({
      x: p.x,
      y: p.y,
      w: p.w,
      h: p.h,
      scale: p.scale,
    })
  }
  try {
    localStorage.setItem('vigil.geometry', JSON.stringify(geo))
  } catch {
    /* ignore */
  }
}

function loadPinLayout(): PinLayout {
  try {
    const raw = localStorage.getItem('vigil.pins')
    if (!raw) return { ...DEFAULT_PIN_LAYOUT, positions: { ...DEFAULT_PIN_LAYOUT.positions } }
    const parsed = JSON.parse(raw) as PinLayout
    const pinned = (parsed.pinned || []).filter((id) =>
      PINNABLE_PANELS.includes(id),
    ) as PanelId[]
    const positions = { ...(parsed.positions || {}) }
    // Migrate old tower home that sat too far right (clipped)
    if (positions.tower && positions.tower.x > 70) {
      positions.tower = clampPanelGeo({
        ...TOWER_PIN_HOME,
        w: positions.tower.w ?? TOWER_PIN_HOME.w,
        h: positions.tower.h ?? TOWER_PIN_HOME.h,
        scale: positions.tower.scale ?? 1,
      })
    }
    return { pinned, positions }
  } catch {
    return { ...DEFAULT_PIN_LAYOUT, positions: { ...DEFAULT_PIN_LAYOUT.positions } }
  }
}

function persistPinLayout(panels: Record<PanelId, PanelState>) {
  const pinned = PINNABLE_PANELS.filter((id) => panels[id]?.pinned)
  const positions: PinLayout['positions'] = {}
  for (const id of pinned) {
    const p = panels[id]
    if (!p) continue
    positions[id] = clampPanelGeo({
      x: p.x,
      y: p.y,
      w: p.w,
      h: p.h,
      scale: p.scale,
    })
  }
  try {
    localStorage.setItem('vigil.pins', JSON.stringify({ pinned, positions }))
  } catch {
    /* ignore */
  }
  persistGeometry(panels)
}

function resolveGeo(
  id: PanelId,
  pinPos?: PanelGeo,
  stored?: PanelGeo,
): PanelGeo {
  const base = defaultGeo(id)
  const merged = {
    ...base,
    ...(stored || {}),
    ...(pinPos || {}),
  }
  // Older saves may lack w/h
  if (merged.w == null) merged.w = base.w
  if (merged.h == null) merged.h = base.h
  return clampPanelGeo(merged as PanelGeo)
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
  /** core = particle singularity · graph = Obsidian data · city = globe/district */
  sceneMode: 'core' | 'graph' | 'city'
  setSceneMode: (m: 'core' | 'graph' | 'city') => void
  /** Legacy 0–1 approach hint (OrbitControls owns real camera now) */
  sceneZoom: number
  setSceneZoom: (z: number) => void
  /** Bump to snap OrbitControls back to home (Esc / mode change) */
  viewResetNonce: number
  resetView: () => void
  /** Auto-spin of core/globe/graph ambience — off while working */
  sceneSpin: boolean
  setSceneSpin: (on: boolean) => void
  toggleSceneSpin: () => void
  /** Graph local-focus node id; null = full graph */
  graphFocusId: string | null
  setGraphFocusId: (id: string | null) => void
  /**
   * First-click camera focus (drone isometric). Second click on same id opens UI.
   * `id` matches graph node / company tower / city marker.
   */
  cameraFocus: {
    id: string
    x: number
    y: number
    z: number
    distance: number
  } | null
  cameraFocusNonce: number
  requestCameraFocus: (f: {
    id: string
    x: number
    y: number
    z: number
    distance?: number
  }) => void
  /** Fly camera only — does not change focus / second-click selection */
  teleportCamera: (f: {
    x: number
    y: number
    z: number
    distance?: number
  }) => void
  clearCameraFocus: () => void
  /** City mode drill-down (city_key); null = globe overview */
  cityFocus: string | null
  setCityFocus: (id: string | null) => void
  /** Last selected interactive id (for second-click open) */
  selectFocusId: string | null
  setSelectFocusId: (id: string | null) => void
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
  /** Resize panel; w/h are % of stage. Keeps top-left fixed when fromCorner. */
  resizePanel: (id: PanelId, w: number, h: number, opts?: { anchor?: 'se' }) => void
  focusPanel: (id: PanelId) => void
  togglePin: (id: PanelId) => void
  restoreDashboard: () => void
  insightFocus: InsightFocus
  rankFocus: RankListFocus
  /** Global sector filter (persisted). '' = all sectors */
  sectorFilter: string
  setSectorFilter: (id: string) => void
  sectorOptions: SectorOption[]
  setSectorOptions: (opts: SectorOption[]) => void
  /** Global city filter (persisted). '' = all cities */
  cityFilter: string
  setCityFilter: (id: string) => void
  cityOptions: CityOption[]
  setCityOptions: (opts: CityOption[]) => void
  /** Favourite sector ids (persisted) — shown before Show more */
  sectorFavorites: string[]
  toggleSectorFavorite: (id: string) => void
  /** Favourite city ids (persisted) — shown before Show more */
  cityFavorites: string[]
  toggleCityFavorite: (id: string) => void
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
  const stored = loadGeometry()
  const out = {} as Record<PanelId, PanelState>
  PANEL_META.forEach((p, i) => {
    const pinned = layout.pinned.includes(p.id)
    const geo = resolveGeo(p.id, layout.positions[p.id], stored[p.id])
    out[p.id] = {
      id: p.id,
      title: p.title,
      open: false,
      pinned,
      x: geo.x,
      y: geo.y,
      w: geo.w,
      h: geo.h,
      scale: geo.scale,
      z: i,
    }
  })
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
  sceneMode: 'core',
  setSceneMode: (m) => {
    const labels = {
      core: 'CORE · drag/scroll/pinch · Esc reset',
      graph: 'GRAPH · tagged world model',
      city: 'CITY · globe → click metro → buildings',
    } as const
    set({
      sceneMode: m,
      cityFocus: m === 'city' ? null : get().cityFocus,
      statusLine: labels[m],
      sceneZoom: 0,
      canvasPan: { x: 0, y: 0 },
      viewResetNonce: get().viewResetNonce + 1,
    })
  },
  sceneZoom: 0,
  setSceneZoom: (z) =>
    set({ sceneZoom: Math.max(0, Math.min(1, z)) }),
  viewResetNonce: 0,
  resetView: () =>
    set({
      viewResetNonce: get().viewResetNonce + 1,
      sceneZoom: 0,
      canvasPan: { x: 0, y: 0 },
      graphFocusId: null,
      cameraFocus: null,
      selectFocusId: null,
      cameraFocusNonce: get().cameraFocusNonce + 1,
      statusLine: 'VIEW RESET · drag orbit · scroll/pinch enter',
    }),
  sceneSpin: true,
  setSceneSpin: (on) =>
    set({
      sceneSpin: on,
      statusLine: on ? 'SPIN ON' : 'SPIN OFF — work freely',
    }),
  toggleSceneSpin: () => {
    const on = !get().sceneSpin
    set({
      sceneSpin: on,
      statusLine: on ? 'SPIN ON' : 'SPIN OFF — work freely',
    })
  },
  graphFocusId: null,
  setGraphFocusId: (id) => set({ graphFocusId: id }),
  cameraFocus: null,
  cameraFocusNonce: 0,
  requestCameraFocus: (f) =>
    set({
      cameraFocus: {
        id: f.id,
        x: f.x,
        y: f.y,
        z: f.z,
        distance: f.distance ?? 3.2,
      },
      cameraFocusNonce: get().cameraFocusNonce + 1,
      selectFocusId: f.id,
      statusLine: 'FOCUS · click again to open',
    }),
  teleportCamera: (f) =>
    set({
      cameraFocus: {
        id: get().cameraFocus?.id || get().selectFocusId || 'teleport',
        x: f.x,
        y: f.y,
        z: f.z,
        distance: f.distance ?? 1.7,
      },
      cameraFocusNonce: get().cameraFocusNonce + 1,
      statusLine: 'TELEPORT',
    }),
  clearCameraFocus: () =>
    set({
      cameraFocus: null,
      selectFocusId: null,
      cameraFocusNonce: get().cameraFocusNonce + 1,
    }),
  cityFocus: null,
  setCityFocus: (id) => set({ cityFocus: id }),
  selectFocusId: null,
  setSelectFocusId: (id) => set({ selectFocusId: id }),
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
  sectorFilter: readStoredSector(),
  setSectorFilter: (id) => {
    const next = id || ''
    try {
      localStorage.setItem('vigil.sector', next)
    } catch {
      /* ignore */
    }
    const opts = get().sectorOptions
    const label =
      opts.find((o) => (o.id || '') === next)?.label ||
      (next ? next : 'All sectors')
    set({
      sectorFilter: next,
      statusLine: `SECTOR · ${label.toUpperCase()}`,
    })
  },
  sectorOptions: [],
  setSectorOptions: (opts) => set({ sectorOptions: opts }),
  cityFilter: readStoredCity(),
  setCityFilter: (id) => {
    const next = id || ''
    try {
      localStorage.setItem('vigil.city', next)
    } catch {
      /* ignore */
    }
    const opts = get().cityOptions
    const label =
      opts.find((o) => (o.id || '') === next)?.label ||
      (next ? next : 'All cities')
    set({
      cityFilter: next,
      statusLine: `CITY · ${label.toUpperCase()}`,
    })
  },
  cityOptions: [],
  setCityOptions: (opts) => set({ cityOptions: opts }),
  sectorFavorites: readStoredFavs('vigil.sectorFavs', DEFAULT_SECTOR_FAVS),
  toggleSectorFavorite: (id) => {
    if (!id) return
    const cur = get().sectorFavorites
    const next = cur.includes(id) ? cur.filter((x) => x !== id) : [...cur, id]
    persistFavs('vigil.sectorFavs', next)
    const label =
      get().sectorOptions.find((o) => o.id === id)?.label || id
    set({
      sectorFavorites: next,
      statusLine: next.includes(id)
        ? `FAVOURITE SECTOR · ${label.toUpperCase()}`
        : `UNFAVOURITE SECTOR · ${label.toUpperCase()}`,
    })
  },
  cityFavorites: readStoredFavs('vigil.cityFavs', DEFAULT_CITY_FAVS),
  toggleCityFavorite: (id) => {
    if (!id) return
    const cur = get().cityFavorites
    const next = cur.includes(id) ? cur.filter((x) => x !== id) : [...cur, id]
    persistFavs('vigil.cityFavs', next)
    const label =
      get().cityOptions.find((o) => o.id === id)?.label || id
    set({
      cityFavorites: next,
      statusLine: next.includes(id)
        ? `FAVOURITE CITY · ${label.toUpperCase()}`
        : `UNFAVOURITE CITY · ${label.toUpperCase()}`,
    })
  },
  openPanel: (id) => {
    const panels = { ...get().panels }
    const maxZ = Math.max(...Object.values(panels).map((p) => p.z), 0)
    const cur = panels[id]
    const stored = loadGeometry()[id]
    const geo = clampPanelGeo({
      x: cur.pinned ? cur.x : (stored?.x ?? cur.x ?? PANEL_CENTER.x),
      y: cur.pinned ? cur.y : (stored?.y ?? cur.y ?? PANEL_CENTER.y),
      w: stored?.w ?? cur.w ?? PANEL_CENTER.w,
      h: stored?.h ?? cur.h ?? PANEL_CENTER.h,
      scale: stored?.scale ?? cur.scale ?? 1,
    })
    panels[id] = {
      ...cur,
      open: true,
      z: maxZ + 1,
      ...geo,
    }
    persistGeometry(panels)
    set({
      panels,
      focusedPanel: id,
      statusLine: `OPENING ${panels[id].title}`,
    })
  },
  closePanel: (id, _opts) => {
    const panels = { ...get().panels }
    panels[id] = { ...panels[id], open: false }
    persistGeometry(panels)
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
    const cur = panels[id]
    const geo = clampPanelGeo({
      x,
      y,
      w: cur.w,
      h: cur.h,
      scale: cur.scale,
    })
    panels[id] = { ...cur, ...geo }
    if (cur.pinned) persistPinLayout(panels)
    else persistGeometry(panels)
    set({ panels })
  },
  scalePanel: (id, scale) => {
    const panels = { ...get().panels }
    const cur = panels[id]
    const geo = clampPanelGeo({
      x: cur.x,
      y: cur.y,
      w: cur.w,
      h: cur.h,
      scale,
    })
    panels[id] = { ...cur, ...geo }
    if (cur.pinned) persistPinLayout(panels)
    else persistGeometry(panels)
    set({ panels })
  },
  resizePanel: (id, w, h, opts) => {
    const panels = { ...get().panels }
    const cur = panels[id]
    const nextW = clamp(w, MIN_W, MAX_W)
    const nextH = clamp(h, MIN_H, MAX_H)
    let x = cur.x
    let y = cur.y
    // SE corner: keep top-left fixed while growing/shrinking
    if (opts?.anchor === 'se') {
      const left = cur.x - cur.w / 2
      const top = cur.y - cur.h / 2
      x = left + nextW / 2
      y = top + nextH / 2
    }
    const geo = clampPanelGeo({
      x,
      y,
      w: nextW,
      h: nextH,
      scale: cur.scale,
    })
    panels[id] = { ...cur, ...geo }
    if (cur.pinned) persistPinLayout(panels)
    else persistGeometry(panels)
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
    const nextPinned = !cur.pinned
    panels[id] = {
      ...cur,
      pinned: nextPinned,
      open: nextPinned ? true : cur.open,
      // First pin of Tower uses inset home (never clipped)
      ...(nextPinned && id === 'tower' && !cur.pinned
        ? clampPanelGeo({
            ...TOWER_PIN_HOME,
            w: cur.w || TOWER_PIN_HOME.w,
            h: cur.h || TOWER_PIN_HOME.h,
            scale: cur.scale || 1,
          })
        : {}),
    }
    persistPinLayout(panels)
    set({
      panels,
      focusedPanel: nextPinned || cur.open ? id : get().focusedPanel,
      statusLine: nextPinned
        ? `PINNED ${cur.title} TO DASHBOARD`
        : `UNPINNED ${cur.title}`,
    })
  },
  restoreDashboard: () => {
    const layout = loadPinLayout()
    const stored = loadGeometry()
    const panels = { ...get().panels }
    let maxZ = Math.max(...Object.values(panels).map((p) => p.z), 0)
    let focus: PanelId | null = null
    // Close unpinned panels; reopen only what admin pinned
    for (const id of Object.keys(panels) as PanelId[]) {
      if (!layout.pinned.includes(id)) {
        panels[id] = { ...panels[id], open: false, pinned: false }
      }
    }
    for (const id of layout.pinned) {
      const geo = resolveGeo(id, layout.positions[id], stored[id])
      maxZ += 1
      panels[id] = {
        ...panels[id],
        open: true,
        pinned: true,
        ...geo,
        z: maxZ,
      }
      focus = id
    }
    persistPinLayout(panels)
    set({
      panels,
      focusedPanel: focus,
      statusLine:
        layout.pinned.length > 0
          ? `DASHBOARD · ${layout.pinned.length} PINNED`
          : 'DASHBOARD EMPTY — PIN ANY MODULE',
    })
  },
  openRoleHire: (searchId, name, days = 7) => {
    const panels = { ...get().panels }
    const maxZ = Math.max(...Object.values(panels).map((p) => p.z), 0)
    const stored = loadGeometry().role_hire
    const geo = resolveGeo('role_hire', undefined, stored)
    panels.role_hire = {
      ...panels.role_hire,
      open: true,
      z: maxZ + 1,
      ...geo,
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
    const geo = resolveGeo('jobs', undefined, loadGeometry().jobs)
    panels.jobs = {
      ...panels.jobs,
      open: true,
      z: maxZ + 1,
      ...geo,
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
    const geo = resolveGeo('jobs', undefined, loadGeometry().jobs)
    panels.jobs = {
      ...panels.jobs,
      open: true,
      z: maxZ + 1,
      ...geo,
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
    const geo = resolveGeo('rank_list', undefined, loadGeometry().rank_list)
    panels.rank_list = {
      ...panels.rank_list,
      open: true,
      z: maxZ + 1,
      ...geo,
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
    'tower', 'signals', 'watchlist', 'searches', 'activity', 'jobs', 'live', 'health', 'ask', 'filter_mix', 'cities', 'role_hire', 'rank_list',
  ]
  return p && (valid as string[]).includes(p) ? (p as PanelId) : null
}
