import type { VigilCalibration } from './calibration'
import { getSamples } from './sampleBus'
import type { TrainingStepId } from '../store/vigilStore'

export function buildFailReport(opts: {
  step: TrainingStepId
  feedback: string
  calibration: VigilCalibration
  handsSummary: string
  gestureMode: string
}): string {
  const samples = getSamples()
  const payload = {
    when: new Date().toISOString(),
    failedStep: opts.step,
    feedback: opts.feedback,
    gestureMode: opts.gestureMode,
    hands: opts.handsSummary,
    calibration: opts.calibration,
    samples: {
      pinchCount: samples.pinchDistances.length,
      openCount: samples.openDistances.length,
      dwellCount: samples.dwellDurations.length,
      speedCount: samples.speeds.length,
      jitterCount: samples.jitters.length,
      pinchP50: median(samples.pinchDistances),
      openP50: median(samples.openDistances),
      dwellP50: median(samples.dwellDurations),
      speedAvg: avg(samples.speeds),
      jitterAvg: avg(samples.jitters),
    },
  }
  return JSON.stringify(payload, null, 2)
}

function median(arr: number[]): number | null {
  if (!arr.length) return null
  const s = [...arr].sort((a, b) => a - b)
  return s[Math.floor(s.length / 2)]
}

function avg(arr: number[]): number | null {
  if (!arr.length) return null
  return arr.reduce((a, b) => a + b, 0) / arr.length
}
