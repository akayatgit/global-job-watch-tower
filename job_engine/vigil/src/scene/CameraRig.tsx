import { useFrame, useThree } from '@react-three/fiber'
import { useVigilStore } from '../store/vigilStore'
import { lerp } from '../lib/lerp'

export function CameraRig() {
  const { camera } = useThree()

  useFrame(() => {
    const hands = useVigilStore.getState().hands
    const c = hands.right?.centroid || hands.left?.centroid
    const tx = c ? (c.x - 0.5) * 1.2 : 0
    const ty = c ? (0.5 - c.y) * 0.8 : 0
    camera.position.x = lerp(camera.position.x, tx, 0.08)
    camera.position.y = lerp(camera.position.y, ty, 0.08)
    camera.lookAt(0, 0, 0)
  })

  return null
}
