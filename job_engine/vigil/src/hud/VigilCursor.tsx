import { useEffect, useRef } from 'react'

/**
 * Instant cursor (zero lag). Only the motion path fades behind it.
 */

const TRAIL_LEN = 14
const CORE_R = 2.5
const HALO_R = 5.2
/** How fast trail ghosts die (higher = shorter path) */
const TRAIL_DECAY = 0.88

type Pt = { x: number; y: number; a: number }

export function VigilCursor() {
  const canvasRef = useRef<HTMLCanvasElement>(null)

  useEffect(() => {
    const root = document.documentElement
    root.classList.add('vigil-custom-cursor')

    const canvas = canvasRef.current
    if (!canvas) return
    const ctx = canvas.getContext('2d', { alpha: true })
    if (!ctx) return

    let w = 0
    let h = 0
    const dpr = Math.min(window.devicePixelRatio || 1, 2)

    const pos: Pt = {
      x: window.innerWidth / 2,
      y: window.innerHeight / 2,
      a: 1,
    }
    const prev: Pt = { x: pos.x, y: pos.y, a: 1 }
    const trail: Pt[] = []
    let vel = 0
    let angle = 0
    let visible = true
    let raf = 0

    const resize = () => {
      w = window.innerWidth
      h = window.innerHeight
      canvas.width = Math.floor(w * dpr)
      canvas.height = Math.floor(h * dpr)
      canvas.style.width = `${w}px`
      canvas.style.height = `${h}px`
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
    }
    resize()

    const onMove = (e: PointerEvent) => {
      // Instant — no lerp on the cursor itself
      pos.x = e.clientX
      pos.y = e.clientY
      visible = true
    }
    const onLeave = () => {
      visible = false
    }
    const onEnter = () => {
      visible = true
    }

    window.addEventListener('pointermove', onMove, { passive: true })
    window.addEventListener('pointerleave', onLeave)
    window.addEventListener('pointerenter', onEnter)
    window.addEventListener('resize', resize)

    const draw = () => {
      const dx = pos.x - prev.x
      const dy = pos.y - prev.y
      const instant = Math.hypot(dx, dy)
      vel = vel * 0.85 + instant * 0.15
      if (instant > 0.2) angle = Math.atan2(dy, dx)

      // Path samples: exact positions, fade over time
      if (instant > 0.35) {
        trail.unshift({ x: prev.x, y: prev.y, a: 0.55 })
        if (trail.length > TRAIL_LEN) trail.pop()
      }
      for (let i = 0; i < trail.length; i++) {
        trail[i].a *= TRAIL_DECAY
      }
      while (trail.length && trail[trail.length - 1].a < 0.02) trail.pop()

      prev.x = pos.x
      prev.y = pos.y

      ctx.clearRect(0, 0, w, h)
      if (!visible) {
        raf = requestAnimationFrame(draw)
        return
      }

      const speedNorm = Math.min(1, vel / 18)

      // Fading motion path only
      for (let i = trail.length - 1; i >= 0; i--) {
        const t = trail[i]
        const a = t.a * (0.35 + speedNorm * 0.45)
        ctx.beginPath()
        ctx.fillStyle = `rgba(255, 255, 255, ${a})`
        ctx.shadowColor = `rgba(255, 200, 140, ${a * 0.4})`
        ctx.shadowBlur = 3
        ctx.arc(t.x, t.y, CORE_R * 0.45, 0, Math.PI * 2)
        ctx.fill()
      }

      // Instant cursor core
      ctx.save()
      ctx.translate(pos.x, pos.y)
      const stretch = 1 + speedNorm * 0.35
      const squash = 1 / Math.sqrt(stretch)
      ctx.rotate(angle)
      ctx.scale(stretch, squash)

      const aura = ctx.createRadialGradient(0, 0, 0, 0, 0, HALO_R)
      aura.addColorStop(0, 'rgba(255, 255, 255, 0.8)')
      aura.addColorStop(0.5, 'rgba(255, 220, 180, 0.18)')
      aura.addColorStop(1, 'rgba(255, 255, 255, 0)')
      ctx.beginPath()
      ctx.fillStyle = aura
      ctx.shadowColor = 'rgba(255, 200, 140, 0.3)'
      ctx.shadowBlur = 5
      ctx.arc(0, 0, HALO_R, 0, Math.PI * 2)
      ctx.fill()

      ctx.beginPath()
      ctx.shadowBlur = 2
      ctx.shadowColor = 'rgba(255, 255, 255, 0.45)'
      ctx.fillStyle = '#ffffff'
      ctx.arc(0, 0, CORE_R, 0, Math.PI * 2)
      ctx.fill()
      ctx.restore()

      ctx.shadowBlur = 0
      raf = requestAnimationFrame(draw)
    }
    raf = requestAnimationFrame(draw)

    return () => {
      cancelAnimationFrame(raf)
      root.classList.remove('vigil-custom-cursor')
      window.removeEventListener('pointermove', onMove)
      window.removeEventListener('pointerleave', onLeave)
      window.removeEventListener('pointerenter', onEnter)
      window.removeEventListener('resize', resize)
    }
  }, [])

  return (
    <canvas ref={canvasRef} className="vigil-cursor-layer" aria-hidden />
  )
}
