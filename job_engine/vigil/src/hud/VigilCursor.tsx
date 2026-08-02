import { useEffect, useRef } from 'react'

/**
 * Immersive VIGIL cursor — small glowing white dot.
 * Noticeable fluid lag, subtle halo, soft trail. No rings / hex chrome.
 */

const LERP = 0.038 // clearly felt lag (lower = dreamier)
const TRAIL_LEN = 10
const CORE_R = 2.4 // small crisp core
const HALO_R = 5.5 // subtle outer only

type Pt = { x: number; y: number }

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

    const target: Pt = { x: window.innerWidth / 2, y: window.innerHeight / 2 }
    const pos: Pt = { x: target.x, y: target.y }
    const prev: Pt = { x: pos.x, y: pos.y }
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
      target.x = e.clientX
      target.y = e.clientY
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
      pos.x += (target.x - pos.x) * LERP
      pos.y += (target.y - pos.y) * LERP

      const dx = pos.x - prev.x
      const dy = pos.y - prev.y
      const instant = Math.hypot(dx, dy)
      vel = vel * 0.88 + instant * 0.12
      if (instant > 0.04) angle = Math.atan2(dy, dx)
      prev.x = pos.x
      prev.y = pos.y

      trail.unshift({ x: pos.x, y: pos.y })
      if (trail.length > TRAIL_LEN) trail.pop()

      ctx.clearRect(0, 0, w, h)
      if (!visible) {
        raf = requestAnimationFrame(draw)
        return
      }

      const speedNorm = Math.min(1, vel / 22)

      // Soft trail echoes
      if (speedNorm > 0.06) {
        for (let i = trail.length - 1; i >= 1; i--) {
          const t = trail[i]
          const a = (1 - i / trail.length) * 0.14 * speedNorm
          ctx.beginPath()
          ctx.fillStyle = `rgba(255, 255, 255, ${a})`
          ctx.shadowColor = 'rgba(255, 255, 255, 0.25)'
          ctx.shadowBlur = 4
          ctx.arc(t.x, t.y, CORE_R * 0.55, 0, Math.PI * 2)
          ctx.fill()
        }
      }

      ctx.save()
      ctx.translate(pos.x, pos.y)
      const stretch = 1 + speedNorm * 0.4
      const squash = 1 / Math.sqrt(stretch)
      ctx.rotate(angle)
      ctx.scale(stretch, squash)

      // Subtle halo only
      const aura = ctx.createRadialGradient(0, 0, 0, 0, 0, HALO_R)
      aura.addColorStop(0, 'rgba(255, 255, 255, 0.75)')
      aura.addColorStop(0.45, 'rgba(255, 255, 255, 0.22)')
      aura.addColorStop(1, 'rgba(255, 255, 255, 0)')
      ctx.beginPath()
      ctx.fillStyle = aura
      ctx.shadowColor = 'rgba(255, 255, 255, 0.35)'
      ctx.shadowBlur = 6
      ctx.arc(0, 0, HALO_R, 0, Math.PI * 2)
      ctx.fill()

      // Crisp small core
      ctx.beginPath()
      ctx.shadowBlur = 3
      ctx.shadowColor = 'rgba(255, 255, 255, 0.5)'
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
