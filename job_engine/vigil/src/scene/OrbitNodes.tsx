import { Html } from '@react-three/drei'
import { useFrame } from '@react-three/fiber'
import { useRef } from 'react'
import * as THREE from 'three'
import { ORBIT_NODES, useVigilStore } from '../store/vigilStore'

export function OrbitNodes() {
  const group = useRef<THREE.Group>(null)
  const hover = useVigilStore((s) => s.hoverTarget)

  useFrame((state) => {
    if (group.current) {
      group.current.rotation.y = Math.sin(state.clock.elapsedTime * 0.15) * 0.08
    }
  })

  return (
    <group ref={group}>
      {ORBIT_NODES.map((node) => {
        const x = Math.cos(node.angle) * node.radius
        const y = Math.sin(node.angle) * node.radius * 0.55
        const z = Math.sin(node.angle * 1.3) * 0.35
        const active = hover === `orbit:${node.id}`
        return (
          <group key={node.id} position={[x, y, z]}>
            <mesh>
              <sphereGeometry args={[active ? 0.12 : 0.08, 16, 16]} />
              <meshBasicMaterial color={active ? '#ffffff' : '#ff5500'} />
            </mesh>
            <mesh>
              <ringGeometry args={[0.16, 0.2, 32]} />
              <meshBasicMaterial
                color={active ? '#ffaa00' : '#cc1100'}
                transparent
                opacity={active ? 0.95 : 0.45}
                side={THREE.DoubleSide}
              />
            </mesh>
            <Html center distanceFactor={8} style={{ pointerEvents: 'none' }}>
              <div
                style={{
                  color: active ? '#fff' : '#ffaa00',
                  fontFamily: 'Orbitron, sans-serif',
                  fontSize: 10,
                  letterSpacing: '0.12em',
                  textTransform: 'uppercase',
                  whiteSpace: 'nowrap',
                  textShadow: '0 0 10px rgba(255,85,0,0.8)',
                  marginTop: 28,
                }}
              >
                {node.label}
              </div>
            </Html>
          </group>
        )
      })}
    </group>
  )
}
