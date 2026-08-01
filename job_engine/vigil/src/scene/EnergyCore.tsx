import { useMemo, useRef } from 'react'
import { useFrame } from '@react-three/fiber'
import * as THREE from 'three'
import { useVigilStore } from '../store/vigilStore'

export function EnergyCore() {
  const group = useRef<THREE.Group>(null)
  const particles = useRef<THREE.Points>(null)
  const ringA = useRef<THREE.Mesh>(null)
  const ringB = useRef<THREE.Mesh>(null)
  const ringC = useRef<THREE.Mesh>(null)
  const coreScale = useVigilStore((s) => s.coreScale)
  const coreBurst = useVigilStore((s) => s.coreBurst)

  const { positions, colors } = useMemo(() => {
    const count = 1800
    const positions = new Float32Array(count * 3)
    const colors = new Float32Array(count * 3)
    const cOrange = new THREE.Color('#ff5500')
    const cAmber = new THREE.Color('#ffaa00')
    const cWhite = new THREE.Color('#ffffff')
    for (let i = 0; i < count; i++) {
      const r = Math.pow(Math.random(), 0.55) * 1.35
      const theta = Math.random() * Math.PI * 2
      const phi = Math.acos(2 * Math.random() - 1)
      positions[i * 3] = r * Math.sin(phi) * Math.cos(theta)
      positions[i * 3 + 1] = r * Math.sin(phi) * Math.sin(theta)
      positions[i * 3 + 2] = r * Math.cos(phi)
      const mix = Math.random()
      const col = mix > 0.85 ? cWhite : mix > 0.4 ? cAmber : cOrange
      colors[i * 3] = col.r
      colors[i * 3 + 1] = col.g
      colors[i * 3 + 2] = col.b
    }
    return { positions, colors }
  }, [])

  useFrame((state) => {
    const t = state.clock.elapsedTime
    if (group.current) {
      const target = coreScale
      group.current.scale.lerp(new THREE.Vector3(target, target, target), 0.12)
      group.current.rotation.y = t * 0.18
      const burstAge = (performance.now() - coreBurst) / 1000
      if (burstAge >= 0 && burstAge < 0.6) {
        const kick = 1 + (0.6 - burstAge) * 0.35
        group.current.scale.multiplyScalar(kick)
      }
    }
    if (particles.current) {
      particles.current.rotation.y = -t * 0.12
      particles.current.rotation.x = Math.sin(t * 0.2) * 0.15
    }
    if (ringA.current) ringA.current.rotation.x = t * 0.7
    if (ringB.current) {
      ringB.current.rotation.y = t * 0.55
      ringB.current.rotation.z = t * 0.25
    }
    if (ringC.current) {
      ringC.current.rotation.x = -t * 0.4
      ringC.current.rotation.y = t * 0.35
    }
  })

  return (
    <group ref={group}>
      <mesh>
        <sphereGeometry args={[0.28, 32, 32]} />
        <meshBasicMaterial color="#ffffff" />
      </mesh>
      <mesh>
        <sphereGeometry args={[0.55, 32, 32]} />
        <meshBasicMaterial color="#ffaa00" transparent opacity={0.35} />
      </mesh>
      <mesh>
        <sphereGeometry args={[0.9, 32, 32]} />
        <meshBasicMaterial color="#ff5500" transparent opacity={0.12} />
      </mesh>

      <points ref={particles}>
        <bufferGeometry>
          <bufferAttribute attach="attributes-position" args={[positions, 3]} />
          <bufferAttribute attach="attributes-color" args={[colors, 3]} />
        </bufferGeometry>
        <pointsMaterial
          size={0.035}
          vertexColors
          transparent
          opacity={0.9}
          depthWrite={false}
          blending={THREE.AdditiveBlending}
          sizeAttenuation
        />
      </points>

      <mesh ref={ringA} rotation={[Math.PI / 2.4, 0.2, 0]}>
        <torusGeometry args={[1.35, 0.018, 16, 120]} />
        <meshBasicMaterial color="#ff5500" transparent opacity={0.85} />
      </mesh>
      <mesh ref={ringB} rotation={[0.4, 0.8, 0.3]}>
        <torusGeometry args={[1.55, 0.012, 16, 120]} />
        <meshBasicMaterial color="#cc1100" transparent opacity={0.75} />
      </mesh>
      <mesh ref={ringC} rotation={[1.2, 0.1, 0.7]}>
        <torusGeometry args={[1.75, 0.01, 16, 140]} />
        <meshBasicMaterial color="#ffaa00" transparent opacity={0.55} />
      </mesh>
    </group>
  )
}
