import { useMemo, useRef } from 'react'
import { useFrame } from '@react-three/fiber'
import * as THREE from 'three'
import { useVigilStore } from '../store/vigilStore'

/**
 * Labor-market singularity — GPU particle swarm.
 * Stays a readable orb in dark space (never a full-screen whiteout).
 */
const COUNT = 14000

const vertexShader = /* glsl */ `
uniform float uTime;
uniform float uBurst;
uniform float uScale;
uniform float uDim;
attribute float aIndex;
varying vec3 vColor;
varying float vAlpha;

void main() {
  float count = ${COUNT}.0;
  float i = aIndex;
  float t = i / max(count - 1.0, 1.0);
  float golden = 2.399963229728653;
  float breathe = 1.0 + 0.1 * sin(uTime * 0.65);
  // Compact orb — camera stays outside this radius
  float radius = pow(t, 0.55) * 1.15 * breathe * uScale;
  float theta = i * golden + uTime * 0.14;
  float phi = acos(clamp(1.0 - 2.0 * ((i + 0.5) / count), -1.0, 1.0));
  float swirl = uTime * 0.32 + radius * 2.0;
  float px = radius * sin(phi) * cos(theta + swirl);
  float py = radius * cos(phi) * 0.9 + 0.06 * sin(uTime * 1.0 + i * 0.007);
  float pz = radius * sin(phi) * sin(theta + swirl);
  float fold = 0.12 * sin(uTime * 1.1 + radius * 3.0);
  float warp = 0.08 * sin(theta * 2.0 - uTime * 0.85);
  px = px * (1.0 + fold) + warp * pz;
  pz = pz * (1.0 + fold) - warp * px * 0.45;
  float kick = 1.0 + uBurst * (1.0 - t) * 0.35;
  vec3 pos = vec3(px, py, pz) * kick;

  // Orange/amber heat — little pure white (white + bloom = whiteout)
  vColor = mix(
    vec3(1.0, 0.28, 0.02),
    vec3(1.0, 0.62, 0.12),
    t
  );
  vColor = mix(vColor, vec3(1.0, 0.85, 0.45), pow(1.0 - t, 6.0) * 0.35);
  vColor *= (0.55 + 0.45 * uDim);

  vec4 mvPosition = modelViewMatrix * vec4(pos, 1.0);
  float dist = max(-mvPosition.z, 1.0);
  // HARD CAP — never let points fill the viewport
  float psz = (1.4 + 2.2 * (1.0 - t)) * (90.0 / dist);
  gl_PointSize = clamp(psz, 0.8, 6.5);
  vAlpha = (0.55 + 0.35 * (1.0 - t)) * uDim;
  gl_Position = projectionMatrix * mvPosition;
}
`

const fragmentShader = /* glsl */ `
varying vec3 vColor;
varying float vAlpha;
void main() {
  vec2 c = gl_PointCoord - vec2(0.5);
  float d = length(c);
  float alpha = smoothstep(0.5, 0.12, d) * vAlpha;
  if (alpha < 0.03) discard;
  gl_FragColor = vec4(vColor, alpha);
}
`

export function EnergyCore() {
  const points = useRef<THREE.Points>(null)
  const mat = useRef<THREE.ShaderMaterial>(null)
  const coreScale = useVigilStore((s) => s.coreScale)
  const coreBurst = useVigilStore((s) => s.coreBurst)
  const sceneMode = useVigilStore((s) => s.sceneMode)
  const sceneZoom = useVigilStore((s) => s.sceneZoom)

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
      uDim: { value: 1 },
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
    const modeScale =
      sceneMode === 'core' ? 1 : sceneMode === 'graph' ? 0.28 : 0.18
    mat.current.uniforms.uScale.value = coreScale * modeScale
    // Dim slightly as you approach — keeps shape readable
    mat.current.uniforms.uDim.value =
      sceneMode === 'core' ? 1.0 - sceneZoom * 0.25 : 0.55
    if (points.current) points.current.rotation.y = t * 0.035
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
