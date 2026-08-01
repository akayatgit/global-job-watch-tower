import type { TrainingSamples } from './calibration'

/** Mutable bag filled during a training session, then folded into calibration. */
export function emptySamples(): TrainingSamples {
  return {
    pinchDistances: [],
    openDistances: [],
    dwellDurations: [],
    speeds: [],
    jitters: [],
  }
}

let bag = emptySamples()

export function resetSamples() {
  bag = emptySamples()
}

export function getSamples(): TrainingSamples {
  return bag
}

export function pushPinch(dist: number) {
  if (bag.pinchDistances.length < 200) bag.pinchDistances.push(dist)
}

export function pushOpen(dist: number) {
  if (bag.openDistances.length < 200) bag.openDistances.push(dist)
}

export function pushDwell(ms: number) {
  if (ms > 100 && bag.dwellDurations.length < 40) bag.dwellDurations.push(ms)
}

export function pushSpeed(s: number) {
  if (s > 0 && bag.speeds.length < 300) bag.speeds.push(s)
}

export function pushJitter(j: number) {
  if (bag.jitters.length < 200) bag.jitters.push(j)
}
