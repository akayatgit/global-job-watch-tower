import { useFrame, useThree } from '@react-three/fiber'
import { useVigilStore } from '../store/vigilStore'
import { lerp } from '../lib/lerp'

/** Zoom enters the orb (camera Z), not the browser page. */
export function CameraRig() {
  const { camera } = useThree()

  useFrame(() => {
    const st = useVigilStore.getState()
    const pan = st.canvasPan
    let tx = pan.x
    let ty = pan.y
    if (st.gestureMode === 'none' && !st.trainingActive) {
      const c = st.hands.right?.centroid || st.hands.left?.centroid
      if (c) {
        tx += (c.x - 0.5) * 0.35
        ty += (0.5 - c.y) * 0.25
      }
    }
    // Far overview → deep inside singularity / city district
    const zFar = st.sceneMode === 'city' ? 8.2 : 9.2
    const zNear = st.sceneMode === 'city' ? 3.4 : 2.35
    const zTarget = zFar + (zNear - zFar) * st.sceneZoom
    camera.position.x = lerp(camera.position.x, tx, 0.12)
    camera.position.y = lerp(camera.position.y, ty, 0.12)
    camera.position.z = lerp(camera.position.z, zTarget, 0.1)
    camera.lookAt(0, 0, 0)
  })

  return null
}
