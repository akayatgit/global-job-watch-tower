/** Persisted hand-feel calibration for Ashok's VIGIL training. */

export type VigilCalibration = {
  version: 1
  updatedAt: string
  /** Thumb↔index distance below this = pinch (normalized MediaPipe space) */
  pinchThreshold: number
  /** Dwell ms before press-by-dot fires */
  dwellMs: number
  /** Orbit / hit radius in CSS pixels */
  hitPx: number
  /** Finger guide / hand lerp factor (higher = snappier) */
  lerpFactor: number
  /** Sessions completed (for progress) */
  sessionsCompleted: number
  /** Last measured hand speed (normalized units / second) — informational */
  handSpeed: number
  notes: string
}

export const DEFAULT_CALIBRATION: VigilCalibration = {
  version: 1,
  updatedAt: '',
  pinchThreshold: 0.045,
  dwellMs: 550,
  hitPx: 72,
  lerpFactor: 0.15,
  sessionsCompleted: 0,
  handSpeed: 0,
  notes: 'factory defaults',
}

const KEY = 'vigil.calibration.v1'

export function loadCalibration(): VigilCalibration {
  try {
    const raw = localStorage.getItem(KEY)
    if (!raw) return { ...DEFAULT_CALIBRATION }
    const parsed = JSON.parse(raw) as Partial<VigilCalibration>
    return {
      ...DEFAULT_CALIBRATION,
      ...parsed,
      version: 1,
    }
  } catch {
    return { ...DEFAULT_CALIBRATION }
  }
}

export function saveCalibration(cal: VigilCalibration): void {
  try {
    localStorage.setItem(KEY, JSON.stringify(cal))
  } catch {
    /* ignore */
  }
}

function percentile(sorted: number[], p: number): number {
  if (!sorted.length) return DEFAULT_CALIBRATION.pinchThreshold
  const idx = Math.min(sorted.length - 1, Math.max(0, Math.floor(p * (sorted.length - 1))))
  return sorted[idx]
}

export type TrainingSamples = {
  /** Distances while Ashok believed he was pinching */
  pinchDistances: number[]
  /** Distances while open hand (not pinching) */
  openDistances: number[]
  /** Successful dwell durations (ms) */
  dwellDurations: number[]
  /** Index tip speed samples (norm units / s) */
  speeds: number[]
  /** Jitter (std of index position over short windows) */
  jitters: number[]
}

/** Derive calibration from a completed training session. */
export function computeCalibration(
  samples: TrainingSamples,
  prev: VigilCalibration,
): VigilCalibration {
  const pinches = [...samples.pinchDistances].sort((a, b) => a - b)
  const opens = [...samples.openDistances].sort((a, b) => a - b)

  let pinchThreshold = prev.pinchThreshold
  if (pinches.length >= 3) {
    // Midpoint between typical pinch and typical open, biased toward easier pinch
    const pinchP80 = percentile(pinches, 0.8)
    const openP20 = opens.length >= 3 ? percentile(opens, 0.2) : pinchP80 + 0.04
    const mid = (pinchP80 + openP20) / 2
    pinchThreshold = Math.min(0.08, Math.max(0.025, mid * 1.05))
  }

  const avgSpeed =
    samples.speeds.length > 0
      ? samples.speeds.reduce((a, b) => a + b, 0) / samples.speeds.length
      : prev.handSpeed

  const avgJitter =
    samples.jitters.length > 0
      ? samples.jitters.reduce((a, b) => a + b, 0) / samples.jitters.length
      : 0.01

  // Dwell: if Ashok needs longer holds (jitter resets), train toward a shorter
  // required time AND larger hit pads — not a longer impossible hold.
  let dwellMs = prev.dwellMs
  if (samples.dwellDurations.length >= 1) {
    const sorted = [...samples.dwellDurations].sort((a, b) => a - b)
    const med = percentile(sorted, 0.5)
    // Target slightly under median successful hold
    dwellMs = Math.min(900, Math.max(320, Math.round(med * 0.75)))
  } else if (avgJitter > 0.012) {
    // Jittery hands, no completed dwell yet — ease the requirement
    dwellMs = Math.min(prev.dwellMs, 480)
  }

  let lerpFactor = 0.12 + Math.min(0.18, avgSpeed * 0.8) - Math.min(0.08, avgJitter * 4)
  lerpFactor = Math.min(0.28, Math.max(0.08, lerpFactor))

  // Larger hit targets when jittery or fast
  const hitPx = Math.min(
    110,
    Math.max(56, Math.round(64 + avgSpeed * 80 + avgJitter * 1200)),
  )

  return {
    version: 1,
    updatedAt: new Date().toISOString(),
    pinchThreshold,
    dwellMs,
    hitPx,
    lerpFactor,
    sessionsCompleted: prev.sessionsCompleted + 1,
    handSpeed: avgSpeed,
    notes: `trained pinch=${pinchThreshold.toFixed(3)} dwell=${dwellMs}ms lerp=${lerpFactor.toFixed(2)}`,
  }
}
