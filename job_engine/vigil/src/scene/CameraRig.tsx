import { useFrame, useThree } from '@react-three/fiber'
import { useVigilStore } from '../store/vigilStore'
import { lerp } from '../lib/lerp'

export function CameraRig() {
  const { camera } = useThree()

  useFrame(() => {
    const st = useVigilStore.getState()
    // Canvas pan from pinch-drag on empty space; light follow when idle
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
    camera.position.x = lerp(camera.position.x, tx, 0.12)
    camera.position.y = lerp(camera.position.y, ty, 0.12)
    camera.lookAt(0, 0, 0)
  })

  return null
}
