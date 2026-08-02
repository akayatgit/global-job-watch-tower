import { useMemo, useRef } from 'react'
import { useFrame } from '@react-three/fiber'
import * as THREE from 'three'
import { useVigilStore } from '../store/vigilStore'

/**
 * Labor-market singularity — GPU particle swarm (no nested spheres / toruses).
 * Motion + color live in the vertex shader (20k units, zero per-frame GC).
 */
const COUNT = 20000

const vertexShader = /* glsl */ `
uniform float uTime;
uniform float uBurst;
uniform float uScale;
attribute float aIndex;
varying vec3 vColor;

void main() {
  float count = ${COUNT}.0;
  float i = aIndex;
  float t = i / max(count - 1.0, 1.0);
  float golden = 2.399963229728653;
  float breathe = 1.0 + 0.14 * sin(uTime * 0.65);
  float radius = pow(t, 0.52) * 1.62 * breathe * uScale;
  float theta = i * golden + uTime * 0.16;
  float phi = acos(clamp(1.0 - 2.0 * ((i + 0.5) / count), -1.0, 1.0));
  float swirl = uTime * 0.38 + radius * 2.35;
  float px = radius * sin(phi) * cos(theta + swirl);
  float py = radius * cos(phi) * 0.88 + 0.1 * sin(uTime * 1.05 + i * 0.007);
  float pz = radius * sin(phi) * sin(theta + swirl);
  // Soft Lorenz-ish fold — organic field, stable finite maths
  float fold = 0.18 * sin(uTime * 1.15 + radius * 3.1);
  float warp = 0.12 * sin(theta * 2.0 - uTime * 0.9);
  px = px * (1.0 + fold) + warp * pz;
  pz = pz * (1.0 + fold) - warp * px * 0.5;
  py = py + 0.08 * sin(uTime * 0.5 + theta);
  // Burst kick from center
  float kick = 1.0 + uBurst * (1.0 - t) * 0.55;
  vec3 pos = vec3(px, py, pz) * kick;

  // Brand heat: deep orange → amber → white near singularity
  float hue = 0.055 + 0.035 * sin(uTime * 0.4 + t * 6.28318);
  float lit = 0.38 + 0.42 * (1.0 - t) + 0.12 * uBurst;
  vColor = vec3(
    1.0,
    clamp(0.28 + 0.55 * t + 0.2 * lit, 0.0, 1.0),
    clamp(0.02 + 0.18 * (1.0 - t), 0.0, 0.55)
  );
  vColor = mix(vColor, vec3(1.0, 0.95, 0.85), pow(1.0 - t, 5.0) * 0.65);
  vColor *= (0.75 + 0.25 * sin(hue * 40.0));

  vec4 mvPosition = modelViewMatrix * vec4(pos, 1.0);
  float psz = 2.2 + 4.8 * (1.0 - t);
  gl_PointSize = psz * (280.0 / max(-mvPosition.z, 0.5));
  gl_Position = projectionMatrix * mvPosition;
}
`

const fragmentShader = /* glsl */ `
varying vec3 vColor;
void main() {
  vec2 c = gl_PointCoord - vec2(0.5);
  float d = length(c);
  float alpha = smoothstep(0.5, 0.08, d);
  if (alpha < 0.02) discard;
  gl_FragColor = vec4(vColor, alpha * 0.92);
}
`

export function EnergyCore() {
  const points = useRef<THREE.Points>(null)
  const mat = useRef<THREE.ShaderMaterial>(null)
  const coreScale = useVigilStore((s) => s.coreScale)
  const coreBurst = useVigilStore((s) => s.coreBurst)
  const sceneMode = useVigilStore((s) => s.sceneMode)

  const { positions, aIndex } = useMemo(() => {
    const positions = new Float32Array(COUNT * 3)
    const aIndex = new Float32Array(COUNT)
    for (let i = 0; i < COUNT; i++) aIndex[i] = i
    return { positions, aIndex }
  }, [])

  const uniforms = useMemo(
    () => ({
      uTime: { value: 0 },
      uBurst: { value: 0 },
      uScale: { value: 1 },
    }),
    [],
  )

  useFrame((state) => {
    if (!mat.current) return
    const t = state.clock.elapsedTime
    mat.current.uniforms.uTime.value = t
    const burstAge = (performance.now() - coreBurst) / 1000
    const burst =
      burstAge >= 0 && burstAge < 0.7 ? (0.7 - burstAge) / 0.7 : 0
    mat.current.uniforms.uBurst.value = burst
    // Graph/City modes: keep singularity as a dim heart, not the stage
    const modeScale =
      sceneMode === 'core' ? 1 : sceneMode === 'graph' ? 0.35 : 0.22
    mat.current.uniforms.uScale.value = coreScale * modeScale
    if (points.current) {
      points.current.rotation.y = t * 0.04
    }
  })

  if (sceneMode === 'city') return null

  return (
    <points ref={points} frustumCulled={false}>
      <bufferGeometry>
        <bufferAttribute attach="attributes-position" args={[positions, 3]} />
        <bufferAttribute attach="attributes-aIndex" args={[aIndex, 1]} />
      </bufferGeometry>
      <shaderMaterial
        ref={mat}
        uniforms={uniforms}
        vertexShader={vertexShader}
        fragmentShader={fragmentShader}
        transparent
        depthWrite={false}
        blending={THREE.AdditiveBlending}
      />
    </points>
  )
}
