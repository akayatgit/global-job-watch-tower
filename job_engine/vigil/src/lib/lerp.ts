export function lerp(current: number, target: number, factor = 0.15): number {
  return current + (target - current) * factor
}

export function dist2(ax: number, ay: number, bx: number, by: number): number {
  const dx = ax - bx
  const dy = ay - by
  return Math.hypot(dx, dy)
}

export function clamp(v: number, min: number, max: number): number {
  return Math.max(min, Math.min(max, v))
}
