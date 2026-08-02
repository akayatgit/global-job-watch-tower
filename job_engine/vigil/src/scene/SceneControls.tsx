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

type Flight =
  | {
      mode: 'point'
      active: boolean
      fromPos: THREE.Vector3
      toPos: THREE.Vector3
      fromTarget: THREE.Vector3
      toTarget: THREE.Vector3
      t: number
      speed: number
    }
  | {
      mode: 'path'
      active: boolean
      waypoints: THREE.Vector3[]
      distance: number
      endFocusId: string | null
      t: number
      speed: number
    }

function samplePath(waypoints: THREE.Vector3[], u: number, out: THREE.Vector3) {
  if (waypoints.length === 0) return out.set(0, 0, 0)
  if (waypoints.length === 1) return out.copy(waypoints[0])
  const clamped = THREE.MathUtils.clamp(u, 0, 1)
  const segCount = waypoints.length - 1
  const f = clamped * segCount
  const i = Math.min(segCount - 1, Math.floor(f))
  const local = f - i
  // Smoothstep within segment
  const s = local * local * (3 - 2 * local)
  return out.copy(waypoints[i]).lerp(waypoints[i + 1], s)
}

/**
 * Miro / Figma–style nav + cinematic focus + edge-path follow to parent.
 */
export function SceneControls() {
  const ref = useRef<ControlsHandle | null>(null)
  const { camera } = useThree()
  const focusedPanel = useVigilStore((s) => s.focusedPanel)
  const trainingActive = useVigilStore((s) => s.trainingActive)
  const viewResetNonce = useVigilStore((s) => s.viewResetNonce)
  const sceneMode = useVigilStore((s) => s.sceneMode)
  const cameraFocusNonce = useVigilStore((s) => s.cameraFocusNonce)
  const cameraPathNonce = useVigilStore((s) => s.cameraPathNonce)
  const [flying, setFlying] = useState(false)
  const enabled = !focusedPanel && !trainingActive && !flying

  const fly = useRef<Flight | null>(null)
  const tmpLook = useRef(new THREE.Vector3())
  const tmpCam = useRef(new THREE.Vector3())

  useEffect(() => {
    const c = ref.current
    if (!c) return
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
      'DRAG orbit · SCROLL zoom · RIGHT-DRAG pan · RIGHT-CLICK parent path · click focus · click again open',
    )
  }, [viewResetNonce, sceneMode, camera])

  // Path follow (edge → parent) takes priority over point fly
  useEffect(() => {
    const c = ref.current
    const path = useVigilStore.getState().cameraPath
    if (!c || !path || path.waypoints.length < 2) return
    fly.current = {
      mode: 'path',
      active: true,
      waypoints: path.waypoints.map((p) => new THREE.Vector3(p.x, p.y, p.z)),
      distance: path.distance,
      endFocusId: path.endFocusId,
      t: 0,
      speed: 0.55,
    }
    setFlying(true)
  }, [cameraPathNonce])

  // Point fly-to (first click / teleport) — skipped while a path is queued
  useEffect(() => {
    const c = ref.current
    const st = useVigilStore.getState()
    if (st.cameraPath) return
    const f = st.cameraFocus
    if (!c || !f) return
    if (fly.current?.mode === 'path' && fly.current.active) return
    const dist = f.distance
    const toPos = new THREE.Vector3(
      f.x + dist * 0.78,
      f.y + dist * 0.72,
      f.z + dist * 0.78,
    )
    const toTarget = new THREE.Vector3(f.x, f.y, f.z)
    fly.current = {
      mode: 'point',
      active: true,
      fromPos: camera.position.clone(),
      toPos,
      fromTarget: c.target.clone(),
      toTarget,
      t: 0,
      speed: 1.15,
    }
    setFlying(true)
  }, [cameraFocusNonce, camera])

  useFrame((_, dt) => {
    const c = ref.current
    if (!c) return

    const flight = fly.current
    if (flight?.active && flight.mode === 'path') {
      flight.t = Math.min(1, flight.t + dt * flight.speed)
      const u = flight.t * flight.t * (3 - 2 * flight.t)
      samplePath(flight.waypoints, u, tmpLook.current)
      // Drone rides beside the edge — offset rotates gently along the path
      const dist = flight.distance
      tmpCam.current.set(
        tmpLook.current.x + dist * 0.78,
        tmpLook.current.y + dist * 0.62,
        tmpLook.current.z + dist * 0.78,
      )
      camera.position.lerp(tmpCam.current, 0.35)
      c.target.copy(tmpLook.current)
      c.update()
      if (flight.t >= 1) {
        flight.active = false
        setFlying(false)
        const endId = flight.endFocusId
        if (endId) {
          const end = flight.waypoints[flight.waypoints.length - 1]
          useVigilStore.setState({
            graphFocusId: endId,
            selectFocusId: endId,
            cameraFocus: {
              id: endId,
              x: end.x,
              y: end.y,
              z: end.z,
              distance: flight.distance,
            },
            cameraPath: null,
            statusLine: 'FOCUS · parent · click again to open',
          })
        } else {
          useVigilStore.setState({ cameraPath: null })
        }
      }
      return
    }

    if (flight?.active && flight.mode === 'point') {
      flight.t = Math.min(1, flight.t + dt * flight.speed)
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
