import { useFrame, useThree } from '@react-three/fiber'
import { useVigilStore } from '../store/vigilStore'
import { lerp } from '../lib/lerp'

/**
 * Camera always stays OUTSIDE the particle orb.
 * Zoom = approach the surface, never fly into additive white soup.
 */
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
        tx += (c.x - 0.5) * 0.25
        ty += (0.5 - c.y) * 0.18
      }
    }

    let zFar = 8.8
    let zNear = 4.6 // stay outside ~1.2 radius orb + margin
    if (st.sceneMode === 'city') {
      zFar = 8.2
      zNear = st.cityFocus ? 4.0 : 5.5
    } else if (st.sceneMode === 'graph') {
      zFar = 9.0
      zNear = 5.2
    }

    const zTarget = zFar + (zNear - zFar) * st.sceneZoom
    camera.position.x = lerp(camera.position.x, tx, 0.12)
    camera.position.y = lerp(camera.position.y, ty, 0.12)
    camera.position.z = lerp(camera.position.z, zTarget, 0.14)
    camera.lookAt(0, 0, 0)
  })

  return null
}
