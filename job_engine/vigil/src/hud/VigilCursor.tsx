import { useEffect, useRef } from 'react'

/**
 * Immersive VIGIL cursor — glowing white singularity dot.
 * Physics: lerp trail + velocity stretch + click/hover geometric rings.
 * Native cursor hidden via `.vigil-custom-cursor` on <html>.
 */

const LERP = 0.13
const TRAIL_LEN = 10
const CORE_R = 7 // ~14px diameter
const HALO_R = 14

type Pt = { x: number; y: number }

function isHotTarget(el: Element | null): boolean {
  if (!el) return false
  return Boolean(
    el.closest(
      'button, a, input, select, textarea, label, [role="button"], .hud-icon-btn, .module-rail-btn, .float-panel, .chip, .vigil-canvas, [data-cursor="hot"]',
    ),
  )
}

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
    let hover = 0 // 0..1
    let clickPulse = 0 // 0..1 decaying
    let ringPhase = 0
    let visible = true
    let raf = 0
    let lastT = performance.now()

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
    const onDown = () => {
      clickPulse = 1
    }
    const onLeave = () => {
      visible = false
    }
    const onEnter = () => {
      visible = true
    }

    window.addEventListener('pointermove', onMove, { passive: true })
    window.addEventListener('pointerdown', onDown, { passive: true })
    window.addEventListener('pointerleave', onLeave)
    window.addEventListener('pointerenter', onEnter)
    window.addEventListener('resize', resize)

    const draw = (now: number) => {
      const dt = Math.min(0.033, (now - lastT) / 1000)
      lastT = now

      // Dual-stage lerp — soft overshoot / momentum when stopping
      pos.x += (target.x - pos.x) * LERP
      pos.y += (target.y - pos.y) * LERP
      // Secondary settle toward target (damps residual lag)
      pos.x += (target.x - pos.x) * 0.04
      pos.y += (target.y - pos.y) * 0.04

      const dx = pos.x - prev.x
      const dy = pos.y - prev.y
      const instant = Math.hypot(dx, dy)
      vel = vel * 0.82 + instant * 0.18
      if (instant > 0.05) angle = Math.atan2(dy, dx)
      prev.x = pos.x
      prev.y = pos.y

      trail.unshift({ x: pos.x, y: pos.y })
      if (trail.length > TRAIL_LEN) trail.pop()

      // Refresh hover more cheaply each frame near cursor
      const el = document.elementFromPoint(target.x, target.y)
      const wantHover = isHotTarget(el) ? 1 : 0
      hover += (wantHover - hover) * Math.min(1, dt * 12)

      clickPulse = Math.max(0, clickPulse - dt * 2.8)
      ringPhase += dt * (2.2 + hover * 1.5)

      ctx.clearRect(0, 0, w, h)
      if (!visible) {
        raf = requestAnimationFrame(draw)
        return
      }

      // --- Trail / motion-blur echoes along velocity vector ---
      const speedNorm = Math.min(1, vel / 28)
      if (speedNorm > 0.08) {
        for (let i = trail.length - 1; i >= 1; i--) {
          const t = trail[i]
          const a = (1 - i / trail.length) * 0.22 * speedNorm
          const r = CORE_R * (0.45 + (1 - i / trail.length) * 0.4)
          ctx.beginPath()
          ctx.fillStyle = `rgba(255, 255, 255, ${a})`
          ctx.shadowColor = 'rgba(255, 200, 140, 0.45)'
          ctx.shadowBlur = 10
          ctx.arc(t.x, t.y, r, 0, Math.PI * 2)
          ctx.fill()
        }
      }

      ctx.save()
      ctx.translate(pos.x, pos.y)
      // Velocity stretch along motion angle
      const stretch = 1 + speedNorm * 0.55
      const squash = 1 / Math.sqrt(stretch)
      ctx.rotate(angle)
      ctx.scale(stretch, squash)

      // Outer aura
      const aura = ctx.createRadialGradient(0, 0, 0, 0, 0, HALO_R * (1.1 + hover * 0.35))
      aura.addColorStop(0, 'rgba(255, 255, 255, 0.95)')
      aura.addColorStop(0.35, 'rgba(255, 255, 255, 0.55)')
      aura.addColorStop(0.65, 'rgba(255, 200, 140, 0.28)')
      aura.addColorStop(1, 'rgba(255, 255, 255, 0)')
      ctx.beginPath()
      ctx.fillStyle = aura
      ctx.shadowColor = 'rgba(255, 255, 255, 0.65)'
      ctx.shadowBlur = 18
      ctx.arc(0, 0, HALO_R * (1 + hover * 0.2), 0, Math.PI * 2)
      ctx.fill()

      // Core
      ctx.beginPath()
      ctx.shadowBlur = 8
      ctx.shadowColor = 'rgba(255, 255, 255, 0.9)'
      ctx.fillStyle = '#ffffff'
      ctx.arc(0, 0, CORE_R * (0.95 + hover * 0.15), 0, Math.PI * 2)
      ctx.fill()
      ctx.restore()

      // Concentric / geometric rings on hover + click
      const rings = hover > 0.08 || clickPulse > 0.02
      if (rings) {
        const base = 16 + hover * 10
        // Soft circle
        ctx.beginPath()
        ctx.strokeStyle = `rgba(255, 255, 255, ${0.35 + hover * 0.35 + clickPulse * 0.4})`
        ctx.lineWidth = 1.25
        ctx.shadowColor = 'rgba(255, 170, 0, 0.4)'
        ctx.shadowBlur = 12
        const pulseR = base + clickPulse * 22 + Math.sin(ringPhase * 2) * 2
        ctx.arc(pos.x, pos.y, pulseR, 0, Math.PI * 2)
        ctx.stroke()

        // Hexagon on interactive
        if (hover > 0.4) {
          const hr = base + 8 + Math.sin(ringPhase) * 3
          ctx.beginPath()
          for (let i = 0; i < 6; i++) {
            const a = ringPhase * 0.6 + (i / 6) * Math.PI * 2
            const x = pos.x + Math.cos(a) * hr
            const y = pos.y + Math.sin(a) * hr
            if (i === 0) ctx.moveTo(x, y)
            else ctx.lineTo(x, y)
          }
          ctx.closePath()
          ctx.strokeStyle = `rgba(255, 170, 0, ${0.25 + hover * 0.35})`
          ctx.lineWidth = 1
          ctx.shadowBlur = 8
          ctx.stroke()
        }

        // Click shockwave
        if (clickPulse > 0.02) {
          ctx.beginPath()
          ctx.strokeStyle = `rgba(255, 255, 255, ${clickPulse * 0.7})`
          ctx.lineWidth = 2
          ctx.arc(pos.x, pos.y, 12 + (1 - clickPulse) * 36, 0, Math.PI * 2)
          ctx.stroke()
        }
      }

      ctx.shadowBlur = 0
      raf = requestAnimationFrame(draw)
    }
    raf = requestAnimationFrame(draw)

    return () => {
      cancelAnimationFrame(raf)
      root.classList.remove('vigil-custom-cursor')
      window.removeEventListener('pointermove', onMove)
      window.removeEventListener('pointerdown', onDown)
      window.removeEventListener('pointerleave', onLeave)
      window.removeEventListener('pointerenter', onEnter)
      window.removeEventListener('resize', resize)
    }
  }, [])

  return (
    <canvas
      ref={canvasRef}
      className="vigil-cursor-layer"
      aria-hidden
    />
  )
}
