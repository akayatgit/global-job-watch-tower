import { useEffect, useRef } from 'react'
import { useThree } from '@react-three/fiber'
import { OrbitControls } from '@react-three/drei'
import * as THREE from 'three'
import { useVigilStore } from '../store/vigilStore'

type ControlsHandle = {
  target: THREE.Vector3
  minDistance: number
  maxDistance: number
  update: () => void
}

/**
 * Miro / Figma–style navigation in 3D:
 *  - Drag = orbit   ·  Right-drag / two-finger = pan
 *  - Wheel / pinch  = dolly in & out (deep into the orb)
 *  - Esc / Home / 0 / double-click = reset
 */
export function SceneControls() {
  const ref = useRef<ControlsHandle | null>(null)
  const { camera } = useThree()
  const focusedPanel = useVigilStore((s) => s.focusedPanel)
  const trainingActive = useVigilStore((s) => s.trainingActive)
  const viewResetNonce = useVigilStore((s) => s.viewResetNonce)
  const sceneMode = useVigilStore((s) => s.sceneMode)
  const enabled = !focusedPanel && !trainingActive

  useEffect(() => {
    const c = ref.current
    if (!c) return
    camera.position.set(0, 0.6, sceneMode === 'graph' ? 7.5 : 7.2)
    c.target.set(0, 0, 0)
    c.minDistance = 0.25
    c.maxDistance = 24
    c.update()
    useVigilStore.getState().setStatus(
      'DRAG orbit · SCROLL/PINCH zoom · RIGHT-DRAG pan · Esc reset',
    )
  }, [viewResetNonce, sceneMode, camera])

  // Hand-pan from VIGIL mode nudges the look target (Miro-like canvas feel)
  useEffect(() => {
    let raf = 0
    const tick = () => {
      const st = useVigilStore.getState()
      const c = ref.current
      if (c && st.vigilMode && st.gestureMode === 'none' && !st.focusedPanel) {
        const pan = st.canvasPan
        c.target.x = THREE.MathUtils.lerp(c.target.x, pan.x * 0.85, 0.08)
        c.target.y = THREE.MathUtils.lerp(c.target.y, pan.y * 0.85, 0.08)
        c.update()
      }
      // Two-hand pinch on empty canvas → dolly (enter / exit orb)
      if (c && st.gestureMode === 'core_zoom') {
        const d = camera.position.distanceTo(c.target)
        const want = THREE.MathUtils.clamp(2.8 / Math.max(st.coreScale, 0.5), 0.3, 20)
        const next = THREE.MathUtils.lerp(d, want, 0.12)
        const dir = new THREE.Vector3()
          .subVectors(camera.position, c.target)
          .normalize()
        camera.position.copy(c.target).addScaledVector(dir, next)
        c.update()
      }
      raf = requestAnimationFrame(tick)
    }
    raf = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(raf)
  }, [camera])

  return (
    <OrbitControls
      ref={ref as any}
      makeDefault
      enabled={enabled}
      enableDamping
      dampingFactor={0.085}
      enablePan
      enableZoom
      enableRotate
      zoomSpeed={1.35}
      panSpeed={1.0}
      rotateSpeed={0.75}
      minDistance={0.25}
      maxDistance={24}
      minPolarAngle={0.12}
      maxPolarAngle={Math.PI - 0.12}
      mouseButtons={{
        LEFT: THREE.MOUSE.ROTATE,
        MIDDLE: THREE.MOUSE.DOLLY,
        RIGHT: THREE.MOUSE.PAN,
      }}
      touches={{
        ONE: THREE.TOUCH.ROTATE,
        TWO: THREE.TOUCH.DOLLY_PAN,
      }}
    />
  )
}
