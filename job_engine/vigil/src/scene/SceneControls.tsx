import { useEffect, useRef, useState } from 'react'
import { useFrame, useThree } from '@react-three/fiber'
import { OrbitControls } from '@react-three/drei'
import * as THREE from 'three'
import { useVigilStore } from '../store/vigilStore'

type ControlsHandle = {
  target: THREE.Vector3
  minDistance: number
  maxDistance: number
  update: () => void
  enabled: boolean
}

/**
 * Miro / Figma–style nav + cinematic first-click focus (drone isometric).
 */
export function SceneControls() {
  const ref = useRef<ControlsHandle | null>(null)
  const { camera } = useThree()
  const focusedPanel = useVigilStore((s) => s.focusedPanel)
  const trainingActive = useVigilStore((s) => s.trainingActive)
  const viewResetNonce = useVigilStore((s) => s.viewResetNonce)
  const sceneMode = useVigilStore((s) => s.sceneMode)
  const cameraFocusNonce = useVigilStore((s) => s.cameraFocusNonce)
  const [flying, setFlying] = useState(false)
  const enabled = !focusedPanel && !trainingActive && !flying

  const fly = useRef<{
    active: boolean
    fromPos: THREE.Vector3
    toPos: THREE.Vector3
    fromTarget: THREE.Vector3
    toTarget: THREE.Vector3
    t: number
  } | null>(null)

  useEffect(() => {
    const c = ref.current
    if (!c) return
    // Home framing per mode
    if (sceneMode === 'city') {
      camera.position.set(6.5, 5.8, 6.5)
    } else {
      camera.position.set(0, 0.6, sceneMode === 'graph' ? 7.5 : 7.2)
    }
    c.target.set(0, 0, 0)
    c.minDistance = 0.25
    c.maxDistance = 28
    c.update()
    fly.current = null
    useVigilStore.getState().setStatus(
      'DRAG orbit · SCROLL zoom · RIGHT-DRAG pan · RIGHT-CLICK teleport · click focus · click again open',
    )
  }, [viewResetNonce, sceneMode, camera])

  // Kick a cinematic fly-to when focus is requested
  useEffect(() => {
    const c = ref.current
    const f = useVigilStore.getState().cameraFocus
    if (!c || !f) return
    const dist = f.distance
    // Drone isometric: elevated 3/4 view, wide but intimate
    const toPos = new THREE.Vector3(
      f.x + dist * 0.78,
      f.y + dist * 0.72,
      f.z + dist * 0.78,
    )
    const toTarget = new THREE.Vector3(f.x, f.y, f.z)
    fly.current = {
      active: true,
      fromPos: camera.position.clone(),
      toPos,
      fromTarget: c.target.clone(),
      toTarget,
      t: 0,
    }
    setFlying(true)
  }, [cameraFocusNonce, camera])

  useFrame((_, dt) => {
    const c = ref.current
    if (!c) return

    const flight = fly.current
    if (flight?.active) {
      flight.t = Math.min(1, flight.t + dt * 1.15)
      // Smoothstep ease — cinematic settle
      const u = flight.t * flight.t * (3 - 2 * flight.t)
      camera.position.lerpVectors(flight.fromPos, flight.toPos, u)
      c.target.lerpVectors(flight.fromTarget, flight.toTarget, u)
      c.update()
      if (flight.t >= 1) {
        flight.active = false
        setFlying(false)
      }
      return
    }

    const st = useVigilStore.getState()
    if (st.vigilMode && st.gestureMode === 'none' && !st.focusedPanel) {
      const pan = st.canvasPan
      c.target.x = THREE.MathUtils.lerp(c.target.x, pan.x * 0.85, 0.08)
      c.target.y = THREE.MathUtils.lerp(c.target.y, pan.y * 0.85, 0.08)
      c.update()
    }
    if (st.gestureMode === 'core_zoom') {
      const d = camera.position.distanceTo(c.target)
      const want = THREE.MathUtils.clamp(2.8 / Math.max(st.coreScale, 0.5), 0.3, 20)
      const next = THREE.MathUtils.lerp(d, want, 0.12)
      const dir = new THREE.Vector3()
        .subVectors(camera.position, c.target)
        .normalize()
      camera.position.copy(c.target).addScaledVector(dir, next)
      c.update()
    }
  })

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
      maxDistance={28}
      minPolarAngle={0.15}
      maxPolarAngle={Math.PI * 0.48}
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
