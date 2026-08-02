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
  const s = local * local * (3 - 2 * local)
  return out.copy(waypoints[i]).lerp(waypoints[i + 1], s)
}

/**
 * Miro / Figma–style nav: cursor-pivot zoom with ease ramp,
 * cinematic focus, edge-path follow to parent.
 */
export function SceneControls() {
  const ref = useRef<ControlsHandle | null>(null)
  const { camera, gl } = useThree()
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
  const tmpBefore = useRef(new THREE.Vector3())
  const tmpAfter = useRef(new THREE.Vector3())
  const tmpDir = useRef(new THREE.Vector3())
  const tmpOffset = useRef(new THREE.Vector3())
  const plane = useRef(new THREE.Plane())
  const raycaster = useRef(new THREE.Raycaster())
  const ndc = useRef(new THREE.Vector2())
  const pointer = useRef({ x: 0.5, y: 0.5 }) // 0..1 in canvas
  const scrollAccum = useRef(0)
  const lastWheelAt = useRef(0)

  useEffect(() => {
    const c = ref.current
    if (!c) return
    if (sceneMode === 'city') {
      // Always high-angle isometric over the campus
      camera.position.set(3.6, 7.2, 3.6)
    } else {
      camera.position.set(0, 0.6, sceneMode === 'graph' ? 7.5 : 7.2)
    }
    c.target.set(0, 0, 0)
    c.minDistance = 0.25
    c.maxDistance = 28
    c.update()
    fly.current = null
    useVigilStore.getState().setStatus(
      'DRAG orbit · SCROLL zoom (cursor pivot) · RIGHT-DRAG pan · RIGHT-CLICK parent · click focus',
    )
  }, [viewResetNonce, sceneMode, camera])

  // Track pointer for zoom-to-cursor pivot
  useEffect(() => {
    const el = gl.domElement
    const onMove = (e: PointerEvent) => {
      const rect = el.getBoundingClientRect()
      pointer.current.x = (e.clientX - rect.left) / Math.max(1, rect.width)
      pointer.current.y = (e.clientY - rect.top) / Math.max(1, rect.height)
    }
    el.addEventListener('pointermove', onMove, { passive: true })
    return () => el.removeEventListener('pointermove', onMove)
  }, [gl])

  // Custom wheel: ease ramp + zoom toward cursor
  useEffect(() => {
    const el = gl.domElement
    const onWheel = (e: WheelEvent) => {
      e.preventDefault()
      if (!enabled) return
      const now = performance.now()
      const gap = now - lastWheelAt.current
      lastWheelAt.current = now
      // Medium ease ramp — readable on graph + city
      const ramp = gap < 50 ? 1.45 : gap < 110 ? 1.2 : 1
      scrollAccum.current += e.deltaY * 0.0017 * ramp
      scrollAccum.current = THREE.MathUtils.clamp(scrollAccum.current, -0.85, 0.85)
    }
    el.addEventListener('wheel', onWheel, { passive: false })
    return () => el.removeEventListener('wheel', onWheel)
  }, [gl, enabled])

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

  useEffect(() => {
    const c = ref.current
    const st = useVigilStore.getState()
    if (st.cameraPath) return
    const f = st.cameraFocus
    if (!c || !f) return
    if (fly.current?.mode === 'path' && fly.current.active) return
    const dist = f.distance
    const cityHigh = useVigilStore.getState().sceneMode === 'city'
    // City: steeper drone angle looking down at roof tops
    const toPos = cityHigh
      ? new THREE.Vector3(
          f.x + dist * 0.55,
          f.y + dist * 1.05,
          f.z + dist * 0.55,
        )
      : new THREE.Vector3(
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

    // —— Cursor-pivot zoom with ease decay ——
    if (enabled && Math.abs(scrollAccum.current) > 0.0002) {
      // Ease: apply a chunk each frame, decay the rest (smooth ramp feel)
      const step = scrollAccum.current * Math.min(1, dt * 7)
      scrollAccum.current *= Math.exp(-dt * 6.2)

      ndc.current.set(
        pointer.current.x * 2 - 1,
        -(pointer.current.y * 2 - 1),
      )
      raycaster.current.setFromCamera(ndc.current, camera)

      // Pivot plane: through orbit target, facing camera
      camera.getWorldDirection(tmpDir.current)
      plane.current.setFromNormalAndCoplanarPoint(
        tmpDir.current,
        c.target,
      )
      const hitBefore = raycaster.current.ray.intersectPlane(
        plane.current,
        tmpBefore.current,
      )

      // Dolly along view axis
      tmpOffset.current.copy(camera.position).sub(c.target)
      const dist = tmpOffset.current.length()
      const factor = Math.exp(step * 0.85)
      const nextDist = THREE.MathUtils.clamp(
        dist * factor,
        c.minDistance,
        c.maxDistance,
      )
      tmpOffset.current.setLength(nextDist)
      camera.position.copy(c.target).add(tmpOffset.current)

      // Keep the world point under the cursor stable
      if (hitBefore) {
        camera.getWorldDirection(tmpDir.current)
        plane.current.setFromNormalAndCoplanarPoint(
          tmpDir.current,
          c.target,
        )
        raycaster.current.setFromCamera(ndc.current, camera)
        const hitAfter = raycaster.current.ray.intersectPlane(
          plane.current,
          tmpAfter.current,
        )
        if (hitAfter) {
          const dx = tmpBefore.current.x - tmpAfter.current.x
          const dy = tmpBefore.current.y - tmpAfter.current.y
          const dz = tmpBefore.current.z - tmpAfter.current.z
          camera.position.x += dx
          camera.position.y += dy
          camera.position.z += dz
          c.target.x += dx
          c.target.y += dy
          c.target.z += dz
        }
      }
      c.update()
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
      enableZoom={false}
      enableRotate
      panSpeed={1.0}
      rotateSpeed={0.75}
      minDistance={0.25}
      maxDistance={28}
      minPolarAngle={0.15}
      // City stays high-angle; other modes allow a bit more tilt
      maxPolarAngle={
        sceneMode === 'city' ? Math.PI * 0.38 : Math.PI * 0.48
      }
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
